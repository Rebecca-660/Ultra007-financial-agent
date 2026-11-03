"""Versioned inputs for company research; financial assumptions have no defaults."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, get_args

from pydantic import Field, StrictBool, model_validator

from .models import StrictModel, Review

Text = Annotated[str, Field(min_length=1, pattern=r'.*\S.*')]
Rate = Annotated[Decimal, Field(ge=0, le=1)]
Positive = Annotated[Decimal, Field(gt=0)]
Nonnegative = Annotated[Decimal, Field(ge=0)]
ReportingCurrency = Literal['CNY','USD','HKD','EUR','GBP','JPY','AUD','CAD','CHF','SGD',
    'NZD','KRW','INR','TWD','MOP','MYR','IDR','THB','VND','PHP','AED','SAR','ZAR',
    'BRL','MXN','RUB','SEK','NOK','DKK','PLN','TRY','ILS']
REPORTING_CURRENCIES = get_args(ReportingCurrency)


class Company(StrictModel):
    company_id: Text
    name: Text
    industry: Text
    business_type: Literal['non_financial', 'financial']
    accounting_standard: Text
    fiscal_year_end: str = Field(pattern=r'^\d{2}-\d{2}$')
    comparability_confirmed: StrictBool
    parser_profile: str | None = None
    display_names: dict[Literal['EN','RU'], Text] = Field(default_factory=dict)

    @model_validator(mode='after')
    def valid_metadata(self):
        if self.company_id.strip() != self.company_id or any(c in self.company_id for c in '/\\:'):
            raise ValueError('company_id 不允许路径字符或首尾空白。')
        date.fromisoformat('2000-' + self.fiscal_year_end)
        if not self.comparability_confirmed:
            raise ValueError('请由用户确认公司、会计准则和完整财年口径。')
        return self


class ReportInput(StrictModel):
    company_id: Text
    report_year: int = Field(ge=1900, le=2200)
    file_name: Text
    reporting_currency: ReportingCurrency | None = None


class ResearchManifest(StrictModel):
    schema_version: Literal['finance-research-input-v1'] = 'finance-research-input-v1'
    confirmed_by: Text
    companies: list[Company] = Field(min_length=1)
    reports: list[ReportInput] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_scope(self):
        ids=[c.company_id for c in self.companies]
        if len(set(ids)) != len(ids):
            raise ValueError('公司标识不能重复。')
        if set(ids) != {r.company_id for r in self.reports}:
            raise ValueError('每份报告必须属于已列出的公司，每家公司至少有一份报告。')
        keys=[(r.company_id,r.report_year) for r in self.reports]
        if len(keys) != len(set(keys)):
            raise ValueError('同公司同年度请只选一个主年报版本。')
        return self


class HumanReview(StrictModel):
    """The attestation is submitted by the human caller, never by an Agent."""
    schema_version: Literal['finance-human-review-v1'] = 'finance-human-review-v1'
    confirmed_by: Text
    source_checked: StrictBool
    statement: Text
    review: Review

    @model_validator(mode='after')
    def human_confirmed(self):
        if self.source_checked is not True:
            raise ValueError('需要用户明确确认已核对来源。')
        return self


class DiscountRate(StrictModel):
    mode: Literal['direct', 'components']
    wacc: Positive | None = None
    risk_free_rate: Decimal | None = None
    beta: Nonnegative | None = None
    equity_risk_premium: Rate | None = None
    country_risk_premium: Rate | None = None
    pretax_cost_of_debt: Rate | None = None
    debt_tax_rate: Rate | None = None
    market_equity: Positive | None = None
    market_debt: Nonnegative | None = None
    rationale: Text

    @model_validator(mode='after')
    def valid_inputs(self):
        fields=('risk_free_rate','beta','equity_risk_premium','country_risk_premium',
                'pretax_cost_of_debt','debt_tax_rate','market_equity','market_debt')
        if self.mode=='direct':
            if self.wacc is None or self.wacc>1 or any(getattr(self,k) is not None for k in fields):
                raise ValueError('直接 WACC 需在 (0,1] 内，不混入组成项。')
        elif self.wacc is not None or any(getattr(self,k) is None for k in fields):
            raise ValueError('组成项模式需填写全部组成项，且不另外填写 WACC。')
        if self.risk_free_rate is not None and not Decimal('-.1') <= self.risk_free_rate <= 1:
            raise ValueError('无风险利率需以小数填写。')
        return self


class ForecastYear(StrictModel):
    year: int = Field(ge=1901, le=2215)
    revenue_growth: Decimal = Field(gt=-1, le=3)
    ebit_margin: Decimal = Field(ge=-1, le=1)
    cash_tax_rate: Rate
    depreciation_to_revenue: Rate
    capex_to_revenue: Decimal = Field(ge=0, le=5)
    operating_nwc_to_revenue: Decimal = Field(ge=-2, le=2)
    rationale: Text


class TerminalAssumptions(StrictModel):
    growth: Decimal = Field(ge=0, lt=1)
    ebit_margin: Decimal = Field(gt=0, le=1)
    cash_tax_rate: Decimal = Field(ge=0, lt=1)
    return_on_invested_capital: Positive
    rationale: Text

    @model_validator(mode='after')
    def reinvestment_possible(self):
        if self.growth >= self.return_on_invested_capital:
            raise ValueError('终值增长率须小于终值 ROIC，避免不可持续的再投资假设。')
        return self


class Scenario(StrictModel):
    name: Literal['Base','Bear','Bull']
    discount_rate: DiscountRate
    forecasts: list[ForecastYear] = Field(min_length=1, max_length=15)
    terminal: TerminalAssumptions
    sensitivity_wacc: list[Positive] = Field(min_length=1, max_length=20)
    sensitivity_growth: list[Rate] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def continuous_years(self):
        years=[x.year for x in self.forecasts]
        if years != list(range(years[0],years[0]+len(years))):
            raise ValueError('预测年度必须连续且递增。')
        if any(x>1 for x in self.sensitivity_wacc):
            raise ValueError('敏感性 WACC 需以小数填写且不超过 1。')
        if len(set(self.sensitivity_wacc))!=len(self.sensitivity_wacc) or len(set(self.sensitivity_growth))!=len(self.sensitivity_growth):
            raise ValueError('敏感性参数不能重复。')
        return self


class EquityBridge(StrictModel):
    as_of: date
    excess_cash: Nonnegative
    non_operating_assets: Nonnegative
    interest_bearing_debt: Nonnegative
    minority_interest: Nonnegative
    preferred_equity: Nonnegative
    other_claims: Nonnegative
    diluted_shares: Positive
    market_price: Positive | None = None
    rationale: Text


class ValuationRequest(StrictModel):
    schema_version: Literal['finance-fcff-assumptions-v1'] = 'finance-fcff-assumptions-v1'
    company_id: Text
    dataset_fingerprint: Text
    analysis_fingerprint: Text
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    unit: Literal['currency_base_unit']
    base_year: int = Field(ge=1900, le=2200)
    valuation_date: date
    initial_operating_nwc: Decimal
    initial_operating_nwc_evidence: Text
    scenarios: list[Scenario] = Field(min_length=1, max_length=3)
    bridge: EquityBridge
    confirmed: StrictBool
    confirmed_by: Text
    rationale: Text

    @model_validator(mode='after')
    def valid_scope(self):
        if self.confirmed is not True:
            raise ValueError('估值参数须由用户明确确认。')
        if len({s.name for s in self.scenarios}) != len(self.scenarios):
            raise ValueError('情景名称不能重复。')
        horizons={len(s.forecasts) for s in self.scenarios}
        if len(horizons)!=1 or any(s.forecasts[0].year != self.base_year+1 for s in self.scenarios):
            raise ValueError('各情景应从基准年下一年开始，且采用相同预测期间。')
        if self.bridge.as_of != self.valuation_date:
            raise ValueError('权益桥接输入和参考股价须对应估值日。')
        return self
