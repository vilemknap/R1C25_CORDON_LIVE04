from pathlib import Path
import json
r=Path('/mnt/data/R1_CORDON_UPDATE_20261022/release');p=r/'cordon2025/common.py';s=p.read_text()
s=s.replace("    cfg = read_json(p)\n", "    cfg = read_json(p)\n    from .state import validate_runtime_options\n    validate_runtime_options(cfg)\n")
p.write_text(s)
p=r/'cordon2025/incidence.py';s=p.read_text();s=s.replace('from .common import write_npz','from .common import write_npz\nfrom .state import snapshot_semantics')
s=s.replace("        meta=dict(db.execute('SELECT key,value FROM metadata'))", "        meta=dict(db.execute('SELECT key,value FROM metadata'))\n        state_audit=snapshot_semantics(evidence,cfg,meta)")
s=s.replace("        require(set(station_map).issubset(set(edges.values()))", "        require(len(edges)==len(set(edges.values())),'DUPLICATE_DIRECTIONAL_EDGE_IDENTITY')\n        require(set(station_map).issubset(set(edges.values()))")
# Include state evidence in every method without changing numerical arrays.
s=s.replace("dict(audit,method=meth,nnz=len(vv))", "dict(audit,method=meth,nnz=len(vv),semantic_snapshot=state_audit,cross_run_cache_reuse=False)")
p.write_text(s)
p=r/'cordon2025/__main__.py';s=p.read_text();s=s.replace('from .io import read_json, safe_failure_report','from .io import read_json, safe_failure_report\nfrom .state import observation_roster\nfrom .targeting import path_targeting_report')
s=s.replace("        inc.save(out)\n", "        inc.save(out)\n        write_json(out/'OBSERVATION_ROSTER.json',observation_roster(inc.rows,cfg.get('expected_observation_roster')))\n        write_json(out/'TARGETING_CONTEXT.json',path_targeting_report(inc))\n")
p.write_text(s)
p=r/'CORDON_2025_CONFIG.json';c=json.loads(p.read_text());c.update(schema='R1_CORDON_2025_OFFLINE_V2',authority_family='CORDON_SDP',persistent_path_cache_enabled=False,automatic_cache_discovery=False,automatic_live_reload=False,flowbundle_count_authority=False,wallclock_limit_seconds=None,expected_snapshot_semantics=None,expected_observation_roster=None,actual_demand_sha256=None,upstream_technical_port='V24915_PERF2C_RESUME_IOFIX4_AND_V24916_FRESH0_IOFIX3_PATHFIX3_20261022')
p.write_text(json.dumps(c,indent=2)+'\n')
