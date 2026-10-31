"""Source-state, observation roster and cache contracts for isolated CORDON V2.

Ports the SEMRELOAD1 lesson: a filename is NOT a semantic-state identity. This
module never reloads a live model. A mismatch blocks the offline run and requires
a new, explicitly sealed read-only snapshot. GATEFIX uses this run's roster,
never a 2022 constant (488/498/... are not an authority here).
"""
from __future__ import annotations
from collections import Counter
import re
from .common import require, canonical_hash, parent_module

SEMANTIC_FIELDS = ('addval_hash', 'fixed_link_hash', 'matrix_hash', 'dseg_hash',
                   'generation_hash', 'td_hash', 'operations_hash', 'state_hash')


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def validate_runtime_options(cfg):
    require(cfg.get('persistent_path_cache_enabled', False) is False, 'CROSS_RUN_CACHE_REUSE_FORBIDDEN')
    require(cfg.get('automatic_cache_discovery', False) is False, 'AUTOMATIC_CACHE_DISCOVERY_FORBIDDEN')
    require(cfg.get('automatic_live_reload', False) is False, 'OFFLINE_LOADVERSION_FORBIDDEN')
    require(cfg.get('flowbundle_count_authority', False) is False, 'FLOWBUNDLE_CANNOT_BE_CORDON_AUTHORITY')
    require(cfg.get('wallclock_limit_seconds') in (None, 0), 'WALLCLOCK_STOP_NOT_AUTHORIZED')
    require(cfg.get('authority_family', 'CORDON_SDP') == 'CORDON_SDP', 'CSD_AUTHORITY_NOT_ALLOWED_IN_CORDON_BRANCH')
    return {'automatic_discovery': False, 'cross_run_cache_reuse': False,
            'explicit_frozen_sqlite_supported': True, 'live_reload': False,
            'wallclock_stop': False}


def snapshot_semantics(evidence, cfg, metadata=None):
    validate_runtime_options(cfg)
    metadata = metadata or {}
    actual = evidence.get('semantic_hashes')
    expected = cfg.get('expected_snapshot_semantics')
    synthetic = evidence.get('origin') == 'SYNTHETIC_TEST_FIXTURE'
    # Source expectations are independent of availability of semantic metadata.
    for evidence_key, config_key in (('network_sha256', 'actual_network_sha256'),
                                    ('demand_sha256', 'actual_demand_sha256')):
        if cfg.get(config_key) is not None:
            require(valid_hash(cfg[config_key]), ('CACHE_NETWORK_IDENTITY_HASH_INVALID' if evidence_key == 'network_sha256' else 'EXPECTED_SOURCE_HASH_INVALID:' + config_key))
            require(evidence.get(evidence_key) == cfg[config_key], 'CACHE_SOURCE_IDENTITY_MISMATCH:' + evidence_key)
    if not actual:
        require(not expected, 'EXPECTED_SEMANTICS_WITHOUT_SNAPSHOT_EVIDENCE')
        return {'status': 'SYNTHETIC_FIXTURE' if synthetic else 'SEMANTIC_SNAPSHOT_NOT_SUPPLIED',
                'complete': False, 'live_verified': False, 'automatic_reload_performed': False}
    require(isinstance(actual, dict), 'INVALID_SEMANTIC_SNAPSHOT')
    for key in SEMANTIC_FIELDS:
        require(valid_hash(actual.get(key)), 'SEMANTIC_HASH_MISSING_OR_INVALID:' + key)
    if expected is not None:
        require(isinstance(expected, dict) and all(valid_hash(expected.get(k)) for k in SEMANTIC_FIELDS), 'EXPECTED_SEMANTICS_INCOMPLETE')
        differences = {key: {'expected': expected[key], 'actual': actual[key]}
                       for key in SEMANTIC_FIELDS if expected[key] != actual[key]}
        require(not differences, 'CACHE_SEMANTIC_STATE_MISMATCH:' + ','.join(sorted(differences)))
    if metadata.get('parent_hash'):
        require(metadata['parent_hash'] == actual['state_hash'], 'CACHE_PARENT_SEMANTIC_HASH_MISMATCH')
    for evidence_key, config_key in (('network_sha256', 'actual_network_sha256'),
                                    ('demand_sha256', 'actual_demand_sha256')):
        require(valid_hash(evidence.get(evidence_key)), 'SOURCE_HASH_MISSING_OR_INVALID:' + evidence_key)
        if cfg.get(config_key) is not None:
            require(evidence[evidence_key] == cfg[config_key], 'CACHE_SOURCE_IDENTITY_MISMATCH:' + evidence_key)
    return {'status': 'DECLARED_SEMANTIC_HASHES_MATCH' if expected else 'DECLARED_SEMANTIC_HASHES_NO_EXTERNAL_COMPARISON',
            'complete': True, 'expected_compared': bool(expected),
            'semantic_hashes': dict(actual), 'cache_parent_hash_compared': bool(metadata.get('parent_hash')),
            'live_verified': False, 'automatic_reload_performed': False}


