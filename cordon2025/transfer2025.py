"""R1 2022 -> 2025 parameter transfer and LIVE04 readiness check (TRANSFER2025).

Three actions, each its own Visum entry script:

EXPORT    (open: the calibrated 2022 version, read-only)
          Reads the calibrated parameters and writes R1_2022_CALIBRATED_PARAMETERS.json:
          zone coefficients by group (W/S ADD_*, ZAHR_*, ADD_SALARY, LONG/SCHOOL ADD_*,
          optional boundary P/A volumes), TD gravity b/c of every component and the
          ADDVAL1 of every link (key NO:FROMNODENO:TONODENO).  No COM write at all.

IMPORT    (open: an ISOLATED COPY of the 2025 model)
          1. validates the export file (schema, content hash) and maps zones by NO and
             links by key, complete plan written BEFORE the first write;
          2. writes only the planned zone attributes, TD b/c and ADDVAL1 with readback;
          3. recomputes once with the v7 sequence (PERF1 GENERATION plan: TG -> TD ->
             LONG person mask -> 20A/20B -> LONG vehicle mask -> 17-19 + 20), checks
             that no operation overwrote the transferred parameters;
          4. requires a clean LONG support (>= 80 km on 9697);
          5. saves a NEW version <copy>_LIVE04_BASE_<id>.ver (the open file is never
             overwritten, LoadVersion is never called);
          6. runs READINESS on the result.

READINESS (open: any 2025 version, read-only)
          Everything the LIVE04 cordon run requires before its first write: release
          pins, LIVE01 model preflight (681 zones, network, demand segments, paths),
          isolated-copy name, operations 17-20 / single TD, matrices 9697 / 9111-9115 /
          9291-9295 (DATA) / 9305 (FORMULA), clean LONG support, MOBILITY2 /
          MOBILITYZONE1 authority, optional parameter identity with an export file and
          optional full cordon baseline capture (objective of every method).

Writes allowed by the TRANSFER guard: the LIVE04 policy (zone TG attributes, TD b/c,
ACTIVE flags, Procedures.Execute, LONG mask matrices) + ADDVAL1 of links +
SaveVersion to the one approved new path.  Never a direct demand OD write.
"""
from __future__ import annotations
import math
import os
import traceback
import uuid
from pathlib import Path
from .common import ROOT, require, read_json, parent_module, canonical_hash, sha256
from .io import write_json, mkdir, exception_text
from .live04_guard import Live04GuardedCOM, Live04WriteAudit, _policy as _live04_policy, WriteForbidden
from .live02_adapter import CordonTrialAdapter

EXPORT_SCHEMA = 'R1_2022_CALIBRATED_PARAMETERS_V1'
CONFIG_FILE = 'TRANSFER_2025_CONFIG.json'
CONFIG_SCHEMA = 'R1_TRANSFER_2022_2025_CONFIG_V1'
EXPORT_NAME = 'R1_2022_CALIBRATED_PARAMETERS.json'
REQUIRED_GROUPS = ('ws_coefficients', 'zahr_coefficients', 'salary')
ZONE_POLICIES = ('REQUIRE_IDENTICAL_ZONE_SET', 'MATCHING_ZONES_ONLY')
LINK_POLICIES = ('MATCHING_LINK_KEYS_ONLY', 'FAIL_ON_UNMATCHED_NONZERO')


def attribute_groups():
    lsgen = parent_module('r1_15a2_long_school_generation_v24917')
    bdgen = parent_module('r1_15a2_boundary_generation_v24917')
    mb = parent_module('r1_15a2_multiblock')
    groups = {'ws_coefficients': ['ADD_PROD_W', 'ADD_ATT_W', 'ADD_PROD_S', 'ADD_ATT_S'],
              'zahr_coefficients': ['ZAHR_PROD_WORK', 'ZAHR_ATR_WORK', 'ZAHR_PROD_SERV', 'ZAHR_ATR_SERV'],
              'salary': ['ADD_SALARY'],
              'long_school': list(lsgen.ATTRS),
              'boundary_pa_volumes': list(bdgen.ALL_ATTRS)}
    base = {a for g in REQUIRED_GROUPS for a in groups[g]}
    require(base <= {str(a).upper() for a in mb.GENERATION_ATTRS}, 'TRANSFER_GENERATION_ATTRIBUTE_SET_DRIFT')
    return groups


def link_key(no, frm, to):
    return '%d:%d:%d' % (int(no), int(frm), int(to))


