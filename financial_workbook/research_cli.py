"""CLI adapters and a human-only parameter interview, reusable by future clients."""
from __future__ import annotations
import asyncio
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from .research import ResearchWorkflow
from .research_io import read_json
from .research_models import ValuationRequest
from .service import _write_json


def add_research_commands(commands):
    root=commands.add_parser('research',help='单报告、跨年、多公司研究与人机协作估值')
    sub=root.add_subparsers(dest='research_command',required=True)
    p=sub.add_parser('create'); p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,default=Path('outputs/research_projects'))
    for name in ('status','prepare','history','review','finalize','offer','decide','value','interact'):
        p=sub.add_parser(name); p.add_argument('--project',type=Path,required=True)
        if name in ('prepare','history','interact'): p.add_argument('--companies',nargs='+')
        if name in ('review','finalize','offer','decide','value'): p.add_argument('--company',required=True)
        if name=='review': p.add_argument('--submission',type=Path,required=True)
        if name=='finalize': p.add_argument('--review',type=Path)
        if name=='history': p.add_argument('--years',nargs='+',type=int)
        if name=='decide':
            p.add_argument('--choice',choices=['continue','stop'],required=True); p.add_argument('--by',required=True)
        if name=='value': p.add_argument('--assumptions',type=Path,required=True)
        if name=='interact':
            p.add_argument('--by',required=True); p.add_argument('--collect',action='store_true',
                help='选择继续后，在命令行逐项收集参数并计算；不带此项则输出待填写参数模板')


def _text(prompt,input_fn):
    while True:
        value=input_fn(prompt).strip()
        if value: return value


def _decimal(prompt,input_fn):
    while True:
        value=_text(prompt+'（小数，金额为原币基本单位）: ',input_fn)
        try:
            parsed=Decimal(value)
            if parsed.is_finite(): return str(parsed)
        except InvalidOperation: pass
        print('请输入有限数值，例如 0.05 表示 5%；不接受百分号。')


def collect_assumptions(template: dict, actor: str, input_fn=input) -> dict:
    """No guessed financial numbers. Empty answers never count as consent."""
    result=json.loads(json.dumps(template)); base=result['base_year']
    print(f"{result['company_id']}：基准年 {base}，估值日 {result['valuation_date']}，币种 {result['currency']}。")
    result['initial_operating_nwc']=_decimal('基准年末经营性非现金营运资本',input_fn)
    result['initial_operating_nwc_evidence']=_text('该营运资本的原页、组成项与核查依据: ',input_fn)
    bridge=result['bridge']
    for key,label in [('excess_cash','可加回的非经营或超额现金'),('non_operating_assets','其他非经营资产价值'),
        ('interest_bearing_debt','有息债务价值（说明租赁口径）'),('minority_interest','少数股东权益价值'),
        ('preferred_equity','优先股价值'),('other_claims','其他需扣除权益请求权'),('diluted_shares','稀释股数（股）')]:
        bridge[key]=_decimal(label,input_fn)
    market=input_fn('估值日参考股价，可留空: ').strip()
    bridge['market_price']=market or None
    bridge['rationale']=_text('桥接输入的日期、来源与避免重复计入的依据: ',input_fn)
    while True:
        names=[x.strip() for x in _text('情景名称，用逗号分隔，选 Base/Bear/Bull: ',input_fn).split(',')]
        if names and len(set(names))==len(names) and all(x in ('Base','Bear','Bull') for x in names): break
    while True:
        value=_text('预测年数（1 至 15）: ',input_fn)
        if value.isdigit() and 1<=int(value)<=15: horizon=int(value); break
    result['scenarios']=[]
    for name in names:
        print('填写情景 '+name)
        while True:
            choice=_text('折现率方式：1 直接 WACC，2 组成项: ',input_fn)
            if choice in ('1','2'): break
        rate={'mode':'direct' if choice=='1' else 'components'}
        if choice=='1': rate['wacc']=_decimal('WACC',input_fn)
        else:
            for key,label in [('risk_free_rate','无风险利率'),('beta','杠杆 Beta'),('equity_risk_premium','股权风险溢价'),
                ('country_risk_premium','额外国家风险溢价（没有也需明确填 0）'),('pretax_cost_of_debt','税前债务成本'),
                ('debt_tax_rate','债务利息税盾税率'),('market_equity','权益市场价值'),('market_debt','债务市场价值')]:
                rate[key]=_decimal(label,input_fn)
        rate['rationale']=_text('折现参数的经验依据与日期: ',input_fn)
        forecasts=[]
        for year in range(base+1,base+horizon+1):
            row={'year':year}; print(f'{year} 年预测参数')
            for key,label in [('revenue_growth','收入增长率'),('ebit_margin','EBIT 利润率'),('cash_tax_rate','经营现金税率'),
                ('depreciation_to_revenue','折旧摊销/收入'),('capex_to_revenue','资本支出/收入'),
                ('operating_nwc_to_revenue','经营性非现金营运资本/收入')]:
                row[key]=_decimal(label,input_fn)
            row['rationale']=_text('本年预测依据: ',input_fn); forecasts.append(row)
        terminal={}
        for key,label in [('growth','长期增长率'),('ebit_margin','长期 EBIT 利润率'),
            ('cash_tax_rate','长期现金税率'),('return_on_invested_capital','长期 ROIC')]:
            terminal[key]=_decimal(label,input_fn)
        terminal['rationale']=_text('终值假设依据: ',input_fn)
        wacc=[x.strip() for x in _text('敏感性 WACC 列表，逗号分隔: ',input_fn).split(',')]
        growth=[x.strip() for x in _text('敏感性长期增长率列表，逗号分隔: ',input_fn).split(',')]
        result['scenarios'].append({'name':name,'discount_rate':rate,'forecasts':forecasts,'terminal':terminal,
                                   'sensitivity_wacc':wacc,'sensitivity_growth':growth})
    result['confirmed_by']=actor
    result['rationale']=_text('整体假设依据、适用边界及希望检验的问题: ',input_fn)
    result['confirmed']=False
    print(json.dumps(result,ensure_ascii=False,indent=2))
    result['confirmed']=_text('核对全部参数后，输入 CONFIRM 确认；其他输入保留草稿: ',input_fn)=='CONFIRM'
    if result['confirmed']: ValuationRequest.model_validate(result)
    return result


