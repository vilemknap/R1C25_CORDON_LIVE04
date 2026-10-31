#!/usr/bin/env python3
"""Independent offline verifier for the complete V24915 deployment tree."""
from __future__ import annotations
import hashlib, importlib.util, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
MANIFEST=ROOT/"MANIFEST_V24915.json"
RELEASE="R1_15A2_V2_4_9_15_COM_BUSY_RETRY_SAFE_FINALIZER_20261019"

def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def fail(code): raise SystemExit(code)

def main():
    if not MANIFEST.is_file(): fail("V24915_PACKAGE_MANIFEST_MISSING")
    manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema")!="R1_15A2_V24915_PACKAGE_MANIFEST_V1": fail("V24915_PACKAGE_MANIFEST_SCHEMA_MISMATCH")
    if manifest.get("release")!=RELEASE: fail("V24915_PACKAGE_RELEASE_MISMATCH")
    failures=[]
    for row in manifest.get("files",[]):
        rel=row.get("path"); path=ROOT/str(rel)
        if not path.is_file(): failures.append({"path":rel,"reason":"MISSING"}); continue
        if path.stat().st_size!=int(row.get("size",-1)): failures.append({"path":rel,"reason":"SIZE_MISMATCH"}); continue
        if sha256(path)!=row.get("sha256"): failures.append({"path":rel,"reason":"SHA256_MISMATCH"})
    if failures: fail("V24915_PACKAGE_MANIFEST_INVALID:"+json.dumps(failures,sort_keys=True))
    sys.path.insert(0,str(ROOT))
    spec=importlib.util.spec_from_file_location("v24915_verify_launcher",ROOT/"R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15.py")
    if spec is None or spec.loader is None: fail("V24915_LAUNCHER_IMPORT_SPEC_FAILED")
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    cfg=module.load_config()
    from r1_15a2_safety_v24915 import validate_v24915_config, validate_v24915_runtime_bundle
    config_result=validate_v24915_config(cfg,ROOT)
    runtime_result=validate_v24915_runtime_bundle(cfg,ROOT)
    result={"schema":"R1_15A2_V24915_PACKAGE_VERIFICATION_V1","release":RELEASE,"passes":True,
            "package_files_checked":len(manifest.get("files",[])),
            "runtime_files_checked":runtime_result.get("files_checked"),
            "accepted_count_start":config_result.get("accepted_count_start"),
            "next_outer_cycle":config_result.get("next_outer_cycle"),
            "generic_retry":runtime_result.get("retry_policy",{}).get("generic"),
            "bounded_path_export_retry":runtime_result.get("retry_policy",{}).get("bounded_path_export"),
            "final_verification_retry":runtime_result.get("retry_policy",{}).get("final_verification"),
            "safe_transient_finalizer":runtime_result.get("safe_transient_finalizer"),
            "supply_policy_preserved":runtime_result.get("supply_policy_preserved"),
            "real_visum_tested":False,"production_ready":False}
    print(json.dumps(result,indent=2,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
