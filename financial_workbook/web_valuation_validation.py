"""Local, field-addressed valuation feedback; no defaults or approvals.

Ranges below are in the units displayed by the UI (percentage points). The
backend Pydantic models remain authoritative and are checked again on submit.
"""
from __future__ import annotations

from decimal import Decimal,InvalidOperation
import math


MESSAGES={
 'required':('必填：请填写此项。','Required: enter a value.','Обязательно: заполните поле.'),
 'number':('请输入有限数值，不要填写百分号。','Enter a finite number without a percent sign.','Введите конечное число без знака процента.'),
 'positive':('必须大于 0。','Must be greater than 0.','Значение должно быть больше 0.'),
 'nonnegative':('不能小于 0；没有该项时请明确填 0。','Must be at least 0. Enter 0 explicitly when absent.','Значение не может быть отрицательным. При отсутствии укажите 0.'),
 'range':('允许范围：{low} 至 {high}{unit}（含边界）。','Allowed range: {low} to {high}{unit}, inclusive.','Допустимый диапазон: от {low} до {high}{unit}, включая границы.'),
 'open_low':('必须大于 {low}{unit}，且不超过 {high}{unit}。','Must be above {low}{unit} and at most {high}{unit}.','Значение должно быть больше {low}{unit} и не выше {high}{unit}.'),
 'open_high':('必须不小于 {low}{unit}，且小于 {high}{unit}。','Must be at least {low}{unit} and below {high}{unit}.','Значение должно быть не ниже {low}{unit} и меньше {high}{unit}.'),
 'open_both':('必须大于 {low}{unit}，且小于 {high}{unit}。','Must be above {low}{unit} and below {high}{unit}.','Значение должно быть больше {low}{unit} и меньше {high}{unit}.'),
 'years':('必填：预测年数须为 1 至 15 的整数。','Required: forecast years must be an integer from 1 to 15.','Обязательно: горизонт прогноза — целое число от 1 до 15.'),
 'scenario':('必填：请至少选择一个情景。','Required: select at least one scenario.','Обязательно: выберите хотя бы один сценарий.'),
 'wacc_growth':('WACC 必须大于永续增长率。','WACC must exceed perpetual growth.','WACC должна превышать постоянный темп роста.'),
 'roic_growth':('长期 ROIC 必须大于长期增长率。','Long-term ROIC must exceed long-term growth.','Долгосрочная ROIC должна превышать долгосрочный темп роста.'),
 'computed_wacc':('组成项计算出的 WACC 须大于 0 且不超过 100%；请核对组成项。','Component-based WACC must be above 0 and at most 100%. Check its inputs.','WACC по компонентам должна быть больше 0 и не выше 100%. Проверьте исходные данные.'),
 'grid':('请填写 1 至 20 个互不重复的百分数，用逗号分隔。','Enter 1 to 20 distinct percentages, separated by commas.','Введите от 1 до 20 различных процентов через запятую.'),
 'forecast':('请填写第 {year} 年的全部必填预测项。','Complete all required forecast inputs for {year}.','Заполните все обязательные прогнозные параметры за {year} год.'),
}


def message(code,t,**params):
    index={'zh':0,'en':1,'ru':2}.get(getattr(t,'language_token','zh'),0)
    return MESSAGES[code][index].format(**params)


def missing(value):
    return value is None or isinstance(value,float) and math.isnan(value) or isinstance(value,str) and not value.strip()


def _add(issues,key,value):
    if value not in issues.setdefault(key,[]): issues[key].append(value)


def _text(issues,key,value,t):
    if missing(value): _add(issues,key,message('required',t))


def _number(issues,key,value,t,*,low=None,high=None,open_low=False,open_high=False,percent=False):
    if missing(value):
        _add(issues,key,message('required',t)); return None
    try:
        if isinstance(value,bool): raise InvalidOperation
        number=Decimal(str(value).strip())
        if not number.is_finite(): raise InvalidOperation
    except (InvalidOperation,ValueError):
        _add(issues,key,message('number',t)); return None
    invalid=(low is not None and (number<=low if open_low else number<low) or
             high is not None and (number>=high if open_high else number>high))
    if invalid:
        if low==0 and high is None: code='positive' if open_low else 'nonnegative'
        else: code='open_both' if open_low and open_high else 'open_low' if open_low else 'open_high' if open_high else 'range'
        _add(issues,key,message(code,t,low=str(low),high=str(high),unit='%' if percent else ''))
    return number


def _horizon(issues,key,value,t):
    if type(value) is not int or not 1<=value<=15:
        _add(issues,key,message('years',t))


def trial_issues(values,t):
    issues={}
    for key in ('actor','rationale'): _text(issues,key,values.get(key),t)
    _number(issues,'base_fcff',values.get('base_fcff'),t,low=0,open_low=True)
    _number(issues,'growth',values.get('growth'),t,low=-100,high=300,open_low=True,percent=True)
    wacc=_number(issues,'wacc',values.get('wacc'),t,low=0,high=100,open_low=True,percent=True)
    growth=_number(issues,'terminal_growth',values.get('terminal_growth'),t,low=-100,high=100,open_low=True,open_high=True,percent=True)
    _number(issues,'net_debt',values.get('net_debt'),t)
    _number(issues,'shares',values.get('shares'),t,low=0,open_low=True)
    _horizon(issues,'years',values.get('years'),t)
    if wacc is not None and growth is not None and wacc<=growth:
        for key in ('wacc','terminal_growth'): _add(issues,key,message('wacc_growth',t))
    return issues


