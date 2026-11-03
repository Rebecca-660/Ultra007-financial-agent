"""Read-only view models for completed financial runs. No model/API invocation."""
from __future__ import annotations
from decimal import Decimal,InvalidOperation
import json
from pathlib import Path

from .models import Dataset,Review,SystemValidation,digest
from .analysis import RECIPES,INPUTS

PROJECT=Path(__file__).resolve().parents[1]
DEFAULT_RUNS=PROJECT/'outputs/agent_runs'
CATEGORIES={
    '增长':['营业收入同比','合并净利润同比','营业收入变动额','合并净利润变动额'],
    '盈利':['毛利','毛利率','营业利润率','净利率','ROA','ROE'],
    '偿债与流动性':['资产负债率','负债权益比','流动比率','简化速动比率'],
    '周转效率':['存货周转率','应收账款周转率','总资产周转率'],
    '现金流':['经营现金流/净利润','经营现金流利润率','简化自由现金流'],
}


class ResultError(ValueError):
    """A saved run is incomplete, inconsistent or unsafe to display."""


def inside(folder:Path,name:str)->Path:
    if not isinstance(name,str) or not name: raise ResultError('结果文件位置缺失。')
    folder=Path(folder).resolve(); target=(folder/name).resolve()
    if not target.is_relative_to(folder): raise ResultError('结果文件位置越出运行目录。')
    return target


def read_json(path:Path)->dict:
    try:
        result=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(result,dict): raise ValueError()
        return result
    except (OSError,ValueError): raise ResultError('结果记录缺失或格式无效。') from None


def discover_runs(root:Path=DEFAULT_RUNS)->tuple[list[dict],int]:
    root=Path(root).resolve(); results=[]; invalid=0
    if not root.is_dir(): return [],0
    for record in root.glob('*/*/run.json'):
        try:
            if not record.resolve().is_relative_to(root): raise ResultError('运行位置无效。')
            state=read_json(record)
            if state.get('status')!='completed': continue
            if state.get('schema_version')!='finance-agent-run-v1': raise ResultError('版本无效。')
            analysis=read_json(inside(record.parent,state['last_attempt'])/'analysis.json')
            workbook=inside(record.parent,state['formal_workbook'])
            if not workbook.is_file() or workbook.suffix.lower()!='.xlsx': raise ResultError('工作簿缺失。')
            years=analysis['years']
            results.append({'path':str(record.parent.resolve()),'company':state['company_id'],
                            'years':years,'updated_at':state.get('updated_at',''),
                            'label':f"{state['company_id']} · {min(years)}–{max(years)} · {state.get('updated_at','')[:10]} · {record.parent.name[-8:]}"})
        except (ResultError,KeyError,TypeError,ValueError): invalid+=1
    results.sort(key=lambda item:(item['updated_at'],item['path']),reverse=True)
    return results,invalid


def run_signature(folder:Path)->tuple:
    folder=Path(folder).resolve(); state=read_json(folder/'run.json')
    try:
        attempt=inside(folder,state['last_attempt'])
        paths=[folder/'run.json',inside(folder,state['files']['candidates']),attempt/'analysis.json',
               attempt/('system_validation.json' if state.get('validation_method')=='system' else 'review.json'),inside(folder,state['formal_workbook'])]
        return tuple((str(p),p.stat().st_mtime_ns,p.stat().st_size) for p in paths)
    except (OSError,KeyError): raise ResultError('正式结果尚未保存完整。') from None


def number(value)->float|None:
    if value is None: return None
    try:
        decimal=Decimal(str(value))
        if not decimal.is_finite(): raise ValueError()
        result=float(decimal)
        if abs(result)==float('inf'): raise ValueError()
        return result
    except (ValueError,InvalidOperation,OverflowError): raise ResultError('结果中含有无效数字。') from None


