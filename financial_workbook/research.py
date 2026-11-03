"""Reusable research lifecycle. No Streamlit dependency and no implicit consent."""
from __future__ import annotations
import asyncio
from pathlib import Path
import uuid

from .models import Dataset, digest, now
from .service import FinanceConfig, FinancialAnalysisAgent, _inside, _write_json
from .research_models import ResearchManifest, ValuationRequest
from .research_io import (approved_bundle, create_project, load_project, project_lock,
                          read_json, selected_companies)


class ResearchWorkflow:
    def __init__(self, *, llm_factory=None, progress=None):
        self.llm_factory=llm_factory
        self.progress=progress or (lambda message:None)

    @staticmethod
    def create(manifest_path: Path, destination: Path) -> dict:
        manifest_path=Path(manifest_path).resolve()
        manifest=ResearchManifest.model_validate(read_json(manifest_path))
        return create_project(manifest,destination,source_dir=manifest_path.parent)

    @staticmethod
    def create_from_uploads(manifest: dict, uploads: dict[str,bytes], destination: Path) -> dict:
        model=ResearchManifest.model_validate(manifest)
        if any(c.parser_profile for c in model.companies):
            raise ValueError('字节上传接口不读取客户端本地配置路径；请在文件清单入口提供解析配置。')
        return create_project(model,destination,source_dir=Path.cwd(),uploads=uploads)

    @staticmethod
    def status(project_dir: Path) -> dict:
        folder=Path(project_dir).resolve(); state=load_project(folder)
        # Reload backend state so an interrupted caller can recover a completed operation.
        for entry in state['companies'].values():
            if entry['run_dir']:
                entry['status']=FinancialAnalysisAgent.status(_inside(folder,entry['run_dir']))['status']
        return {**state,'project_dir':str(folder)}

    def _agent(self, folder, entry):
        return FinancialAnalysisAgent(FinanceConfig(report_set=_inside(folder,entry['manifest']),
            output_dir=folder/'runs',parser_profile=_inside(folder,entry['profile']) if entry.get('profile') else None),
            llm_factory=self.llm_factory,progress=self.progress)

    @staticmethod
    def _persist(folder, state):
        state['updated_at']=now(); _write_json(folder/'project.json',state,replace=True)

    async def prepare(self, project_dir: Path, companies: list[str] | None=None, *, review_templates=True):
        from .human_review import review_template
        folder=Path(project_dir).resolve()
        with project_lock(folder):
            state=load_project(folder)
            for cid in selected_companies(state,companies):
                entry=state['companies'][cid]
                if entry['run_dir']:
                    current=FinancialAnalysisAgent.status(_inside(folder,entry['run_dir']))
                    if current['status']!='prepare_failed':
                        if current['status']=='preparing':
                            from .research_io import process_alive
                            owner=current.get('process_id')
                            if type(owner) is not int or process_alive(owner) is not False:
                                raise ValueError('候选提取仍在运行或所有者状态不明，不能重复启动。')
                            interrupted=read_json(_inside(folder,entry['run_dir'])/'run.json')
                            interrupted.update(status='prepare_failed',error_type='InterruptedWorker',updated_at=now())
                            _write_json(_inside(folder,entry['run_dir'])/'run.json',interrupted,replace=True)
                            current['status']='prepare_failed'
                        template=_inside(folder,entry['run_dir'])/'human_review.template.json'
                        if review_templates and current['status']=='needs_human_review' and not template.exists():
                            dataset=Dataset.model_validate_json(_inside(template.parent,current['files']['candidates']).read_text(encoding='utf-8'))
                            _write_json(template,review_template(dataset))
                        if current['status']!='prepare_failed':
                            self.progress(f'{cid} 已有运行，保留并恢复，不重复调用。')
                            continue
                before=set((folder/'runs').glob('*/*/run.json'))
                try:
                    result=await self._agent(folder,entry).prepare()
                    run=Path(result['run_dir'])
                    entry.update(run_dir=str(run.relative_to(folder)),status=result['status'])
                    dataset=Dataset.model_validate_json(_inside(run,result['files']['candidates']).read_text(encoding='utf-8'))
                    if review_templates:
                        _write_json(run/'human_review.template.json',review_template(dataset))
                    self._persist(folder,state)
                except Exception:
                    added=set((folder/'runs').glob('*/*/run.json'))-before
                    if len(added)==1:
                        run=next(iter(added)).parent
                        entry.update(run_dir=str(run.relative_to(folder)),status=read_json(run/'run.json')['status'])
                    self._persist(folder,state)
                    raise
        return self.status(folder)

    async def analyze_automatically(self, project_dir: Path, companies: list[str] | None=None):
        """New application flow: extract, machine-validate and calculate without review UI."""
        folder=Path(project_dir).resolve()
        await self.prepare(folder,companies,review_templates=False)
        with project_lock(folder):
            state=load_project(folder)
            for cid in selected_companies(state,companies):
                entry=state['companies'][cid]
                if not entry['run_dir']: raise ValueError('报告候选尚未建立。')
                run=_inside(folder,entry['run_dir'])
                current=FinancialAnalysisAgent.status(run)
                if current['status']=='completed':
                    entry['status']='completed'; continue
                self.progress(f'正在校验并计算 {entry["metadata"]["name"]}。')
                try:
                    result=await self._agent(folder,entry).finalize_automatically(run)
                    entry['status']=result['status']; self._persist(folder,state)
                except Exception:
                    entry['status']=FinancialAnalysisAgent.status(run)['status']; self._persist(folder,state); raise
        return self.status(folder)

    def list_valuations(self, project_dir: Path, company_id: str):
        """Read saved results without triggering a calculation or consent change."""
        folder=Path(project_dir).resolve(); state=load_project(folder)
        selected_companies(state,[company_id]); records=[]
        entry=state['companies'][company_id]
        if not entry.get('run_dir'): return []
        run=FinancialAnalysisAgent.status(_inside(folder,entry['run_dir']))
        if run['status']!='completed': return []
        current_analysis=read_json(_inside(folder,entry['run_dir'])/run['last_attempt']/'analysis.json')
        for path in folder.glob('investment/*/valuation_*/valuation.json'):
            try:
                if not path.resolve().is_relative_to(folder): continue
                result=read_json(path)
                if (result.get('company_id')!=company_id or result.get('dataset_fingerprint')!=run.get('dataset_fingerprint')
                    or result.get('analysis_fingerprint')!=digest(current_analysis)): continue
                workbook=path.parent/'DCF估值.xlsx'
                if workbook.is_file(): records.append({'output_dir':str(path.parent),'workbook':str(workbook),
                    'result':result,'assumptions':read_json(path.parent/'assumptions.json')})
            except (OSError,ValueError): continue
        return sorted(records,key=lambda r:Path(r['output_dir']).stat().st_mtime_ns,reverse=True)

    def value_trial(self,project_dir:Path,company_id:str,parameters:dict):
        from .trial_valuation import TrialRequest,calculate_trial,export_trial
        folder=Path(project_dir).resolve()
        with project_lock(folder):
            state=load_project(folder); metadata,bundle=self._bundle(folder,state,company_id)
            location=self._invitation_location(folder,metadata,bundle)
            if not (location/'invitation.json').exists() or read_json(location/'invitation.json')['status']!='accepted':
                raise ValueError('用户尚未选择继续，或已选择结束；不执行简易试算。')
            request=TrialRequest.model_validate(parameters)
            result=calculate_trial(bundle,metadata,request)
            destination=location/('valuation_trial_'+uuid.uuid4().hex[:12]); destination.mkdir()
            _write_json(destination/'assumptions.json',request.model_dump(mode='json'))
            _write_json(destination/'valuation.json',result)
            output=destination/'DCF估值.xlsx'; export_trial(result,request.model_dump(mode='json'),output)
            return {'status':'valued','model':'fcff_growth_trial','company_id':company_id,
                    'output_dir':str(destination),'workbook':str(output),'assumptions_fingerprint':digest(request)}

    def submit_review(self, project_dir: Path, company_id: str, submission: Path):
        """Validate explicit human JSON, retain it, and produce an audit XLSX copy."""
        from .human_review import import_human_review
        from .cli import export_payload,export_workbook
        from rag_step1.report import load_report_set
        folder=Path(project_dir).resolve()
        with project_lock(folder):
            state=load_project(folder); selected_companies(state,[company_id])
            entry=state['companies'][company_id]
            if not entry['run_dir']: raise ValueError('请先提取候选报表。')
            run=_inside(folder,entry['run_dir']); backend=FinancialAnalysisAgent.status(run)
            if backend['status'] not in ('needs_human_review','finalize_failed'):
                raise ValueError('只有待审核的候选可以提交审核。')
            dataset=Dataset.model_validate_json(_inside(run,backend['files']['candidates']).read_text(encoding='utf-8'))
            sources=load_report_set(_inside(run,backend['files']['sources']))
            review=import_human_review(submission,dataset,sources)
            destination=run/('human_review_'+uuid.uuid4().hex[:12]); destination.mkdir()
            _write_json(destination/'submission.json',read_json(submission))
            _write_json(destination/'review.json',review.model_dump(mode='json'))
            payload=export_payload(dataset,None,False); payload['review']=review.model_dump(mode='json')
            export_workbook(payload,destination/'已填写审核.xlsx')
            entry['review_submission']=str((destination/'submission.json').relative_to(folder))
            self._persist(folder,state)
            return {'submission':str(destination/'submission.json'),'review_workbook':str(destination/'已填写审核.xlsx'),
                    'approved':sum(d.decision=='approved' for d in review.decisions),'total':len(dataset.statements)}

    async def finalize(self, project_dir: Path, company_id: str, review_path: Path | None=None):
        folder=Path(project_dir).resolve()
        with project_lock(folder):
            state=load_project(folder); selected_companies(state,[company_id]); entry=state['companies'][company_id]
            if not entry['run_dir']: raise ValueError('请先提取候选报表。')
            if review_path is None:
                if not entry.get('review_submission'): raise ValueError('请提交人工审核 JSON，或指定已填写的审核 Excel。')
                review_path=_inside(folder,entry['review_submission'])
            try:
                result=await self._agent(folder,entry).finalize(_inside(folder,entry['run_dir']),review_path)
                entry['status']=result['status']; self._persist(folder,state)
            except Exception:
                entry['status']=FinancialAnalysisAgent.status(_inside(folder,entry['run_dir']))['status']
                self._persist(folder,state); raise
        # Offer creation has its own project lock, after the long operation finishes.
        return {'history':result,'investment_offer':self.offer(folder,company_id)}

    @staticmethod
    def _bundle(folder, state, company_id):
        selected_companies(state,[company_id]); entry=state['companies'][company_id]
        if not entry['run_dir']: raise ValueError('该公司尚未生成候选报表。')
        bundle=approved_bundle(_inside(folder,entry['run_dir']))
        if (bundle['state']['report_set_id']!=entry['report_set_id'] or
            entry['metadata']['company_id']!=company_id or bundle['state']['company_id']!=company_id):
            raise ValueError('项目公司与正式分析的报告集合不一致。')
        return entry['metadata'],bundle

    def history(self, project_dir: Path, companies: list[str] | None=None, years: list[int] | None=None):
        from .comparison import compare_companies
        from .research_export import export_comparison
        folder=Path(project_dir).resolve()
        with project_lock(folder):
            state=load_project(folder); selected=selected_companies(state,companies)
            bundles=[self._bundle(folder,state,cid) for cid in selected]
            if len(bundles)>1:
                result=compare_companies(bundles,years)
                destination=folder/'comparisons'/uuid.uuid4().hex[:12]; destination.mkdir(parents=True)
                _write_json(destination/'comparison.json',result)
                export_comparison(result,destination/'公司对比.xlsx')
                state['history_exports'].append(str(destination.relative_to(folder))); self._persist(folder,state)
                paths={'comparison':str(destination/'comparison.json'),'workbook':str(destination/'公司对比.xlsx')}
                mode='cross_company'
            else:
                if years is not None: raise ValueError('单公司历史输出保留已审核的完整年度；年度筛选用于多公司比较。')
                metadata,bundle=bundles[0]
                mode='single_report' if len(bundle['analysis']['years'])==1 else 'longitudinal'
                paths={'workbook':bundle['workbook'],'years':bundle['analysis']['years']}
        offers=[self.offer(folder,cid) for cid in selected]
        return {'mode':mode,'selected_companies':selected,**paths,'investment_offers':offers}

    @staticmethod
    def _invitation_location(folder, company, bundle):
        key=digest({'company':company['company_id'],'dataset':bundle['state']['dataset_fingerprint'],
                    'analysis':digest(bundle['analysis'])})[:24]
        return folder/'investment'/key

    def offer(self, project_dir: Path, company_id: str):
        folder=Path(project_dir).resolve()
        with project_lock(folder):
            state=load_project(folder); metadata,bundle=self._bundle(folder,state,company_id)
            location=self._invitation_location(folder,metadata,bundle); path=location/'invitation.json'
            if path.exists(): return {**read_json(path),'invitation_dir':str(location)}
            result={'schema_version':'finance-investment-invitation-v1','company_id':company_id,
                'dataset_fingerprint':bundle['state']['dataset_fingerprint'],'analysis_fingerprint':digest(bundle['analysis']),
                'created_at':now(),'status':'awaiting_user_choice',
                'eligible':metadata['business_type']=='non_financial',
                'question':'历史分析已完成。是否继续提供你确认的增长、盈利、再投资和折现参数，由代码计算 FCFF DCF？可选择不继续。',
                'required_inputs':['WACC 或其全部组成项','逐年收入增长、EBIT利润率、现金税率、折旧摊销、资本支出与经营NWC假设',
                    '基准经营NWC及来源依据','终值增长、利润率、税率与ROIC','估值日现金、债务、其他权益桥接及稀释股数'],
                'limitations':['首版仅支持非金融企业、完整财年末估值。','仅输入一个宏观利率不足以完成估值。']}
            _write_json(path,result)
            _write_json(location/'assumptions.template.json',self._template(metadata,bundle))
            return {**result,'invitation_dir':str(location)}

    @staticmethod
    def _template(metadata,bundle):
        year=max(bundle['analysis']['years']); stamp=f"{year}-{metadata['fiscal_year_end']}"
        # Only historical identities and dates are pre-filled, never judgment parameters.
        return {'schema_version':'finance-fcff-assumptions-v1','company_id':metadata['company_id'],
            'dataset_fingerprint':bundle['state']['dataset_fingerprint'],'analysis_fingerprint':digest(bundle['analysis']),
            'currency':bundle['currency'],'unit':'currency_base_unit','base_year':year,'valuation_date':stamp,
            'initial_operating_nwc':None,'initial_operating_nwc_evidence':'',
            'scenarios':[{'name':'Base','discount_rate':{'mode':'direct','wacc':None,'rationale':''},
                'forecasts':[{'year':year+1,'revenue_growth':None,'ebit_margin':None,'cash_tax_rate':None,
                    'depreciation_to_revenue':None,'capex_to_revenue':None,'operating_nwc_to_revenue':None,'rationale':''}],
                'terminal':{'growth':None,'ebit_margin':None,'cash_tax_rate':None,'return_on_invested_capital':None,'rationale':''},
                'sensitivity_wacc':[],'sensitivity_growth':[]}],
            'bridge':{'as_of':stamp,'excess_cash':None,'non_operating_assets':None,'interest_bearing_debt':None,
                'minority_interest':None,'preferred_equity':None,'other_claims':None,'diluted_shares':None,
                'market_price':None,'rationale':''},'confirmed':False,'confirmed_by':'','rationale':''}

    def decide(self, project_dir: Path, company_id: str, *, proceed: bool, decided_by: str):
        if type(proceed) is not bool or not isinstance(decided_by,str) or not decided_by.strip():
            raise ValueError('必须由用户明确选择继续或停止，并填写决定人。')
        self.offer(project_dir,company_id)
        folder=Path(project_dir).resolve()
        with project_lock(folder):
            state=load_project(folder); metadata,bundle=self._bundle(folder,state,company_id)
            location=self._invitation_location(folder,metadata,bundle)
            invitation=read_json(location/'invitation.json')
            status='accepted' if proceed else 'declined'
            if proceed and not invitation['eligible']: raise ValueError('金融企业暂不适用 FCFF；历史分析可正常使用。')
            if invitation['status']!='awaiting_user_choice':
                if invitation['status']!=status or invitation.get('decided_by')!=decided_by:
                    raise ValueError('该次估值选择已经保存，不能悄悄改写。新数据版本需重新确认。')
            else:
                invitation.update(status=status,decided_by=decided_by,decided_at=now())
                _write_json(location/'invitation.json',invitation,replace=True)
            return {**invitation,'invitation_dir':str(location),'assumptions_template':str(location/'assumptions.template.json') if proceed else None}

    def value(self, project_dir: Path, company_id: str, assumptions: Path):
        from .valuation import value_company
        from .research_export import export_valuation
        folder=Path(project_dir).resolve()
        with project_lock(folder):
            state=load_project(folder); metadata,bundle=self._bundle(folder,state,company_id)
            location=self._invitation_location(folder,metadata,bundle)
            if not (location/'invitation.json').exists() or read_json(location/'invitation.json')['status']!='accepted':
                raise ValueError('用户未选择继续估值，或已经选择停止；不读取参数、不进行估值。')
            raw=read_json(assumptions)
            if raw.get('confirmed') is not True: raise ValueError('参数必须由用户填写并明确确认。')
            request=ValuationRequest.model_validate(raw)
            result=value_company(bundle,metadata,request)
            destination=location/('valuation_'+uuid.uuid4().hex[:12]); destination.mkdir()
            _write_json(destination/'assumptions.json',request.model_dump(mode='json'))
            _write_json(destination/'valuation.json',result)
            export_valuation(result,request.model_dump(mode='json'),destination/'DCF估值.xlsx')
            return {'status':'valued','company_id':company_id,'output_dir':str(destination),
                    'workbook':str(destination/'DCF估值.xlsx'),'assumptions_fingerprint':digest(request)}
