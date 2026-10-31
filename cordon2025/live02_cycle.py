"""LIVE02 orchestration: fresh baseline -> donor TG search -> ACCEPT/ROLLBACK.

All mutations go through GuardedCOM (TG zone attributes, ACTIVE flags of the
phase plan, Procedures.Execute).  Rollback = donor parameter restoration plus
real recomputation and verified equivalence; never LoadVersion, never a direct
OD matrix write.  The source .ver is never overwritten.
"""
from __future__ import annotations
import contextlib
import functools
import os
import threading
import time
import uuid
import copy
import traceback
from contextlib import contextmanager
from pathlib import Path
from .common import ROOT, require, read_json, parent_module
from .io import write_json, write_csv, write_text, mkdir, exception_text, safe_failure_report, sha256
from .session import RunSession
from . import com_busy
from .visum_startup import ReadControl, settings
from .live01_observations import load_authority
from .live01_visum import model_preflight
from .live01_provenance import verify_protected_sources, guarded_output_root
from .live01_config import calculation_config
from .live02_config import load_config, live01_view, adapter_config
from .live02_guard import GuardedCOM, WriteAudit
from .live02_evaluation import CordonEvaluator
from .live02_namespace import DonorTransaction

RESULT_SCHEMA = 'LIVE02_RESULT_V1'


class LiveControl(ReadControl):
    """ReadControl + donor cooperative-stop semantics (deferred during recovery)."""

    def __init__(self, folder, stop_exception):
        super().__init__(folder)
        self.recovery_depth = 0
        self.stop_exception = stop_exception
        self.recovery_reasons = []

    def stop_requested(self):
        return (self.folder / 'STOP_REQUESTED').exists() or (self.folder.parent / 'STOP_REQUESTED').exists()

    def checkpoint(self, phase=None, force=False, **details):
        require(threading.get_ident() == self.thread, 'COM_THREAD_CHANGED')
        if self.recovery_depth == 0 and self.stop_requested():
            raise self.stop_exception('USER_STOP_REQUESTED')
        if isinstance(details.get('com_retry_event'), dict):
            com_busy.record_event(self, details['com_retry_event'])
        self.state.update(details)
        if phase:
            self.state['phase'] = phase
        self.state['recovery_depth'] = self.recovery_depth
        now = time.monotonic()
        if force or now - self.last > 2:
            try:
                write_json(self.folder / '00_PROGRESS.json', dict(self.state, stage='LIVE02'))
            except Exception as exc:
                self.telemetry_failures = (self.telemetry_failures + [exception_text(exc)])[-20:]
            self.last = now

    @contextmanager
    def recovery(self, reason):
        self.recovery_depth += 1
        self.recovery_reasons.append(reason)
        try:
            yield
        finally:
            self.recovery_depth -= 1


def isolated_copy_guard(cfg, source_version):
    name = Path(str(source_version)).name.upper()
    guard = cfg['isolated_copy_guard']
    for token in guard['forbidden_version_name_tokens']:
        require(token.upper() not in name, 'LIVE02_FORBIDDEN_MODEL_VERSION_NAME:' + token)
    require(any(t.upper() in name for t in guard['required_version_name_tokens_any']),
            'LIVE02_OPEN_MODEL_IS_NOT_MARKED_AS_ISOLATED_COPY:' + Path(str(source_version)).name)
    return {'version_file': str(source_version), 'matched_tokens':
            [t for t in guard['required_version_name_tokens_any'] if t.upper() in name]}


