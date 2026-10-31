# -*- coding: utf-8 -*-
"""Offline fault injection: initial Visum COM read rejects transient calls."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

import r1_15a2_com_compat as com
from r1_15a2_com_busy_snapshot_hotfix_v1 import activate
from r1_15a2_supply_visum import VisumAdapter as SupplyAdapter
from r1_15a2_trial_adapter_v24915p2c import VisumAdapter as Perf2cAdapter
from tests.test_supply_visum_v22 import small_cfg, state_visum


class Busy(RuntimeError):
    hresult = com.RPC_E_CALL_REJECTED


class TryLater(RuntimeError):
    hresult = com.RPC_E_SERVERCALL_RETRYLATER


class NetIntermittent:
    def __init__(self, inner, *, property_name="Links", times=2,
                 exception_type=Busy):
        self.inner = inner
        self.property_name = property_name
        self.times = times
        self.exception_type = exception_type
        self.calls = 0

    def __getattr__(self, name):
        if name == self.property_name:
            self.calls += 1
            if self.calls <= self.times:
                raise self.exception_type("Volaný odmítl volání.")
        return getattr(self.inner, name)


def cfg():
    result = copy.deepcopy(small_cfg())
    result["com_resilience"] = {
        "enabled": True,
        "max_attempts": 5,
        "initial_delay_seconds": 0.0,
        "backoff_factor": 1.0,
        "max_delay_seconds": 0.0,
        "scoped_policies": {
            "startup_snapshot_read": {
                "max_attempts": 5,
                "initial_delay_seconds": 0.0,
                "max_delay_seconds": 0.0,
                "backoff_factor": 1.0,
                "max_elapsed_seconds": 10.0,
            }
        },
    }
    return result


def test_hotfix_retry_preflight_bulk_links_transient_then_pass():
    activate()
    visum = state_visum()
    adapter = SupplyAdapter(visum, cfg())
    before = adapter.read_links()
    proxy = NetIntermittent(visum.Net, property_name="Links", times=2)
    visum.Net = proxy
    after = adapter.read_links()
    assert before == after
    assert proxy.calls >= 3
    assert adapter.r1_com_busy_read_retry_events[0]["label"] == "SUPPLY_VISUM_READ_LINKS"
    assert all(event["event"] == "RETRY" for event in adapter.r1_com_busy_read_retry_events)


def test_hotfix_retry_legacy_snapshot_without_change_of_semantic_hashes():
    activate()
    visum = state_visum()
    adapter = SupplyAdapter(visum, cfg())
    reference = adapter.snapshot()
    proxy = NetIntermittent(visum.Net, property_name="Matrices", times=2,
                            exception_type=TryLater)
    visum.Net = proxy
    actual = adapter.snapshot()
    assert actual == reference
    assert proxy.calls >= 3
    assert any(event["label"] == "SUPPLY_VISUM_SNAPSHOT"
               for event in adapter.r1_com_busy_read_retry_events)


def test_hotfix_retry_optimized_and_preserve_perf2c_shadow_parity():
    activate()
    visum = state_visum()
    runtime = cfg()
    runtime.update({"apply": False, "production_apply": False,
                    "trial_calibration": {"enabled": True},
                    "performance": {"persistent_path_cache": {"enabled": False},
                                    "v24915_perf2c_single_pass_snapshot": {
                                        "enabled": True,
                                        "shadow_parity_once": True,
                                        "fallback_to_legacy": True}}})
    adapter = Perf2cAdapter(visum, runtime)
    first = adapter.legacy_snapshot_from_live_visum()
    assert adapter.last_perf2c_snapshot_parity["status"] == "EXACT_PARITY_PASS"
    proxy = NetIntermittent(visum.Net, property_name="Matrices", times=1)
    visum.Net = proxy
    actual = adapter.legacy_snapshot_from_live_visum()
    assert actual == first
    assert actual["state_hash"]
    assert proxy.calls >= 2
    assert adapter._perf2c_runtime_disabled is False
    assert adapter.last_perf2c_snapshot_parity["status"] == "EXACT_PARITY_PASS"
    assert any(event["label"] == "PERF2C_SINGLE_PASS_SNAPSHOT"
               for event in adapter.r1_com_busy_read_retry_events)


def test_hotfix_nontransient_com_error_is_not_retried():
    activate()
    visum = state_visum()
    adapter = SupplyAdapter(visum, cfg())
    class NotTransient(ValueError):
        def __init__(self, _message):
            super().__init__("PERMANENT_SCHEMA_ERROR")
    proxy = NetIntermittent(visum.Net, property_name="Links", times=50,
                            exception_type=NotTransient)
    visum.Net = proxy
    with pytest.raises(ValueError, match="PERMANENT_SCHEMA_ERROR"):
        adapter.read_links()
    # Plain ValueError is not a transient COM HRESULT, regardless of its text.
    assert proxy.calls == 1


def test_hotfix_exhaustion_propagates_original_error_with_bounded_retries():
    activate()
    visum = state_visum()
    config = cfg()
    config["com_resilience"]["scoped_policies"]["startup_snapshot_read"]["max_attempts"] = 3
    adapter = SupplyAdapter(visum, config)
    proxy = NetIntermittent(visum.Net, property_name="Links", times=50)
    visum.Net = proxy
    with pytest.raises(Busy):
        adapter.read_links()
    assert proxy.calls <= 6  # internal bulk -> scalar fallback; 3 outer attempts
    assert any(event["event"] == "EXHAUSTED"
               for event in adapter.r1_com_busy_read_retry_events)


def test_original_parent_bundle_still_passes_all_seals_after_hotfix():
    path = Path(__file__).resolve().parents[1] / "R1_15A2_AGGRESSIVE_TGTD_V1_FIX1.py"
    spec = importlib.util.spec_from_file_location("_r1_agg_sealed_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    activate(module)
    evidence = module._verify_rebase_bundle()
    assert evidence["passes"] is True
    assert evidence["base_files_verified_unchanged"] == 947
    effective, *_ = module.prepare_runtime_config()
    assert effective["aggressive_tuning"]["com_busy_snapshot_retry_hotfix"]["status"] == "ACTIVE"
    non_science_keys = {"config_path", "config_sha256", "implementation_hash",
                        "tg_dependency_contract_path", "tg_dependency_contract_sha256",
                        "long_authority_path", "long_authority_sha256", "aggressive_tuning"}
    assert effective["aggressive_tuning"]["effective_science_hash"] == (
        module.canonical_hash({k: v for k, v in effective.items()
                               if k not in non_science_keys}))
    assert "r1_15a2_com_busy_snapshot_hotfix_v1.py" in effective["implementation_files"]
    assert "R1_15A2_AGGRESSIVE_TGTD_V1_FIX1_COMBUSY_RETRY.py" in effective["implementation_files"]
    assert effective["coupled_demand"]["max_outer_cycles"] == 100
    assert effective["coupled_demand"]["finecdf_td"]["ipf_tolerance_policy"] == (
        "UNCHANGED_NEVER_RELAXED_BY_CALIBRATOR")
