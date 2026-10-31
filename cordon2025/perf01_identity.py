"""Content identities for OFFLINE derived cache; never proves a new Visum epoch."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import hashlib
import json
import math
import os
import re
import stat
from .common import ROOT, require, canonical_hash, parent_core
from .io import native_path, retry
from .state import validate_runtime_options

SCHEMA = 'CORDON_PERF01_DERIVED_V1'
IMPLEMENTATION = 'PERF01_1.0_20261023'
SIDECARS = ('-wal', '-shm', '-journal')


def clean_path(path):
    """Reject links/reparse points at every existing ancestor, before resolve()."""
    path = Path(os.path.abspath(os.fspath(path)))
    for item in (path, *path.parents):
        try:
            s = os.lstat(native_path(item))
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(s.st_mode) and not
                (getattr(s, 'st_file_attributes', 0) & 0x400), 'PERF01_SYMLINK_OR_REPARSE_FORBIDDEN')
    return path


def relative_file(root, name):
    require(isinstance(name, str) and name != '', 'PERF01_ARTIFACT_PATH_INVALID')
    rel = PurePosixPath(name)
    require(not rel.is_absolute() and '..' not in rel.parts and '\\' not in name
            and ':' not in name and all(x not in ('', '.') for x in name.split('/')),
            'PERF01_ARTIFACT_PATH_INVALID')
    root = clean_path(root)
    p = clean_path(root.joinpath(*rel.parts))
    require(root in p.parents, 'PERF01_ARTIFACT_PATH_ESCAPE')
    return p


def strict_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'PERF01_DUPLICATE_JSON_KEY:' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('PERF01_NONFINITE_JSON:' + value)
    def load():
        with open(native_path(clean_path(path)), encoding='utf-8-sig') as f:
            return json.load(f, object_pairs_hook=pairs, parse_constant=invalid)
    value = retry(load)
    # Also rejects float overflow, e.g. 1e999.
    canonical_hash(value)
    return value


def _file_record_once(path):
    path = clean_path(path)
    require(path.is_file(), 'PERF01_SOURCE_FILE_MISSING:' + path.name)
    before = path.stat()
    h = hashlib.sha256(); count = 0
    with open(native_path(path), 'rb') as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b''):
            count += len(b); h.update(b)
    after = path.stat()
    require((before.st_size, before.st_mtime_ns, before.st_ino) ==
            (after.st_size, after.st_mtime_ns, after.st_ino) and count == before.st_size,
            'PERF01_FILE_CHANGED_DURING_HASH')
    return {'bytes': count, 'sha256': h.hexdigest()}


def file_record(path, counter=None, field='source_bytes_hashed'):
    record=retry(lambda:_file_record_once(path))
    if counter is not None: counter[field]=counter.get(field,0)+record['bytes']
    return record


def algorithm_identity():
    names = ['common.py', 'incidence.py', 'external_parity.py', 'parity.py',
             'limits.py', 'state.py', 'io.py', 'perf01_identity.py',
             'perf01_cache.py', 'perf01_codec.py']
    files = {'cordon2025/' + name: file_record(ROOT/'cordon2025'/name)['sha256'] for name in names}
    for name in ('r1_15a2_core.py', 'r1_15a2_two_mode_v238.py', 'r1_15a2_runtime_io_hotfix_profile488.py'):
        files['parent/' + name] = file_record(ROOT/'parent'/name)['sha256']
    return {'implementation': IMPLEMENTATION, 'sha256': canonical_hash(files), 'files': files}


def _scope(cfg, context):
    validate_runtime_options(cfg)
    require(context == 'same-sealed-snapshot', 'CACHE_EPOCH_NOT_PROVEN_RECAPTURE_REQUIRED')
    require(cfg.get('apply') is False and cfg.get('category') == 'OA', 'PERF01_OFFLINE_OA_ONLY')
    require(cfg.get('model_year') == 2025 and cfg.get('survey_year') == 2026 and cfg.get('basis') == 'RPDI', 'PERF01_YEAR_BASIS_SCOPE')
    require(cfg.get('mode') == 'OFFLINE_PROPOSAL', 'PERF01_OFFLINE_ONLY')
    require(not any(cfg.get(k) for k in ('run_assignment','run_procseq','write_od','supply_enabled')), 'PERF01_LIVE_SWITCH_FORBIDDEN')


@dataclass
class SourceSeal:
    path: Path
    evidence_path: Path
    evidence: dict
    identity: dict
    source_id: str
    tracked: dict

    def recheck(self, counter=None):
        require(not any(Path(str(self.path)+s).exists() for s in SIDECARS), 'LIVE_SQLITE_SIDECAR_PRESENT_COPY_COMPLETED_SNAPSHOT')
        for path, record in self.tracked.items():
            require(file_record(path, counter) == record, 'PERF01_SOURCE_CHANGED_DURING_OPERATION:' + Path(path).name)


def source_seal(path, evidence_path, cfg, *, checkpoint=None, context='same-sealed-snapshot', counter=None):
    _scope(cfg, context)
    path = clean_path(path); ep = clean_path(evidence_path)
    require(path != ep, 'PERF01_INPUT_COLLISION')
    require(not any(Path(str(path)+s).exists() for s in SIDECARS), 'LIVE_SQLITE_SIDECAR_PRESENT_COPY_COMPLETED_SNAPSHOT')
    tracked = {}
    def track(p):
        p = clean_path(p)
        if p not in tracked: tracked[p] = file_record(p, counter)
        return tracked[p]
    er = track(ep); e = strict_json(ep); source = track(path)
    require(e.get('schema') == 'CORDON_FROZEN_CACHE_EVIDENCE_V1', 'PERF01_EVIDENCE_SCHEMA')
    require(e.get('completed') is True, 'CACHE_SNAPSHOT_NOT_COMPLETE')
    require(e.get('geometry_full_identity_proven') is True, 'PERF01_FULL_GEOMETRY_PROOF_REQUIRED')
    require(e.get('model_year') == 2025 and e.get('basis') == 'RPDI' and e.get('category') == 'OA', 'CACHE_MODEL_YEAR_OR_SCOPE_MISMATCH')
    require(e.get('origin') in ('VISUM_SAVED_PATHS','SYNTHETIC_TEST_FIXTURE'), 'PERF01_ORIGIN_UNPROVEN')
    require(source['sha256'] == e.get('cache_sha256'), 'CACHE_SHA256_MISMATCH')
    for key in ('network_sha256', 'demand_sha256'):
        require(re.fullmatch('[0-9a-f]{64}', str(e.get(key,''))), 'PERF01_SOURCE_IDENTITY_MISSING:' + key)
        expected = cfg.get('actual_' + key)
        require(expected is None or expected == e[key], 'CACHE_SOURCE_IDENTITY_MISMATCH:' + key)
    core = parent_core()
    totals = e.get('dseg_totals', {})
    require(totals and all(type(v) in (int,float) and math.isfinite(v) and v >= 0 for v in totals.values()), 'PERF01_DSEG_TOTALS_INVALID')
    inventory = sorted(core.norm_code(c) for c in totals)
    require(len(inventory) == len(set(inventory)), 'PERF01_DSEG_COLLISION')
    require(set(map(core.norm_code,cfg.get('selected_dsegs',[]))) == set(inventory), 'PERF01_SELECTED_DSEG_SCOPE_MISMATCH')
    records = {'p.sqlite': source, 'SNAPSHOT_EVIDENCE.json': er}
    if e['origin'] == 'VISUM_SAVED_PATHS':
        gp = path.parent/'GEOMETRY_PROOF.json'; pr = track(gp); proof = strict_json(gp)
        require(proof.get('full') is True and proof.get('checks') == e.get('full_geometry_checks'), 'PERF01_GEOMETRY_PROOF_MISMATCH')
        checks = proof.get('checks', [])
        require(sorted(core.norm_code(r['dseg']) for r in checks) == inventory and
                all(r.get('check') in ('FULL_REPRESENTATIVE','FULL_SAME_MODE_MATCH') for r in checks), 'PERF01_GEOMETRY_PROOF_SCOPE')
        pp = path.parent/'OD_PARITY.json'; pr2 = track(pp); parity = strict_json(pp)
        require(pr2['sha256'] == e.get('external_od_parity_sha256'), 'PERF01_EXTERNAL_PARITY_SHA_MISMATCH')
        require(isinstance(parity,list) and sorted(core.norm_code(r['dseg']) for r in parity)==inventory and
                all(r.get('status')=='PASS' for r in parity), 'PERF01_EXTERNAL_PARITY_NOT_PASS')
        policy = e.get('path_matrix_parity_policy')
        require(isinstance(policy,dict) and canonical_hash(policy)==e.get('path_matrix_parity_policy_sha256'), 'PARITY_POLICY_SHA_MISMATCH')
        records.update({'GEOMETRY_PROOF.json':pr,'OD_PARITY.json':pr2})
        matrices = e.get('od_matrix_authorities',[])
        require(sorted(core.norm_code(r['dseg']) for r in matrices)==inventory, 'PERF01_MATRIX_AUTHORITY_SCOPE')
        for rec in matrices:
            p = relative_file(path.parent, rec['path']); r = track(p)
            require(r['sha256']==rec.get('sha256'), 'EXTERNAL_MATRIX_SHA_MISMATCH')
            require(rec['path'] not in records,'PERF01_DUPLICATE_SOURCE_RECORD')
            records[rec['path']]=r
    else:
        require(isinstance(e.get('od_totals'),list), 'PERF01_SYNTHETIC_OD_AUTHORITY_REQUIRED')
    if checkpoint is not None:
        cp = clean_path(checkpoint); cr = track(cp); check = strict_json(cp)
        require(check.get('completed') is True and check.get('stage')=='READONLY_VISUM_RUN_COMPLETE', 'PERF01_CHECKPOINT_NOT_COMPLETE')
        require(check.get('context',{}).get('model_year')==2025 and check.get('context',{}).get('survey_year')==2026, 'PERF01_CHECKPOINT_SCOPE')
        byname={}
        for item in check.get('artifacts',[]):
            name=item['path'];relative_file(path.parent,name)
            require(name not in byname,'PERF01_DUPLICATE_CHECKPOINT_ARTIFACT');byname[name]=item
        for name,rec in records.items():
            require(name in byname and all(byname[name].get(k)==rec[k] for k in ('bytes','sha256')), 'PERF01_CHECKPOINT_SOURCE_MISMATCH:' + name)
        records['RUN_CHECKPOINT.json']=cr
    identity = {'schema':SCHEMA, 'files':records, 'origin':e['origin'],
                'model_year':2025,'survey_year':2026,'basis':'RPDI','category':'OA',
                'network_sha256':e['network_sha256'],'demand_sha256':e['demand_sha256'],
                'dseg_inventory':inventory,'completed':True,'geometry_full_identity_proven':True,
                'assignment_freshness':e.get('assignment_freshness','NOT_CERTIFIED'),
                'new_assignment_verified':False}
    # Exclude optional checkpoint from address: it binds the same contents, not their semantics.
    idbody = dict(identity,files={k:v for k,v in records.items() if k!='RUN_CHECKPOINT.json'})
    return SourceSeal(path,ep,e,identity,canonical_hash(idbody),tracked)


def cache_keys(source, mapping, cfg):
    core=parent_core(); from .limits import numerical
    require(isinstance(mapping,dict) and mapping,'PERF01_MAPPING_REQUIRED')
    for key,v in mapping.items():
        require(isinstance(key,tuple) and len(key)==3 and all(type(x) is int and x>0 for x in key)
                and type(v) is int and v>0,'PERF01_MAPPING_INVALID')
    require(cfg.get('observation_methods',['ALL_ORDERED_UNIQUE_PAIRS','EXACT_TWO_HITS']) ==
            ['ALL_ORDERED_UNIQUE_PAIRS','EXACT_TWO_HITS'],'PERF01_BOTH_ENUMERATION_METHODS_REQUIRED')
    algo=algorithm_identity()
    geometry={'source_id':source.source_id,'algorithm':algo,'mapping':sorted([*k,v] for k,v in mapping.items()),'model_year':2025}
    geom_id=canonical_hash(geometry)
    numeric=numerical(cfg)
    contract={'geometry_key':geom_id,'selected_dsegs':[core.norm_code(c) for c in cfg['selected_dsegs']],
              'mutable_dsegs':sorted(core.norm_code(c) for c in cfg.get('mutable_dsegs',[])),
              'mutable_relation_policy':cfg.get('mutable_relation_policy','BOTH_ENDPOINTS_ACTUATABLE'),
              'actuatable_zones':sorted(cfg['actuatable_zones']) if cfg.get('actuatable_zones') is not None else None,
              'repeat_policy':cfg.get('repeat_policy','EXCLUDE_FLAGGED'),
              'methods':['ALL_ORDERED_UNIQUE_PAIRS','EXACT_TWO_HITS'],
              'internal_sum_atol':numeric['internal_sum_atol'],'internal_sum_rtol':numeric['internal_sum_rtol'],
              'expected_snapshot_semantics':cfg.get('expected_snapshot_semantics'),
              'actual_network_sha256':cfg.get('actual_network_sha256'), 'actual_demand_sha256':cfg.get('actual_demand_sha256')}
    return geom_id,canonical_hash(contract),{'geometry':geometry,'incidence':contract}