# ------------------------------------------------------------------ config
def load_transfer_config(path=None, overrides=None):
    from .live02_config import merge
    cfg = read_json(path or ROOT / CONFIG_FILE)
    if overrides:
        cfg = merge(cfg, overrides)
    require(cfg.get('schema') == CONFIG_SCHEMA, 'TRANSFER_CONFIG_SCHEMA')
    require(set(cfg) == set(read_json(ROOT / CONFIG_FILE)), 'TRANSFER_CONFIG_FIELDS')
    require(cfg['zone_policy'] in ZONE_POLICIES, 'TRANSFER_ZONE_POLICY')
    require(cfg['addval1_policy'] in LINK_POLICIES, 'TRANSFER_ADDVAL1_POLICY')
    groups = attribute_groups()
    require(set(cfg['attribute_groups']) == set(groups), 'TRANSFER_ATTRIBUTE_GROUPS')
    for g in REQUIRED_GROUPS:
        require(cfg['attribute_groups'][g] is True, 'TRANSFER_REQUIRED_GROUP_DISABLED:' + g)
    for key in ('td', 'addval1', 'recompute', 'save_new_version', 'readiness_after_import',
                'readiness_baseline_capture'):
        require(isinstance(cfg[key], bool), 'TRANSFER_FLAG:' + key)
    require(cfg['parameter_file'] is None or isinstance(cfg['parameter_file'], str), 'TRANSFER_PARAMETER_FILE')
    require(not cfg['save_new_version'] or cfg['recompute'], 'TRANSFER_SAVE_REQUIRES_RECOMPUTE')
    return cfg


def default_root():
    if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        return Path(os.environ['LOCALAPPDATA']) / 'R1C25_TRANSFER2025'
    return ROOT / 'OFFLINE_RESULTS' / 'TRANSFER2025'


def _run_folder(output_root, action):
    from .live01_provenance import guarded_output_root
    root = guarded_output_root(output_root or default_root())
    folder = Path(root) / ('%s_%s' % (action, uuid.uuid4().hex[:12]))
    mkdir(folder)
    return folder


# ------------------------------------------------------------------ guard
class TransferWriteAudit(Live04WriteAudit):
    def __init__(self, path=None):
        super().__init__(path)
        self.allowed_zone_attrs = set()      # opened per planned write, never by default
        self.addval_writes = False
        self.save_target = None

    def summary(self):
        out = super().summary()
        out['addval1_writes'] = sum(1 for e in self.events if e['kind'] == 'ADDVAL1_WRITE')
        out['save_version_calls'] = sum(1 for e in self.events if e['kind'] == 'SAVE_VERSION_NEW_FILE')
        return out


def _transfer_policy(label, name, args, audit):
    if (name == 'SetAttValue' and getattr(audit, 'addval_writes', False) and '.Net.Links' in label
            and len(args) == 2 and isinstance(args[0], str) and args[0].upper() == 'ADDVAL1'
            and isinstance(args[1], (int, float)) and not isinstance(args[1], bool) and math.isfinite(args[1])):
        audit.record('ADDVAL1_WRITE', label, value=float(args[1]))
        return
    if (name == 'SaveVersion' and label.endswith('.IO') and getattr(audit, 'save_target', None) is not None
            and len(args) == 1 and Path(str(args[0])) == Path(audit.save_target) and not Path(str(args[0])).exists()):
        audit.record('SAVE_VERSION_NEW_FILE', label, path=str(args[0]))
        return
    if name.startswith('Save'):
        audit.record('FORBIDDEN', label, method=name, args=repr(args)[:200])
        raise WriteForbidden('TRANSFER_SAVE_FORBIDDEN:%s.%s' % (label, name))
    return _live04_policy(label, name, args, audit)


class TransferGuardedCOM(Live04GuardedCOM):
    __slots__ = ()
    POLICY = staticmethod(_transfer_policy)


# ------------------------------------------------------------------ model access
class TransferAdapter(CordonTrialAdapter):
    """Donor reads/recompute on the open model without the cordon evaluator."""
    runtime_backend = 'TRANSFER2025_DONOR_SUPPLY_VISUM'

    def __init__(self, visum, cfg, *, expected_zones=None):
        com = parent_module('r1_15a2_com_compat')
        rt = parent_module('r1_15a2_runtime_v1')
        supply = parent_module('r1_15a2_supply_visum')
        self.visum = visum
        self.raw_visum = visum
        self.cfg = cfg
        self.policy = None
        self.com_retry_policy = dict(cfg.get('com_resilience', {}) or {})
        self.zones, self.zone_write_index_by_no = com.zone_identity(visum, None, self.com_retry_policy)
        if expected_zones is not None:
            require(len(self.zones) == int(expected_zones), 'TRANSFER_ZONE_COUNT:%d' % len(self.zones))
        self.zone_readback_tolerance = float(self.com_retry_policy.get('zone_readback_tolerance', 1.0e-7))
        self.baseline_addval = None
        self.supply_path_proof = None
        self.generation_reference_values = None
        self._long_post_td_mask_enabled = True
        rt.Visum = visum
        supply.base.Visum = visum

    def assign_for_block(self, folder, block):
        mask = parent_module('r1_15a2_long_post_td_mask_v24917')
        with mask.execution_scope(self):
            return super().assign_for_block(folder, block)

    def read_zone_values(self, attr):
        rt = parent_module('r1_15a2_runtime_v1')
        values = rt.read_zone_attr_strict(self.visum, attr, self.zones, zone_indices=self.zone_write_index_by_no,
                                          retry_policy=self.com_retry_policy)
        out = {}
        for z, v in zip(self.zones, values):
            x = float(v)
            require(math.isfinite(x), 'TRANSFER_NONFINITE_ZONE_VALUE:%s:%s' % (attr, z))
            out[str(int(z))] = x
        return out

    def link_rows(self):
        rows = parent_module('r1_15a2_supply_visum').VisumAdapter.read_links(self)
        return {link_key(*k): r for k, r in rows.items()}


