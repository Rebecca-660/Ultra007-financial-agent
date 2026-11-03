"""Explicit simplified FCFF-growth trial, separate from operating-driver DCF."""
from datetime import date
from decimal import Decimal,localcontext

from pydantic import Field,StrictBool,model_validator

from .models import StrictModel,digest
from .research_models import Text

D=Decimal


class TrialRequest(StrictModel):
    company_id: Text
    dataset_fingerprint: Text
    analysis_fingerprint: Text
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    unit: str = Field(pattern=r'^currency_base_unit$')
    base_year: int = Field(ge=1900,le=2200)
    valuation_date: date
    base_fcff: Decimal = Field(gt=0)
    growth: Decimal = Field(gt=-1,le=3)
    wacc: Decimal = Field(gt=0,le=1)
    terminal_growth: Decimal = Field(gt=-1,lt=1)
    years: int = Field(ge=1,le=15,strict=True)
    net_debt: Decimal
    shares: Decimal = Field(gt=0)
    confirmed: StrictBool
    confirmed_by: Text
    rationale: Text

    @model_validator(mode='after')
    def confirmed_valid(self):
        if self.confirmed is not True: raise ValueError('简易试算参数须由用户明确确认。')
        if self.wacc<=self.terminal_growth: raise ValueError('WACC 必须大于长期增长率。')
        return self


def calculate_trial(bundle:dict,company:dict,request:TrialRequest)->dict:
    from .research_io import assert_approved_snapshot
    assert_approved_snapshot(bundle)
    if company['business_type']!='non_financial': raise ValueError('金融企业不适用当前 FCFF 试算。')
    if (request.company_id!=company['company_id'] or request.company_id!=bundle['state']['company_id']
        or request.dataset_fingerprint!=bundle['state']['dataset_fingerprint']
        or request.analysis_fingerprint!=digest(bundle['analysis']) or request.currency!=bundle['currency']):
        raise ValueError('简易试算参数与公司或历史版本不一致。')
    if request.base_year not in bundle['analysis']['years'] or request.valuation_date.isoformat()!=f"{request.base_year}-{company['fiscal_year_end']}":
        raise ValueError('简易试算使用已分析基准年的完整财年末。')
    with localcontext() as context:
        context.prec=34
        forecasts=[{'year':request.base_year+t,'period':t,'fcff':request.base_fcff*(1+request.growth)**t} for t in range(1,request.years+1)]
        def point(wacc,growth):
            if not 0<wacc<=1 or not -1<growth<wacc:
                return None
            tv=forecasts[-1]['fcff']*(1+growth)/(wacc-growth)
            pvtv=tv/(1+wacc)**request.years
            operating=sum((r['fcff']/(1+wacc)**r['period'] for r in forecasts),D(0))+pvtv
            equity=operating-request.net_debt
            return {'terminal_value':tv,'pv_terminal_value':pvtv,'operating_value':operating,'equity_value':equity,
                    'per_share_value':equity/request.shares if equity>0 else None}
        result=point(request.wacc,request.terminal_growth)
        sensitivity=[]
        for rate in [request.wacc-D('.01'),request.wacc,request.wacc+D('.01')]:
            for growth in [request.terminal_growth-D('.005'),request.terminal_growth,request.terminal_growth+D('.005')]:
                cell=point(rate,growth)
                sensitivity.append({'wacc':str(rate),'growth':str(growth),
                    **({k:str(cell[k]) if cell[k] is not None else None for k in ('operating_value','equity_value','per_share_value')} if cell else
                       {'operating_value':None,'equity_value':None,'per_share_value':None}),
                    'reason':'' if cell else 'WACC 或长期增长率组合无效'})
        return {'schema_version':'finance-fcff-growth-trial-v1','model':'fcff_growth_trial',
            'company_id':request.company_id,'dataset_fingerprint':request.dataset_fingerprint,
            'analysis_fingerprint':request.analysis_fingerprint,'assumptions_fingerprint':digest(request),
            'currency':request.currency,'valuation_date':request.valuation_date.isoformat(),'base_year':request.base_year,
            **{k:str(v) if v is not None else None for k,v in result.items()},
            'forecasts':[{'year':r['year'],'fcff':str(r['fcff']),'pv':str(r['fcff']/(1+request.wacc)**r['period'])} for r in forecasts],
            'sensitivity':sensitivity,'formulas':{'forecast':'base_fcff * (1+growth)^t',
                'terminal_value':'FCFF_N*(1+terminal_growth)/(WACC-terminal_growth)',
                'operating_value':'sum(FCFF_t/(1+WACC)^t)+TV_N/(1+WACC)^N',
                'equity_value':'operating_value-net_debt','per_share_value':'positive equity_value/shares'},
            'limitations':['简易试算模型：基期 FCFF 与其增长由用户核实和确认，不从历史简化 FCF 自动代入。',
                '本模型不单独预测 EBIT、税、再投资或营运资本，不能冒称完整经营驱动 DCF。',
                '净债务口径和股数由用户确认；结果为该模型和所填假设下的条件性试算。']}


def export_trial(result:dict,assumptions:dict,path):
    from .research_export import _workbook,_sheet
    book,fmt=_workbook(path)
    try:
        _sheet(book,fmt,'简易试算结果',['项目','值'],[[k,D(result[k]) if result[k] is not None else None]
            for k in ('operating_value','equity_value','per_share_value','terminal_value','pv_terminal_value')])
        _sheet(book,fmt,'现金流与现值',['年度','FCFF','现值'],[[r['year'],D(r['fcff']),D(r['pv'])] for r in result['forecasts']])
        _sheet(book,fmt,'敏感性',['WACC','长期增长率','经营资产价值','权益价值','每股模型值','原因'],
            [[D(r['wacc']),D(r['growth']),D(r['operating_value']) if r['operating_value'] is not None else None,
              D(r['equity_value']) if r['equity_value'] is not None else None,
              D(r['per_share_value']) if r['per_share_value'] is not None else None,r['reason']] for r in result['sensitivity']])
        _sheet(book,fmt,'确认参数',['字段','值'],list(assumptions.items()))
        _sheet(book,fmt,'模型与口径',['项目','说明'],list(result['formulas'].items())+[['适用限制',s] for s in result['limitations']])
    finally: book.close()
