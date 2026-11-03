"""User-facing unified CLI. Importing modules never starts an analysis."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from pydantic import ValidationError

from .service import FinanceConfig,FinancialAnalysisAgent


def main(argv=None):
    parser=argparse.ArgumentParser(description='通用财报分析 Agent：年报 → RAG/完整三表 → 人工审核 → 分析 Excel')
    commands=parser.add_subparsers(dest='command',required=True)
    from .research_cli import add_research_commands
    add_research_commands(commands)
    for name in ('prepare','ask'):
        p=commands.add_parser(name)
        p.add_argument('--config',type=Path)
        p.add_argument('--report-set',type=Path)
        p.add_argument('--output-dir',type=Path)
        p.add_argument('--index-dir',type=Path)
        p.add_argument('--parser-profile',type=Path)
        if name=='ask':
            p.add_argument('question')
            p.add_argument('--year',type=int,action='append')
    p=commands.add_parser('finalize')
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--review-workbook',type=Path,required=True)
    p=commands.add_parser('status'); p.add_argument('--run-dir',type=Path,required=True)
    p=commands.add_parser('doctor'); p.add_argument('--online',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.command=='research':
            from .research_cli import run_research
            result=run_research(args)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0
        if args.command=='doctor':
            from rag_step1.cli import doctor
            result=asyncio.run(doctor(args.online))
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if not args.online or result.get('online_tool_call')=='passed' else 2
        config=FinanceConfig.from_file(args.config) if getattr(args,'config',None) else FinanceConfig()
        for key in ('report_set','output_dir','index_dir','parser_profile'):
            value=getattr(args,key,None)
            if value is not None: setattr(config,key,value.resolve())
        agent=FinancialAnalysisAgent(config,progress=lambda message:print(message,flush=True))
        if args.command=='prepare': result=asyncio.run(agent.prepare())
        elif args.command=='finalize': result=asyncio.run(agent.finalize(args.run_dir,args.review_workbook))
        elif args.command=='status': result=agent.status(args.run_dir)
        else: result=asyncio.run(agent.ask(args.question,report_years=args.year))
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if result.get('status') in ('invalid_agent_output','agent_error'): return 2
        return 0
    except ValidationError as exc:
        details=['.'.join(map(str,e['loc']))+': '+e['msg'] for e in exc.errors(include_input=False,include_context=False,include_url=False)]
        print('配置/数据校验失败：'+'；'.join(details),file=sys.stderr)
        return 2
    except Exception as exc:
        # Provider exceptions can contain credential-bearing request headers.
        module=exc.__class__.__module__
        safe=module.startswith(('builtins','financial_workbook','rag_step1')) and isinstance(exc,(ValueError,RuntimeError,OSError))
        print('错误：'+(str(exc) if safe else type(exc).__name__),file=sys.stderr)
        return 2


if __name__=='__main__': raise SystemExit(main())
