"""Comparable, user-selected peer panels; sample statistics are not industry data."""
from decimal import Decimal
from statistics import median

from .models import digest


def compare_companies(companies: list[tuple[dict,dict]], years: list[int] | None=None) -> dict:
    if len(companies)<2 or len({m['company_id'] for m,b in companies})!=len(companies):
        raise ValueError('横向比较至少需要两个不同公司，每个公司使用一个已审核运行。')
    from .research_io import assert_approved_snapshot
    for metadata,bundle in companies:
        assert_approved_snapshot(bundle)
        if metadata['company_id']!=bundle['state']['company_id']:
            raise ValueError('所选公司与历史数据身份不一致。')
    currencies={b['currency'] for m,b in companies}
    standards={m['accounting_standard'].strip().upper() for m,b in companies}
    year_ends={m['fiscal_year_end'] for m,b in companies}
    if len(currencies)!=1 or len(standards)!=1 or len(year_ends)!=1:
        raise ValueError('比较要求币种、会计准则和完整财年末一致；本版不自动换汇或跨财年对齐。')
    if any(not m['comparability_confirmed'] for m,b in companies):
        raise ValueError('比较口径尚未由用户确认。')
    common=set.intersection(*(set(b['analysis']['years']) for m,b in companies))
    selected=sorted(common) if years is None else sorted(years)
    if not selected or len(set(selected))!=len(selected) or not set(selected)<=common:
        raise ValueError('没有匹配年度，或选择的年度并非所有公司的共同报告年度。')
    same_industry=len({m['industry'].strip() for m,b in companies})==1
    rows=[]; indexed=[]; snapshots=[]; exclusions=[]
    for metadata,bundle in companies:
        analysis=bundle['analysis']; cid=metadata['company_id']
        snapshots.append({'company':metadata,'dataset_fingerprint':bundle['state']['dataset_fingerprint'],
                          'analysis_fingerprint':digest(analysis),'years':analysis['years']})
        exclusions.append({'company_id':cid,'excluded_years':sorted(set(analysis['years'])-set(selected))})
        first=analysis['inputs'][str(selected[0])]['revenue']['value']
        for year in selected:
            for metric in ('revenue','net_income','assets','liabilities','cfo'):
                value=analysis['inputs'][str(year)][metric]
                rows.append({'company_id':cid,'year':year,'metric':metric,'value':value['value'],
                             'format':'amount','reason':value['reason'],'source':value['source']})
            for result in [r for r in analysis['results'] if r['year']==year]:
                rows.append({'company_id':cid,'year':year,'metric':result['name'],'value':result['value'],
                             'format':result['format'],'reason':result['reason'],'formula':result['expression'],
                             'source_inputs':analysis['inputs'][str(year)]})
            value=analysis['inputs'][str(year)]['revenue']['value']
            index=(str(Decimal(value)/Decimal(first)*100)
                   if first is not None and Decimal(first)>0 and value is not None else None)
            indexed.append({'company_id':cid,'year':year,'revenue_index':index,
                            'base_year':selected[0],'reason':'' if index else '基准收入缺失或非正'})
    sample=[]
    if same_industry:
        for year in selected:
            for metric in dict.fromkeys(r['metric'] for r in rows):
                group=[r for r in rows if r['year']==year and r['metric']==metric]
                values=[Decimal(r['value']) for r in group if r['value'] is not None]
                sample.append({'year':year,'metric':metric,'count':len(values),'selected_count':len(companies),
                               'median':str(median(values)) if values else None,
                               'label':'用户选择公司样本中位数，不代表全行业'})
    return {'schema_version':'finance-peer-comparison-v1','currency':next(iter(currencies)),
            'years':selected,'company_ids':[m['company_id'] for m,b in companies],
            'comparison_type':'selected_same_industry_peers' if same_industry else 'selected_cross_industry_companies',
            'snapshots':snapshots,'exclusions':exclusions,'rows':rows,'revenue_index':indexed,
            'sample_statistics':sample,'limitations':[
                '只比较用户选择的已审核样本；不代表完整行业，不自动给出投资排名。',
                '统一报告年度、币种及会计准则后，业务结构与会计估计仍可能存在差异。',
                '同比可能使用各年原报本年数或缺少上年报告时的比较栏，来源输入保留供核对。']}
