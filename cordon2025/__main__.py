"""Offline CLI. There is deliberately no COM import, discovery or APPLY command."""
from __future__ import annotations
import argparse,json,sys,traceback,datetime
from pathlib import Path
from .common import ROOT,ContractError,require,read_config,new_output,write_json,read_csv,sha256,canonical_hash,deployment_gate
from .authority import audit_workbooks,mapping
from .incidence import build_from_snapshot,aggregate_observations,METHODS
from .budget import from_audit_csv
from .optimizer import solve
from .feasibility import parent_projection,evaluate_realizability,finecdf_availability
from .demos import synthetic_demo
from .io import read_json, safe_failure_report
from .state import observation_roster
from .targeting import path_targeting_report
from .session import RunSession, verify_run
from .aggressive_policy import enabled as aggressive_enabled, SOURCE_REL as AGGRESSIVE_SOURCE_REL, DESIGN_SOURCE_REL
from .aggressive import propose as aggressive_propose


def targets_from_audit():
    target={}
    for row in read_csv(ROOT/'data/audited/PHYSICAL_TARGETS.csv'):
        if row['category']!='OA':continue
        require(int(row['survey_year'])==2026 and row['basis']=='RPDI','TARGET_BASIS_INVALID')
        a,b=int(row['matrix_row_station']),int(row['matrix_column_station'])
        key=(a,b);require(key not in target,'DUPLICATE_TARGET_CELL')
        target[key]=float(row['observed_rpdi'])
    require(len(target)==256,'OA_TARGET_GRID_INCOMPLETE')
    return target


