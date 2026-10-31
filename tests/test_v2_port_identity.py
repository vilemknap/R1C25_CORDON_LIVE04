import hashlib,json
from pathlib import Path
from cordon2025.common import ROOT,parent_core


def test_additive_donor_library_bytes_exact():
    manifest=json.loads((ROOT/'docs/update_v2/DONOR_LIBRARY_MANIFEST.json').read_text())
    assert len(manifest)==52
    for name,entry in manifest.items():
        assert hashlib.sha256((ROOT/'parent'/name).read_bytes()).hexdigest()==entry['sha256']


def test_no_new_run_specific_launchers_in_parent():
    assert not (ROOT/'parent/00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py').exists()
    assert not (ROOT/'parent/r1_15a2_fresh0_shortroot_parent_v24916.py').exists()
    assert not (ROOT/'parent/r1_15a2_active_targeting_runtime_v24916_a0004.py').exists()


def test_legacy_core_and_cordon_hook_survive():
    core=parent_core()
    assert 'deadband' in core.GuidanceProblem.__dataclass_fields__
    from r1_15a2_two_mode_v238 import TwoModeRouteCollector
    assert hasattr(TwoModeRouteCollector,'cordon_incidence_offline')


def test_new_pure_libraries_import_without_global_activation():
    parent_core()
    import r1_15a2_runtime_io_hotfix_profile488 as io
    import r1_15a2_candidate_readback_bundle_v24915p2 as bundle
    import r1_15a2_single_pass_snapshot_v24915p2c as snap
    import r1_15a2_skim_v24916p2c as skim
    import r1_15a2_two_mode_v238 as two
    assert io.replace_with_retry and bundle.CandidateReadbackManager and snap.single_pass_exact_snapshot and skim.seal_dist_km
    assert two.atomic_json is not io.critical_atomic_json
