"""LIVE03 orchestration: survey-semantics baseline -> joint TG/TD cycles -> verified end.

Per outer cycle the configured blocks run in order (default GENERATION, then
TD_CORDON).  Each block either keeps an eligible native trial in place or ends
with the donor verified rollback, so the open model is always the last
accepted state or the baseline.  Writes: TG zone attributes, TD gravity b/c,
ACTIVE flags of phase plans (restored), Procedures.Execute.  Never LoadVersion,
never a direct OD matrix write, never the source .ver.
"""
from __future__ import annotations
import contextlib
import copy
import os
import traceback
import uuid
from pathlib import Path
from .common import ROOT, require, read_json, parent_module
from .io import write_json, write_csv, write_text, mkdir, exception_text, safe_failure_report
from . import com_busy
from .visum_startup import settings
from .live01_visum import model_preflight
from .live01_provenance import verify_protected_sources, guarded_output_root
from .live01_config import calculation_config
from .live02_guard import GuardedCOM, WriteAudit
from .live02_namespace import DonorTransaction
from .live02_cycle import (LiveControl, isolated_copy_guard, gate_shortcut, failure_readback, write_timing,
                           HashCachingRunSession, make_generation_block, _parameter_changes)
from .live03_config import load_config, live01_view, adapter_config, CONFIG_FILE
from .live03_observations import Contract
from .live03_evaluation import Live03Evaluator

RESULT_SCHEMA = 'LIVE03_RESULT_V1'


def _default_output_root():
    if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        return Path(os.environ['LOCALAPPDATA']) / 'R1C25_LIVE03'
    return ROOT / 'OFFLINE_RESULTS' / 'LIVE03'


def make_td_block(tx, cfg):
    from .live03_td import td_block
    com = parent_module('r1_15a2_com_compat')
    cb = parent_module('r1_15a2_combusy2_v24917')
    from .live02_v24917 import run_options
    opts = run_options(cfg)
    idp_cfg = dict(cfg['idp_guard'], enabled=cfg['idp_guard']['enabled'] and 'TD_CORDON' in cfg['idp_guard']['blocks'])

    def block(adapter, cfg_, folder_, control, state, diag, anchors, reference, policy, outer_cycle=None):
        return td_block(tx, adapter, cfg_, folder_, control, state, diag, anchors, reference, policy,
                        tdc=cfg['td_cordon'], idp_cfg=idp_cfg)
    return cb._wrap_block(block, com, 'TD_CORDON', 1, int(opts['cb_block_retries']))


def _td_changes(before, after):
    b = {r['component']: r for r in before['td_values']}
    out = []
    for r in after['td_values']:
        o = b[r['component']]
        if (o['current_b'], o['current_c']) != (r['current_b'], r['current_c']):
            out.append({'component': r['component'], 'b_run_start': o['current_b'], 'b_accepted': r['current_b'],
                        'c_run_start': o['current_c'], 'c_accepted': r['current_c']})
    return out


def save_accepted_version(visum, folder, state):
    """SaveVersion to a NEW file in the run folder after all verification."""
    from .io import sha256
    rt = parent_module('r1_15a2_runtime_v1')
    source = Path(state['source_version'])
    target = Path(folder) / (source.stem + '_LIVE03_ACCEPTED_' + uuid.uuid4().hex[:8] + source.suffix)
    require(target.resolve() != source.resolve() and not target.exists(), 'LIVE03_SAVE_TARGET_INVALID')
    before = sha256(source)
    rt.save_version(visum, target)
    require(sha256(source) == before, 'LIVE03_SOURCE_VERSION_CHANGED_BY_SAVE')
    record = {'path': str(target), 'sha256': sha256(target), 'bytes': target.stat().st_size,
              'source_version': str(source), 'source_sha256_unchanged': before,
              'note': 'Visum may now report the saved file as the current version.'}
    write_json(Path(folder) / 'SAVED_ACCEPTED_VERSION.json', record)
    return record


