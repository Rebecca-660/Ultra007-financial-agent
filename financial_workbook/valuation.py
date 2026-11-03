"""Deterministic, human-parameterized non-financial FCFF valuation.

No market data defaults and no LLM arithmetic. All rates are decimal fractions,
all money is in the stated currency's base unit, and discounting is year-end.
"""
from __future__ import annotations
from decimal import Decimal, localcontext

from .models import digest
from .research_models import DiscountRate, ValuationRequest

D=Decimal

FORMULAS={
    'cost_of_equity':'risk_free_rate + beta * equity_risk_premium + country_risk_premium',
    'wacc':'Ke * E/(D+E) + pretax_cost_of_debt * (1-debt_tax_rate) * D/(D+E)',
    'revenue':'previous_revenue * (1+revenue_growth)',
    'ebit':'revenue * ebit_margin',
    'cash_tax':'max(ebit,0) * cash_tax_rate (no assumed immediate tax credit or loss carryforward)',
    'fcff':'ebit - cash_tax + depreciation - capex - change_in_operating_nwc',
    'terminal_reinvestment_rate':'terminal_growth / terminal_ROIC',
    'terminal_fcff':'terminal_NOPAT * (1-terminal_growth/terminal_ROIC)',
    'terminal_value':'terminal_fcff / (WACC-terminal_growth)',
    'operating_value':'sum(FCFF_t/(1+WACC)^t) + terminal_value/(1+WACC)^n',
    'equity_value':'operating_value + excess_cash + non_operating_assets - interest_bearing_debt - minority_interest - preferred_equity - other_claims',
    'per_share_value':'positive equity_value / diluted_shares',
}
METHOD_SOURCES=[
    'https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/free-cash-flow-valuation',
    'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valquestions/termvalueexreturns.htm',
]


def calculate_wacc(rate: DiscountRate) -> dict:
    rate=DiscountRate.model_validate(rate.model_dump())
    if rate.mode=='direct':
        return {'wacc':str(rate.wacc),'mode':'direct','cost_of_equity':None,'aftertax_cost_of_debt':None}
    ke=rate.risk_free_rate+rate.beta*rate.equity_risk_premium+rate.country_risk_premium
    kd=rate.pretax_cost_of_debt*(1-rate.debt_tax_rate)
    total=rate.market_equity+rate.market_debt
    wacc=(ke*rate.market_equity+kd*rate.market_debt)/total
    if not 0<wacc<=1:
        raise ValueError('组成项计算出的 WACC 必须在 (0,1] 内，请核对参数和单位。')
    return {'wacc':str(wacc),'mode':'components','cost_of_equity':str(ke),
            'aftertax_cost_of_debt':str(kd),'equity_weight':str(rate.market_equity/total),
            'debt_weight':str(rate.market_debt/total)}


def _equity_bridge(operating: Decimal, bridge) -> tuple[Decimal,Decimal|None]:
    equity=(operating+bridge.excess_cash+bridge.non_operating_assets-bridge.interest_bearing_debt
            -bridge.minority_interest-bridge.preferred_equity-bridge.other_claims)
    return equity,(equity/bridge.diluted_shares if equity>0 else None)


def _present_value(rows, terminal, wacc, growth, bridge):
    if wacc<=growth or growth>=terminal.return_on_invested_capital:
        raise ValueError('WACC 必须大于长期增长率，且长期增长率须小于终值 ROIC。')
    terminal_revenue=rows[-1]['revenue']*(1+growth)
    nopat=terminal_revenue*terminal.ebit_margin*(1-terminal.cash_tax_rate)
    reinvestment= growth/terminal.return_on_invested_capital
    fcff=nopat*(1-reinvestment)
    tv=fcff/(wacc-growth)
    pv_terminal=tv/(1+wacc)**len(rows)
    pv_forecast=sum((row['fcff']/(1+wacc)**row['period'] for row in rows),D(0))
    operating=pv_forecast+pv_terminal
    equity,share=_equity_bridge(operating,bridge)
    return {'terminal_revenue':terminal_revenue,'terminal_nopat':nopat,
            'terminal_reinvestment_rate':reinvestment,'terminal_fcff':fcff,'terminal_value':tv,
            'pv_terminal_value':pv_terminal,'pv_forecast_fcff':pv_forecast,'operating_value':operating,
            'equity_value':equity,'per_share_value':share,
            'terminal_share_of_operating_value':pv_terminal/operating if operating>0 else None}


