# -*- coding: utf-8 -*-
"""Read-only COM-busy retry for R1_15A2 Aggressive V1 FIX1/PERF2C.

Applied in memory AFTER the parent package is imported.  Parent source files
and all pinned bundle manifests stay byte-for-byte unchanged.

Only these read-only entry points are retried:
* supply_visum.VisumAdapter.read_links (both bulk and scalar fallback)
* supply_visum.VisumAdapter.snapshot (legacy semantic snapshot)
* single_pass_snapshot_v24915p2c.single_pass_exact_snapshot (optimized)

The existing r1_15a2_com_compat.com_call_with_retry is used verbatim.  It
retries ONLY RPC_E_CALL_REJECTED and RPC_E_SERVERCALL_RETRYLATER; all unrelated
errors propagate immediately.  There is no new Visum instance, LoadVersion,
OD writing, matrix manipulation, procedure execution or fallback on corruption.
"""
from __future__ import annotations

from functools import wraps
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import r1_15a2_com_compat as com
import r1_15a2_supply as supply
import r1_15a2_runtime_v1 as rt
import r1_15a2_supply_visum as supply_visum
import r1_15a2_single_pass_snapshot_v24915p2c as optimized
import r1_15a2_trial_adapter_v24915p2c as adapter_mod

RELEASE = "R1_15A2_AGGRESSIVE_FIX1_COMBUSY_SNAPSHOT_RETRY_V1_20261023"
SCOPE = "startup_snapshot_read"
# A host may temporarily reject calls while it is finishing a heavy operation.
# Bounds are per failed read; they are not new global calibration time limits.
DEFAULTS = {
    "max_attempts": 64,
    "initial_delay_seconds": 0.15,
    "backoff_factor": 1.5,
    "max_delay_seconds": 1.5,
    "max_elapsed_seconds": 75.0,
}

_ACTIVE = False
_COUNTERS: Dict[str, int] = {}


def _policy(adapter: Any) -> Dict[str, Any]:
    raw = dict(getattr(adapter, "com_retry_policy", None) or
               (getattr(adapter, "cfg", {}) or {}).get("com_resilience", {}) or {})
    # Respect the explicit global opt-out; never silently enable retry.
    merged = com.scoped_retry_policy(raw, SCOPE)
    if merged.get("enabled") is True:
        original_scope = (raw.get("scoped_policies", {}) or {}).get(SCOPE, {}) or {}
        # Preserve caller overrides; increase only the scope's missing defaults.
        for key, value in DEFAULTS.items():
            if key not in original_scope:
                merged[key] = value
    return merged


def _telemetry(adapter: Any, name: str, label: str, event: Dict[str, Any]) -> None:
    # No calls to Visum, and failure to log must never mask an original COM error.
    try:
        records = getattr(adapter, "r1_com_busy_read_retry_events", None)
        if records is None:
            records = []
            setattr(adapter, "r1_com_busy_read_retry_events", records)
        if len(records) < 1000:
            records.append({"event": name, "label": label,
                            "com_call_label": event.get("label"),
                            **{k: v for k, v in event.items() if k != "label"}})
        if name == "RETRY" and event.get("attempt") in (1, 5, 15, 30, 50):
            logging.warning("%s %s: COM busy (%s), retry %s/%s, pause %.3fs",
                            RELEASE, label, event.get("hresult"),
                            event.get("next_attempt"), event.get("max_attempts"),
                            event.get("delay_seconds", 0.0))
        if name == "EXHAUSTED":
            logging.error("%s %s: COM remained busy after %s attempts (%s)",
                          RELEASE, label, event.get("attempt"), event.get("error"))
    except Exception:
        pass


def _read_retry(adapter: Any, label: str, call: Callable[[], Any]) -> Any:
    # snapshot() -> read_links() is nested. Without this depth guard, a busy
    # server could spend a separate 75-second retry lease on EACH nested call
    # and then multiply that budget by the outer loop's 64 attempts.
    depth = int(getattr(adapter, "_r1_combusy_read_retry_depth", 0))
    if depth:
        return call()  # An outer read-only transaction owns the retry lease.
    setattr(adapter, "_r1_combusy_read_retry_depth", depth + 1)
    try:
        policy = _policy(adapter)
        return com.com_call_with_retry(
            call,
            label="%s:%s" % (SCOPE, label),
            retry_policy=policy,
            on_retry=lambda event: _telemetry(adapter, "RETRY", label, event),
            on_exhausted=lambda event: _telemetry(adapter, "EXHAUSTED", label, event),
        )
    finally:
        setattr(adapter, "_r1_combusy_read_retry_depth", depth)