def load_run(folder:Path)->dict:
    """Check version-bound saved results without rerunning financial calculations."""
    folder=Path(folder).resolve(); state=read_json(folder/'run.json')
    # Run records can be copied to another computer. The verified folder is
    # authoritative for runtime navigation; the archived JSON stays untouched.
    state={**state,'run_dir':str(folder)}
    if state.get('schema_version')!='finance-agent-run-v1' or state.get('status')!='completed':
        raise ResultError('请选择已完成正式分析的运行记录。')
    try:
        attempt=inside(folder,state['last_attempt'])
        dataset=Dataset.model_validate(read_json(inside(folder,state['files']['candidates'])))
        automatic=state.get('validation_method')=='system'
        review=None if automatic else Review.model_validate(read_json(attempt/'review.json'))
        validation=SystemValidation.model_validate(read_json(attempt/'system_validation.json')) if automatic else None
        analysis=read_json(attempt/'analysis.json')
        workbook=inside(folder,state['formal_workbook'])
        if workbook.suffix.lower()!='.xlsx' or not workbook.is_file(): raise ResultError('正式工作簿缺失。')
        authorization=validation if automatic else review
        if not (dataset.fingerprint==state['dataset_fingerprint']==authorization.dataset_fingerprint==analysis['dataset_fingerprint']):
            raise ResultError('数据版本与审核或分析不一致，请重新生成正式结果。')
        if dataset.report_set_id!=authorization.report_set_id or dataset.report_set_id!=state['report_set_id'] or dataset.company_id!=state['company_id']:
            raise ResultError('结果中混入其他公司或报告集合。')
        statements={s.statement_id:s for s in dataset.statements}
        if automatic:
            from .automatic import assert_validation
            from .analysis import analyze
            assert_validation(dataset,validation)
            if digest(analyze(dataset,validation))!=digest(analysis):
                raise ResultError('系统校验分析与保存数据不一致。')
        elif len(review.decisions)!=len(statements) or len({d.statement_id for d in review.decisions})!=len(statements):
            raise ResultError('人工审核记录不完整。')
        for decision in review.decisions if review else []:
            source=statements.get(decision.statement_id)
            if source is None or decision.decision!='approved' or decision.statement_digest!=digest(source) or not decision.reviewer.strip():
                raise ResultError('来源与人工批准不匹配。')
            if any(decision.statement_id in (c['current_statement_id'],c['comparison_statement_id']) for c in dataset.conflicts) and decision.conflict_resolution!='as_reported':
                raise ResultError('比较差异尚未确认。')
        valid_analysis=(analysis.get('status')=='validated' and analysis.get('validated_statements')==len(statements)
                        and analysis.get('approved_statements')==0) if automatic else (
                        analysis.get('status')=='approved' and analysis.get('approved_statements')==len(statements))
        if not valid_analysis or analysis['total_statements']!=len(statements):
            raise ResultError('该结果尚未完整批准。')
        years=sorted({s.report_year for s in dataset.statements})
        if analysis['years']!=years: raise ResultError('分析年度与来源不一致。')
        expected={(y,r[0]) for y in years for r in RECIPES}
        actual=[(r['year'],r['name']) for r in analysis['results']]
        if len(actual)!=len(expected) or set(actual)!=expected: raise ResultError('年度指标不完整或重复。')
        for result in analysis['results']: number(result['value'])
        for year in years:
            annual=analysis['inputs'][str(year)]
            if set(annual)!=set(INPUTS): raise ResultError('指标输入不完整。')
            for item in annual.values(): number(item['value'])
        number(analysis['cagr']['value'])
        currencies={s.currency for s in dataset.statements}
        if len(currencies)!=1 or None in currencies: raise ResultError('币种口径不明确。')
        return {'state':state,'analysis':analysis,'dataset':dataset.model_dump(mode='json'),
                'review':review.model_dump(mode='json') if review else None,
                'validation':validation.model_dump(mode='json') if validation else None,
                'workbook':str(workbook),'currency':next(iter(currencies))}
    except ResultError: raise
    except (KeyError,TypeError,ValueError): raise ResultError('正式结果结构无效或版本不兼容。') from None


def result_for(bundle:dict,year:int,name:str)->dict:
    return next(r for r in bundle['analysis']['results'] if r['year']==year and r['name']==name)


def display_value(value,kind:str='amount',currency:str='CNY')->str:
    if value is None: return '不可计算'
    amount=number(value)
    if kind=='percent': return f'{amount:.1%}'
    if kind=='multiple': return f'{amount:.2f} 倍'
    return f'{amount/1e8:,.2f} 亿 {currency}'


def metric_rows(bundle:dict,years:list[int],categories:list[str])->list[dict]:
    selected={name for category in categories for name in CATEGORIES[category]}
    category_of={name:category for category,names in CATEGORIES.items() for name in names}
    output=[]
    for result in bundle['analysis']['results']:
        if result['year'] not in years or result['name'] not in selected: continue
        kind=result['format']
        output.append({'年度':result['year'],'类别':category_of[result['name']],'指标':result['name'],
                       '结果':display_value(result['value'],kind,bundle['currency']),
                       '状态':'可计算' if result['value'] is not None else '不可计算',
                       '说明':result['reason'] or result['definition'],'公式':result['expression']})
    return output


def chart_rows(bundle:dict,years:list[int],metrics:list[str],percent=False)->list[dict]:
    output=[]
    for year in sorted(years):
        for name in metrics:
            if name in INPUTS:
                item=bundle['analysis']['inputs'][str(year)][name]; label=INPUTS[name][0]
            else: item=result_for(bundle,year,name); label=name
            value=number(item['value'])
            output.append({'年度':str(year),'指标':label,'数值':value if percent or value is None else value/1e8})
    return output


def source_rows(bundle:dict,year:int)->list[dict]:
    by_id={s['statement_id']:s for s in bundle['dataset']['statements']}
    output=[]
    for key,item in bundle['analysis']['inputs'][str(year)].items():
        source=item['source']
        if source:
            table=by_id[source['statement_id']]
            row=next(r for r in table['rows'] if r['row_id']==source['row_id'])
            column=table['columns'][source['column']]
            output.append({'输入':item['label'],'原始项目':row['raw_label'],'报告':table['file_name'],
                'PDF物理页':row['pdf_page'],'报告年度':table['report_year'],'数据年度':column['value_year'],
                '原列头':column['raw_header'],'原披露单位':table['raw_unit'],
                '标准化金额':item['value'],'币种':source['currency']})
        else:
            output.append({'输入':item['label'],'原始项目':'','报告':'','PDF物理页':None,
                           '说明':item['reason']})
    return output