def value_company(bundle: dict, company: dict, request: ValuationRequest) -> dict:
    """Caller must supply an approved bundle and an accepted invitation."""
    request=ValuationRequest.model_validate(request.model_dump())
    from .research_io import assert_approved_snapshot
    assert_approved_snapshot(bundle)
    analysis=bundle['analysis']; fingerprint=bundle['state']['dataset_fingerprint']
    if company['business_type']!='non_financial':
        raise ValueError('金融企业不适用当前 FCFF 模型，需另选专用估值模型。')
    if (request.company_id!=company['company_id'] or request.company_id!=bundle['state']['company_id']
        or request.dataset_fingerprint!=fingerprint or request.analysis_fingerprint!=digest(analysis)):
        raise ValueError('估值参数属于其他公司或旧版分析，请重新确认。')
    if request.currency!=bundle['currency']:
        raise ValueError('估值参数与历史财报币种不一致，不自动换汇。')
    if request.base_year not in analysis['years']:
        raise ValueError('基准年不属于已审核历史数据。')
    if request.valuation_date.isoformat()!=f"{request.base_year}-{company['fiscal_year_end']}":
        raise ValueError('首版采用完整财年末估值；估值日须等于基准财年末，不隐含处理期间现金流。')
    base=analysis['inputs'][str(request.base_year)]['revenue']
    if base['value'] is None or D(base['value'])<=0:
        raise ValueError('DCF 需要已审核且为正的基准营业收入。')
    results=[]
    with localcontext() as context:
        context.prec=34
        for scenario in request.scenarios:
            discount=calculate_wacc(scenario.discount_rate); wacc=D(discount['wacc'])
            rows=[]; revenue=D(base['value']); nwc=request.initial_operating_nwc
            for period,assumption in enumerate(scenario.forecasts,1):
                revenue*=1+assumption.revenue_growth
                ebit=revenue*assumption.ebit_margin
                tax=max(ebit,D(0))*assumption.cash_tax_rate
                depreciation=revenue*assumption.depreciation_to_revenue
                capex=revenue*assumption.capex_to_revenue
                ending_nwc=revenue*assumption.operating_nwc_to_revenue
                change=ending_nwc-nwc
                fcff=ebit-tax+depreciation-capex-change
                rows.append({'period':period,'year':assumption.year,'revenue':revenue,'ebit':ebit,
                    'cash_tax':tax,'nopat':ebit-tax,'depreciation':depreciation,'capex':capex,
                    'opening_operating_nwc':nwc,'operating_nwc':ending_nwc,'change_in_operating_nwc':change,
                    'fcff':fcff,'discount_factor':1/(1+wacc)**period,'pv_fcff':fcff/(1+wacc)**period})
                nwc=ending_nwc
            values=_present_value(rows,scenario.terminal,wacc,scenario.terminal.growth,request.bridge)
            sensitivity=[]
            for rate in scenario.sensitivity_wacc:
                for growth in scenario.sensitivity_growth:
                    try:
                        cell=_present_value(rows,scenario.terminal,rate,growth,request.bridge)
                        sensitivity.append({'wacc':str(rate),'growth':str(growth),
                            'equity_value':str(cell['equity_value']),
                            'per_share_value':str(cell['per_share_value']) if cell['per_share_value'] is not None else None,'reason':''})
                    except ValueError:
                        sensitivity.append({'wacc':str(rate),'growth':str(growth),'equity_value':None,
                            'per_share_value':None,'reason':'WACC ≤ g 或 g ≥ 终值 ROIC；不计算该组合'})
            observations=[]
            if values['terminal_share_of_operating_value'] is not None:
                observations.append('终值现值占经营资产价值 '+f"{values['terminal_share_of_operating_value']:.2%}"+'；请结合敏感性结果核对长期假设。')
            if any(row['fcff']<0 for row in rows):
                observations.append('存在预测期 FCFF 为负的年度，请核查增长、再投资和营运资本融资需求。')
            if values['per_share_value'] is None:
                observations.append('模型权益残值非正，不输出可解释为交易价格的每股价值。')
            upside=None
            if request.bridge.market_price is not None and values['per_share_value'] is not None:
                upside=values['per_share_value']/request.bridge.market_price-1
                observations.append('每股模型值相对用户提供估值日价格的差异为 '+f'{upside:.2%}'+'；该差异取决于所确认假设，不构成自动买卖结论。')
            results.append({'name':scenario.name,'discount_rate':discount,
                'forecast':[{k:(str(v) if isinstance(v,D) else v) for k,v in row.items()} for row in rows],
                'valuation':{k:(str(v) if v is not None else None) for k,v in values.items()},
                'implied_price_difference':str(upside) if upside is not None else None,
                'sensitivity':sensitivity,'observations':observations})
    positives=[D(s['valuation']['per_share_value']) for s in results if s['valuation']['per_share_value'] is not None]
    conclusions=[]
    if positives:
        conclusions.append('所提交情景的每股模型值范围为 '+str(min(positives))+' 至 '+str(max(positives))+' '+request.currency+'；范围仅覆盖用户选择的情景。')
    ordered={s['name']:D(s['valuation']['equity_value']) for s in results}
    if (('Bear' in ordered and 'Base' in ordered and ordered['Bear']>ordered['Base']) or
        ('Bull' in ordered and 'Base' in ordered and ordered['Bull']<ordered['Base'])):
        conclusions.append('情景结果顺序与 Bear/Base/Bull 名称不一致，请核对增长、再投资和折现参数的组合；程序不自动重排或修改假设。')
    return {'schema_version':'finance-fcff-result-v1','company_id':request.company_id,
        'dataset_fingerprint':fingerprint,'analysis_fingerprint':digest(analysis),
        'assumptions_fingerprint':digest(request),'currency':request.currency,'unit':request.unit,
        'valuation_date':request.valuation_date.isoformat(),'base_year':request.base_year,
        'base_revenue':base,'scenarios':results,'conclusions':conclusions,'formulas':FORMULAS,'method_sources':METHOD_SOURCES,
        'limitations':['完整财年末估值，年末折现；不处理期中现金流或短财年。',
            '负 EBIT 不假定即期抵税或结转亏损；税率作用于正 EBIT。',
            '终值以用户确认的长期利润率、税率及 ROIC 计算再投资，不机械延长最后一年 FCFF。',
            '债务、租赁、受限现金与非经营资产的边界由用户在桥接依据中核实，禁止重复调整。']}