def _adapter_cfg():
    from .live04_config import load_config, adapter_config
    cfg = load_config()
    return cfg, adapter_config(cfg, cfg['outer_cycle_start'], None)


def _td_rows(visum):
    base = parent_module('r1_15a2_supply_visum').base
    rows = base.td_snapshot(visum)
    bad = [r.get('component') for r in rows if r.get('status') != 'OK']
    require(not bad, 'TRANSFER_TD_SNAPSHOT_FAILED:' + ','.join(map(str, bad)))
    return sorted(({'component': r['component'], 'b': float(r['current_b']), 'c': float(r['current_c'])} for r in rows),
                  key=lambda r: r['component'])


def _source_version(visum):
    try:
        path = str(visum.IO.CurrentVersionFile)
    except Exception:
        path = ''
    digest = sha256(Path(path)) if path and Path(path).is_file() else None
    return path, digest


# ------------------------------------------------------------------ EXPORT
def export_parameters(visum, *, output_root=None):
    folder = _run_folder(output_root, 'EXPORT')
    audit = TransferWriteAudit(folder / 'WRITE_AUDIT.jsonl')   # no permission at all: read-only
    guarded = TransferGuardedCOM(visum, 'Visum', audit)
    try:
        _, acfg = _adapter_cfg()
        m = TransferAdapter(guarded, acfg)
        groups = attribute_groups()
        attrs, missing = {}, {}
        for group, names in groups.items():
            for a in names:
                try:
                    attrs[a] = m.read_zone_values(a)
                except Exception as exc:
                    require(group not in REQUIRED_GROUPS, 'TRANSFER_REQUIRED_ATTRIBUTE_UNREADABLE:%s:%s' % (a, exc))
                    missing[a] = exception_text(exc)[:300]
        links = m.link_rows()
        path, digest = _source_version(visum)
        payload = {'schema': EXPORT_SCHEMA, 'source_version': path, 'source_version_sha256': digest,
                   'zones': [int(z) for z in m.zones], 'attribute_groups': groups, 'zone_attributes': attrs,
                   'missing_attributes': missing, 'td': _td_rows(guarded),
                   'addval1': {k: float(r['addval1']) for k, r in sorted(links.items())},
                   'link_count': len(links)}
        payload['content_sha256'] = canonical_hash(payload)
        require(not audit.events or all(e['kind'] == 'READ_LIST_CREATE' for e in audit.events), 'TRANSFER_EXPORT_MUTATED_MODEL')
        write_json(folder / EXPORT_NAME, payload)
        result = {'status': 'EXPORTED', 'file': str(folder / EXPORT_NAME), 'content_sha256': payload['content_sha256'],
                  'zones': len(m.zones), 'attributes': sorted(attrs), 'missing_attributes': sorted(missing),
                  'td_components': len(payload['td']),
                  'nonzero_addval1_links': sum(1 for v in payload['addval1'].values() if v != 0),
                  'source_version': path, 'model_writes': 0}
    except BaseException as exc:
        result = {'status': 'EXPORT_FAILED', 'reason': exception_text(exc), 'model_writes': 0}
        write_json(folder / '99_TRACEBACK.json', {'traceback': traceback.format_exc()})
        write_json(folder / '00_RESULT.json', dict(result, folder=str(folder)))
        raise
    write_json(folder / '00_RESULT.json', dict(result, folder=str(folder)))
    return dict(result, folder=str(folder))


def load_export(path):
    data = read_json(path)
    require(data.get('schema') == EXPORT_SCHEMA, 'TRANSFER_EXPORT_SCHEMA')
    content = {k: v for k, v in data.items() if k != 'content_sha256'}
    require(canonical_hash(content) == data.get('content_sha256'), 'TRANSFER_EXPORT_CONTENT_HASH')
    return data


