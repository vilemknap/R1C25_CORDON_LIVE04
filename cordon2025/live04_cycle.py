"""LIVE04 orchestration (v7 @ 7b4c681): baseline -> joint TG/SupplyMix/TD cycles -> verified end.

Same flow as LIVE03 (live03_cycle), on the v7 runtime (live04_v7.runtime_scope),
the LIVE04 adapter (MOBILITY2/MOBILITYZONE1, BDPA1, GENFIX2 STEP1) and the v7
LONG post-TD mask.  Additional run-level checks: the baseline LONG support must
already be masked (>= 80 km on 9697) before any write, every accepted state
carries its LONG support audit, and the final state must reproduce it exactly.

Per outer cycle the configured blocks run in order (default GENERATION, then
TD_CORDON); LIVE04.4 runs the v7 SupplyMix block (SUPPLY_ADDVAL1) right after
GENERATION in the cycles where it is due (v7: every 2nd cycle from cycle 2).
Every block gate also applies the v7 SEVRELAX3 limits to the cordon rows.  Each block either keeps an eligible native trial in place or ends
with the donor verified rollback, so the open model is always the last
accepted state or the baseline.  Writes: TG zone attributes, TD gravity b/c,
link ADDVAL1 (SupplyMix), ACTIVE flags of phase plans (restored), Procedures.Execute.  Never LoadVersion,
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
from .live04_guard import Live04GuardedCOM, Live04WriteAudit
from .live02_namespace import DonorTransaction
from .live02_cycle import (LiveControl, isolated_copy_guard, gate_shortcut, failure_readback, write_timing,
                           HashCachingRunSession, _parameter_changes)
from .live04_config import load_config, live01_view, adapter_config, CONFIG_FILE
from .live03_observations import Contract
from .live04_evaluation import Live04Evaluator

RESULT_SCHEMA = 'LIVE04_RESULT_V1'


def _default_output_root():
    if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        return Path(os.environ['LOCALAPPDATA']) / 'R1C25_LIVE04'
    return ROOT / 'OFFLINE_RESULTS' / 'LIVE04'


def make_generation_block(tx, cfg):
    """v7 GENFIX2 STEP1 on the cordon objective; COMBUSY2 rollback/block retries."""
    com = parent_module('r1_15a2_com_compat')
    cb = parent_module('r1_15a2_combusy2_v24917')
    from .live04_v7 import run_options
    from .live04_step1 import step1_block
    opts = run_options(cfg)
    tx.ctrl_ns['_rollback_candidate'] = cb._wrap_rollback(tx.ctrl_ns['_rollback_candidate'], com,
                                                          float(opts['cb_max_wait_seconds']))

    def generation(adapter, cfg_, folder_, control, state, diag, anchors, reference, policy, outer_cycle=None):
        return step1_block(tx, adapter, cfg_, folder_, control, state, diag, anchors, reference, policy,
                           write_json=write_json)
    return cb._wrap_block(generation, com, 'GENERATION', 1, int(opts['cb_block_retries']))


def make_td_block(tx, cfg):
    from .live03_td import td_block
    com = parent_module('r1_15a2_com_compat')
    cb = parent_module('r1_15a2_combusy2_v24917')
    from .live04_v7 import run_options
    opts = run_options(cfg)
    idp_cfg = dict(cfg['idp_guard'], enabled=cfg['idp_guard']['enabled'] and 'TD_CORDON' in cfg['idp_guard']['blocks'])

    def block(adapter, cfg_, folder_, control, state, diag, anchors, reference, policy, outer_cycle=None):
        return td_block(tx, adapter, cfg_, folder_, control, state, diag, anchors, reference, policy,
                        tdc=cfg['td_cordon'], idp_cfg=idp_cfg, memory=getattr(adapter, 'run_memory', None))
    return cb._wrap_block(block, com, 'TD_CORDON', 1, int(opts['cb_block_retries']))


def make_supply_block(tx, cfg):
    """v7 SupplyMix on the cordon rows; COMBUSY2 block retries as the other blocks."""
    com = parent_module('r1_15a2_com_compat')
    cb = parent_module('r1_15a2_combusy2_v24917')
    from .live04_v7 import run_options
    from .live04_supply import supply_block, options
    opts = run_options(cfg)
    sopts = options(cfg)

    def block(adapter, cfg_, folder_, control, state, diag, anchors, reference, policy, outer_cycle=None):
        return supply_block(tx, adapter, cfg_, folder_, control, state, diag, anchors, reference, policy,
                            outer_cycle=outer_cycle, opts=sopts)
    return cb._wrap_block(block, com, 'SUPPLY_ADDVAL1', 1, int(opts['cb_block_retries']))


def _addval_changes(before, after):
    b = before.get('addval1') or {}
    return [{'link': k, 'addval1_run_start': b.get(k), 'addval1_accepted': v}
            for k, v in sorted((after.get('addval1') or {}).items()) if b.get(k) != v]


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
    from .live04_continue import base_stem
    target = Path(folder) / (base_stem(source) + '_LIVE04_ACCEPTED_' + uuid.uuid4().hex[:8] + source.suffix)
    require(target.resolve() != source.resolve() and not target.exists(), 'LIVE04_SAVE_TARGET_INVALID')
    before = sha256(source)
    rt.save_version(visum, target)
    require(sha256(source) == before, 'LIVE04_SOURCE_VERSION_CHANGED_BY_SAVE')
    record = {'path': str(target), 'sha256': sha256(target), 'bytes': target.stat().st_size,
              'source_version': str(source), 'source_sha256_unchanged': before,
              'note': 'Visum may now report the saved file as the current version.'}
    write_json(Path(folder) / 'SAVED_ACCEPTED_VERSION.json', record)
    return record


def _repair(adapter, ctl, bdir, state, diag):
    """Restore the assignment after a stop that interrupted a demand-only probe (stops deferred)."""
    safety = parent_module('r1_15a2_safety_v245')
    try:
        ctl.recovery_depth += 1
        with safety.recovery_scope(ctl, 'LIVE04_ASSIGNMENT_REPAIR_AFTER_STOP'):
            return adapter.repair_assignment(Path(bdir) / 'ASSIGNMENT_REPAIR_AT_STOP', state, diag)
    except BaseException as exc:
        return {'status': 'REPAIR_FAILED', 'error': exception_text(exc)[:500]}
    finally:
        ctl.recovery_depth -= 1


def planned_blocks(cfg, outer):
    """Block order of one outer cycle (v7: SupplyMix right after Generation in due cycles)."""
    from .live04_supply import options as supply_options, due as supply_due
    sopts = supply_options(cfg)
    avail = {'GENERATION'}
    if 'TD_CORDON' in cfg['blocks_per_cycle'] and cfg['td_cordon']['enabled']:
        avail.add('TD_CORDON')
    if sopts['enabled']:
        avail.add('SUPPLY_ADDVAL1')
    names = []
    for name in cfg['blocks_per_cycle']:
        names.append(name)
        if name == 'GENERATION' and sopts['enabled'] and supply_due(outer, sopts)[0]:
            names.append('SUPPLY_ADDVAL1')
    return [n for n in names if n in avail]


def run(visum, *, output_root=None, options=None, config_path=None, config_overrides=None, continuation=False):
    require(visum is not None, 'VISUM_NOT_INJECTED')
    from . import live04_continue as cont
    cfg = load_config(config_path, config_overrides)
    pins = verify_protected_sources()
    output_root = guarded_output_root(output_root or _default_output_root())
    configured = read_json(ROOT / 'CORDON_2025_STARTUP_OPTIONS.json')
    configured.update(options or {})
    from .live04_v7 import run_options
    wait = float(run_options(cfg)['cb_max_wait_seconds'])
    configured['com_retry_max_elapsed_seconds'] = max(float(configured.get('com_retry_max_elapsed_seconds', 0)), wait)
    configured['com_retry_attempts'] = max(int(configured.get('com_retry_attempts', 1)), 1000)
    configured['com_retry_max_delay_seconds'] = max(float(configured.get('com_retry_max_delay_seconds', 0)), 2.0)
    opt = settings(configured)
    require(opt['full_geometry_check'], 'LIVE04_FULL_GEOMETRY_REQUIRED_FOR_BASELINE')
    view = live01_view(cfg, cfg['outer_cycle_start'])
    contract = Contract(cfg['observations'])
    try:
        origin = visum.origin
    except Exception:
        origin = 'NATIVE_INJECTED_VISUM'
    synthetic = isinstance(origin, str) and any(s in origin.upper() for s in ('MOCK', 'SYNTHETIC', 'FIXTURE'))
    execution = 'MOCK' if synthetic else 'NATIVE_INJECTED'
    folder = None; ctl = None; audit = None; adapter = None; v17status = None
    progress = {'accepted_states': 0, 'cycles': [], 'model_mutated': False, 'accepted_by_block': {},
                'checkpoints': []}
    plan = None
    try:
        with HashCachingRunSession('LIVE04_TGTD_' + uuid.uuid4().hex[:12], output_root) as session, \
                contextlib.ExitStack() as stack:
            folder = session.folder
            parent_ctrl = parent_module('r1_15a2_overnight_controller_v24915p2')
            ctl = LiveControl(folder, parent_ctrl.UserStopRequested)
            session.start(cfg, {'live04_config': Path(config_path or ROOT / CONFIG_FILE)})
            write_json(folder / 'LIVE04_SOURCE_PROOF.json', pins)
            write_json(folder / 'EFFECTIVE_CONFIG.json', cfg)
            write_json(folder / 'OBSERVATION_CONTRACT.json', contract.audit)
            with com_busy.parent_hotfix_scope() as hotfix:
                write_json(folder / 'COMBUSY_HOTFIX_ACTIVATION.json', hotfix)
                base_dir = folder / '00_BASELINE'; mkdir(base_dir)
                pre, state = model_preflight(visum, view, base_dir, ctl, opt)
                copy_guard = isolated_copy_guard(cfg, state['source_version'])
                write_json(folder / 'ISOLATED_COPY_GUARD.json', copy_guard)
                if continuation:
                    plan = cont.resolve(state['source_version'], state['source_file_sha256'],
                                        lambda o: planned_blocks(cfg, o), cfg['outer_cycle_start'])
                    write_json(folder / 'CONTINUATION.json', {k: v for k, v in plan.items() if k != 'anchors'})
                progress['bound_state'] = state
                mathcfg = calculation_config(view, state['actuatable_zones'])
                mathcfg['actual_network_sha256'] = pre[0]['network_sha256']
                from .live04_config import row_guard_policy
                evaluator = Live04Evaluator(cfg, mathcfg, contract, opt, ctl, pre, row_guard_policy=row_guard_policy(cfg))
                audit = Live04WriteAudit(folder / 'WRITE_AUDIT.jsonl')
                audit.td_writes = bool(cfg['write_policy']['td_parameter_writes'])
                audit.long_mask_writes = bool(cfg['write_policy']['long_post_td_mask_matrix_writes'])
                audit.supply_addval_writes = bool(cfg['write_policy']['supply_addval1_writes'])
                guarded = Live04GuardedCOM(visum, 'Visum', audit)
                from .live04_v7 import runtime_scope
                v17status = stack.enter_context(runtime_scope(cfg, guarded, pre[2], state['actuatable_zones'], folder))
                mb = parent_module('r1_15a2_multiblock')
                audit.allowed_zone_attrs |= {str(a).upper() for a in mb.GENERATION_ATTRS}
                acfg = adapter_config(cfg, cfg['outer_cycle_start'], state['actuatable_zones'])
                from .live04_adapter import CordonLive04Adapter
                lm = cfg['v7']['long_post_td_mask']
                from .live04_supply import options as supply_options, sealed_supply_policy
                sopts = supply_options(cfg)
                adapter = CordonLive04Adapter(guarded, acfg, v24917_status=v17status, evaluator=evaluator, raw_visum=visum,
                                              long_mask=lm['enabled'],
                                              supply_policy=sealed_supply_policy() if sopts['enabled'] else None,
                                              supply_reset_position=sopts['reset_position'],
                                              expected_zones=pre[2], actuatable_zones=state['actuatable_zones'],
                                              folder=folder, live02=cfg)
                session.checkpoint('LIVE04_CURRENT_MODEL_BOUND')
                baseline = evaluator.evaluate(visum, folder / '01_BASELINE_CAPTURE', 'BASELINE', full_geometry=True, keep_db=True)
                snap0 = adapter.snapshot()
                require(not audit.events or all(e['kind'] == 'READ_LIST_CREATE' for e in audit.events),
                        'LIVE04_BASELINE_MUTATED_MODEL')
                long_support0 = None
                if lm['enabled']:
                    long_support0 = adapter.long_support(folder, 'BASELINE')
                    require(long_support0['support_clean'] or not lm['require_masked_baseline'],
                            'LIVE04_BASELINE_LONG_SUPPORT_NOT_MASKED:person_below_80km=%.6g;vehicle_clean=%s'
                            % (long_support0['person']['below_min_km'], long_support0['vehicle_support_clean']))
                    adapter.accept_long_support(long_support0)
                write_json(folder / 'RESTORE_POINT.json', {
                    'schema': 'LIVE04_RESTORE_POINT_V1', 'snapshot': snap0, 'state_hash': snap0['state_hash'],
                    'baseline_diagnostic_hash': baseline['diagnostic_hash'],
                    'method': 'DONOR_PARAMETER_RESTORE_PLUS_NATIVE_RECOMPUTE_NO_LOADVERSION',
                    'source_version': state['source_version'], 'source_file_sha256': state['source_file_sha256']})
                adapter.set_generation_reference(snap0, folder)
                if sopts['enabled']:
                    # Cumulative ADDVAL1 bounds are relative to the run start (donor baseline anchors).
                    adapter.baseline_addval = {k: r['addval1'] for k, r in adapter.read_links().items()}
                    require(adapter.snapshot() == snap0, 'LIVE04_SUPPLY_BASELINE_READ_CHANGED_MODEL')
                if plan is not None and plan['kind'] == 'STATE_MATCH_PENDING':
                    plan = cont.resolve_by_state(plan, snap0, output_root, lambda o: planned_blocks(cfg, o),
                                                 cfg['outer_cycle_start'], current_folder=folder)
                    require(plan['expected_state_hash'] == snap0['state_hash'], 'LIVE04_CONTINUE_STATE_MATCH')
                if plan is not None:
                    anchors = dict(plan['anchors'], chain=list(plan['anchors'].get('chain') or []) +
                                   [{'run_folder': plan['previous_run_folder'], 'kind': plan['kind']}])
                    plan['opened_state'] = cont.verify_opened_state(plan, snap0)
                    plan['anchors_applied'] = cont.apply_anchors(adapter, anchors, folder)
                    write_json(folder / 'CONTINUATION.json', {k: v for k, v in plan.items() if k != 'anchors'})
                else:
                    anchors = cont.anchors_from_snapshot(snap0, folder, state['source_version'], cfg['outer_cycle_start'])
                write_json(folder / cont.ANCHORS_FILE, anchors)
                from .live04_memory import RunMemory
                adapter.run_memory = RunMemory(cfg['memory'], folder / 'MEMORY') if cfg['memory']['enabled'] else None
                reference = evaluator.reference(baseline)
                write_json(folder / 'BASELINE_OBJECTIVE.json', {m: baseline['methods'][m]['metrics'] for m in baseline['methods']})
                gs = cfg['generation_search']
                tx = DonorTransaction(evaluator.ledger, evaluator.diagnostic_hash,
                                      gate_nonfatal=gs['pre_apply_gate_nonfatal'],
                                      outer_wrap=gate_shortcut if gs['pre_apply_gate_shortcut'] else None)
                write_json(folder / 'DONOR_TRANSACTION_IDENTITY.json', tx.identity())
                blocks = {'GENERATION': make_generation_block(tx, cfg)}
                if 'TD_CORDON' in cfg['blocks_per_cycle'] and cfg['td_cordon']['enabled']:
                    blocks['TD_CORDON'] = make_td_block(tx, cfg)
                if sopts['enabled']:
                    blocks['SUPPLY_ADDVAL1'] = make_supply_block(tx, cfg)
                from .live04_supply import due as supply_due
                session.checkpoint('LIVE04_BASELINE_AND_RESTORE_POINT_SEALED')
                current_state, current_diag = snap0, baseline
                progress['accepted_state_hash'] = snap0['state_hash']
                ckcfg = cfg['checkpoint']
                origin_start = int(anchors.get('origin_outer_cycle_start', cfg['outer_cycle_start']))
                first_outer = plan['outer_cycle'] if plan else cfg['outer_cycle_start']
                last_outer = origin_start + cfg['max_cycles'] - 1
                require(first_outer <= last_outer, 'LIVE04_CONTINUE_NO_CYCLE_LEFT_RAISE_MAX_CYCLES:next=%d,last=%d'
                        % (first_outer, last_outer))
                for outer in range(first_outer, last_outer + 1):
                    adapter.cfg = adapter_config(cfg, outer, state['actuatable_zones'])
                    if adapter.run_memory is not None:
                        adapter.run_memory.begin_cycle(outer)
                    cycle = {'outer_cycle': outer, 'blocks': []}
                    changed_cycle = False
                    names = planned_blocks(cfg, outer)      # v7: SupplyMix right after Generation
                    require(all(n in blocks for n in names), 'LIVE04_PLANNED_BLOCK_NOT_BUILT')
                    skip = 0
                    if plan and outer == plan['outer_cycle']:
                        skip = plan['block_index']; changed_cycle = plan['changed_so_far']
                        cycle['continued_from_block_index'] = skip
                    for index, name in enumerate(names):
                        if index < skip:
                            continue
                        bdir = folder / ('C%02d_%s' % (outer, name))
                        progress['model_mutated'] = True
                        try:
                            changed, current_state, current_diag, value, rec = blocks[name](
                                adapter, adapter.cfg, bdir, ctl, current_state, current_diag, {}, reference, None,
                                outer_cycle=outer)
                        except BaseException:
                            progress['failure_readback'] = failure_readback(adapter, progress)
                            if getattr(adapter, 'assignment_invalidated', False) and \
                                    (progress['failure_readback'] or {}).get('matches_last_accepted_or_baseline'):
                                progress['assignment_repair'] = _repair(adapter, ctl, bdir, current_state, current_diag)
                            raise
                        finally:
                            write_timing(bdir, True)
                            if adapter.run_memory is not None:
                                adapter.run_memory.save()
                        progress['accepted_state_hash'] = current_state['state_hash']
                        repair = None
                        if getattr(adapter, 'assignment_invalidated', False):
                            repair = adapter.repair_assignment(bdir / 'ASSIGNMENT_REPAIR', current_state, current_diag)
                        entry = {'block': name, 'status': rec.get('status'), 'changed': bool(changed),
                                 'objective_before': (rec.get('objective_before') or {}).get('total'),
                                 'objective_after': (rec.get('objective_after') or {}).get('total'),
                                 'stop_reason': rec.get('stop_reason'),
                                 'native_prediction': bool(rec.get('native_prediction') or rec.get('base_parity'))}
                        if repair is not None:
                            entry['assignment_repair'] = repair['status']
                        cycle['blocks'].append(entry)
                        if changed:
                            if lm['enabled']:
                                accepted_support = adapter.long_support_last_trial
                                require(accepted_support is not None and accepted_support['support_clean'],
                                        'LIVE04_ACCEPTED_STATE_LONG_SUPPORT_UNVERIFIED')
                                adapter.accept_long_support(accepted_support)
                            changed_cycle = True
                            progress['accepted_states'] += 1
                            progress['accepted_by_block'][name] = progress['accepted_by_block'].get(name, 0) + 1
                            write_json(bdir / 'ACCEPTED_STATE.json', {
                                'schema': 'LIVE04_ACCEPTED_STATE_V1', 'outer_cycle': outer, 'block': name,
                                'snapshot_state_hash': current_state['state_hash'],
                                'diagnostic_hash': current_diag['diagnostic_hash'], 'ledger': value})
                            if ckcfg['enabled']:
                                nxt = dict(cont.next_position(names, index, outer),
                                           cycle_changed_so_far=bool(index + 1 < len(names) and changed_cycle))
                                try:
                                    rec_ck = cont.save_checkpoint(visum, adapter, folder, state, current_state, outer,
                                                                  name, nxt, progress['accepted_states'],
                                                                  ckcfg['keep_last'])
                                    entry['checkpoint'] = Path(rec_ck['path']).name
                                    progress['checkpoints'].append({'path': rec_ck['path'], 'block': name,
                                                                    'outer_cycle': outer})
                                except Exception as ck_exc:
                                    if 'NOT_AT_ACCEPTED_STATE' in str(ck_exc):
                                        raise
                                    entry['checkpoint_error'] = exception_text(ck_exc)[:500]
                        write_json(folder / 'CYCLE_PROGRESS.json', dict(progress, cycles=progress['cycles'] + [cycle]))
                    progress['cycles'].append(cycle)
                    write_json(folder / 'CYCLE_PROGRESS.json', progress)
                    if not changed_cycle and cfg['stop_after_cycle_without_change']:
                        break
                ctl.checkpoint('LIVE04_FINAL_VERIFICATION', force=True)
                final = adapter.snapshot()
                require(final == current_state, 'LIVE04_FINAL_STATE_NOT_LAST_ACCEPTED_OR_BASELINE')
                long_final = None
                if lm['enabled']:
                    long_final = adapter.long_support(folder, 'FINAL')
                    accepted_support = adapter.long_support_accepted
                    require(long_final['support_clean'] and long_final['person_sha256'] == accepted_support['person_sha256']
                            and {k: v['sha256'] for k, v in long_final['vehicle'].items()}
                            == {k: v['sha256'] for k, v in accepted_support['vehicle'].items()},
                            'LIVE04_FINAL_LONG_SUPPORT_NOT_LAST_ACCEPTED')
                tg_changes = _parameter_changes(snap0, final, adapter.zones)
                td_changes = _td_changes(snap0, final)
                addval_changes = _addval_changes(snap0, final)
                write_csv(folder / 'ACCEPTED_ADDVAL1.csv', addval_changes, ['link', 'addval1_run_start', 'addval1_accepted'])
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
                          'status': ('MOCK_' if synthetic else 'NATIVE_') + 'LIVE04_' +
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
                          'changed_addval1_links': len(addval_changes),
                          'supply_mix': {'enabled': sopts['enabled'], 'every_n_cycles': sopts['every_n'],
                                         'start_cycle': sopts['start_cycle'], 'max_groups': sopts['max_groups'],
                                         'max_edges': sopts['max_edges'], 'max_trials': sopts['max_trials'],
                                         'step_units': sopts['step_units'],
                                         'addval1_writes': audit.summary().get('supply_addval1_writes', 0)},
                          'row_geh_guard': evaluator.row_guard_policy,
                          'model_state': 'LAST_ACCEPTED_STATE_IN_OPEN_VISUM' if progress['accepted_states'] else 'BASELINE_RESTORED',
                          'saved_version': saved, 'source_version_overwritten': False,
                          'direct_od_matrix_writes': False, 'load_version_called': False,
                          'write_audit': audit.summary()['counts'], 'gate_events': len(tx.gate_events),
                          'evaluations': evaluator.count, 'real_visum_verified': not synthetic, 'production_ready': False,
                          'observation_contract_sha256': contract.audit['contract_sha256'],
                          'observation_semantics': 'FIRST_LAST_TRANSIT_PAIRS_PLUS_C17_STATION_MARGINS' + ('_PLUS_STATION_PROFILES' if contract.profile_cells else ''),
                          'year_bridge_factor': contract.factor,
                          'prediction': ('NATIVE_DEMAND_ON_FROZEN_PATHS' if cfg['native_prediction']['enabled']
                                         else 'GENFIX2_FINAL_EFFECT_LINEAR'),
                          'v7_source': {'repository': cfg['v7']['source_repository'],
                                        'commit': cfg['v7']['source_commit']},
                          'mobility_band': [v17status['mobility']['lo'], v17status['mobility']['hi']],
                          'ws_attraction_band': v17status['mobility']['ws_attraction_coefficient_band'],
                          'generation_counts': dict(adapter.v24917_counts),
                          'long_post_td_mask': {'enabled': lm['enabled'],
                                                'baseline': {k: (long_support0 or {}).get(k) for k in ('support_clean',)},
                                                'final_support_clean': (long_final or {}).get('support_clean'),
                                                'matrix_writes': audit.summary()['long_mask_matrix_writes']},
                          'step1': {k: step_state.get(k) for k in ('rho', 'rho_history', 'blocks', 'trials', 'kept', 'exhausted')},
                          'timing': copy.deepcopy(parent_module('r1_15a2_perf_v24917')._STATE['timing']),
                          'memory': (adapter.run_memory.summary() if adapter.run_memory is not None
                                     else {'enabled': False})}
                write_json(folder / '00_RESULT.json', result)
                write_json(folder / 'COM_READ_RETRY.json', com_busy.telemetry(ctl, opt))
            session.checkpoint('LIVE04_COMPLETE', completed=True)
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
                kind = 'LIVE04_BLOCKED_BEFORE_ANY_WRITE'
            elif verified is True:
                kind = 'LIVE04_STOPPED_MODEL_VERIFIED_AT_LAST_ACCEPTED_STATE'
            else:
                kind = 'LIVE04_STOPPED_MODEL_STATE_NOT_VERIFIED_REOPEN_SOURCE_OR_SAVED_VERSION'
            saved_at_stop = None
            repair_stop = progress.get('assignment_repair')
            # parameters may be fine, but without a valid assignment a saved .ver would have no paths
            assignment_ok = repair_stop is None or repair_stop.get('status') == 'REPAIRED_VERIFIED'
            # LIVE04.5.2: keep the accepted progress of a stopped run (STOP_REQUESTED, a block
            # error, ...) - but only when the open model was read back AT the last accepted state.
            if verified is True and assignment_ok and progress['accepted_states'] and progress.get('bound_state') \
                    and cfg['write_policy'].get('save_accepted_version_new_file'):
                try:
                    saved_at_stop = save_accepted_version(visum, folder, progress['bound_state'])
                except BaseException as save_exc:
                    saved_at_stop = {'error': type(save_exc).__name__ + ':' + str(save_exc)[:500]}
            try:
                cp = read_json(folder / 'RUN_CHECKPOINT.json')
                cp.update(completed=False, stage='LIVE04_FAILED', failure_reason=text)
                write_json(folder / 'RUN_CHECKPOINT.json', cp)
            except Exception:
                pass
            try:
                write_text(folder / '99_TRACEBACK.txt', traceback.format_exc())
                write_json(folder / '00_RESULT.json', {
                    'schema': RESULT_SCHEMA, 'status': kind, 'reason': text, 'execution_kind': execution,
                    'accepted_states': progress['accepted_states'], 'cycles': progress['cycles'],
                    'model_state_verified': verified, 'saved_version_at_stop': saved_at_stop,
                    'assignment_repair_at_stop': repair_stop,
                    'write_audit': audit.summary() if audit else None,
                    'source_version_overwritten': False, 'direct_od_matrix_writes': False,
                    'load_version_called': False, 'production_ready': False})
                if ctl:
                    write_json(folder / 'COM_READ_RETRY.json', com_busy.telemetry(ctl, opt))
            except Exception:
                pass
        raise