def _sensitivity(issues,key,value,t,*,wacc=False):
    if missing(value): _add(issues,key,message('required',t)); return
    tokens=str(value).replace('，',',').replace(';',',').split(',')
    if not 1<=len(tokens)<=20:
        _add(issues,key,message('grid',t)); return
    numbers=[_number(issues,key,part,t,low=0,high=100,open_low=wacc,percent=True) for part in tokens]
    if any(number is None for number in numbers) or len(set(numbers))!=len(numbers):
        _add(issues,key,message('grid',t))


def full_issues(values,grids,scenarios,horizon,base_year,t):
    issues={}
    for key in ('actor','nwc_basis','bridge_basis','overall_basis'): _text(issues,key,values.get(key),t)
    _number(issues,'nwc',values.get('nwc'),t)
    for key in ('excess_cash','non_operating_assets','interest_bearing_debt','minority_interest','preferred_equity','other_claims'):
        _number(issues,key,values.get(key),t,low=0)
    _number(issues,'diluted_shares',values.get('diluted_shares'),t,low=0,open_low=True)
    if not missing(values.get('market_price')):
        _number(issues,'market_price',values.get('market_price'),t,low=0,open_low=True)
    if not scenarios: _add(issues,'scenarios',message('scenario',t))
    _horizon(issues,'horizon',horizon,t)
    forecast_limits={'revenue_growth':(-100,300,True,False),'ebit_margin':(-100,100,False,False),
        'cash_tax_rate':(0,100,False,False),'depreciation_to_revenue':(0,100,False,False),
        'capex_to_revenue':(0,500,False,False),'operating_nwc_to_revenue':(-200,200,False,False)}
    for scenario in scenarios:
        prefix=scenario+'_'
        mode=values.get(prefix+'mode','direct')
        _text(issues,prefix+'rate_basis',values.get(prefix+'rate_basis'),t)
        rate_values={}
        if mode=='direct':
            wacc=_number(issues,prefix+'wacc',values.get(prefix+'wacc'),t,low=0,high=100,open_low=True,percent=True)
        else:
            keys=('risk_free_rate','beta','equity_risk_premium','country_risk_premium','pretax_cost_of_debt','debt_tax_rate','market_equity','market_debt')
            for key in keys:
                low=-10 if key=='risk_free_rate' else 0
                high=None if key in ('beta','market_equity','market_debt') else 100
                rate_values[key]=_number(issues,prefix+key,values.get(prefix+key),t,low=low,high=high,
                    open_low=key=='market_equity',percent=high is not None)
            wacc=None
            if all(rate_values[key] is not None and prefix+key not in issues for key in keys) and prefix+'rate_basis' not in issues:
                from .research_models import DiscountRate
                from .valuation import calculate_wacc
                raw={key:(number if key in ('beta','market_equity','market_debt') else number/100) for key,number in rate_values.items()}
                try:
                    calculated=calculate_wacc(DiscountRate(mode='components',rationale=values[prefix+'rate_basis'],**raw))
                    wacc=Decimal(calculated['wacc'])*100
                except ValueError: _add(issues,prefix+'rate_basis',message('computed_wacc',t))
        growth=_number(issues,prefix+'terminal_growth',values.get(prefix+'terminal_growth'),t,low=0,high=100,open_high=True,percent=True)
        _number(issues,prefix+'terminal_ebit_margin',values.get(prefix+'terminal_ebit_margin'),t,low=0,high=100,open_low=True,percent=True)
        _number(issues,prefix+'terminal_cash_tax_rate',values.get(prefix+'terminal_cash_tax_rate'),t,low=0,high=100,open_high=True,percent=True)
        roic=_number(issues,prefix+'terminal_return_on_invested_capital',values.get(prefix+'terminal_return_on_invested_capital'),t,low=0,open_low=True,percent=True)
        _text(issues,prefix+'terminal_basis',values.get(prefix+'terminal_basis'),t)
        if growth is not None and wacc is not None and wacc<=growth:
            _add(issues,prefix+('wacc' if mode=='direct' else 'rate_basis'),message('wacc_growth',t))
            _add(issues,prefix+'terminal_growth',message('wacc_growth',t))
        if growth is not None and roic is not None and growth>=roic:
            for key in ('terminal_growth','terminal_return_on_invested_capital'):
                _add(issues,prefix+key,message('roic_growth',t))
        _sensitivity(issues,prefix+'sensitivity_wacc',values.get(prefix+'sensitivity_wacc'),t,wacc=True)
        _sensitivity(issues,prefix+'sensitivity_growth',values.get(prefix+'sensitivity_growth'),t)
        grid=grids.get(scenario,[])
        rows=grid.to_dict('records') if hasattr(grid,'to_dict') else grid
        if type(horizon) is int and len(rows)!=horizon:
            _add(issues,prefix+'forecast',message('forecast',t,year=base_year+1))
        for index,row in enumerate(rows):
            year=row.get('year',base_year+index+1); cell_issues={}
            for key,(low,high,open_low,open_high) in forecast_limits.items():
                _number(cell_issues,key,row.get(key),t,low=low,high=high,open_low=open_low,open_high=open_high,percent=True)
            _text(cell_issues,'rationale',row.get('rationale'),t)
            for key,messages in cell_issues.items():
                for note in messages: _add(issues,prefix+'forecast',f"{year} · {t(key)}: {note}")
    return issues