def observation_roster(rows, expected=None):
    from .incidence import validate_roles
    validate_roles(rows)
    identities = []
    for row in rows:
        identities.append((row.get('observation_type', 'KORDON_PAIR'), row.get('category', 'OA'),
                           int(row['origin_station']), int(row['destination_station']),
                           row.get('aggregation', 'DIRECTED'), row['role']))
    require(len(identities) == len(set(identities)), 'DUPLICATE_OBSERVATION_ROSTER_ROW')
    counts = Counter(r['role'] for r in rows)
    result = {'rows': len(rows), 'calibration': counts['CALIBRATION'],
              'validation': counts['VALIDATION'], 'diagnostic': counts['DIAGNOSTIC'],
              'identity_sha256': canonical_hash(sorted(identities)),
              'authority_family': 'CORDON_SDP', 'uses_2022_profile_count': False}
    if expected is not None:
        require(isinstance(expected, dict), 'INVALID_EXPECTED_ROSTER')
        for key in ('rows', 'calibration', 'validation', 'diagnostic', 'identity_sha256'):
            require(key in expected and expected[key] == result[key], 'OBSERVATION_ROSTER_GATE_MISMATCH:' + key)
    return result


def diagnostic_reference_hash(reference):
    """Use PERF2 nonfinite-safe diagnostic hashing, never for objective numbers."""
    return parent_module('r1_15a2_candidate_readback_bundle_v24915p2').diagnostic_reference_hash(reference)


def readback_manager(cfg, *, run_token, session_token, telemetry=None):
    """Prepared API for future explicitly authorized adapter integration.

    Does not discover/attach Visum or mark an assignment complete. The inherited
    manager remains unable to capture until its full caller-owned protocol runs.
    """
    validate_runtime_options(cfg)
    return parent_module('r1_15a2_candidate_readback_bundle_v24915p2').CandidateReadbackManager(
        cfg, telemetry=telemetry, run_token=run_token, visum_session_token=session_token)


def validate_perf01_options(policy='disabled', cache_dir=None, context='same-sealed-snapshot', command=None):
    """Separate explicit offline derivative permission; no legacy cache bypass."""
    require(policy in ('disabled','build-offline','require-verified-hit'),'PERF01_UNKNOWN_REUSE_POLICY')
    require(context=='same-sealed-snapshot','CACHE_EPOCH_NOT_PROVEN_RECAPTURE_REQUIRED')
    if policy=='disabled':
        require(cache_dir is None,'PERF01_CACHE_DIR_WITH_DISABLED_POLICY')
    else:
        require(cache_dir is not None,'PERF01_EXPLICIT_CACHE_DIR_REQUIRED')
        require(command is None or command in ('inspect-cache','propose'),'PERF01_OFFLINE_COMMAND_ONLY')
    return {'derived_cache_policy':policy,'native_com_permitted':False,'apply_permitted':False,
            'same_sealed_snapshot_only':True,'legacy_cross_run_cache_enabled':False}