def gate_shortcut(evaluate, tx):
    """Exact-safe TGFIX acceleration: a pre-apply GENERATION_GATE failure is
    decided on the identical preview design BEFORE any write, so no restore and
    no recomputation is needed; the unchanged parent snapshot is verified."""
    supply = parent_module('r1_15a2_supply_visum')

    @functools.wraps(evaluate)
    def wrapped(adapter, cfg, policy, block, candidate, rows, context, before, baseline_diag, baseline_value, *args, **kwargs):
        if block == 'GENERATION':
            design = adapter.generation_preview(context, float(candidate['scale']))
            gate = supply.base.generation_apply_gate(design, adapter.cfg)
            if not gate['passes']:
                folder = Path(args[2]); mkdir(folder)
                require(adapter.snapshot() == before, 'LIVE02_GATE_SHORTCUT_PARENT_CHANGED')
                error = 'GENERATION_GATE:' + ';'.join(gate['reasons'])
                decision = {'accepted': False, 'reasons': ['PRE_APPLY_GATE:' + r for r in gate['reasons']],
                            'pre_apply_generation_gate_rejected': True, 'original_error': error,
                            'hotfix': tx.tgfix.RELEASE,
                            'shortcut': 'NO_WRITE_NO_RECOMPUTE_PARENT_SNAPSHOT_VERIFIED'}
                write_json(folder / 'TRIAL_RESULT.json', {'status': 'REJECTED_PRE_APPLY_GATE', 'block': block,
                           'decision': decision, 'gate': gate, 'model_mutated': False})
                tx.gate_events.append({'candidate': candidate, 'error': error, 'shortcut': True})
                ev = {'eligible': False, 'decision': decision, 'after_value': baseline_value,
                      'candidate': candidate, 'rows': [], 'gap': None, 'pre_apply_gate_rejected': True}
                return ev, baseline_diag, error
        return evaluate(adapter, cfg, policy, block, candidate, rows, context, before,
                        baseline_diag, baseline_value, *args, **kwargs)
    return wrapped


def _default_output_root():
    if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        return Path(os.environ['LOCALAPPDATA']) / 'R1C25_LIVE02'
    return ROOT / 'OFFLINE_RESULTS' / 'LIVE02'


def _parameter_changes(before, after, zones):
    rows = []
    for attr in sorted(before['generation_values']):
        b = before['generation_values'][attr]; a = after['generation_values'][attr]
        for z in zones:
            k = str(z)
            if b[k] != a[k]:
                rows.append({'zone_no': z, 'attr': attr, 'run_start': b[k], 'accepted': a[k],
                             'ratio': (a[k] / b[k]) if b[k] else None})
    return rows


