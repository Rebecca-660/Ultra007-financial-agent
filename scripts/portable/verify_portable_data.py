"""Verify moved Ultra 007 data offline, optionally exercising synthetic exports.

Only Python standard-library modules and the project's runtime requirements are
used. Existing projects are read-only. Exercise outputs go into a fresh copy in
the receiving package's tmp directory. No API or embedding operation is allowed.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path, PureWindowsPath
import shutil
import sys
import tempfile
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile


class PortableCheckError(RuntimeError):
    pass


def _require(condition, code):
    if not condition:
        raise PortableCheckError(code)


def _json(path):
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    _require(isinstance(value,dict),'json_object_required')
    return value


def _inside(root, base, value):
    path=(base/str(value)).resolve()
    _require(path.is_relative_to(root),'path_outside_receiving_package')
    return path


def _relative(root,path):
    return path.resolve().relative_to(root).as_posix()


def _xlsx(path):
    with zipfile.ZipFile(path) as book:
        _require(book.testzip() is None,'xlsx_integrity_failed')
        names=book.namelist()
        xml=ET.fromstring(book.read('xl/workbook.xml'))
        ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        sheets=[sheet.attrib['name'] for sheet in xml.findall('m:sheets/m:sheet',ns)]
        charts=[name for name in names if name.startswith('xl/charts/chart') and name.endswith('.xml') and '/' not in name[len('xl/charts/'):]]
        return {'sheet_count':len(sheets),'chart_count':len(charts)}


def _application(root):
    # --root must never accidentally test imports from the original checkout.
    sys.path[:]=[str(root),*[entry for entry in sys.path if str(Path(entry or '.').resolve())!=str(root)]]
    for name in list(sys.modules):
        if name in ('financial_workbook','rag_step1') or name.startswith(('financial_workbook.','rag_step1.')):
            del sys.modules[name]
    modules={name:importlib.import_module(name) for name in (
        'financial_workbook','financial_workbook.research_io','financial_workbook.research',
        'financial_workbook.models','financial_workbook.analysis','financial_workbook.service',
        'rag_step1.report','rag_step1.config')}
    origins={}
    for name,module in modules.items():
        package=root/name.split('.')[0]
        origin=Path(module.__file__).resolve()
        _require(origin.is_relative_to(package),'foreign_application_module_imported')
        origins[name]=_relative(root,origin)
    _require(modules['rag_step1.config'].ROOT.resolve()==root,'foreign_runtime_root')
    return modules,origins


def _snapshot(root,run,state,report_module):
    snapshot=_inside(root,run,state['files']['sources'])
    data=_json(snapshot)
    _require(bool(data.get('reports')),'source_snapshot_empty')
    resolved=[]
    for item in data['reports']:
        filename=item['file_name']
        # A Windows absolute path must not masquerade as a Linux filename.
        if PureWindowsPath(filename).is_absolute() and not Path(filename).is_absolute():
            raise PortableCheckError('foreign_windows_absolute_source_path')
        path=_inside(root,snapshot.parent,filename)
        _require(path.is_file(),'source_pdf_missing')
        resolved.append(_relative(root,path))
    sources=report_module.load_report_set(snapshot)
    _require(sources.report_set_id==state['report_set_id'],'report_set_identity_changed')
    for source in sources.sources:
        _require(source.pdf_path.resolve().is_relative_to(root),'resolved_pdf_outside_receiving_package')
    return resolved


def _verify_run(root,run,modules):
    state=_json(run/'run.json')
    _require(state.get('status')=='completed','run_not_completed')
    source_paths=_snapshot(root,run,state,modules['rag_step1.report'])
    bundle=modules['financial_workbook.research_io'].approved_bundle(run,verify_sources=True)
    models=modules['financial_workbook.models']
    dataset=models.Dataset.model_validate(bundle['dataset'])
    automatic=bool(bundle.get('validation'))
    authorization=(models.SystemValidation.model_validate(bundle['validation']) if automatic else
                   models.Review.model_validate(bundle['review']))
    _require(dataset.fingerprint==state['dataset_fingerprint']==authorization.dataset_fingerprint,
             'dataset_fingerprint_changed')
    if automatic:
        _require(authorization.statement_digests=={item.statement_id:models.digest(item) for item in dataset.statements},
                 'system_validation_statement_digest_changed')
    else:
        by_id={item.statement_id:item for item in dataset.statements}
        _require(all(decision.statement_id in by_id and decision.statement_digest==models.digest(by_id[decision.statement_id])
                     for decision in authorization.decisions),'legacy_review_statement_digest_changed')
    recomputed=modules['financial_workbook.analysis'].analyze(dataset,authorization)
    _require(models.digest(recomputed)==models.digest(bundle['analysis']),'analysis_recomputation_changed')
    workbook=Path(bundle['workbook']).resolve()
    _require(workbook.is_relative_to(root),'workbook_outside_receiving_package')
    workbook_info=_xlsx(workbook)
    _require(workbook_info['chart_count']==5,'historical_chart_count_changed')
    return {'run':_relative(root,run),'years':bundle['analysis']['years'],
        'statement_count':len(dataset.statements),'row_count':sum(len(item.rows) for item in dataset.statements),
        'source_pdf_count':len(source_paths),'source_pdfs':source_paths,
        'validation_method':'system' if automatic else 'historical_human_review',
        'dataset_fingerprint':dataset.fingerprint,'analysis_fingerprint':models.digest(recomputed),
        'source_reparse':'passed','fingerprint_recomputation':'passed','workbook':_relative(root,workbook),
        **workbook_info}


def _tree_hashes(folder):
    import hashlib
    return {path.relative_to(folder).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob('*') if path.is_file()}


def _exercise(root,project,modules):
    original=_json(project/'project.json')
    ids=sorted(original['companies'])
    _require(set(ids)=={'DEMO_A','DEMO_B'},'exercise_requires_explicit_synthetic_demo_ids')
    _require(all('合成数据' in item['metadata']['name'] for item in original['companies'].values()),
             'exercise_requires_explicit_synthetic_demo_names')
    before=_tree_hashes(project)
    work_base=_inside(root,root,'tmp'); work_base.mkdir(exist_ok=True)
    working=Path(tempfile.mkdtemp(prefix='portable_data_check_',dir=work_base)).resolve()
    _require(working.is_relative_to(work_base),'exercise_workspace_outside_package_tmp')
    clone=working/project.name
    shutil.copytree(project,clone,ignore=shutil.ignore_patterns('.web_jobs','investment','comparisons','*.lock','__pycache__'))
    state=_json(clone/'project.json'); state['history_exports']=[]
    (clone/'project.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    workflow=modules['financial_workbook.research'].ResearchWorkflow()
    result=workflow.history(clone,ids)
    _require(result['mode']=='cross_company','comparison_mode_wrong')
    comparison_path=Path(result['comparison']).resolve()
    comparison_book=Path(result['workbook']).resolve()
    _require(comparison_path.is_relative_to(clone) and comparison_book.is_relative_to(clone),'exercise_output_outside_clone')
    comparison=_json(comparison_path)
    _require(set(comparison['company_ids'])==set(ids) and bool(comparison['years']),'comparison_scope_wrong')
    comparison_info=_xlsx(comparison_book)
    _require(comparison_info['chart_count']==4,'comparison_requires_four_charts')
    cid='DEMO_B'
    actor='portable verification (synthetic assumptions only)'
    offer=workflow.offer(clone,cid)
    _require(offer['status']=='awaiting_user_choice','fresh_synthetic_invitation_required')
    accepted=workflow.decide(clone,cid,proceed=True,decided_by=actor)
    _require(accepted['status']=='accepted','synthetic_valuation_choice_failed')
    cloned_state=_json(clone/'project.json')
    entry=cloned_state['companies'][cid]
    metadata,bundle=workflow._bundle(clone,cloned_state,cid)
    models=modules['financial_workbook.models']
    year=max(bundle['analysis']['years'])
    parameters={'company_id':cid,'dataset_fingerprint':bundle['state']['dataset_fingerprint'],
        'analysis_fingerprint':models.digest(bundle['analysis']),'currency':bundle['currency'],
        'unit':'currency_base_unit','base_year':year,'valuation_date':f"{year}-{metadata['fiscal_year_end']}",
        'base_fcff':'100','growth':'0.05','wacc':'0.10','terminal_growth':'0.02','years':5,
        'net_debt':'200','shares':'100','confirmed':True,'confirmed_by':actor,
        'rationale':'Synthetic portability test; not a valuation of a real company.'}
    valued=workflow.value_trial(clone,cid,parameters)
    valuation_folder=Path(valued['output_dir']).resolve()
    _require(valuation_folder.is_relative_to(clone),'valuation_output_outside_clone')
    valuation=_json(valuation_folder/'valuation.json')
    assumptions=_json(valuation_folder/'assumptions.json')
    _require(valuation['model']=='fcff_growth_trial' and valuation['company_id']==cid,'valuation_model_or_company_wrong')
    _require(valuation['dataset_fingerprint']==bundle['state']['dataset_fingerprint'] and
             valuation['analysis_fingerprint']==models.digest(bundle['analysis']) and
             valuation['assumptions_fingerprint']==models.digest(assumptions),'valuation_fingerprints_changed')
    _require(len(valuation['forecasts'])==5 and valuation['per_share_value'] is not None,'valuation_result_incomplete')
    valuation_book=Path(valued['workbook']).resolve()
    valuation_info=_xlsx(valuation_book)
    _require(valuation_info['sheet_count']==5,'trial_workbook_sheet_count_changed')
    _require(bool(workflow.list_valuations(clone,cid)),'saved_valuation_not_discoverable')
    _require(before==_tree_hashes(project),'preloaded_project_was_modified')
    return {'status':'passed','synthetic_only':True,'workspace':_relative(root,working),
        'preloaded_project_unchanged':True,'comparison':{'json':_relative(root,comparison_path),
        'workbook':_relative(root,comparison_book),'years':comparison['years'],**comparison_info},
        'trial_valuation':{'workbook':_relative(root,valuation_book),'result':_relative(root,valuation_folder/'valuation.json'),
        'forecast_years':5,'fingerprints':'passed','version_discovery':'passed',**valuation_info}}


def verify_root(root,exercise=False):
    root=Path(root).resolve()
    report={'status':'failed','root':'.','api_called':False,'network_called':False,
            'checked_at':datetime.now(timezone.utc).isoformat(),'runs':[],'projects':[]}
    stage='imports'; context='.'; attempted=[]
    def blocked(name):
        def fail(*args,**kwargs):
            attempted.append(name)
            raise PortableCheckError('external_operation_not_allowed')
        return fail
    try:
        _require((root/'financial_workbook/__init__.py').is_file(),'receiving_package_not_found')
        with ExitStack() as guards:
            guards.enter_context(patch('socket.socket.connect',new=blocked('socket.connect')))
            guards.enter_context(patch('socket.create_connection',new=blocked('socket.create_connection')))
            modules,origins=_application(root)
            report['module_origins']=origins
            guards.enter_context(patch.object(modules['rag_step1.config'],'create_llm',new=blocked('create_llm')))
            guards.enter_context(patch.object(modules['financial_workbook.service'].FinancialAnalysisAgent,
                                              '_llm',new=blocked('agent_llm')))
            stage='research_projects'; seen=set(); demo=None
            projects_root=root/'outputs/research_projects'
            for project_file in sorted(projects_root.glob('*/project.json')):
                project=project_file.parent.resolve(); context=_relative(root,project)
                state=modules['financial_workbook.research_io'].load_project(project)
                checked=0
                for cid,entry in state['companies'].items():
                    if not entry.get('run_dir'): continue
                    run=_inside(root,project,entry['run_dir'])
                    run_state=_json(run/'run.json')
                    if run_state.get('status')!='completed': continue
                    _require(run_state['company_id']==cid and run_state['report_set_id']==entry['report_set_id'],
                             'project_run_scope_changed')
                    context=_relative(root,run)
                    if run not in seen:
                        report['runs'].append(_verify_run(root,run,modules)); seen.add(run)
                    checked+=1
                report['projects'].append({'project':_relative(root,project),'completed_companies':checked})
                if set(state['companies'])=={'DEMO_A','DEMO_B'} and all('合成数据' in item['metadata']['name'] for item in state['companies'].values()):
                    demo=project
            stage='legacy_runs'
            for file in sorted((root/'outputs/agent_runs').glob('*/*/run.json')):
                run=file.parent.resolve(); context=_relative(root,run)
                if _json(file).get('status')=='completed' and run not in seen:
                    report['runs'].append(_verify_run(root,run,modules)); seen.add(run)
            _require(bool(seen),'no_completed_saved_runs_found')
            if exercise:
                stage='synthetic_exercise'
                _require(demo is not None,'synthetic_demo_project_missing')
                context=_relative(root,demo)
                report['exercise']=_exercise(root,demo,modules)
            _require(not attempted,'unexpected_external_operation_attempted')
            stage='module_origin_recheck'
            for name,module in tuple(sys.modules.items()):
                if name.startswith(('financial_workbook.','rag_step1.')) and getattr(module,'__file__',None):
                    _require(Path(module.__file__).resolve().is_relative_to(root/name.split('.')[0]),'foreign_application_module_imported')
            report.update(status='passed',completed_runs=len(seen),
                statement_count=sum(run['statement_count'] for run in report['runs']),
                row_count=sum(run['row_count'] for run in report['runs']),
                source_pdf_count=sum(run['source_pdf_count'] for run in report['runs']),
                source_paths_within_package=True,fingerprint_recomputation='passed',
                external_operations_attempted=0)
    except Exception as error:
        report.update(status='failed',failure_stage=stage,context=context,error_type=type(error).__name__,
            error_code=str(error) if isinstance(error,PortableCheckError) else 'local_data_or_dependency_check_failed',
            external_operations_attempted=len(attempted))
        if isinstance(error,ModuleNotFoundError): report['missing_module']=error.name
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--exercise',action='store_true',help='Exercise comparison and trial valuation in a synthetic tmp copy.')
    parser.add_argument('--output',type=Path,help='Optional JSON report path within the receiving package.')
    args=parser.parse_args(argv); root=args.root.resolve()
    result=verify_root(root,args.exercise)
    if args.output:
        try:
            output=_inside(root,root,args.output)
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        except Exception as error:
            result={'status':'failed','root':'.','error_type':type(error).__name__,
                    'error_code':'report_output_must_be_inside_receiving_package','api_called':False,'network_called':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
