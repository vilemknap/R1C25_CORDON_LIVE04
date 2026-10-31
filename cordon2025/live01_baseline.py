"""Complete LIVE01 read-only orchestration, deliberately no LIVE02 transaction."""
from pathlib import Path
import uuid
import traceback
import numpy as np
from .common import ROOT,require,read_json,canonical_hash
from .io import write_json,write_csv,write_npz,safe_failure_report,mkdir,exception_text,write_text
from .session import RunSession
from . import com_busy
from .visum_startup import ReadControl,settings,capture
from .live01_config import load_config,calculation_config
from .live01_observations import load_authority,aggregate_whole
from .live01_visum import model_preflight,verify_end_state
from .live01_provenance import verify_protected_sources,bind_snapshot,guarded_output_root
from .live01_generation import propose_generation
from .incidence import build_from_snapshot
from .authority import mapping


def run(visum,*,output_root=None,options=None,config_path=None):
    require(visum is not None,'VISUM_NOT_INJECTED')
    cfg=load_config(config_path);pins=verify_protected_sources()
    output_root=guarded_output_root(output_root)
    configured=read_json(ROOT/'CORDON_2025_STARTUP_OPTIONS.json')
    configured.update(options or {});opt=settings(configured)
    require(opt['full_geometry_check'],'LIVE01_FULL_GEOMETRY_REQUIRED')
    cells,authority=load_authority(cfg)
    folder=None;ctl=None;session=None
    # Mock label must be visible on all synthetic runs; never claim native PASS.
    try:origin=visum.origin
    except Exception:origin='NATIVE_INJECTED_VISUM'
    synthetic=isinstance(origin,str) and any(s in origin.upper() for s in ('MOCK','SYNTHETIC','FIXTURE'))
    execution='MOCK' if synthetic else 'NATIVE_INJECTED'
    try:
        with RunSession('LIVE01_BASELINE_'+uuid.uuid4().hex[:12],output_root) as session:
            folder=session.folder;ctl=ReadControl(folder)
            session.start(cfg,{'live_config':Path(config_path or ROOT/'CORDON_LIVE01_CONFIG.json')})
            write_json(folder/'LIVE01_SOURCE_PROOF.json',pins)
            write_json(folder/'EFFECTIVE_CONFIG.json',cfg)
            write_json(folder/'WHOLE_MATRIX_AUTHORITY_AUDIT.json',authority)
            with com_busy.parent_hotfix_scope() as hotfix:
                write_json(folder/'COMBUSY_HOTFIX_ACTIVATION.json',hotfix)
                pre,state=model_preflight(visum,cfg,folder,ctl,opt)
                session.checkpoint('LIVE01_CURRENT_MODEL_BOUND')
                mathcfg=calculation_config(cfg,state['actuatable_zones'])
                cache,epath=capture(visum,mathcfg,folder,ctl,opt,pre)
                evidence=read_json(epath);binding=bind_snapshot(pre,state,evidence,cache)
                unchanged=verify_end_state(visum,cfg,folder,ctl,opt,pre,state)
                write_json(folder/'SOURCE_FINGERPRINT.json',binding)
                write_json(folder/'END_STATE_READBACK.json',unchanged)
                session.checkpoint('LIVE01_FRESH_CAPTURE_SEALED')
            mathcfg['actual_network_sha256']=pre[0]['network_sha256']
            mathcfg['actual_demand_sha256']=evidence['demand_sha256']
            station_map,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv')
            directed=build_from_snapshot(cache,station_map,mathcfg,evidence,hits_output=folder/'STATION_HITS.csv')
            all_rows=[];reports={};proof={};rosters={}
            for method,dinc in directed.items():
                ctl.checkpoint('LIVE01_SOLVE_'+method,force=True)
                inc,trace,roster=aggregate_whole(dinc,cells)
                solution,proposal=propose_generation(inc,cfg,state)
                out=folder/method;mkdir(out)
                solution.save(out,inc)
                # Compact derived evidence, no four copies of the all-OD audit.
                write_npz(out/'INCIDENCE.npz',row=inc.operator.row_idx,col=inc.operator.col_idx,
                          through=inc.operator.values,share=inc.share_operator.values,q=inc.q_current,
                          model=inc.model,mutable=inc.mutable,fixed=inc.fixed)
                write_json(out/'OBSERVATION_ROSTER.json',roster)
                write_csv(out/'WHOLE_MATRIX_TRANSFORM_TRACE.csv',trace)
                write_json(out/'PROPOSED_TG_CANDIDATES.json',proposal)
                write_json(out/'LIVE01_INCIDENCE_BINDING.json',{'source_snapshot':binding,
                    'method':method,'rows':inc.rows,'variables':'OD_GUIDANCE.csv',
                    'source_geometry_and_od_audit':'../p.sqlite',
                    'per_od_external_parity':inc.audit['per_od_external_parity'],
                    'selected_dsegs':inc.audit['selected_dsegs']})
                all_rows.extend(dict(r,method=method,linearized=float(solution.prediction[i]),
                                     mutable=float(inc.mutable[i]),fixed=float(inc.fixed[i])) for i,r in enumerate(trace))
                reports[method]={'status':proposal['status'],'candidate_count':proposal['candidate_count'],
                                 'proposal_sha256':proposal['proposal_sha256'],
                                 'proposal_path':method+'/PROPOSED_TG_CANDIDATES.json'}
                proof[method]={'objective_rows':solution.problem.operator.n_rows,
                               'selected_row_indices':solution.problem.original_profile_indices.tolist(),
                               'operator_nonzeros':len(inc.operator.values),'mutable_variables':len(inc.variables),
                               'roles':roster,'target_model_transform':'LEGACY_BIDIRECTIONAL_SUM'}
                rosters[method]=roster
            # Pure solve can be long. Recheck the injected model immediately
            # before publishing its proposal rather than claiming stale values
            # are still current merely because capture succeeded earlier.
            ctl.checkpoint('LIVE01_FINAL_STATE_READBACK',force=True)
            with com_busy.parent_hotfix_scope():
                final_state=verify_end_state(visum,cfg,folder,ctl,opt,pre,state)
            write_json(folder/'FINAL_STATE_READBACK.json',final_state)
            write_csv(folder/'WHOLE_MATRIX_DIAGNOSTICS.csv',all_rows)
            write_json(folder/'OBSERVATION_ROSTER.json',{'policy':cfg['observation_policy'],'methods':rosters})
            write_json(folder/'WHOLE_MATRIX_ROLE_AND_OBJECTIVE_PROOF.json',proof)
            write_json(folder/'PROPOSED_TG_CANDIDATES.json',reports)
            handoff={'schema':'CORDON_LIVE02_HANDOFF_V1','preflight_authority':'MODEL_READBACK.json',
                'baseline_state':binding,'proposed_tg_candidate':reports,
                'current_model_fingerprint':state['current_model_fingerprint'],
                'restore_proof_needed':True,'fresh_assignment_required_after_candidate':True,
                'checkpoint_manifest':'RUN_CHECKPOINT.json','variant_selection':'NOT_ACCEPTED_DIAGNOSTIC_ALTERNATIVES',
                'apply_permitted':False,'native_candidate_accepted':False,'execution_kind':execution,
                'source_state_scope':'SAME_INVOCATION_CAPTURE_AND_FINAL_READBACK_NOT_FUTURE_EPOCH',
                'fresh_live_readback_required_before_any_write':True,
                'candidate_effect_verified':False,'calibration_ready':False}
            write_json(folder/'BASELINE_AND_PROPOSAL_CONTRACT.json',handoff)
            result={'schema':'LIVE01_RESULT_V1','status':'MOCK_READONLY_BASELINE_PASS' if synthetic else 'NATIVE_READONLY_BASELINE_PASS',
                'stage':'LIVE01_BASELINE_READ_ONLY','execution_kind':execution,'output_directory':str(folder),
                'model_year':2025,'source_cells':256,'objective_rows_per_method':120,'validation_rows':0,
                'variants':reports,'apply_permitted':False,'assignment_executed':False,
                'native_candidate_accepted':False,'real_visum_verified':False,'native_readonly_baseline_verified':not synthetic,
                'production_ready':False,'next_stage':'LIVE02_FIRST_NATIVE_TG_CYCLE',
                'remaining_gates':['NATIVE_CANDIDATE_EFFECT_NOT_RUN','ROLLBACK_NOT_RUN','PRODUCTION_METHODOLOGY_NOT_CERTIFIED']}
            ctl.checkpoint('LIVE01_BASELINE_COMPLETE',force=True)
            write_json(folder/'COM_READ_RETRY.json',com_busy.telemetry(ctl,opt))
            write_json(folder/'00_RESULT.json',result)
            session.checkpoint('LIVE01_BASELINE_COMPLETE',completed=True)
            return result
    except BaseException as exc:
        if folder:
            safe_failure_report(folder,exc,traceback_text=traceback.format_exc())
            # Even failure after completion publication (e.g. lock cleanup)
            # must not leave a successful checkpoint advertised as complete.
            try:
                cp=read_json(folder/'RUN_CHECKPOINT.json')
                cp.update(completed=False,stage='LIVE01_FAILED',failure_reason=exception_text(exc))
                write_json(folder/'RUN_CHECKPOINT.json',cp)
            except Exception:
                pass
            try:
                write_text(folder/'99_TRACEBACK.txt',traceback.format_exc())
            except Exception:
                pass
            try:
                write_json(folder/'00_RESULT.json',{'status':'LIVE01_BLOCKED','reason':exception_text(exc),
                    'execution_kind':execution,'apply_permitted':False,'assignment_executed':False,
                    'native_candidate_accepted':False,'production_ready':False})
                if ctl:write_json(folder/'COM_READ_RETRY.json',com_busy.telemetry(ctl,opt))
            except Exception:pass
        raise