def run(visum, *, output_root=None, options=None, config_path=None, config_overrides=None):
    require(visum is not None, 'VISUM_NOT_INJECTED')
    cfg = load_config(config_path, config_overrides)
    pins = verify_protected_sources()
    output_root = guarded_output_root(output_root or _default_output_root())
    configured = read_json(ROOT / 'CORDON_2025_STARTUP_OPTIONS.json')
    configured.update(options or {})
    v17mode = cfg['generation_mode'] == 'V24917_TARGETED_STEP1'
    if v17mode:
        # COMBUSY2 floor also for the cordon capture reads (rejected calls up to cb_max_wait).
        from .live02_v24917 import run_options
        wait = float(run_options(cfg)['cb_max_wait_seconds'])
        configured['com_retry_max_elapsed_seconds'] = max(float(configured.get('com_retry_max_elapsed_seconds', 0)), wait)
        configured['com_retry_attempts'] = max(int(configured.get('com_retry_attempts', 1)), 1000)
        configured['com_retry_max_delay_seconds'] = max(float(configured.get('com_retry_max_delay_seconds', 0)), 2.0)
    opt = settings(configured)
    require(opt['full_geometry_check'], 'LIVE02_FULL_GEOMETRY_REQUIRED_FOR_BASELINE')
    view = live01_view(cfg, cfg['outer_cycle_start'])
    cells, authority = load_authority(view)
    try:
        origin = visum.origin
    except Exception:
        origin = 'NATIVE_INJECTED_VISUM'
    synthetic = isinstance(origin, str) and any(s in origin.upper() for s in ('MOCK', 'SYNTHETIC', 'FIXTURE'))
    execution = 'MOCK' if synthetic else 'NATIVE_INJECTED'
    folder = None; ctl = None; audit = None; adapter = None; v17status = None
    progress = {'accepted_states': 0, 'cycles': [], 'model_mutated': False}
    try:
        with HashCachingRunSession('LIVE02_TG_' + uuid.uuid4().hex[:12], output_root) as session, \
                contextlib.ExitStack() as stack:
            folder = session.folder
            parent_ctrl = parent_module('r1_15a2_overnight_controller_v24915p2')
            ctl = LiveControl(folder, parent_ctrl.UserStopRequested)
            session.start(cfg, {'live02_config': Path(config_path or ROOT / 'CORDON_LIVE02_CONFIG.json')})
            write_json(folder / 'LIVE02_SOURCE_PROOF.json', pins)
            write_json(folder / 'EFFECTIVE_CONFIG.json', cfg)
            write_json(folder / 'WHOLE_MATRIX_AUTHORITY_AUDIT.json', authority)
            with com_busy.parent_hotfix_scope() as hotfix:
                write_json(folder / 'COMBUSY_HOTFIX_ACTIVATION.json', hotfix)
                # ---- A. fresh read-only binding (LIVE01 contract, unchanged)
                base_dir = folder / '00_BASELINE'; mkdir(base_dir)
                pre, state = model_preflight(visum, view, base_dir, ctl, opt)
                copy_guard = isolated_copy_guard(cfg, state['source_version'])
                write_json(folder / 'ISOLATED_COPY_GUARD.json', copy_guard)
                mathcfg = calculation_config(view, state['actuatable_zones'])
                mathcfg['actual_network_sha256'] = pre[0]['network_sha256']
                evaluator = CordonEvaluator(cfg, mathcfg, cells, opt, ctl, pre)
                audit = WriteAudit(folder / 'WRITE_AUDIT.jsonl')
                guarded = GuardedCOM(visum, 'Visum', audit)
                if v17mode:
                    from .live02_v24917 import runtime_scope
                    v17status = stack.enter_context(runtime_scope(cfg, guarded, pre[2], state['actuatable_zones'], folder))
                    mb = parent_module('r1_15a2_multiblock')
                    audit.allowed_zone_attrs |= {str(a).upper() for a in mb.GENERATION_ATTRS}
                acfg = adapter_config(cfg, cfg['outer_cycle_start'], state['actuatable_zones'])
                adapter = CordonTrialAdapter_factory(guarded, acfg, evaluator, visum, pre, state, folder, cfg, v17status)
                session.checkpoint('LIVE02_CURRENT_MODEL_BOUND')
                # ---- B. baseline cordon diagnostic + restore point
                baseline = evaluator.evaluate(visum, folder / '01_BASELINE_CAPTURE', 'BASELINE',
                                              full_geometry=True, keep_db=True)
                snap0 = adapter.snapshot()
                require(not audit.events or all(e['kind'] == 'READ_LIST_CREATE' for e in audit.events),
                        'LIVE02_BASELINE_MUTATED_MODEL')
                write_json(folder / 'RESTORE_POINT.json', {
                    'schema': 'LIVE02_RESTORE_POINT_V1', 'snapshot': snap0, 'state_hash': snap0['state_hash'],
                    'baseline_diagnostic_hash': baseline['diagnostic_hash'],
                    'method': 'DONOR_PARAMETER_RESTORE_PLUS_NATIVE_RECOMPUTE_NO_LOADVERSION',
                    'source_version': state['source_version'], 'source_file_sha256': state['source_file_sha256']})
                adapter.set_generation_reference(snap0, folder)
                reference = evaluator.reference(baseline)
                write_json(folder / 'BASELINE_OBJECTIVE.json', {m: baseline['methods'][m]['metrics'] for m in baseline['methods']})
                gs = cfg['generation_search']
                tx = DonorTransaction(evaluator.ledger, evaluator.diagnostic_hash,
                                      gate_nonfatal=gs['pre_apply_gate_nonfatal'],
                                      outer_wrap=gate_shortcut if gs['pre_apply_gate_shortcut'] else None)
                write_json(folder / 'DONOR_TRANSACTION_IDENTITY.json', tx.identity())
                block = make_generation_block(tx, cfg, v17status, folder)
                session.checkpoint('LIVE02_BASELINE_AND_RESTORE_POINT_SEALED')
                # ---- C. TG cycles via the original donor search
                current_state, current_diag = snap0, baseline
                progress['accepted_state_hash'] = snap0['state_hash']
                status = 'NO_CYCLE_RUN'
                for k in range(cfg['max_tg_cycles']):
                    outer = cfg['outer_cycle_start'] + k
                    adapter.cfg = adapter_config(cfg, outer, state['actuatable_zones'])
                    cyc_dir = folder / ('C%02d_GENERATION' % outer)
                    progress['model_mutated'] = True
                    try:
                        changed, current_state, current_diag, value, rec = block(
                            adapter, adapter.cfg, cyc_dir, ctl, current_state, current_diag, {}, reference, None,
                            outer_cycle=outer)
                    except BaseException:
                        progress['failure_readback'] = failure_readback(adapter, progress)
                        raise
                    finally:
                        write_timing(cyc_dir, v17mode)
                    progress['cycles'].append({'outer_cycle': outer, 'status': rec['status'], 'changed': bool(changed),
                                               'attempts': [{k2: a.get(k2) for k2 in ('trial', 'status', 'candidate', 'error')}
                                                            for a in rec.get('attempts', [])],
                                               'objective_before': rec.get('objective_before', {}).get('total'),
                                               'objective_after': (rec.get('objective_after') or {}).get('total')})
                    write_json(folder / 'CYCLE_PROGRESS.json', progress)
                    progress['accepted_state_hash'] = current_state['state_hash']
                    if changed:
                        progress['accepted_states'] += 1
                        write_json(cyc_dir / 'ACCEPTED_STATE.json', {
                            'schema': 'LIVE02_ACCEPTED_STATE_V1', 'outer_cycle': outer,
                            'snapshot_state_hash': current_state['state_hash'],
                            'diagnostic_hash': current_diag['diagnostic_hash'], 'ledger': value,
                            'candidate': rec.get('candidate'), 'rows': rec.get('rows')})
                        status = 'ACCEPTED'
                    else:
                        status = rec['status']
                        break
                # ---- D. final independent verification
                ctl.checkpoint('LIVE02_FINAL_VERIFICATION', force=True)
                final = adapter.snapshot()
                require(final == current_state, 'LIVE02_FINAL_STATE_NOT_LAST_ACCEPTED_OR_BASELINE')
                changes = _parameter_changes(snap0, final, adapter.zones)
                step_state = parent_module('r1_15a2_step_search_v24917')._STATE if v17mode else None
                write_csv(folder / 'ACCEPTED_TG_PARAMETERS.csv', changes,
                          ['zone_no', 'attr', 'run_start', 'accepted', 'ratio'])
                saved = None
                if progress['accepted_states'] and cfg['write_policy']['save_accepted_version_new_file']:
                    saved = save_accepted_version(visum, folder, state)
                write_json(folder / 'WRITE_AUDIT_SUMMARY.json', audit.summary())
                summary = {m: current_diag['methods'][m]['metrics'] for m in current_diag['methods']}
                result = {'schema': RESULT_SCHEMA,
                          'status': ('MOCK_' if synthetic else 'NATIVE_') + 'LIVE02_' +
                                    ('TG_ACCEPTED' if progress['accepted_states'] else 'NO_ACCEPTED_TG_CHANGE'),
                          'last_cycle_status': status, 'execution_kind': execution,
                          'output_directory': str(folder), 'accepted_states': progress['accepted_states'],
                          'cycles': progress['cycles'], 'acceptance_method': cfg['acceptance']['method'],
                          'objective_baseline': baseline['methods'][cfg['acceptance']['method']]['objective'],
                          'objective_final': current_diag['methods'][cfg['acceptance']['method']]['objective'],
                          'metrics_baseline': {m: baseline['methods'][m]['metrics'] for m in baseline['methods']},
                          'metrics_final': summary, 'changed_tg_parameters': len(changes),
                          'model_state': 'LAST_ACCEPTED_STATE_IN_OPEN_VISUM' if progress['accepted_states'] else 'BASELINE_RESTORED',
                          'saved_version': saved, 'source_version_overwritten': False,
                          'direct_od_matrix_writes': False, 'load_version_called': False,
                          'write_audit': audit.summary()['counts'],
                          'gate_events': len(tx.gate_events), 'evaluations': evaluator.count,
                          'real_visum_verified': not synthetic, 'production_ready': False,
                          'observation_semantics': 'UNAPPROVED_TECHNICAL_TRIAL',
                          'next_stage': 'LIVE03_TD_FINECDF_AND_JOINT_TG_TD_CYCLES',
                          'generation_mode': cfg['generation_mode'],
                          'v24917': None if not v17mode else {
                              'step1': {k: step_state.get(k) for k in ('rho', 'rho_history', 'blocks', 'trials', 'kept', 'exhausted')},
                              'long_school_active': bool((v17status.get('long_school') or {}).get('active')),
                              'boundary_active': bool((v17status.get('boundary') or {}).get('active')),
                              'boundary_zones': (v17status.get('boundary') or {}).get('zones'),
                              'adapter_counts': getattr(adapter, 'v24917_counts', None),
                              'timing': copy.deepcopy(parent_module('r1_15a2_perf_v24917')._STATE['timing'])}}
                write_json(folder / '00_RESULT.json', result)
                write_json(folder / 'COM_READ_RETRY.json', com_busy.telemetry(ctl, opt))
            session.checkpoint('LIVE02_COMPLETE', completed=True)
            return result
    except BaseException as exc:
        if folder:
            safe_failure_report(folder, exc, traceback_text=traceback.format_exc())
            text = exception_text(exc)
            readback = progress.get('failure_readback')
            if readback is None and progress['model_mutated'] and adapter is not None and not v17status:
                with com_busy.parent_hotfix_scope():
                    readback = failure_readback(adapter, progress)
            verified = (readback or {}).get('matches_last_accepted_or_baseline')
            try:
                write_json(folder / 'FAILURE_STATE_READBACK.json', readback or {'status': 'NOT_READ'})
            except Exception:
                pass
            if not progress['model_mutated']:
                kind = 'LIVE02_BLOCKED_BEFORE_ANY_WRITE'
            elif verified is True:
                kind = 'LIVE02_STOPPED_MODEL_VERIFIED_AT_LAST_ACCEPTED_STATE'
            else:
                kind = 'LIVE02_STOPPED_MODEL_STATE_NOT_VERIFIED_REOPEN_SOURCE_OR_SAVED_VERSION'
            try:
                cp = read_json(folder / 'RUN_CHECKPOINT.json')
                cp.update(completed=False, stage='LIVE02_FAILED', failure_reason=text)
                write_json(folder / 'RUN_CHECKPOINT.json', cp)
            except Exception:
                pass
            try:
                write_text(folder / '99_TRACEBACK.txt', traceback.format_exc())
                write_json(folder / '00_RESULT.json', {
                    'schema': RESULT_SCHEMA, 'status': kind, 'reason': text, 'execution_kind': execution,
                    'accepted_states': progress['accepted_states'], 'cycles': progress['cycles'],
                    'model_state_verified': verified,
                    'write_audit': audit.summary() if audit else None,
                    'source_version_overwritten': False, 'direct_od_matrix_writes': False,
                    'load_version_called': False, 'production_ready': False})
                if ctl:
                    write_json(folder / 'COM_READ_RETRY.json', com_busy.telemetry(ctl, opt))
            except Exception:
                pass
        raise


