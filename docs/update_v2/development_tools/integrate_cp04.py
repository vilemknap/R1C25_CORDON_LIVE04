from pathlib import Path
r=Path('/mnt/data/R1_CORDON_UPDATE_20261022/release')
p=r/'cordon2025/__main__.py';s=p.read_text();s=s.replace('from .targeting import path_targeting_report','from .targeting import path_targeting_report\nfrom .session import RunSession, verify_run')
s=s.replace('credit_scenario=False):','credit_scenario=False,checkpoint=None):',1)
s=s.replace("    targets=targets_from_audit()", "    if checkpoint: checkpoint('INCIDENCE_READ_COMPLETE')\n    targets=targets_from_audit()")
s=s.replace('        summaries.append(summary)',"        summaries.append(summary)\n        if checkpoint: checkpoint(method+'_COMPLETE')")
s=s.replace("choices=['audit-inputs','preflight','demo','inspect-cache','propose']","choices=['audit-inputs','preflight','demo','inspect-cache','propose','verify-run']")
s=s.replace("help='New folder under this release OFFLINE_RESULTS; no external output roots'", "help='New isolated run name; long names are shortened deterministically'")
s=s.replace("    p.add_argument('--cache'", "    p.add_argument('--output-root',type=Path,help='New empty or owned 2025 root; never an existing 2022 directory')\n    p.add_argument('--run-directory',type=Path,help='Completed/interrupted run to verify read-only')\n    p.add_argument('--cache'")
start=s.index('        cfg=read_config(args.config)');end=s.index('    except Exception as exc:',start)
s=s[:start]+'''        if args.command=='verify-run':
            require(args.run_directory is not None,'RUN_DIRECTORY_REQUIRED')
            report=verify_run(args.run_directory)
            print(json.dumps(report));return 0
        cfg=read_config(args.config)
        name=args.run_name or (args.command.replace('-','_')+'_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
        with RunSession(name,args.output_root) as session:
            folder=session.folder
            session.start(cfg,{'config':args.config,'cache':args.cache,'evidence':args.evidence})
            if args.command=='audit-inputs':
                report=audit_workbooks(ROOT/'data/source',folder/'audited')
            elif args.command=='demo':report=synthetic_demo(folder,cfg)
            elif args.command=='preflight':
                report={'status':'NO_2025_PATH_CACHE' if args.cache is None else 'EXPLICIT_CACHE_REQUIRES_INSPECT_CACHE',
                    'gate':deployment_gate(cfg,args.cache is not None and args.cache.is_file()),
                    'source_scope':'READ_ONLY_STATIC_PREFLIGHT','finecdf_reference':finecdf_availability()}
                write_json(folder/'PREFLIGHT.json',report)
            else:
                require(not args.bounded_c17_scenario or args.allow_unapproved_scenario,'C17_SCENARIO_OPT_IN_REQUIRED')
                report=empirical_run(folder,cfg,args.cache,args.evidence,args.command=='propose',args.allow_unapproved_scenario,args.bounded_c17_scenario,session.checkpoint)
            write_json(folder/'COMMAND_STATUS.json',{'command':args.command,'status':report.get('status'),'output':str(folder),
                'config_sha256':sha256(args.config),'apply_permitted':False,'live_visum_tested':False})
            failed_solver=(report.get('status')=='SYNTHETIC_DEMO_NOT_CONVERGED' or
                any(v.get('status')=='OFFLINE_SOLVER_NOT_CONVERGED' for v in report.get('variants',[])))
            session.checkpoint('OFFLINE_COMMAND_COMPLETE' if not failed_solver else 'OFFLINE_SOLVER_INCOMPLETE', completed=not failed_solver)
        print(json.dumps({'status':report.get('status'),'output':str(folder),'apply':False}))
        if args.command=='preflight':return 2
        if failed_solver:return 3
        return 0
''' + s[end:];p.write_text(s)
p=r/'cordon2025/common.py';s=p.read_text().replace("    p.mkdir(parents=True, exist_ok=False)","    from .io import mkdir\n    mkdir(p, exist_ok=False)");s=s.replace("['NOT_LIVE_TESTED', 'V1_OFFLINE_ONLY']", "['NOT_LIVE_TESTED', 'V2_OFFLINE_ONLY' if str(cfg.get('schema','')).endswith('V2') else 'V1_OFFLINE_ONLY']");p.write_text(s)