def find_export(cfg, output_root=None):
    if cfg['parameter_file']:
        path = Path(cfg['parameter_file'])
        require(path.is_file(), 'TRANSFER_PARAMETER_FILE_MISSING:' + str(path))
        return path
    root = Path(output_root or default_root())
    files = sorted(root.glob('EXPORT_*/' + EXPORT_NAME), key=lambda p: p.stat().st_mtime)
    require(files, 'TRANSFER_NO_EXPORT_FOUND_UNDER:' + str(root))
    return files[-1]


# ------------------------------------------------------------------ IMPORT plan
def build_plan(export, m, tcfg):
    """Complete write plan from the export and the live target, BEFORE any write."""
    src_zones = [int(z) for z in export['zones']]
    tgt_zones = [int(z) for z in m.zones]
    only_src = sorted(set(src_zones) - set(tgt_zones)); only_tgt = sorted(set(tgt_zones) - set(src_zones))
    zone_audit = {'source': len(src_zones), 'target': len(tgt_zones), 'only_in_2022': only_src[:200],
                  'only_in_2025': only_tgt[:200], 'only_in_2022_count': len(only_src),
                  'only_in_2025_count': len(only_tgt), 'policy': tcfg['zone_policy']}
    if tcfg['zone_policy'] == 'REQUIRE_IDENTICAL_ZONE_SET':
        require(not only_src and not only_tgt, 'TRANSFER_ZONE_SET_DIFFERS:2022_only=%d,2025_only=%d'
                % (len(only_src), len(only_tgt)))
    common = [z for z in tgt_zones if z in set(src_zones)]
    require(common, 'TRANSFER_NO_COMMON_ZONE')
    zone_rows, attr_audit = [], {}
    for group, enabled in tcfg['attribute_groups'].items():
        if not enabled:
            continue
        for a in export['attribute_groups'][group]:
            src = export['zone_attributes'].get(a)
            if src is None:
                # Only optional groups can be absent from an export (required ones fail at export).
                attr_audit[a] = {'group': group, 'status': 'NOT_IN_2022_EXPORT_2025_VALUES_KEPT'}
                continue
            cur = m.read_zone_values(a)                  # a missing target attribute raises here
            changed = 0
            for z in common:
                new, old = float(src[str(z)]), float(cur[str(z)])
                if abs(new - old) > 1e-12 * max(1.0, abs(old)):
                    zone_rows.append({'zone_no': z, 'attr': a, 'group': group, 'current': old, 'proposed': new})
                    changed += 1
            attr_audit[a] = {'group': group, 'changed_zones': changed}
    td_rows, td_audit = [], {'components': 0}
    if tcfg['td']:
        current = {r['component']: r for r in _td_rows(m.visum)}
        source = {r['component']: r for r in export['td']}
        require(set(source) == set(current), 'TRANSFER_TD_COMPONENTS_DIFFER:' +
                ','.join(sorted(set(source) ^ set(current))))
        for comp in sorted(source):
            s, c = source[comp], current[comp]
            if abs(s['b'] - c['b']) > 1e-12 or abs(s['c'] - c['c']) > 1e-12:
                td_rows.append({'component': comp, 'current_b': c['b'], 'current_c': c['c'],
                                'candidate_b': s['b'], 'candidate_c': s['c']})
        td_audit = {'components': len(source), 'changed': len(td_rows)}
    link_changes, link_audit = [], {}
    if tcfg['addval1']:
        links = m.link_rows()
        src = export['addval1']
        unmatched = sorted(k for k, v in src.items() if k not in links and v != 0)
        if tcfg['addval1_policy'] == 'FAIL_ON_UNMATCHED_NONZERO':
            require(not unmatched, 'TRANSFER_ADDVAL1_LINKS_MISSING_IN_2025:%d' % len(unmatched))
        for k, v in sorted(src.items()):
            if k in links and float(links[k]['addval1']) != float(v):
                link_changes.append({'key': k, 'current': float(links[k]['addval1']), 'proposed': float(v)})
        link_audit = {'source_links': len(src), 'target_links': len(links),
                      'unmatched_nonzero_in_2025': len(unmatched), 'unmatched_examples': unmatched[:50],
                      'new_in_2025': sum(1 for k in links if k not in src), 'changed': len(link_changes),
                      'policy': tcfg['addval1_policy']}
    return {'zones': zone_audit, 'zone_rows': zone_rows, 'attributes': attr_audit, 'td_rows': td_rows,
            'td': td_audit, 'addval1_changes': link_changes, 'addval1': link_audit}