def CordonTrialAdapter_factory(guarded, acfg, evaluator, visum, pre, state, folder, cfg, v17status=None):
    kwargs = dict(evaluator=evaluator, raw_visum=visum, expected_zones=pre[2],
                  actuatable_zones=state['actuatable_zones'], folder=folder, live02=cfg)
    if cfg['generation_mode'] == 'V24917_TARGETED_STEP1':
        from .live02_adapter_v24917 import CordonV24917Adapter
        return CordonV24917Adapter(guarded, acfg, v24917_status=v17status, **kwargs)
    from .live02_adapter import CordonTrialAdapter
    return CordonTrialAdapter(guarded, acfg, **kwargs)


def failure_readback(adapter, progress):
    """Read the live state while the run-time scopes are still installed."""
    if not progress.get('model_mutated') or adapter is None or not progress.get('accepted_state_hash'):
        return None
    try:
        live = adapter.snapshot()
        return {'live_state_hash': live['state_hash'], 'expected_last_accepted': progress['accepted_state_hash'],
                'matches_last_accepted_or_baseline': live['state_hash'] == progress['accepted_state_hash']}
    except Exception as exc:
        return {'error': exception_text(exc), 'matches_last_accepted_or_baseline': None}


def make_generation_block(tx, cfg, v17status, folder):
    """Donor search (HOTFIX2 or V24917 targeted) or STEP1; COMBUSY2 retries in V24917 mode."""
    if cfg['generation_mode'] != 'V24917_TARGETED_STEP1':
        return tx.generation_update_once
    com = parent_module('r1_15a2_com_compat')
    cb = parent_module('r1_15a2_combusy2_v24917')
    from .live02_v24917 import run_options
    opts = run_options(cfg)
    tx.ctrl_ns['_rollback_candidate'] = cb._wrap_rollback(tx.ctrl_ns['_rollback_candidate'], com,
                                                          float(opts['cb_max_wait_seconds']))
    if opts['ts_enabled']:
        from .live02_step1 import step1_block

        def generation(adapter, cfg_, folder_, control, state, diag, anchors, reference, policy, outer_cycle=None):
            return step1_block(tx, adapter, cfg_, folder_, control, state, diag, anchors, reference, policy,
                               write_json=write_json)
    else:
        generation = tx.generation_update_once
    return cb._wrap_block(generation, com, 'GENERATION', 1, int(opts['cb_block_retries']))


