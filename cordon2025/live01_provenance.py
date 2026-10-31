"""LIVE01 immutable source identity and serializable handoff guard."""
from pathlib import Path
from .common import ROOT,require,canonical_hash,read_json
from .io import sha256


def verify_protected_sources():
    records=read_json(ROOT/'provenance/live01/BASE_SOURCE_MANIFEST.json')['files']
    failures=[]
    for r in records:
        p=ROOT/r['path']
        if not p.is_file() or sha256(p)!=r['sha256']:failures.append(r['path'])
    require(not failures,'LIVE01_PROTECTED_SOURCE_CHANGED:'+','.join(failures[:10]))
    return {'status':'PROTECTED_SOURCE_IDENTITY_PASS','checked':len(records),
            'source_pins':read_json(ROOT/'provenance/live01/SOURCE_PINS.json')}


def bind_snapshot(pre,state,evidence,cache):
    require(evidence['completed'] and evidence['geometry_full_identity_proven'],'LIVE01_INCOMPLETE_SNAPSHOT')
    checks=evidence.get('full_geometry_checks',[])
    expected=set(state['od_segment_bindings'])
    require(len(checks)==12 and {c.get('dseg') for c in checks}==expected and all(c.get('check') in ('FULL_REPRESENTATIVE','FULL_SAME_MODE_MATCH') for c in checks),'LIVE01_FULL_GEOMETRY_COVERAGE')
    authorities=evidence.get('od_matrix_authorities',[])
    require(len(authorities)==12 and {a.get('dseg') for a in authorities}==expected,'LIVE01_MATRIX_AUTHORITY_COVERAGE')
    require(set(evidence.get('dseg_totals',{}))==expected,'LIVE01_VOLUME_COVERAGE')
    require(evidence['model_year']==2025 and evidence['origin']=='VISUM_SAVED_PATHS','LIVE01_WRONG_SNAPSHOT_SCOPE')
    require(evidence['network_sha256']==pre[0]['network_sha256'],'LIVE01_SNAPSHOT_NETWORK_STALE')
    require(evidence['demand_sha256']==canonical_hash(pre[0]['matrix_audit']),'LIVE01_SNAPSHOT_DEMAND_STALE')
    require(evidence['cache_sha256']==sha256(cache),'LIVE01_SNAPSHOT_HASH_CHANGED')
    require(evidence['source_version']==state['source_version'],'LIVE01_SNAPSHOT_SOURCE_CHANGED')
    return {'schema':'LIVE01_CAPTURE_BINDING_V1','source_snapshot_sha256':sha256(cache),
        'current_model_fingerprint':state['current_model_fingerprint'],
        'network_sha256':evidence['network_sha256'],'demand_sha256':evidence['demand_sha256'],
        'capture_policy':'FRESH_CAPTURE_THIS_INVOCATION',
        'saved_paths_read_from_current_injected_model':True,
        'new_assignment_verified':False,'historical_2022_cache_used':False,
        'apply_permitted':False,'production_ready':False}


def verify_handoff(handoff,current_fingerprint):
    require(handoff.get('schema')=='CORDON_LIVE02_HANDOFF_V1','LIVE01_HANDOFF_SCHEMA')
    require(handoff.get('apply_permitted') is False,'LIVE01_HANDOFF_WRITES_NOT_ALLOWED')
    require(handoff['current_model_fingerprint']==current_fingerprint,'LIVE01_HANDOFF_STALE_REBASE_REQUIRED')
    require(handoff['restore_proof_needed'] is True and handoff['fresh_assignment_required_after_candidate'] is True,'LIVE01_HANDOFF_TRANSACTION_GUARD')
    return True


def guarded_output_root(output_root=None):
    """Guard without resolving away symlinks/junctions or parent traversal."""
    import os
    import stat
    if output_root is None:
        path=Path(os.environ['LOCALAPPDATA'])/'R1C25_LIVE01' if os.name=='nt' and os.environ.get('LOCALAPPDATA') else ROOT/'OFFLINE_RESULTS'/'LIVE01'
    else:path=Path(output_root)
    require('..' not in path.parts,'LIVE01_OUTPUT_TRAVERSAL')
    path=path.absolute()
    for p in (path,*path.parents):
        require(not p.is_symlink(),'LIVE01_OUTPUT_LINK_FORBIDDEN')
        try:attr=getattr(p.lstat(),'st_file_attributes',0)
        except FileNotFoundError:continue
        require(not (attr & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)),'LIVE01_OUTPUT_REPARSE_FORBIDDEN')
    allowed=ROOT/'OFFLINE_RESULTS'
    require(not (path==ROOT or ROOT in path.parents) or path==allowed or allowed in path.parents,'LIVE01_OUTPUT_INSIDE_RELEASE')
    return path


def verify_handoff_directory(folder,current_fingerprint):
    """Verify an immutable LIVE01 handoff. This is NOT permission to apply it.

    LIVE02 must freshly bind its injected Visum state and take a restore point.
    Raw handoff JSON or matching model hashes alone never authorize a write.
    """
    from .session import verify_run
    folder=Path(folder)
    checked=verify_run(folder)
    require(checked['completed'] and checked['stage']=='LIVE01_BASELINE_COMPLETE',
            'LIVE01_HANDOFF_RUN_INCOMPLETE')
    handoff=read_json(folder/'BASELINE_AND_PROPOSAL_CONTRACT.json')
    verify_handoff(handoff,current_fingerprint)
    require(handoff.get('fresh_live_readback_required_before_any_write') is True,
            'LIVE01_HANDOFF_LIVE_REBIND_REQUIRED')
    candidates={}
    for method,rec in handoff['proposed_tg_candidate'].items():
        require(method in ('ALL_ORDERED_UNIQUE_PAIRS','EXACT_TWO_HITS'),
                'LIVE01_HANDOFF_METHOD_INVALID')
        require(rec['proposal_path']==method+'/PROPOSED_TG_CANDIDATES.json',
                'LIVE01_HANDOFF_PROPOSAL_PATH')
        proposal=read_json(folder/rec['proposal_path'])
        actual=canonical_hash({k:v for k,v in proposal.items() if k!='proposal_sha256'})
        require(actual==rec['proposal_sha256']==proposal['proposal_sha256'],
                'LIVE01_HANDOFF_PROPOSAL_HASH_CHANGED')
        require(proposal['current_model_fingerprint']==current_fingerprint,
                'LIVE01_HANDOFF_PROPOSAL_STALE')
        require(proposal['apply_permitted'] is False and proposal['real_visum_verified'] is False,
                'LIVE01_HANDOFF_NATIVE_EFFECT_NOT_ALLOWED')
        candidates[method]=len(proposal['candidate_rows'])
    require(len(candidates)==2,'LIVE01_HANDOFF_METHOD_MISSING')
    return {'status':'LIVE01_HANDOFF_ARTIFACTS_VERIFIED_NOT_APPLY_AUTHORIZED',
            'candidate_counts':candidates,'checkpoint':checked,
            'apply_permitted':False,'fresh_live_readback_required':True,
            'restore_proof_needed':True,'native_candidate_effect_verified':False}