def _write_addval(m, changes):
    links = m.link_rows()
    audit = []
    for ch in changes:
        obj = links[ch['key']]['object']
        value = int(round(ch['proposed'])) if float(ch['proposed']).is_integer() else float(ch['proposed'])
        obj.SetAttValue('ADDVAL1', value)
        got = float(obj.AttValue('ADDVAL1'))
        audit.append(dict(ch, readback=got, status='OK' if abs(got - ch['proposed']) <= 1e-9 else 'READBACK_MISMATCH'))
    return audit


def _restore(m, plan, folder):
    """Best effort: parameters back to the pre-import values (demand may stay recomputed)."""
    rt = parent_module('r1_15a2_runtime_v1')
    vp = parent_module('r1_15a2_visum_parameters')
    steps = [('zones', plan['zone_rows'], lambda rows: rt.apply_add_candidate(
                 m.visum, [dict(r, proposed=r['current']) for r in rows], m.zones,
                 zone_indices=m.zone_write_index_by_no, retry_policy=m.com_retry_policy)),
             ('td', plan['td_rows'], lambda rows: vp.apply_td_candidates(
                 m.visum, [dict(r, candidate_b=r['current_b'], candidate_c=r['current_c']) for r in rows])),
             ('addval1', plan['addval1_changes'], lambda rows: _write_addval(
                 m, [dict(c, proposed=c['current']) for c in rows]))]
    out = {}
    for name, rows, fn in steps:
        if not rows:
            out[name] = 'NOTHING_TO_RESTORE'
            continue
        try:
            res = fn(rows)
            out[name] = 'RESTORED' if all(x.get('status') == 'OK' for x in res) else 'READBACK_MISMATCH'
        except Exception as exc:
            out[name] = 'FAILED:' + exception_text(exc)[:300]
    write_json(Path(folder) / 'RESTORE_AFTER_FAILURE.json', out)
    return out