def empirical_run(folder,cfg,cache,evidence_path,propose=False,allow_scenario=False,credit_scenario=False,checkpoint=None,zone_parameters=None,*,reuse_cache_dir=None,reuse_policy="disabled",reuse_context="same-sealed-snapshot",source_checkpoint=None,legacy_incidence_output=False):
    require(cache is not None and Path(cache).is_file(),'NO_2025_PATH_CACHE')
    require(evidence_path is not None and Path(evidence_path).is_file(),'SNAPSHOT_EVIDENCE_REQUIRED')
    evidence=read_json(evidence_path)
    require(evidence.get('origin')=='VISUM_SAVED_PATHS','EMPIRICAL_RUN_REQUIRES_VISUM_SAVED_PATHS_NOT_SYNTHETIC')
    cfg=dict(cfg)
    zone_rows=read_csv(zone_parameters) if zone_parameters is not None else None
    if zone_rows is not None:
        zone_ids=[int(row['zone_no']) for row in zone_rows]
        require(len(zone_ids)==len(set(zone_ids)), 'DUPLICATE_ZONE_PARAMETER_ROW')
    if not propose:
        cfg['mutable_dsegs']=[]  # Pure inspection requires no zonal actuator authority.
        if aggressive_enabled(cfg):
            from .aggressive_policy import META, DESIGN_KEYS, effective_config
            cfg.pop(META,None)
            for key in DESIGN_KEYS:cfg.pop(key,None)
            cfg=effective_config(cfg)
    idx,_=mapping(ROOT/'data/audited/STATION_MAPPING.csv')
    from .state import validate_perf01_options
    validate_perf01_options(reuse_policy,reuse_cache_dir,reuse_context,'propose' if propose else 'inspect-cache')
    perf=None
    if reuse_policy=='disabled':
        variants=build_from_snapshot(cache,idx,cfg,evidence,hits_output=folder/'STATION_HITS.csv')
    else:
        from .perf01_cache import get_or_build, write_run_binding
        perf=get_or_build(cache,idx,cfg,evidence_path,cache_dir=reuse_cache_dir,
                          policy=reuse_policy,context=reuse_context,source_checkpoint=source_checkpoint,
                          status_path=folder/'PERF01_CACHE_STATUS.json')
        variants=perf.variants
        perf.save_hits_reference(folder/'STATION_HITS_REFERENCE.json')
        write_run_binding(folder,perf)
    def save_inc(inc,destination):
        if perf is None:inc.save(destination)
        else:perf.save_incidence(inc,destination,legacy=legacy_incidence_output)
    if checkpoint: checkpoint('INCIDENCE_READ_COMPLETE')
    targets=targets_from_audit()
    holdout={tuple(sorted(p)) for p in cfg['validation_unordered_pairs']}
    roles={(a,b):('VALIDATION' if (a,b) in holdout else 'CALIBRATION') for a in range(1,17) for b in range(a+1,17)}
    gate=deployment_gate(cfg,True);summaries=[]
    for method,raw in variants.items():
        out=folder/method;save_inc(raw,out/'DIRECTED_DIAGNOSTICS')
        inc=aggregate_observations(raw,targets,bidirectional=True,roles=roles)
        save_inc(inc,out)
        write_json(out/'OBSERVATION_ROSTER.json',observation_roster(inc.rows,cfg.get('expected_observation_roster')))
        write_json(out/'TARGETING_CONTEXT.json',path_targeting_report(inc))
        summary={'method':method,'status':'DIAGNOSTIC_PASS','gate':gate,'observation_semantics_approved':False,
                 'survey_year':2026,'model_year':2025,'prediction_kind':'SAVED_PATH_HYPOTHESIS_NOT_CALIBRATED_RESULT'}
        if propose:
            require(allow_scenario,'UNAPPROVED_OBSERVATION_SEMANTICS_EXPLICIT_SCENARIO_REQUIRED')
            budget=from_audit_csv(ROOT/'data/audited/C17_STATION_BUDGETS.csv',
                [(r['origin_station'],r['destination_station']) for r in inc.rows],
                policy='BOUNDED_SCENARIO' if credit_scenario else 'UNAPPROVED',scenario_authorized=credit_scenario)
            if aggressive_enabled(cfg):
                trial=aggressive_propose(inc,cfg,budget,allow_unapproved_scenario=True,zone_rows=zone_rows)
                trial.save(out,inc);result=trial.solution
                summary['aggressive_stage']=cfg['aggressive_effective']['stage']['name']
                summary['selected_scale']=trial.report['selected_scale']
                summary['realization_status']=trial.report['realization_status']
            else:
                result=solve(inc,cfg,budget,allow_unapproved_scenario=True);result.save(out,inc)
                write_json(out/'TG_TD_PROJECTION.json',parent_projection(inc,result,cfg))
                write_json(out/'FULL_OD_FEASIBILITY.json',evaluate_realizability(inc,result))
            summary['status']=result.report['status'];summary['objective_before']=result.report['objective_initial'];summary['objective_after']=result.report['objective_final']
        summaries.append(summary)
        if checkpoint: checkpoint(method+'_COMPLETE')
    report={'status':'OFFLINE_HYPOTHESIS_RESULTS','variants':summaries,'gate':gate,'config_sha256':canonical_hash(cfg),
            'cache_sha256':sha256(cache),'snapshot_evidence_sha256':sha256(evidence_path),
            'authority_audit_sha256':sha256(ROOT/'data/audited/AUTHORITY_AUDIT.json'),
            'directional_axis_mapping':'UNAPPROVED_BIDIRECTIONAL_HYPOTHESIS_ONLY',
            'mutable_actuators_enabled':bool(cfg['mutable_dsegs']),
            'apply_permitted':False,'live_visum_tested':False,'production_ready':False}
    if perf is not None:
        report['perf01']={'cache_action':perf.status['cache_action'],'key':perf.manifest['key'],
                         'geometry_redecode_count':perf.status['geometry_redecode_count'],
                         'native_com_read_count':0,'same_sealed_snapshot_only':True}
        perf.source.recheck()
    write_json(folder/'RUN_REPORT.json',report);return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['audit-inputs','preflight','demo','inspect-cache','propose','verify-run'])
    p.add_argument('--config',type=Path,default=ROOT/'CORDON_2025_CONFIG.json')
    p.add_argument('--outer-cycle',type=int,default=None,help='Explicit aggressive stage selector 1..100; does not run live outer cycles')
    p.add_argument('--run-name',default=None,help='New isolated run name; long names are shortened deterministically')
    p.add_argument('--output-root',type=Path,help='New empty or owned 2025 root; never an existing 2022 directory')
    p.add_argument('--run-directory',type=Path,help='Completed/interrupted run to verify read-only')
    p.add_argument('--cache',type=Path,help='Explicit completed copied SQLite snapshot; never an active WAL database')
    p.add_argument('--zone-parameters',type=Path,help='Optional explicit exported zone-attribute CSV for offline TG parameter design only')
    p.add_argument('--evidence',type=Path,help='Snapshot provenance JSON; no automatic 2022 search')
    p.add_argument('--allow-unapproved-scenario',action='store_true')
    p.add_argument('--bounded-c17-scenario',action='store_true')
    p.add_argument('--reuse-cache-dir',type=Path,help='Explicit owned PERF01 derived-cache root, not a Visum path cache')
    p.add_argument('--reuse-policy',choices=['disabled','build-offline','require-verified-hit'],default='disabled')
    p.add_argument('--reuse-context',choices=['same-sealed-snapshot','after-new-assignment'],default='same-sealed-snapshot')
    p.add_argument('--source-checkpoint',type=Path,help='Optional original completed capture RUN_CHECKPOINT.json')
    p.add_argument('--legacy-incidence-output',action='store_true',help='Explicit large legacy metadata export, not the fast default')
    args=p.parse_args(argv);folder=None
    try:
        if args.command=='verify-run':
            require(args.run_directory is not None,'RUN_DIRECTORY_REQUIRED')
            report=verify_run(args.run_directory)
            print(json.dumps(report));return 0
        from .state import validate_perf01_options
        validate_perf01_options(args.reuse_policy,args.reuse_cache_dir,args.reuse_context,args.command)
        cfg=read_config(args.config,outer_cycle=args.outer_cycle)
        name=args.run_name or (args.command.replace('-','_')+'_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
        with RunSession(name,args.output_root) as session:
            folder=session.folder
            inputs={'config':args.config,'cache':args.cache,'evidence':args.evidence,'zone_parameters':args.zone_parameters,'source_checkpoint':args.source_checkpoint}
            if aggressive_enabled(cfg):
                inputs['aggressive_source_policy']=ROOT/AGGRESSIVE_SOURCE_REL
                inputs['aggressive_design_source']=ROOT/DESIGN_SOURCE_REL
            session.start(cfg,inputs)
            if aggressive_enabled(cfg):write_json(folder/'AGGRESSIVE_EFFECTIVE_CONFIG.json',cfg)
            if args.command=='audit-inputs':
                report=audit_workbooks(ROOT/'data/source',folder/'audited')
            elif args.command=='demo':
                if aggressive_enabled(cfg):
                    from .aggressive_demo import run_demo
                    report=run_demo(folder,cfg)
                else:report=synthetic_demo(folder,cfg)
            elif args.command=='preflight':
                report={'status':'NO_2025_PATH_CACHE' if args.cache is None else 'EXPLICIT_CACHE_REQUIRES_INSPECT_CACHE',
                    'gate':deployment_gate(cfg,args.cache is not None and args.cache.is_file()),
                    'source_scope':'READ_ONLY_STATIC_PREFLIGHT','finecdf_reference':finecdf_availability()}
                write_json(folder/'PREFLIGHT.json',report)
            else:
                require(not args.bounded_c17_scenario or args.allow_unapproved_scenario,'C17_SCENARIO_OPT_IN_REQUIRED')
                report=empirical_run(folder,cfg,args.cache,args.evidence,args.command=='propose',args.allow_unapproved_scenario,args.bounded_c17_scenario,session.checkpoint,args.zone_parameters,reuse_cache_dir=args.reuse_cache_dir,reuse_policy=args.reuse_policy,reuse_context=args.reuse_context,source_checkpoint=args.source_checkpoint,legacy_incidence_output=args.legacy_incidence_output)
            write_json(folder/'COMMAND_STATUS.json',{'command':args.command,'status':report.get('status'),'output':str(folder),
                'config_sha256':sha256(args.config),'apply_permitted':False,'live_visum_tested':False})
            failed_solver=(report.get('status') in ('SYNTHETIC_DEMO_NOT_CONVERGED','SYNTHETIC_AGGRESSIVE_DEMO_NOT_CONVERGED') or
                any(v.get('status') in ('OFFLINE_SOLVER_NOT_CONVERGED','OFFLINE_AGGRESSIVE_SOLVER_NOT_CONVERGED') for v in report.get('variants',[])))
            session.checkpoint('OFFLINE_COMMAND_COMPLETE' if not failed_solver else 'OFFLINE_SOLVER_INCOMPLETE', completed=not failed_solver)
        print(json.dumps({'status':report.get('status'),'output':str(folder),'apply':False}))
        if args.command=='preflight':return 2
        if failed_solver:return 3
        return 0
    except Exception as exc:
        safe_failure_report(folder, exc, traceback_text=traceback.format_exc(), emergency_stream=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