def write_timing(folder, v17mode):
    if not v17mode:
        return
    try:
        timing = parent_module('r1_15a2_perf_v24917')._STATE['timing']
        write_json(Path(folder) / 'V24917_TIMING.json', {'cumulative_inclusive_seconds': timing})
        print('R1 CORDON V24917 TIMING: ' + ', '.join('%s %.0fs/%d' % (k, v['seconds'], v['calls'])
                                                     for k, v in sorted(timing.items())))
    except Exception:
        pass


class HashCachingRunSession(RunSession):
    """PERF3: SHA-256 of an unchanged artifact (path, size, mtime_ns) is not recomputed."""
    def checkpoint(self, stage, *, completed=False):
        from .session import validate_context, CHECKPOINT
        require(self.folder is not None and self.context is not None, 'RUN_NOT_STARTED')
        validate_context(self.context)
        cache = getattr(self, '_sha_cache', None)
        if cache is None:
            cache = self._sha_cache = {}
        records = []
        for p in sorted(self.folder.rglob('*')):
            if p.is_symlink():
                raise ValueError('SYMLINK_RUN_ARTIFACT')
            if p.is_file() and p.name != CHECKPOINT and not p.name.endswith('.tmp'):
                st = p.stat(); key = (str(p), st.st_size, st.st_mtime_ns)
                if key not in cache:
                    cache[key] = sha256(p)
                records.append({'path': p.relative_to(self.folder).as_posix(), 'bytes': st.st_size, 'sha256': cache[key]})
        self.stages.append(stage)
        state = {'schema': 'CORDON_OFFLINE_CHECKPOINT_V2', 'stage': stage, 'completed': completed,
                 'stages': list(self.stages), 'context': self.context, 'artifacts': records,
                 'apply_permitted': False, 'live_visum_tested': False, 'production_ready': False,
                 'restart_mode': 'VERIFIED_OFFLINE_RESTART_FROM_INPUTS_NOT_SOLVER_CONTINUATION'}
        write_json(self.folder / CHECKPOINT, state)
        return state


def save_accepted_version(visum, folder, state):
    """SaveVersion to a NEW file in the run folder after all verification."""
    rt = parent_module('r1_15a2_runtime_v1')
    source = Path(state['source_version'])
    target = Path(folder) / (source.stem + '_LIVE02_ACCEPTED_' + uuid.uuid4().hex[:8] + source.suffix)
    require(target.resolve() != source.resolve() and not target.exists(), 'LIVE02_SAVE_TARGET_INVALID')
    before_source_hash = sha256(source)
    rt.save_version(visum, target)
    require(sha256(source) == before_source_hash, 'LIVE02_SOURCE_VERSION_CHANGED_BY_SAVE')
    record = {'path': str(target), 'sha256': sha256(target), 'bytes': target.stat().st_size,
              'source_version': str(source), 'source_sha256_unchanged': before_source_hash,
              'note': 'Visum may now report the saved file as the current version.'}
    write_json(Path(folder) / 'SAVED_ACCEPTED_VERSION.json', record)
    return record