# ------------------------------------------------------------------ IMPORT
def import_and_recompute(visum, *, output_root=None, config_path=None, config_overrides=None, options=None):
    from .live02_cycle import isolated_copy_guard
    rt = parent_module('r1_15a2_runtime_v1')
    vp = parent_module('r1_15a2_visum_parameters')
    tcfg = load_transfer_config(config_path, config_overrides)
    folder = _run_folder(output_root, 'IMPORT')
    lcfg, acfg = _adapter_cfg()
    audit = TransferWriteAudit(folder / 'WRITE_AUDIT.jsonl')
    guarded = TransferGuardedCOM(visum, 'Visum', audit)
    result = {'schema': 'R1_TRANSFER2025_IMPORT_RESULT_V1', 'folder': str(folder), 'status': 'STARTED',
              'model_mutated': False, 'load_version_called': False, 'source_version_overwritten': False,
              'direct_od_matrix_writes': False}
    plan = None; m = None
    try:
        export_path = find_export(tcfg, output_root)
        export = load_export(export_path)
        result.update(parameter_file=str(export_path), parameter_sha256=export['content_sha256'])
        target_path, target_sha = _source_version(visum)
        require(Path(target_path).name != Path(export['source_version']).name or target_sha != export['source_version_sha256'],
                'TRANSFER_TARGET_IS_THE_2022_SOURCE')
        result['target_version'] = target_path
        result['copy_guard'] = isolated_copy_guard(lcfg, target_path)
        m = TransferAdapter(guarded, acfg, expected_zones=acfg['expected_zones'])
        plan = build_plan(export, m, tcfg)
        write_json(folder / 'TRANSFER_PLAN.json', plan)
        result['plan'] = {k: plan[k] for k in ('zones', 'attributes', 'td', 'addval1')}
        # ---- writes (permissions opened only now, exactly for the planned scope)
        audit.allowed_zone_attrs = {r['attr'].upper() for r in plan['zone_rows']}
        audit.td_writes = bool(plan['td_rows'])
        audit.addval_writes = bool(plan['addval1_changes'])
        audit.long_mask_writes = bool(tcfg['recompute'])
        result['model_mutated'] = True
        za = rt.apply_add_candidate(guarded, plan['zone_rows'], m.zones, zone_indices=m.zone_write_index_by_no,
                                    retry_policy=m.com_retry_policy, readback_tolerance=m.zone_readback_tolerance) \
            if plan['zone_rows'] else []
        require(all(x.get('status') == 'OK' for x in za), 'TRANSFER_ZONE_READBACK_FAILED')
        ta = vp.apply_td_candidates(guarded, plan['td_rows']) if plan['td_rows'] else []
        require(all(x.get('status') == 'OK' for x in ta), 'TRANSFER_TD_READBACK_FAILED')
        la = _write_addval(m, plan['addval1_changes'])
        require(all(x.get('status') == 'OK' for x in la), 'TRANSFER_ADDVAL1_READBACK_FAILED')
        write_json(folder / 'TRANSFER_WRITES.json', {'zones': za, 'td': ta, 'addval1': la})
        result['writes'] = {'zone_values': len(za), 'td_components': len(ta), 'addval1_links': len(la)}
        audit.allowed_zone_attrs = set(); audit.td_writes = False; audit.addval_writes = False
        # ---- one native recompute with the v7 LONG post-TD mask
        if tcfg['recompute']:
            from .live04_long_mask import install_scoped, support_report
            status, restore = install_scoped(rt)
            try:
                gap = m.assign_for_block(folder / 'RECOMPUTE', 'GENERATION')
            finally:
                restore()
            result['recompute'] = {'gap': gap, 'mask_hook': status}
            pz = rt.verify_add_candidate_persistence(guarded, plan['zone_rows'], m.zones,
                                                     zone_indices=m.zone_write_index_by_no,
                                                     retry_policy=m.com_retry_policy) if plan['zone_rows'] else []
            pt = vp.verify_td_persistence(guarded, plan['td_rows']) if plan['td_rows'] else []
            pl = [{'key': c['key'], 'value': float(m.link_rows()[c['key']]['addval1']), 'expected': c['proposed']}
                  for c in plan['addval1_changes']]
            require(all(x.get('status') == 'OK' for x in pz + pt), 'TRANSFER_PARAMETERS_OVERWRITTEN_BY_PROCEDURE')
            require(all(abs(x['value'] - x['expected']) <= 1e-9 for x in pl), 'TRANSFER_ADDVAL1_OVERWRITTEN')
            support = support_report(m, folder, 'AFTER_RECOMPUTE')
            require(support['support_clean'], 'TRANSFER_LONG_SUPPORT_NOT_CLEAN_AFTER_RECOMPUTE')
            result['long_support_clean'] = True
        # ---- new version
        if tcfg['save_new_version']:
            src = Path(target_path)
            target = src.with_name(src.stem + '_LIVE04_BASE_' + uuid.uuid4().hex[:8] + src.suffix)
            require(not target.exists() and target.resolve() != src.resolve(), 'TRANSFER_SAVE_TARGET_INVALID')
            before = sha256(src) if src.is_file() else None
            audit.save_target = target
            rt.save_version(guarded, target)
            audit.save_target = None
            require(before is None or sha256(src) == before, 'TRANSFER_SOURCE_VERSION_CHANGED_BY_SAVE')
            result['saved_version'] = {'path': str(target), 'sha256': sha256(target)}
        result['status'] = 'IMPORTED_RECOMPUTED_SAVED' if tcfg['save_new_version'] else (
            'IMPORTED_RECOMPUTED' if tcfg['recompute'] else 'IMPORTED_NOT_RECOMPUTED')
        result['write_audit'] = audit.summary()
        write_json(folder / '00_RESULT.json', result)
    except BaseException as exc:
        result.update(status='IMPORT_FAILED', reason=exception_text(exc))
        if result['model_mutated'] and plan is not None and m is not None:
            audit.allowed_zone_attrs = {r['attr'].upper() for r in plan['zone_rows']}
            audit.td_writes = bool(plan['td_rows']); audit.addval_writes = bool(plan['addval1_changes'])
            result['restore'] = _restore(m, plan, folder)
            result['model_state'] = 'PARAMETERS_RESTORED_DEMAND_MAY_BE_RECOMPUTED_REOPEN_THE_COPY'
        else:
            result['model_state'] = 'UNCHANGED_NO_WRITE'
        result['write_audit'] = audit.summary()
        write_json(folder / '99_TRACEBACK.json', {'traceback': traceback.format_exc()})
        write_json(folder / '00_RESULT.json', result)
        raise
    if tcfg['readiness_after_import']:
        result['readiness'] = readiness(visum, output_root=output_root, options=options,
                                        expected_parameters=export_path,
                                        baseline_capture=tcfg['readiness_baseline_capture'],
                                        transfer_cfg=tcfg)['status']
        write_json(folder / '00_RESULT.json', result)
    return result


# ------------------------------------------------------------------ READINESS
def _parameter_identity(export, m, tcfg):
    diffs = []
    for group, enabled in tcfg['attribute_groups'].items():
        if not enabled:
            continue
        for a in export['attribute_groups'][group]:
            src = export['zone_attributes'].get(a)
            if src is None:
                continue                      # optional attribute absent in 2022: 2025 values kept
            cur = m.read_zone_values(a)
            bad = [z for z in cur if z in src and abs(cur[z] - src[z]) > 1e-9 * max(1.0, abs(src[z]))]
            if bad:
                diffs.append({'attr': a, 'zones': len(bad), 'examples': bad[:5]})
    if tcfg['td']:
        cur = {r['component']: r for r in _td_rows(m.visum)}
        for r in export['td']:
            c = cur.get(r['component'])
            if c is None or abs(c['b'] - r['b']) > 1e-9 or abs(c['c'] - r['c']) > 1e-9:
                diffs.append({'td_component': r['component']})
    if tcfg['addval1']:
        links = m.link_rows()
        bad = [k for k, v in export['addval1'].items() if k in links and float(links[k]['addval1']) != float(v)]
        if bad:
            diffs.append({'addval1_links': len(bad), 'examples': bad[:5]})
    require(not diffs, 'PARAMETERS_DIFFER_FROM_EXPORT:' + repr(diffs)[:800])
    return {'identical': True}