def interactive(workflow, project, companies, actor, collect=False,input_fn=input):
    history=workflow.history(project,companies)
    print(json.dumps({k:v for k,v in history.items() if k!='investment_offers'},ensure_ascii=False,indent=2))
    decisions=[]
    for offer in history['investment_offers']:
        cid=offer['company_id']
        if not offer['eligible']:
            print(f'{cid} 为金融企业，历史分析完成，当前 FCFF 模型暂不适用。'); continue
        if offer['status']=='declined':
            print(f'{cid} 已选择停止，保留历史分析。'); continue
        if offer['status']=='awaiting_user_choice':
            print(offer['question'])
            while True:
                answer=_text(f'{cid} 继续？输入 yes 或 no: ',input_fn).lower()
                if answer in ('yes','no'): break
            decision=workflow.decide(project,cid,proceed=answer=='yes',decided_by=actor)
        else: decision={**offer,'assumptions_template':str(Path(offer['invitation_dir'])/'assumptions.template.json')}
        decisions.append(decision)
        if decision['status']=='declined':
            print('已停止。历史工作簿保留，不要求参数、不执行估值。'); continue
        print('参数模板：'+decision['assumptions_template'])
        if collect:
            parameters=collect_assumptions(read_json(decision['assumptions_template']),actor,input_fn)
            location=Path(decision['invitation_dir'])/('assumptions_'+__import__('uuid').uuid4().hex[:12]+'.json')
            _write_json(location,parameters)
            if parameters['confirmed']:
                decisions.append(workflow.value(project,cid,location))
            else: print('未确认，仅保存参数草稿，不计算。')
    return {'history':history,'decisions':decisions}


def run_research(args):
    workflow=ResearchWorkflow(progress=lambda message:print(message,flush=True)); action=args.research_command
    if action=='create': return workflow.create(args.manifest,args.output_dir)
    if action=='status': return workflow.status(args.project)
    if action=='prepare': return asyncio.run(workflow.prepare(args.project,args.companies))
    if action=='history': return workflow.history(args.project,args.companies,args.years)
    if action=='review': return workflow.submit_review(args.project,args.company,args.submission)
    if action=='finalize': return asyncio.run(workflow.finalize(args.project,args.company,args.review))
    if action=='offer': return workflow.offer(args.project,args.company)
    if action=='decide': return workflow.decide(args.project,args.company,proceed=args.choice=='continue',decided_by=args.by)
    if action=='value': return workflow.value(args.project,args.company,args.assumptions)
    return interactive(workflow,args.project,args.companies,args.by,args.collect)
