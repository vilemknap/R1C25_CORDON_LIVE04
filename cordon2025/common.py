from __future__ import annotations
import csv
import hashlib
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / 'parent'

def parent_module(name):
    """Only import library modules from this isolated 2025 parent tree."""
    require(name.startswith('r1_15a2_') and name.replace('_', '').isalnum(), 'INVALID_PARENT_MODULE')
    expected = (PARENT / (name + '.py')).resolve()
    require(expected.is_file(), 'PARENT_MODULE_MISSING:' + name)
    # Reject already-imported dependencies from a running/different 2022 source.
    for key, module in tuple(sys.modules.items()):
        if key.startswith('r1_15a2_') and getattr(module, '__file__', None):
            origin = Path(module.__file__).resolve()
            if origin.parent != PARENT.resolve():
                raise ContractError('PARENT_MODULE_COLLISION:' + key)
    if str(PARENT) not in sys.path:
        sys.path.insert(0, str(PARENT))
    import importlib
    module = importlib.import_module(name)
    require(Path(module.__file__).resolve() == expected, 'PARENT_MODULE_COLLISION:' + name)
    return module


def parent_core():
    return parent_module('r1_15a2_core')

class ContractError(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise ContractError(message)

def finite(value, label, nonnegative=True):
    require(not isinstance(value, bool), 'INVALID_NUMBER:' + label)
    try:
        val = float(value)
    except (ValueError, TypeError) as exc:
        raise ContractError('MISSING_OR_INVALID_NUMBER:' + label) from exc
    require(math.isfinite(val) and (not nonnegative or val >= 0), 'INVALID_NUMBER:' + label)
    return val

def sha256(path):
    from .io import sha256 as secure_sha256
    return secure_sha256(path)

def canonical_hash(obj):
    # Lazy PERF01 audit rows serialize identically to the original list only when
    # a caller explicitly needs the legacy canonical digest (e.g. solver lineage).
    def encode_special(value):
        from .perf01_codec import json_default
        return json_default(value)
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False,
                                     default=encode_special).encode()).hexdigest()

def read_csv(path):
    from .io import read_csv as secure_read_csv
    return secure_read_csv(path)


def read_json(path):
    from .io import read_json as secure_read_json
    return secure_read_json(path)


def write_json(path, data):
    from .io import write_json as secure_write_json
    return secure_write_json(path, data)


def write_csv(path, rows, fields=None):
    from .io import write_csv as secure_write_csv
    return secure_write_csv(path, rows, fields)


def write_npz(path, **arrays):
    from .io import write_npz as secure_write_npz
    return secure_write_npz(path, **arrays)

def read_config(path=None, *, outer_cycle=None):
    p = Path(path or ROOT/'CORDON_2025_CONFIG.json')
    cfg = read_json(p)
    from .state import validate_runtime_options
    validate_runtime_options(cfg)
    require(cfg.get('apply') is False, 'V1_APPLY_FORBIDDEN')
    require(cfg.get('mode') == 'OFFLINE_PROPOSAL', 'OFFLINE_MODE_REQUIRED')
    require(cfg.get('model_year') == 2025 and cfg.get('survey_year') == 2026, 'YEAR_CONTRACT_MISSING')
    require(cfg.get('category') == 'OA', 'V1_OA_ONLY')
    require(cfg.get('basis') == 'RPDI', 'V1_RPDI_REQUIRED')
    require(not any(cfg.get(k) for k in ('run_procseq','run_assignment','write_od','supply_enabled')), 'LIVE_SWITCH_FORBIDDEN')
    from .limits import numerical
    numerical(cfg)
    from .aggressive_policy import enabled, effective_config
    if enabled(cfg):
        return effective_config(cfg, outer_cycle)
    require(outer_cycle is None, 'OUTER_CYCLE_REQUIRES_AGGRESSIVE_CONFIG')
    return cfg

def new_output(name):
    require(name and name.replace('_','').replace('-','').isalnum(), 'UNSAFE_OUTPUT_NAME')
    p = ROOT/'OFFLINE_RESULTS'/name
    from .io import mkdir
    mkdir(p, exist_ok=False)
    return p

APPROVAL_FIELDS = ('observation_semantics','direction_mapping','year_bridge','network_mapping',
                   'dseg_scope','geometry_identity','path_volume_parity','c17_policy')
def deployment_gate(cfg, cache_present=False):
    approvals = cfg.get('approvals', {})
    missing = [key.upper() + '_UNAPPROVED' for key in APPROVAL_FIELDS
               if not (isinstance(approvals.get(key), dict) and approvals[key].get('approved') is True
                       and approvals[key].get('evidence_sha256') and approvals[key].get('authority_id'))]
    if not cache_present:
        missing.append('NO_2025_PATH_CACHE')
    return {'blockers': missing + ['NOT_LIVE_TESTED', 'AGGRESSIVE_OFFLINE_ONLY' if cfg.get('aggressive_policy',{}).get('enabled') else ('V2_OFFLINE_ONLY' if str(cfg.get('schema','')).endswith('V2') else 'V1_OFFLINE_ONLY')],
            'apply_permitted': False, 'production_ready': False, 'live_visum_tested': False}
