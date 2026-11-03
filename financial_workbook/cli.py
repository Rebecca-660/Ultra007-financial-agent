from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
from .models import Dataset, Review, SystemValidation, digest
from .analysis import analyze
from .extract import extract
from .review import assert_sources, import_review
from rag_step1.report import load_report_set

ROOT=Path(__file__).resolve().parents[1]
DEFAULT=ROOT/'outputs'/'historical'


def save(path: Path, content: str):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(content,encoding='utf-8')


async def agent_extract(report_set):
    from rag_step1.indexer import load_index
    from rag_step1.retrieval import EvidenceRetriever
    from rag_step1.config import create_llm
    from .agents import WorkbookAgents
    print('加载已有报告索引并运行三个 Agent；不批准数据。',flush=True)
    retriever=EvidenceRetriever(report_set,load_index(report_set),top_k=5)
    pipeline=WorkbookAgents(report_set,retriever,create_llm())
    return await pipeline.run()


def export_payload(dataset: Dataset, review: Review | SystemValidation | None, formal: bool) -> dict:
    result=analyze(dataset,review if formal else None)
    if formal and result['status'] not in ('approved','validated'):
        raise ValueError('尚有报表未经人工批准，不能生成正式分析和图表。')
    if formal and len({s.currency for s in dataset.statements})!=1:
        raise ValueError('正式跨年工作簿需统一币种；当前不自动换汇，仍可导出候选。')
    return {'dataset':dataset.model_dump(mode='json'),'analysis':result,
            'dataset_fingerprint':dataset.fingerprint,
            'statement_digests':{s.statement_id:digest(s) for s in dataset.statements},
            'review':review.model_dump(mode='json') if formal and isinstance(review,Review) else None,
            **({'validation':review.model_dump(mode='json')} if isinstance(review,SystemValidation) else {}),
            'mode':'formal' if formal else 'candidate'}


def export_workbook(payload: dict, output: Path, *, backend: str = 'python'):
    if output.exists():
        raise ValueError('输出文件已存在；请另选文件名，避免覆盖已填写的审核。')
    if backend == 'python':
        from .excel_export import export_xlsx
        export_xlsx(payload,output)
        return
    if backend != 'artifact':
        raise ValueError('Unknown Excel backend')
    if any(len(s['columns'])!=2 or s['columns'][0]['role']!='current' for s in payload['dataset']['statements']):
        raise ValueError('旧 Artifact 导出器仅兼容本年在首列的双金额栏，请使用默认 Python 导出器。')
    node=Path(os.getenv('AIF_ARTIFACT_NODE',str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')))
    if not node.is_file() or not (ROOT/'node_modules/@oai/artifact-tool').exists():
        raise RuntimeError('缺少工作簿运行库。请运行 scripts/setup_workbook_runtime.ps1；可通过 AIF_ARTIFACT_NODE 和 AIF_ARTIFACT_NODE_MODULES 指定已有运行库。')
    prepared=output.with_suffix('.payload.json')
    save(prepared,json.dumps(payload,ensure_ascii=False,indent=2))
    subprocess.run([str(node),str(ROOT/'scripts/export_historical_workbook.mjs'),str(prepared),str(output)],
                   cwd=ROOT,check=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description='年报完整三表、人工审核和历史分析 Excel')
    parser.add_argument('command',choices=['extract','export','review','check'])
    parser.add_argument('--report-set',type=Path,default=ROOT/'data/reports/report_set.json')
    parser.add_argument('--candidates',type=Path,default=DEFAULT/'candidates.json')
    parser.add_argument('--agents',action='store_true',help='实际调用三个 FunctionAgent；需要已建索引和模型 API')
    parser.add_argument('--formal',action='store_true')
    parser.add_argument('--review',type=Path)
    parser.add_argument('--workbook',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--backend',choices=['python','artifact'],default='python')
    args=parser.parse_args(argv)
    report_set=load_report_set(args.report_set)
    if args.command=='extract':
        if args.agents:
            dataset,trace=asyncio.run(agent_extract(report_set))
        else:
            dataset=extract(report_set)
            trace={'status':'deterministic_extraction','agents_executed':False}
        save(args.candidates,dataset.model_dump_json(indent=2))
        save(args.candidates.with_suffix('.trace.json'),json.dumps(trace,ensure_ascii=False,indent=2))
        print(json.dumps({'statements':len(dataset.statements),'rows':sum(len(s.rows) for s in dataset.statements),
              'comparative_differences':len(dataset.conflicts),'approved':False,'output':str(args.candidates)},ensure_ascii=False))
        return 0
    dataset=Dataset.model_validate_json(args.candidates.read_text(encoding='utf-8'))
    assert_sources(dataset,report_set)
    if args.command=='review':
        if not args.workbook:
            parser.error('review requires --workbook')
        review=import_review(args.workbook,dataset,report_set)
        output=args.output or DEFAULT/('review_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json')
        if output.exists():
            raise ValueError('审核记录已存在，请选择新文件名，保留旧审核。')
        save(output,review.model_dump_json(indent=2))
        print(json.dumps({'approved':len([d for d in review.decisions if d.decision=='approved']),
              'total':len(dataset.statements),'review':str(output)},ensure_ascii=False))
        return 0
    review=Review.model_validate_json(args.review.read_text(encoding='utf-8')) if args.review else None
    if args.command=='check':
        result=analyze(dataset,review)
        print(json.dumps({'status':result['status'],'approved_statements':result['approved_statements'],
            'total_statements':result['total_statements'],'computed_results':sum(r['value'] is not None for r in result['results'])},ensure_ascii=False))
        return 0
    payload=export_payload(dataset,review,args.formal)
    output=args.output or DEFAULT/('历史财务分析.xlsx' if args.formal else '年报财务报表_待审核.xlsx')
    export_workbook(payload,output,backend=args.backend)
    return 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (ValueError,RuntimeError) as exc:
        print(str(exc))
        raise SystemExit(2)
