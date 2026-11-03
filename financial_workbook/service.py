"""Public application API: persistent prepare/review/finalize lifecycle."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
import os
from typing import Literal

from pydantic import Field
from .models import StrictModel, Dataset, digest, now

ROOT=Path(__file__).resolve().parents[1]


class FinanceConfig(StrictModel):
    report_set: Path = ROOT/'data/reports/report_set.json'
    output_dir: Path = ROOT/'outputs/agent_runs'
    index_dir: Path | None = None
    parser_profile: Path | None = None
    top_k: int = Field(default=5,ge=1,le=20)
    export_backend: Literal['python','artifact'] = 'python'

    @classmethod
    def from_file(cls,path: Path):
        path=Path(path).resolve()
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        config=cls.model_validate(data)
        for key in ('report_set','output_dir','index_dir','parser_profile'):
            value=getattr(config,key)
            if value is not None:
                setattr(config,key,(path.parent/value).resolve())
        if config.export_backend not in ('python','artifact'):
            raise ValueError('export_backend 仅允许 python / artifact。')
        return config


def _write_json(path: Path,value,*,replace=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not replace and path.exists():
        temporary.unlink()
        raise ValueError('已有运行记录不能覆盖：'+str(path))
    temporary.replace(path)


def _stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]


def _inside(folder: Path,name: str) -> Path:
    path=(folder/name).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise ValueError('运行记录中的路径越出本次运行目录。')
    return path


@contextmanager
def _exclusive_run(folder: Path):
    lock=folder.resolve()/'.finalize.lock'
    if lock.exists():
        try:
            from .research_io import process_alive
            content=lock.read_text(encoding='utf-8'); owner=json.loads(content).get('pid')
            if type(owner) is int and owner>0 and process_alive(owner) is False:
                if lock.read_text(encoding='utf-8')==content: lock.unlink()
        except (OSError,ValueError): pass
    try:
        stream=lock.open('x',encoding='utf-8')
    except FileExistsError:
        raise ValueError('本次运行已有 finalize 锁。请等待另一进程结束；异常中断时先确认进程退出再移除 .finalize.lock。') from None
    try:
        with stream: stream.write(json.dumps({'pid':os.getpid(),'created_at':now()}))
        yield
    finally:
        lock.unlink(missing_ok=True)


class FinancialAnalysisAgent:
    """Reusable system facade; actual orchestration lives in WorkbookAgents.

    Each prepare has its own directory; finalization reuses that exact dataset.
    llm_factory is injectable for user tests; production uses the existing
    DeepSeek configuration and existing LlamaIndex RAG implementation.
    """
    def __init__(self,config: FinanceConfig | None=None,*,llm_factory=None,progress=None):
        self.config=config or FinanceConfig()
        self.llm_factory=llm_factory
        self.progress=progress or (lambda message: None)

    def _llm(self):
        if self.llm_factory is not None: return self.llm_factory()
        from rag_step1.config import create_llm
        return create_llm()

    def _load_sources(self):
        from rag_step1.report import load_report_set
        return load_report_set(self.config.report_set)

    def _retriever(self,report_set):
        from rag_step1.indexer import build_index,load_index
        from rag_step1.retrieval import EvidenceRetriever
        self.progress('核验并建立/复用当前报告集合的 RAG 索引。')
        build_index(report_set,self.config.index_dir)
        return EvidenceRetriever(report_set,load_index(report_set,self.config.index_dir),top_k=self.config.top_k)

    def _preflight(self,report_set,profile):
        """Verify local statement geometry before expensive embedding or API work.

        This is a readiness check, not an Agent result or human approval. The
        actual evidence and extraction specialists still execute their tools
        afterwards, against the same immutable report set.
        """
        from .extract import locate,extract
        from .review import assert_sources
        from .errors import ReportSourceError
        from .automatic import check_dataset
        try:
            locators=locate(report_set,profile)
            dataset=extract(report_set,locators,profile)
            expected={(s.report_year,kind) for s in report_set.sources for kind in ('IS','BS','CF')}
            if {(s.report_year,s.kind) for s in dataset.statements}!=expected:
                raise ValueError('三张主表覆盖不完整，不能开始正式分析。')
            assert_sources(dataset,report_set)
            check_dataset(dataset)
        except ValueError as exc:
            raise ReportSourceError('报表预检失败：'+str(exc)) from None
        return {'status':'passed','method':'local_source_geometry_preflight',
            'report_set_id':report_set.report_set_id,'human_approval':False,
            'statements':[{'report_year':s.report_year,'kind':s.kind,'file_name':s.file_name,
                'pdf_pages':s.pdf_pages,'rows':len(s.rows)} for s in dataset.statements]}

    async def prepare(self) -> dict:
        from .agents import WorkbookAgents
        from .parsing import validated_profile
        from .cli import export_payload,export_workbook
        from .review import assert_sources
        report_set=await asyncio.to_thread(self._load_sources)
        if len({s.report_year for s in report_set.sources})!=len(report_set.sources):
            raise ValueError('完整报表输出每年需选定一份主年报；请先在上传清单排除同年度的重复版本。')
        profile=json.loads(self.config.parser_profile.read_text(encoding='utf-8-sig')) if self.config.parser_profile else {}
        validated_profile(profile,report_set)
        folder=self.config.output_dir.resolve()/report_set.report_set_id/_stamp()
        folder.mkdir(parents=True,exist_ok=False)
        snapshot={'company_id':report_set.company_id,'single_company_confirmed':True,
                  'reports':[{'file_name':str(s.pdf_path),'report_year':s.report_year,'file_hash':s.file_hash,
                              'verified_printed_pages':dict(s.verified_printed_pages)} for s in report_set.sources]}
        _write_json(folder/'report_set.snapshot.json',snapshot)
        _write_json(folder/'parser_profile.snapshot.json',profile)
        state={'schema_version':'finance-agent-run-v1','created_at':now(),'updated_at':now(),
               'process_id':os.getpid(),
               'status':'preparing','company_id':report_set.company_id,'report_set_id':report_set.report_set_id,
               'export_backend':self.config.export_backend,'run_dir':str(folder),
               'files':{'sources':'report_set.snapshot.json','profile':'parser_profile.snapshot.json',
                        'candidates':'candidates.json','prepare_trace':'prepare.trace.json',
                        'review_workbook':'待审核财务报表.xlsx'}}
        _write_json(folder/'run.json',state)
        pipeline=None; phase='preflight'
        try:
            self.progress('正在预检年报主表、年度列与跨页版式；通过后才建立 RAG 索引。')
            preflight=await asyncio.to_thread(self._preflight,report_set,profile)
            _write_json(folder/'preflight.json',preflight)
            state.update(preflight_status='passed',updated_at=now())
            _write_json(folder/'run.json',state,replace=True)
            self.progress('报表版式与来源预检通过，开始建立或复用检索索引。')
            phase='index_and_agents'
            llm=self._llm()
            retriever=await asyncio.to_thread(self._retriever,report_set)
            pipeline=WorkbookAgents(report_set,retriever,llm,profile=profile)
            self.progress('主 Agent 正在调用取证与财务表提取子 Agent。')
            dataset,trace=await pipeline.run()
            expected={(s.report_year,kind) for s in report_set.sources for kind in ('IS','BS','CF')}
            if {(s.report_year,s.kind) for s in dataset.statements}!=expected:
                raise ValueError('三张主表覆盖不完整，不能作为完整候选交付。')
            await asyncio.to_thread(assert_sources,dataset,report_set)
            _write_json(folder/'candidates.json',dataset.model_dump(mode='json'))
            _write_json(folder/'prepare.trace.json',trace)
            self.progress('候选报表已提取，正在保存来源记录与中间工作簿。')
            await asyncio.to_thread(export_workbook,export_payload(dataset,None,False),folder/'待审核财务报表.xlsx',backend=self.config.export_backend)
            state.update(status='needs_human_review',dataset_fingerprint=dataset.fingerprint,
                         statements=len(dataset.statements),visible_rows=sum(len(s.rows) for s in dataset.statements),
                         comparative_differences=len(dataset.conflicts),updated_at=now())
            _write_json(folder/'run.json',state,replace=True)
            return self.status(folder)
        except Exception as exc:
            state.update(status='prepare_failed',updated_at=now(),error_type=type(exc).__name__,failure_stage=phase)
            _write_json(folder/'run.json',state,replace=True)
            if pipeline is not None and not (folder/'prepare.trace.json').exists():
                _write_json(folder/'prepare.trace.json',{'status':'failed','trace':pipeline.last_trace})
            elif phase=='preflight':
                from .errors import ReportSourceError
                details={'event':'source_error' if isinstance(exc,ReportSourceError) else 'preflight_error',
                         'stage':'preflight','error_type':type(exc).__name__}
                if isinstance(exc,ReportSourceError): details['detail']=str(exc)[:700]
                _write_json(folder/'preflight.json',{'status':'failed',**details},replace=True)
                _write_json(folder/'prepare.trace.json',{'status':'failed','trace':[details]})
            self.progress('运行未完成，记录保存在：'+str(folder))
            raise

    @staticmethod
    def status(run_dir: Path) -> dict:
        folder=Path(run_dir).resolve()
        state=json.loads((folder/'run.json').read_text(encoding='utf-8-sig'))
        if state.get('schema_version')!='finance-agent-run-v1':
            raise ValueError('不是本系统的运行记录。')
        for name in state['files'].values(): _inside(folder,name)
        result={**state,'run_dir':str(folder),'review_workbook':str(_inside(folder,state['files']['review_workbook']))}
        if state.get('formal_workbook'):
            result['formal_workbook_path']=str(_inside(folder,state['formal_workbook']))
        return result

    async def finalize(self,run_dir: Path,review_workbook: Path) -> dict:
        with _exclusive_run(Path(run_dir)):
            return await self._finalize(run_dir,review_workbook)

    async def finalize_automatically(self,run_dir: Path) -> dict:
        """Machine validation path, without a human review or fabricated signature."""
        from rag_step1.report import load_report_set
        from .automatic import validate_sources
        from .analysis import analyze
        from .cli import export_payload,export_workbook
        folder=Path(run_dir).resolve()
        with _exclusive_run(folder):
            state=self.status(folder)
            if state['status']=='completed': return state
            if state['status'] not in ('needs_human_review','finalize_failed','validation_failed','validating'):
                raise ValueError('候选尚未提取完成，或分析仍在执行，不能重复运行。')
            reports=await asyncio.to_thread(load_report_set,_inside(folder,state['files']['sources']))
            dataset=Dataset.model_validate_json(_inside(folder,state['files']['candidates']).read_text(encoding='utf-8'))
            if dataset.fingerprint!=state.get('dataset_fingerprint'):
                raise ValueError('候选指纹已改变，不能继续自动分析。')
            attempt='automatic_'+_stamp(); destination=folder/attempt; destination.mkdir()
            state.update(status='validating',updated_at=now(),validation_method='system',last_attempt=attempt,process_id=os.getpid())
            _write_json(folder/'run.json',state,replace=True)
            events=[]
            try:
                self.progress('系统正在重新核对 PDF 来源、完整三表、单位和基础勾稽。')
                validation=await asyncio.to_thread(validate_sources,dataset,reports)
                events.append({'event':'source_validation_completed','method':'system','checks':len(validation.checks)})
                _write_json(destination/'system_validation.json',validation.model_dump(mode='json'))
                self.progress('系统校验完成，使用固定公式计算历史指标。')
                result=await asyncio.to_thread(analyze,dataset,validation)
                _write_json(destination/'analysis.json',result)
                output=destination/'历史财务分析.xlsx'
                await asyncio.to_thread(export_workbook,export_payload(dataset,validation,True),output,backend='python')
                events.append({'event':'deterministic_analysis_export_completed','validated_statements':len(dataset.statements)})
                _write_json(destination/'agents.trace.json',{'status':'completed','finalization_method':'deterministic_system_validation',
                    'agents_executed_in_this_stage':False,'prepare_agent_trace':state['files']['prepare_trace'],'trace':events})
                state.update(status='completed',updated_at=now(),formal_workbook=str(output.relative_to(folder)),
                    validated_statements=len(dataset.statements),approved_statements=0)
                state.pop('error_type',None); _write_json(folder/'run.json',state,replace=True)
                self.progress('历史分析和 Excel 已生成；数据经过系统校验，未记为人工批准。')
                return self.status(folder)
            except Exception as exc:
                state.update(status='validation_failed',updated_at=now(),error_type=type(exc).__name__)
                _write_json(folder/'run.json',state,replace=True)
                _write_json(destination/'agents.trace.json',{'status':'failed','method':'system','trace':events})
                raise

    async def _finalize(self,run_dir: Path,review_workbook: Path) -> dict:
        from rag_step1.report import load_report_set
        from .agents import WorkbookAgents
        from .analysis import analyze
        from .review import import_review,assert_sources
        from .cli import export_payload,export_workbook
        folder=Path(run_dir).resolve(); state=self.status(folder)
        if state['status'] not in ('needs_human_review','finalize_failed','finalizing'):
            raise ValueError('本次运行不是等待审核的状态；完成记录保留不覆盖。')
        report_set=await asyncio.to_thread(load_report_set,_inside(folder,state['files']['sources']))
        dataset=Dataset.model_validate_json(_inside(folder,state['files']['candidates']).read_text(encoding='utf-8'))
        if dataset.fingerprint!=state.get('dataset_fingerprint') or dataset.report_set_id!=report_set.report_set_id:
            raise ValueError('运行快照或候选版本已改变，请重新 prepare 并审核。')
        self.progress('导入你填写的审核副本，核对原始来源与修正记录。')
        review_path=Path(review_workbook).resolve()
        if review_path.suffix.lower()=='.json':
            from .human_review import import_human_review
            review=await asyncio.to_thread(import_human_review,review_path,dataset,report_set)
        else:
            review=await asyncio.to_thread(import_review,review_path,dataset,report_set)
        approved=analyze(dataset,review)
        if approved['status']!='approved':
            count=approved['approved_statements']; total=approved['total_statements']
            raise ValueError(f'目前批准 {count}/{total} 张表；请完成全部人工审核后再生成正式分析。')
        export_payload(dataset,review,True)  # Validate all export prerequisites before any model call.
        attempt='finalize_'+_stamp(); attempt_dir=folder/attempt; attempt_dir.mkdir()
        _write_json(attempt_dir/'review.json',review.model_dump(mode='json'))
        _write_json(attempt_dir/'review_origin.json',{'workbook':str(Path(review_workbook).resolve()),'imported_at':now()})
        output=attempt_dir/'历史财务分析.xlsx'
        def exporter(calculated):
            if digest(calculated)!=digest(analyze(dataset,review)):
                raise ValueError('分析结果与当前批准输入不一致。')
            assert_sources(dataset,report_set)
            payload=export_payload(dataset,review,True)
            export_workbook(payload,output,backend=state['export_backend'])
            _write_json(attempt_dir/'analysis.json',calculated)
            return output
        pipeline=WorkbookAgents(report_set,None,self._llm(),profile=dataset.extraction_profile)
        state.update(status='finalizing',updated_at=now(),last_attempt=attempt)
        _write_json(folder/'run.json',state,replace=True)
        try:
            self.progress('主 Agent 正在调用来源复核、历史分析和 Excel 导出工具。')
            result=await pipeline.finalize(dataset,review,exporter)
            _write_json(attempt_dir/'agents.trace.json',{k:v for k,v in result.items() if k!='analysis'})
            state.update(status='completed',updated_at=now(),formal_workbook=str(output.relative_to(folder)),
                         approved_statements=approved['approved_statements'])
            state.pop('error_type',None)
            _write_json(folder/'run.json',state,replace=True)
            return self.status(folder)
        except Exception as exc:
            state.update(status='finalize_failed',updated_at=now(),error_type=type(exc).__name__)
            _write_json(folder/'run.json',state,replace=True)
            if not (attempt_dir/'agents.trace.json').exists():
                _write_json(attempt_dir/'agents.trace.json',{'status':'failed','trace':pipeline.last_trace})
            raise

    async def ask(self,question: str,report_years=None) -> dict:
        from rag_step1.qa import ask_question
        report_set=await asyncio.to_thread(self._load_sources)
        retriever=await asyncio.to_thread(self._retriever,report_set)
        return await ask_question(retriever,question,report_years=report_years,llm=self._llm())