def run(visum, *, output_root=None, options=None, config_path=None, config_overrides=None):
    require(visum is not None, 'VISUM_NOT_INJECTED')
    cfg = load_config(config_path, config_overrides)
    pins = verify_protected_sources()
    output_root = guarded_output_root(output_root or _default_output_root())
    configured = read_json(ROOT / 'CORDON_2025_STARTUP_OPTIONS.json')
    configured.update(options or {})
    from .live02_v24917 import run_options
    wait = float(run_options(cfg)['cb_max_wait_seconds'])
    configured['com_retry_max_elapsed_seconds'] = max(float(configured.get('com_retry_max_elapsed_seconds', 0)), wait)
    configured['com_retry_attempts'] = max(int(configured.get('com_retry_attempts', 1)), 1000)
    configured['com_retry_max_delay_seconds'] = max(float(configured.get('com_retry_max_delay_seconds', 0)), 2.0)
    opt = settings(configured)
    require(opt['full_geometry_check'], 'LIVE03_FULL_GEOMETRY_REQUIRED_FOR_BASELINE')
    view = live01_view(cfg, cfg['outer_cycle_start'])
    contract = Contract(cfg['observations'])
    try:
        origin = visum.origin
    except Exception:
        origin = 'NATIVE_INJECTED_VISUM'
    synthetic = isinstance(origin, str) and any(s in origin.upper() for s in ('MOCK', 'SYNTHETIC', 'FIXTURE'))
    execution = 'MOCK' if synthetic else 'NATIVE_INJECTED'
    folder = None; ctl = None; audit = None; adapter = None; v17status = None
    progress = {'accepted_states': 0, 'cycles': [], 'model_mutated': False, 'accepted_by_block': {}}
    try:
        with HashCachingRunSession('LIVE03_TGTD_' + uuid.uuid4().hex[:12], output_root) as session, \
                contextlib.ExitStack() as stack:
            folder = session.folder
            parent_ctrl = parent_module('r1_15a2_overnight_controller_v24915p2')
            ctl = LiveControl(folder, parent_ctrl.UserStopRequested)
            session.start(cfg, {'live03_config': Path(config_path or ROOT / CONFIG_FILE)})
            write_json(folder / 'LIVE03_SOURCE_PROOF.json', pins)
            write_json(folder / 'EFFECTIVE_CONFIG.json', cfg)
            write_json(folder / 'OBSERVATION_CONTRACT.json', contract.audit)
            with com_busy.parent_hotfix_scope() as hotfix:
                write_json(folder / 'COMBUSY_HOTFIX_ACTIVATION.json', hotfix)
                base_dir = folder / '00_BASELINE'; mkdir(base_dir)
                pre, state = model_preflight(visum, view, base_dir, ctl, opt)
                copy_guard = isolated_copy_guard(cfg, state['source_version'])
                write_json(folder / 'ISOLATED_COPY_GUARD.json', copy_guard)
                mathcfg = calculation_config(view, state['actuatable_zones'])
                mathcfg['actual_network_sha256'] = pre[0]['network_sha256']
                evaluator = Live03Evaluator(cfg, mathcfg, contract, opt, ctl, pre)
                audit = WriteAudit(folder / 'WRITE_AUDIT.jsonl')
                audit.td_writes = bool(cfg['write_policy']['td_parameter_writes'])
                guarded = GuardedCOM(visum, 'Visum', audit)
                from .live02_v24917 import runtime_scope
                v17status = stack.enter_context(runtime_scope(cfg, guarded, pre[2], state['actuatable_zones'], folder))
                mb = parent_module('r1_15a2_multiblock')
                audit.allowed_zone_attrs |= {str(a).upper() for a in mb.GENERATION_ATTRS}
                acfg = adapter_config(cfg, cfg['outer_cycle_start'], state['actuatable_zones'])
                from .live03_adapter import CordonLive03Adapter
                adapter = CordonLive03Adapter(guarded, acfg, v24917_status=v17status, evaluator=evaluator, raw_visum=visum,
                                              expected_zones=pre[2], actuatable_zones=state['actuatable_zones'],
                                              folder=folder, live02=cfg)
                session.checkpoint('LIVE03_CURRENT_MODEL_BOUND')
                baseline = evaluator.evaluate(visum, folder / '01_BASELINE_CAPTURE', 'BASELINE', full_geometry=True, keep_db=True)
                snap0 = adapter.snapshot()
                require(not audit.events or all(e['kind'] == 'READ_LIST_CREATE' for e in audit.events),
                        'LIVE03_BASELINE_MUTATED_MODEL')
                write_json(folder / 'RESTORE_POINT.json', {
                    'schema': 'LIVE03_RESTORE_POINT_V1', 'snapshot': snap0, 'state_hash': snap0['state_hash'],
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
                blocks = {'GENERATION': make_generation_block(tx, cfg, v17status, folder)}
                if 'TD_CORDON' in cfg['blocks_per_cycle'] and cfg['td_cordon']['enabled']:
                    blocks['TD_CORDON'] = make_td_block(tx, cfg)
                session.checkpoint('LIVE03_BASELINE_AND_RESTORE_POINT_SEALED')
                current_state, current_diag = snap0, baseline
                progress['accepted_state_hash'] = snap0['state_hash']
                for k in range(cfg['max_cycles']):
                    outer = cfg['outer_cycle_start'] + k
                    adapter.cfg = adapter_config(cfg, outer, state['actuatable_zones'])
                    cycle = {'outer_cycle': outer, 'blocks': []}
                    changed_cycle = False
                    for name in cfg['blocks_per_cycle']:
                        if name not in blocks:
                            continue
                        bdir = folder / ('C%02d_%s' % (outer, name))
                        progress['model_mutated'] = True
                        try:
                            changed, current_state, current_diag, value, rec = blocks[name](
                                adapter, adapter.cfg, bdir, ctl, current_state, current_diag, {}, reference, None,
                                outer_cycle=outer)
                        except BaseException:
                            progress['failure_readback'] = failure_readback(adapter, progress)
                            raise
                        finally:
                            write_timing(bdir, True)
                        progress['accepted_state_hash'] = current_state['state_hash']
                        entry = {'block': name, 'status': rec.get('status'), 'changed': bool(changed),
                                 'objective_before': (rec.get('objective_before') or {}).get('total'),
                                 'objective_after': (rec.get('objective_after') or {}).get('total'),
                                 'stop_reason': rec.get('stop_reason'),
                                 'native_prediction': bool(rec.get('native_prediction') or rec.get('base_parity'))}
                        cycle['blocks'].append(entry)
                        if changed:
                            changed_cycle = True
                            progress['accepted_states'] += 1
                            progress['accepted_by_block'][name] = progress['accepted_by_block'].get(name, 0) + 1
                            write_json(bdir / 'ACCEPTED_STATE.json', {
                                'schema': 'LIVE03_ACCEPTED_STATE_V1', 'outer_cycle': outer, 'block': name,
                                'snapshot_state_hash': current_state['state_hash'],
                                'diagnostic_hash': current_diag['diagnostic_hash'], 'ledger': value})
                        write_json(folder / 'CYCLE_PROGRESS.json', dict(progress, cycles=progress['cycles'] + [cycle]))
                    progress['cycles'].append(cycle)
                    write_json(folder / 'CYCLE_PROGRESS.json', progress)
                    if not changed_cycle and cfg['stop_after_cycle_without_change']:
                        break
                ctl.checkpoint('LIVE03_FINAL_VERIFICATION', force=True)
                final = adapter.snapshot()
                require(final == current_state, 'LIVE03_FINAL_STATE_NOT_LAST_ACCEPTED_OR_BASELINE')
                tg_changes = _parameter_changes(snap0, final, adapter.zones)
                td_changes = _td_changes(snap0, final)
                write_csv(folder / 'ACCEPTED_TG_PARAMETERS.csv', tg_changes, ['zone_no', 'attr', 'run_start', 'accepted', 'ratio'])
                write_csv(folder / 'ACCEPTED_TD_PARAMETERS.csv', td_changes,
                          ['component', 'b_run_start', 'b_accepted', 'c_run_start', 'c_accepted'])
                saved = None
                if progress['accepted_states'] and cfg['write_policy']['save_accepted_version_new_file']:
                    saved = save_accepted_version(visum, folder, state)
                write_json(folder / 'WRITE_AUDIT_SUMMARY.json', audit.summary())
                m = cfg['acceptance']['method']
                step_state = parent_module('r1_15a2_step_search_v24917')._STATE
                result = {'schema': RESULT_SCHEMA,
                          'status': ('MOCK_' if synthetic else 'NATIVE_') + 'LIVE03_' +
                                    ('ACCEPTED' if progress['accepted_states'] else 'NO_ACCEPTED_CHANGE'),
                          'execution_kind': execution, 'output_directory': str(folder),
                          'accepted_states': progress['accepted_states'], 'accepted_by_block': progress['accepted_by_block'],
                          'cycles': progress['cycles'], 'acceptance_method': m,
                          'secondary_method': cfg['acceptance']['secondary_method'],
                          'objective_baseline': baseline['methods'][m]['objective'],
                          'objective_final': current_diag['methods'][m]['objective'],
                          'metrics_baseline': {k: baseline['methods'][k]['metrics'] for k in baseline['methods']},
                          'metrics_final': {k: current_diag['methods'][k]['metrics'] for k in current_diag['methods']},
                          'changed_tg_parameters': len(tg_changes), 'changed_td_components': len(td_changes),
                          'model_state': 'LAST_ACCEPTED_STATE_IN_OPEN_VISUM' if progress['accepted_states'] else 'BASELINE_RESTORED',
                          'saved_version': saved, 'source_version_overwritten': False,
                          'direct_od_matrix_writes': False, 'load_version_called': False,
                          'write_audit': audit.summary()['counts'], 'gate_events': len(tx.gate_events),
                          'evaluations': evaluator.count, 'real_visum_verified': not synthetic, 'production_ready': False,
                          'observation_contract_sha256': contract.audit['contract_sha256'],
                          'observation_semantics': 'FIRST_LAST_TRANSIT_PAIRS_PLUS_C17_STATION_MARGINS',
                          'year_bridge_factor': contract.factor,
                          'prediction': 'NATIVE_DEMAND_ON_FROZEN_PATHS' if cfg['native_prediction']['enabled'] else 'LINEAR_V24917',
                          'step1': {k: step_state.get(k) for k in ('rho', 'rho_history', 'blocks', 'trials', 'kept', 'exhausted')},
                          'timing': copy.deepcopy(parent_module('r1_15a2_perf_v24917')._STATE['timing'])}
                write_json(folder / '00_RESULT.json', result)
                write_json(folder / 'COM_READ_RETRY.json', com_busy.telemetry(ctl, opt))
            session.checkpoint('LIVE03_COMPLETE', completed=True)
            return result
    except BaseException as exc:
        if folder:
            safe_failure_report(folder, exc, traceback_text=traceback.format_exc())
            text = exception_text(exc)
            readback = progress.get('failure_readback')
            verified = (readback or {}).get('matches_last_accepted_or_baseline')
            try:
                write_json(folder / 'FAILURE_STATE_READBACK.json', readback or {'status': 'NOT_READ'})
            except Exception:
                pass
            if not progress['model_mutated']:
                kind = 'LIVE03_BLOCKED_BEFORE_ANY_WRITE'
            elif verified is True:
                kind = 'LIVE03_STOPPED_MODEL_VERIFIED_AT_LAST_ACCEPTED_STATE'
            else:
                kind = 'LIVE03_STOPPED_MODEL_STATE_NOT_VERIFIED_REOPEN_SOURCE_OR_SAVED_VERSION'
            try:
                cp = read_json(folder / 'RUN_CHECKPOINT.json')
                cp.update(completed=False, stage='LIVE03_FAILED', failure_reason=text)
                write_json(folder / 'RUN_CHECKPOINT.json', cp)
            except Exception:
                pass
            try:
                write_text(folder / '99_TRACEBACK.txt', traceback.format_exc())
                write_json(folder / '00_RESULT.json', {
                    'schema': RESULT_SCHEMA, 'status': kind, 'reason': text, 'execution_kind': execution,
                    'accepted_states': progress['accepted_states'], 'cycles': progress['cycles'],
                    'model_state_verified': verified, 'write_audit': audit.summary() if audit else None,
                    'source_version_overwritten': False, 'direct_od_matrix_writes': False,
                    'load_version_called': False, 'production_ready': False})
                if ctl:
                    write_json(folder / 'COM_READ_RETRY.json', com_busy.telemetry(ctl, opt))
            except Exception:
                pass
        raise