def _method_retry(method: Callable[..., Any], label: str) -> Callable[..., Any]:
    @wraps(method)
    def wrapped(adapter: Any, *args: Any, **kwargs: Any) -> Any:
        return _read_retry(adapter, label, lambda: method(adapter, *args, **kwargs))
    wrapped._r1_combusy_original = method  # type: ignore[attr-defined]
    return wrapped


def _optimized_retry(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def wrapped(adapter: Any) -> Any:
        return _read_retry(adapter, "PERF2C_SINGLE_PASS_SNAPSHOT", lambda: method(adapter))
    wrapped._r1_combusy_original = method  # type: ignore[attr-defined]
    return wrapped



def _patch_launcher_prepare(launcher: Any) -> None:
    original_prepare = launcher.prepare_runtime_config
    if getattr(original_prepare, "_r1_combusy_original", None) is not None:
        raise RuntimeError("COMBUSY_PREPARE_ALREADY_PATCHED")
    @wraps(original_prepare)
    def prepare_with_hotfix(*args: Any, **kwargs: Any) -> Any:
        result = original_prepare(*args, **kwargs)
        cfg = result[0]
        files = cfg.setdefault("implementation_files", {})
        root = Path(launcher.HERE)
        own_source = Path(__file__).name
        entrypoint = "R1_15A2_AGGRESSIVE_TGTD_V1_FIX1_COMBUSY_RETRY.py"
        for relative in (own_source, entrypoint):
            path = root / relative
            if not path.is_file():
                raise RuntimeError("COMBUSY_RUNTIME_FILE_MISSING:" + relative)
            files[relative] = rt.sha256_file(path)
        cfg["implementation_hash"] = supply.canonical_hash(files)
        tuning = cfg["aggressive_tuning"]
        previous_science_hash = tuning["effective_science_hash"]
        tuning["com_busy_snapshot_retry_hotfix"] = {
            "status": "ACTIVE",
            "release": RELEASE,
            "scope": SCOPE,
            "default_retry": dict(DEFAULTS),
            "execution": "READ_ONLY_TRANSIENT_COM_RPC_ONLY",
            "parent_source_and_sealed_hashes_unchanged": True,
            "pre_hotfix_science_hash": previous_science_hash,
        }
        # Same exact science-hash field exclusion as the parent launcher.
        # When runtime implementation-file hashes change, the hash must also
        # be recalculated or the EFFECTIVE_CONFIG would claim stale provenance.
        non_science_keys = frozenset((
            "config_path", "config_sha256", "implementation_hash",
            "tg_dependency_contract_path", "tg_dependency_contract_sha256",
            "long_authority_path", "long_authority_sha256",
            "aggressive_tuning",
        ))
        tuning["effective_science_hash"] = supply.canonical_hash(
            {k: v for k, v in cfg.items() if k not in non_science_keys})
        return result
    prepare_with_hotfix._r1_combusy_original = original_prepare  # type: ignore[attr-defined]
    launcher.prepare_runtime_config = prepare_with_hotfix

def activate(launcher: Optional[Any] = None) -> Dict[str, Any]:
    """Install patches once, before the first adapter/Visum read.

    The sealed original launcher still executes all parent on-disk manifest
    checks.  The extra runtime module and entrypoint are recorded in the
    derived effective implementation hash (not in historical parent manifests).
    """
    global _ACTIVE
    if _ACTIVE:
        if launcher is not None:
            _patch_launcher_prepare(launcher)
        return {"active": True, "release": RELEASE, "idempotent": True}
    for name in ("read_links", "snapshot"):
        original = getattr(supply_visum.VisumAdapter, name)
        if getattr(original, "_r1_combusy_original", None) is not None:
            raise RuntimeError("COMBUSY_HOTFIX_ALREADY_PATCHED_DIFFERENT_ACTIVATION:" + name)
        setattr(supply_visum.VisumAdapter, name,
                _method_retry(original, "SUPPLY_VISUM_" + name.upper()))
    original_optimized = optimized.single_pass_exact_snapshot
    if getattr(original_optimized, "_r1_combusy_original", None) is not None:
        raise RuntimeError("COMBUSY_OPTIMIZED_ALREADY_PATCHED")
    wrapped_optimized = _optimized_retry(original_optimized)
    optimized.single_pass_exact_snapshot = wrapped_optimized
    # PERF2C imported the function by value, not through the source module.
    adapter_mod.single_pass_exact_snapshot = wrapped_optimized

    if launcher is not None:
        _patch_launcher_prepare(launcher)
    _ACTIVE = True
    return {"active": True, "release": RELEASE, "idempotent": False,
            "patched_read_paths": ["VisumAdapter.read_links",
                                   "VisumAdapter.snapshot",
                                   "single_pass_exact_snapshot"]}
