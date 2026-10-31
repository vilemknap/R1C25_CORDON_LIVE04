from pathlib import Path
import json,hashlib,csv
R=Path('/mnt/data/R1_CORDON_UPDATE_20261022');r=R/'release';docs=r/'docs/update_v2'
removed=['r1_15a2_fresh_baseline_live_preflight_v24916p2c.py','r1_15a2_safety_v24915p2c3.py']
m=json.loads((docs/'DONOR_LIBRARY_MANIFEST.json').read_text())
for n in removed:
    if n in m:
        (r/'parent'/n).unlink();m.pop(n)
(docs/'DONOR_LIBRARY_MANIFEST.json').write_text(json.dumps(m,indent=2))
p=r/'tests/test_v2_port_identity.py';t=p.read_text().replace('len(manifest)==54','len(manifest)==52');p.write_text(t)
d=json.loads((docs/'PORT_DECISIONS.json').read_text())
print(type(d),str(d)[:400])
(docs/'CP03_DEPENDENCY_PRUNING.json').write_text(json.dumps({'removed_in_cp03':removed,'reason':'Run-bound live preflight/extension dependency. Excluded launchers are intentionally not imported into offline 2025. Original bytes remain in CP00 donor archive.','remaining_libraries':len(m),'upstream_io_activate_never_called':True},indent=2))
p=r/'cordon2025/state.py';t=p.read_text();old="    synthetic = evidence.get('origin') == 'SYNTHETIC_TEST_FIXTURE'\n"
new=old+"    # Source expectations are independent of availability of semantic metadata.\n    for evidence_key, config_key in (('network_sha256', 'actual_network_sha256'),\n                                    ('demand_sha256', 'actual_demand_sha256')):\n        if cfg.get(config_key) is not None:\n            require(valid_hash(cfg[config_key]), 'EXPECTED_SOURCE_HASH_INVALID:' + config_key)\n            require(evidence.get(evidence_key) == cfg[config_key], 'CACHE_SOURCE_IDENTITY_MISMATCH:' + evidence_key)\n"
assert old in t;t=t.replace(old,new);p.write_text(t)
p=r/'cordon2025/incidence.py';t=p.read_text();old="    core=parent_core()\n    require(cfg.get('apply') is False,'V1_APPLY_FORBIDDEN')"
new="    if hits_output is not None:\n        require(Path(hits_output).resolve() != Path(path).resolve(), 'OUTPUT_INPUT_COLLISION')\n    core=parent_core()\n    require(cfg.get('apply') is False,'V1_APPLY_FORBIDDEN')"
assert old in t;t=t.replace(old,new,1);p.write_text(t)
jp=R/'audit/DRIVE_JOURNAL.json';j=json.loads(jp.read_text());name='CP02_CRITICAL_IO_FINALIZER_20261022'
if not any(x['checkpoint']==name for x in j):
    x=json.loads((R/'checkpoints'/f'{name}.zip.receipt.json').read_text());x.update(drive_verified=True,drive_id='14_eE5NDNRgo57wOjirO-52NfrrEjOv97',drive_sha_sidecar_id='1U6M4c49pZDqXyWPXKbaMQyAweOFRJHDX',verification_level='METADATA_NAME_SIZE_PARENT');j.append(x)
jp.write_text(json.dumps(j,indent=2))
(docs/'CP03_STATE_TARGETING_REPORT.md').write_text('''# CP03: state, cache and observation contracts

Ported SEMRELOAD1 principle without live reload: compare all eight semantic fields, cache parent state, network and demand identity. Missing evidence is diagnostic-only, never a live PASS. Explicit expected source hashes are checked independently of semantic metadata.

GATEFIX2 uses a dynamically hashed CORDON_SDP roster: counts, roles, category, direction and aggregation, not hardcoded PROFILE488. Runtime disallows persistent cross-run discovery/reuse, live LoadVersion, FlowBundle as observation authority and wallclock termination. Explicit completed SQLite snapshots remain supported.

CAL-only signed targeting uses the exact existing sparse cordon operator: search guidance only, never replacing counts. Original PERF2 diagnostic hashing and readback manager APIs and skim sealing/TD evidence contracts are exposed offline; live optimized snapshot and COM reactivation are NOT called.

Dependency closure refinement: two run-bound donor libraries were removed after detecting dependencies on excluded one-click scripts. 52 exact-byte donor libraries remain. Earlier checkpoints preserve history. Original core tolerance extension and C17 science remain unchanged.

Validation: CP03_STATE_TESTS: 139 passed before final source expectation/collision hardening; follow-up test count is recorded in CP03_FINAL.log. No live Visum tested.
''')