def readiness(visum, *, output_root=None, options=None, expected_parameters=None, baseline_capture=True,
              transfer_cfg=None):
    """Read-only: everything LIVE04 needs before its first write."""
    from .live01_visum import model_preflight
    from .live01_provenance import verify_protected_sources
    from .live01_config import calculation_config
    from .live02_cycle import LiveControl, isolated_copy_guard
    from .visum_startup import settings
    from .live04_config import live01_view
    from . import live04_v7 as v7
    from .live04_long_mask import support_report
    folder = _run_folder(output_root, 'READINESS')
    audit = TransferWriteAudit(folder / 'WRITE_AUDIT.jsonl')        # no write permission at all
    guarded = TransferGuardedCOM(visum, 'Visum', audit)
    checks = []
    ctx = {}

    def check(name, fn, *, required=True):
        try:
            detail = fn()
            checks.append({'check': name, 'status': 'PASS', 'required': required, 'detail': detail})
            return detail
        except Exception as exc:
            checks.append({'check': name, 'status': 'FAIL', 'required': required, 'error': exception_text(exc)[:1500]})
            return None

    lcfg, acfg = _adapter_cfg()
    check('RELEASE_PINS', lambda: {'protected': verify_protected_sources()['status'],
                                   'v7_donors': len(v7.verify_donor_files())})
    configured = read_json(ROOT / 'CORDON_2025_STARTUP_OPTIONS.json'); configured.update(options or {})
    opt = settings(configured)
    parent_ctrl = parent_module('r1_15a2_overnight_controller_v24915p2')
    ctl = LiveControl(folder, parent_ctrl.UserStopRequested)
    view = live01_view(lcfg, lcfg['outer_cycle_start'])

    def preflight():
        pre, state = model_preflight(guarded, view, folder / 'PREFLIGHT', ctl, opt)
        ctx['pre'], ctx['state'] = pre, state
        return {'zones': len(pre[2]), 'network_sha256': pre[0]['network_sha256'],
                'source_version': state['source_version'], 'actuatable_zones': len(state['actuatable_zones'])}
    check('LIVE01_MODEL_PREFLIGHT', preflight)
    check('ISOLATED_COPY_NAME', lambda: isolated_copy_guard(lcfg, (ctx.get('state') or {}).get('source_version')
                                                            or _source_version(visum)[0]))
    def adapter():
        ctx['m'] = TransferAdapter(guarded, acfg, expected_zones=acfg['expected_zones'])
        return {'zones': len(ctx['m'].zones)}
    check('DONOR_ADAPTER', adapter)
    m = ctx.get('m')

    def operations():
        com = parent_module('r1_15a2_com_compat')
        mask = parent_module('r1_15a2_long_post_td_mask_v24917')
        rows = com.operation_rows(guarded)
        by = {int(r['no']): r for r in rows}
        tds = [int(r['no']) for r in rows if int(r['type']) == com.TD and r['active']]
        require(len(tds) == 1, 'EXPECTED_ONE_ACTIVE_TD:%s' % tds)
        rules = acfg['supply']['assignment_operations']
        for rule in rules:
            mask._verify_assignment_scope(by[int(rule['no'])], rule['expected_dsegs'])
        partial = {17: {'LNV', 'NV'}, 18: {'NATIVE_CF', 'NATIVE_CL'},
                   19: {'NATIVE_CS', 'NATIVE_CS_NOT', 'NATIVE_CW', 'NATIVE_CW_NOT'}}
        for no, dsegs in partial.items():
            require(no in by and int(by[no]['type']) == com.ASSIGNMENT_PRT, 'PARTIAL_ASSIGNMENT_MISSING:%d' % no)
            mask._verify_assignment_scope(by[no], dsegs)
        return {'td_position': tds[0], 'assignments_verified': sorted([17, 18, 19] + [int(r['no']) for r in rules]),
                'partial_active': {no: bool(by[no]['active']) for no in partial}}
    check('OPERATIONS_TD_17_20', operations)

    def supply_cold_chain():
        """LIVE04.4 SupplyMix: the v7 cold chain needs an active reset operation before the joint assignment."""
        from .live04_supply import options as supply_options
        sopts = supply_options(lcfg)
        if not sopts['enabled']:
            return {'supply_mix': 'DISABLED'}
        com = parent_module('r1_15a2_com_compat')
        rows = com.operation_rows(guarded)
        by = {int(r['no']): r for r in rows}
        pos = int(sopts['reset_position'])
        last = max(int(r['no']) for r in acfg['supply']['assignment_operations'])
        require(pos in by and int(by[pos]['type']) == parent_module('r1_15a2_supply_mix_v24917').RESET_TYPE
                and bool(by[pos]['active']), 'SUPPLYMIX_RESET_OPERATION:%d' % pos)
        require(last > pos and bool(by[last]['active']), 'SUPPLYMIX_RESET_NOT_BEFORE_ASSIGNMENT')
        return {'reset_position': pos, 'joint_assignment': last}
    check('SUPPLYMIX_COLD_CHAIN', supply_cold_chain)

    def matrices():
        mask = parent_module('r1_15a2_long_post_td_mask_v24917')
        out = {}
        for no in (9111, 9112, 9113, 9114, 9115, 9291, 9292, 9293, 9294, 9295, 9305, 9116):
            obj, _ = mask._read(m, no)
            out[str(no)] = mask._matrix_datasource(m, obj, no)
        require(all(out[str(n)] == 'DATA' for n in (9291, 9292, 9293, 9294, 9295)), 'VEHICLE_COMPONENTS_NOT_DATA')
        require(out['9305'] == 'FORMULA', '9305_NOT_FORMULA')
        return out
    if m is not None:
        check('MATRIX_SOURCE_TYPES', matrices)
        def long_support():
            r = support_report(m, folder, 'READINESS')
            require(r['support_clean'], 'LONG_SUPPORT_NOT_CLEAN:person_below_80km=%.6g;vehicle_clean=%s'
                    % (r['person']['below_min_km'], r['vehicle_support_clean']))
            return {'support_clean': True, 'person_total': r['person']['total_volume']}
        check('LONG_SUPPORT_MASKED', long_support)

        def mobility():
            supply = parent_module('r1_15a2_supply_visum')
            mg = parent_module('r1_15a2_mobility_guard_v24917')
            zg = parent_module('r1_15a2_mobility_zone_v24917')
            opts = v7.mobility_options(lcfg)
            rows, _ = supply.base.zone_state_rows(guarded, m.zones, acfg, zone_indices=m.zone_write_index_by_no,
                                                  retry_policy=m.com_retry_policy)
            ratios = {f: mg.ratio(mg.zone_productions(rows, f)) for f in ('WORK', 'SERVICE')}
            mz = zg.capture(rows, opts, ('WORK', 'SERVICE'))
            return {'band': [opts['lo'], opts['hi']], 'production_ratio': ratios,
                    'mobilityzone1_status': mz['status'], 'zones_out_of_band': len(mz['out_of_band'])}
        check('MOBILITY_AUTHORITY', mobility)
        if expected_parameters:
            tcfg = transfer_cfg or load_transfer_config()
            check('PARAMETERS_EQUAL_EXPORT', lambda: _parameter_identity(load_export(expected_parameters), m, tcfg))
    if baseline_capture and ctx.get('pre') is not None:
        def capture():
            from .live03_observations import Contract
            from .live03_evaluation import Live03Evaluator
            contract = Contract(lcfg['observations'])
            mathcfg = calculation_config(view, ctx['state']['actuatable_zones'])
            mathcfg['actual_network_sha256'] = ctx['pre'][0]['network_sha256']
            ev = Live03Evaluator(lcfg, mathcfg, contract, opt, ctl, ctx['pre'])
            diag = ev.evaluate(guarded, folder / 'BASELINE_CAPTURE', 'BASELINE', full_geometry=True, keep_db=False)
            return {mth: {k: diag['methods'][mth]['metrics'].get(k)
                          for k in ('objective', 'model_obs_ratio', 'geh_mean', 'geh_le_10_share', 'model_total',
                                    'observed_total')} for mth in diag['methods']}
        check('CORDON_BASELINE_CAPTURE', capture)
    mutating = [e for e in audit.events if e['kind'] != 'READ_LIST_CREATE']
    checks.append({'check': 'NO_MODEL_WRITE', 'status': 'PASS' if not mutating else 'FAIL', 'required': True,
                   'detail': {'events': len(mutating)}})
    ready = all(c['status'] == 'PASS' for c in checks if c['required'])
    result = {'schema': 'R1_TRANSFER2025_READINESS_V1', 'status': 'READY_FOR_LIVE04' if ready else 'NOT_READY',
              'folder': str(folder), 'checks': checks,
              'failed': [c['check'] for c in checks if c['status'] != 'PASS'], 'model_writes': 0}
    write_json(folder / '00_RESULT.json', result)
    return result
