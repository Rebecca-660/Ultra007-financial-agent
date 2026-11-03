"""Ultra 007 valuation UI; human judgment stays in explicit, versioned inputs.

The page only calls deterministic valuation services. Opening a page, switching
themes/languages, and editing a draft never invoke an LLM or confirm parameters.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import uuid

import altair as alt
import pandas as pd
from pydantic import ValidationError
import streamlit as st

from .models import digest
from .research import ResearchWorkflow
from .research_io import load_project, read_json
from .research_models import ValuationRequest
from .service import _inside, _write_json
from .web_valuation_validation import trial_issues,full_issues,missing


COPY={
 'title':('你的假设，透明的估值。','Your assumptions. Transparent valuation.','Ваши допущения. Прозрачная оценка.'),
 'intro':('预测和折现参数由你确认，代码负责计算并保留依据。','Confirm the forecasts and discount inputs; code calculates and preserves their basis.','Подтвердите прогноз и ставку дисконтирования; код выполнит расчет и сохранит основания.'),
 'choice':('历史分析已完成，是否继续估值？','Historical analysis is ready. Continue to valuation?','Исторический анализ готов. Продолжить оценку?'),
 'actor':('判断与参数确认人','Decision maker and parameter owner','Автор решения и допущений'),
 'proceed':('继续，填写估值参数','Continue to valuation inputs','Продолжить и задать параметры'),
 'stop':('本次只看历史分析','Finish with historical analysis','Завершить историческим анализом'),
 'stopped':('本次已选择结束，历史分析仍可查看和下载。','This analysis ended without valuation. Historical results remain available.','Оценка не выполняется. Исторические результаты доступны.'),
 'actor_required':('请填写判断人，再选择继续或结束。','Enter the decision maker before choosing.','Укажите автора решения перед выбором.'),
 'financial':('当前 FCFF 模型适用于非金融企业；本公司可继续查看历史分析。','The current FCFF model supports non-financial companies. Historical analysis remains available.','Модель FCFF предназначена для нефинансовых компаний. Исторический анализ доступен.'),
 'base':('基准与估值日期','Base year and valuation date','Базовый год и дата оценки'),
 'year':('基准年度','Base fiscal year','Базовый финансовый год'),
 'valuation_date':('估值日','Valuation date','Дата оценки'),
 'year_end':('本模型使用完整财年末估值和年末折现；桥接输入也应对应该日期。','This model values at fiscal year-end with year-end discounting. Bridge inputs must use the same date.','Модель использует конец финансового года и дисконтирование на конец года. Данные перехода к капиталу должны соответствовать этой дате.'),
 'units':('金额均填原币基本单位，股数填“股”；百分比输入 5 表示 5%。没有的项目请明确填 0。','Money uses currency base units and shares use individual shares. Enter 5 for 5%. Enter 0 explicitly for absent items.','Суммы в базовых денежных единицах, количество акций в штуках. Введите 5 для 5%. Отсутствующие суммы укажите как 0.'),
 'nwc':('基准经营性非现金营运资本','Base operating non-cash working capital','Базовый операционный неденежный оборотный капитал'),
 'nwc_basis':('营运资本的来源及组成依据','Working-capital source and components','Источник и состав оборотного капитала'),
 'bridge':('从经营资产价值到普通股权益','Bridge from operating value to common equity','Переход от стоимости операций к обычному капиталу'),
 'excess_cash':('超额或非经营现金','Excess or non-operating cash','Избыточные или неоперационные денежные средства'),
 'non_operating_assets':('其他非经营资产价值','Other non-operating assets','Прочие неоперационные активы'),
 'interest_bearing_debt':('有息债务价值','Interest-bearing debt value','Стоимость процентного долга'),
 'minority_interest':('少数股东权益价值','Non-controlling interest value','Неконтролирующая доля'),
 'preferred_equity':('优先股价值','Preferred equity value','Привилегированный капитал'),
 'other_claims':('其他需扣除的请求权','Other claims to deduct','Прочие вычитаемые требования'),
 'diluted_shares':('稀释股数','Diluted shares outstanding','Количество разводненных акций'),
 'market_price':('估值日参考股价','Reference share price','Цена акции на дату оценки'),
 'bridge_basis':('桥接来源与口径 说明租赁、受限现金及避免重复计入','Bridge sources and scope Explain leases, restricted cash and double-counting controls','Источники перехода Укажите аренду, ограниченные денежные средства и исключение двойного учета'),
 'forecast':('经营预测与情景','Operating forecasts and scenarios','Операционный прогноз и сценарии'),
 'scenarios':('选择情景','Select scenarios','Выберите сценарии'),
 'horizon':('预测年数','Forecast years','Горизонт прогноза в годах'),
 'discount':('折现率与依据','Discount rate and basis','Ставка дисконтирования и основания'),
 'direct':('直接填写 WACC','Enter WACC directly','Задать WACC напрямую'),
 'components':('根据组成项计算 WACC','Calculate WACC from components','Рассчитать WACC по компонентам'),
 'risk_free_rate':('无风险利率','Risk-free rate','Безрисковая ставка'),
 'beta':('杠杆 Beta','Levered beta','Бета с учетом долга'),
 'equity_risk_premium':('股权风险溢价','Equity risk premium','Премия за риск акций'),
 'country_risk_premium':('额外国家风险溢价','Additional country risk premium','Дополнительная страновая премия'),
 'pretax_cost_of_debt':('税前债务成本','Pretax cost of debt','Стоимость долга до налога'),
 'debt_tax_rate':('利息税盾税率','Interest tax-shield rate','Налоговая ставка для процентного щита'),
 'market_equity':('权益市场价值','Market value of equity','Рыночная стоимость капитала'),
 'market_debt':('债务市场价值','Market value of debt','Рыночная стоимость долга'),
 'rate_basis':('折现参数的来源、日期与判断依据','Discount-input sources, dates and rationale','Источники, даты и основания ставки'),
 'year_column':('年度','Year','Год'),
 'revenue_growth':('收入增长率 %','Revenue growth %','Рост выручки %'),
 'ebit_margin':('EBIT 利润率 %','EBIT margin %','Маржа EBIT %'),
 'cash_tax_rate':('现金税率 %','Cash tax rate %','Ставка денежного налога %'),
 'depreciation_to_revenue':('折旧摊销/收入 %','D&A / revenue %','Амортизация / выручка %'),
 'capex_to_revenue':('资本支出/收入 %','Capex / revenue %','Капзатраты / выручка %'),
 'operating_nwc_to_revenue':('经营 NWC/收入 %','Operating NWC / revenue %','Операционный оборотный капитал / выручка %'),
 'rationale':('判断依据','Rationale','Основания'),
 'terminal':('终值假设','Terminal assumptions','Допущения терминальной стоимости'),
 'growth':('长期增长率','Long-term growth rate','Долгосрочный темп роста'),
 'return_on_invested_capital':('长期 ROIC','Long-term ROIC','Долгосрочная ROIC'),
 'terminal_basis':('长期增长、盈利与再投资的依据','Long-term growth, profitability and reinvestment rationale','Основания долгосрочного роста, рентабельности и реинвестиций'),
 'sensitivity':('敏感性分析','Sensitivity analysis','Анализ чувствительности'),
 'sensitivity_wacc':('WACC 网格 % 用逗号分隔','WACC grid % Comma-separated','Сетка WACC % Через запятую'),
 'sensitivity_growth':('长期增长率网格 % 用逗号分隔','Growth grid % Comma-separated','Сетка долгосрочного роста % Через запятую'),
 'overall_basis':('整体假设与适用边界','Overall rationale and applicability','Общие основания и применимость'),
 'confirmation':('我已核对当前全部估值参数，并确认用这些参数计算。','I have checked all current valuation inputs and confirm this calculation.','Я проверил все текущие параметры и подтверждаю расчет.'),
 'calculate':('确认参数并计算 DCF','Confirm inputs and calculate DCF','Подтвердить и рассчитать DCF'),
 'draft':('输入变化会清除本次确认；完整参数草稿会保存到当前研究任务。','Changing inputs clears confirmation. The draft is saved in this research project.','Изменение параметров сбрасывает подтверждение. Черновик сохраняется в проекте.'),
 'changed':('参数已变化，旧结果不代表当前输入。请重新确认并计算。','Inputs changed. The previous result does not represent this draft. Confirm and recalculate.','Параметры изменены. Предыдущий результат не соответствует черновику. Подтвердите и пересчитайте.'),
 'result':('估值结果','Valuation results','Результаты оценки'),
 'scenario_result':('查看情景','Result scenario','Сценарий результата'),
 'operating_value':('经营资产价值','Operating asset value','Стоимость операционных активов'),
 'equity_value':('普通股权益价值','Common equity value','Стоимость обычного капитала'),
 'per_share_value':('每股模型价值','Model value per share','Модельная стоимость акции'),
 'forecast_detail':('预测现金流与现值','Forecast cash flows and present values','Прогноз денежных потоков и приведенная стоимость'),
 'heatmap_value':('敏感性显示值','Sensitivity value','Показатель чувствительности'),
 'download':('下载 DCF Excel','Download DCF Excel','Скачать DCF Excel'),
 'parameters':('下载本次确认参数','Download confirmed inputs','Скачать подтвержденные параметры'),
 'history':('已保存的估值版本','Saved valuation versions','Сохраненные версии оценки'),
 'history_note':('历史版本按各自确认参数计算，不随当前草稿变化。','Historical versions retain their own confirmed inputs.','Исторические версии сохраняют свои подтвержденные параметры.'),
 'select_version':('查看历史版本','Select saved version','Выбрать сохраненную версию'),
 'error':('估值未完成，请核对必填参数、数值范围和当前任务状态。','Valuation did not complete. Check required inputs, numeric ranges and task status.','Расчет не завершен. Проверьте обязательные параметры, диапазоны и состояние задачи.'),
 'bad_numbers':('请填写有限数值；比率输入不需要百分号。','Enter finite numbers without percent signs.','Введите конечные числа без знака процента.'),
 'no_scenario':('请至少选择一个情景。','Select at least one scenario.','Выберите хотя бы один сценарий.'),
 'method':('计算方法与定义','Method and definitions','Метод и определения'),
 'computed':('已按你确认的参数完成计算并保存。','Calculated and saved using your confirmed inputs.','Расчет выполнен и сохранен по подтвержденным параметрам.'),
}
COPY.update({
 'model':('估值方式','Valuation model','Модель оценки'),
 'full':('完整经营预测模型','Full operating-driver model','Полная операционная модель'),
 'trial':('简易 FCFF 增长试算','Simplified FCFF growth trial','Упрощенный расчет роста FCFF'),
 'trial_note':('简易试算由你提供已核实的基期 FCFF，假设其按固定增长率延续；不替代完整经营预测。','Supply verified base FCFF and assume constant growth. This trial is separate from the full operating forecast.','Укажите проверенный базовый FCFF и постоянный рост. Этот расчет отделен от полной операционной модели.'),
 'base_fcff':('已核实的基期 FCFF','Verified base FCFF','Проверенный базовый FCFF'),
 'net_debt':('净债务 有息债务减可调整现金','Net debt Debt less eligible cash','Чистый долг Долг минус допустимые денежные средства'),
 'shares':('稀释股数 股','Diluted shares Individual shares','Количество разводненных акций Штуки'),
 'trial_growth':('预测期 FCFF 增长率','Forecast FCFF growth','Прогноз роста FCFF'),
 'terminal_growth':('永续增长率','Perpetual growth','Постоянный темп роста'),
 'trial_calculate':('确认参数并计算简易试算','Confirm and calculate trial','Подтвердить и выполнить упрощенный расчет'),
 'horizon_required':('请先填写预测年数，再逐年输入经营假设。','Enter the forecast horizon before adding annual operating assumptions.','Укажите горизонт прогноза, затем задайте годовые операционные допущения.'),
 'year_required':('请选择基准年度。','Select a base fiscal year.','Выберите базовый финансовый год.'),
 'required':('必填','Required','Обязательно'),
 'optional':('选填','Optional','Необязательно'),
 'field_legend':('标有“必填”的项目必须填写；没有的金额请明确填 0。参考股价为选填。红字会指出缺少或无效的项目。','Fields marked Required must be filled; enter 0 explicitly for absent amounts. Reference share price is optional. Red messages identify missing or invalid inputs.','Заполните поля «Обязательно»; отсутствующие суммы укажите как 0. Цена акции необязательна. Красные сообщения указывают на пропуски и ошибки.'),
 'trial_legend':('简易试算中的数值、确认人和整体假设说明均为必填；没有净债务可明确填 0。','All trial amounts, the parameter owner and overall rationale are required. Enter 0 explicitly when there is no net debt.','Все параметры упрощенного расчета, автор и общие основания обязательны. При отсутствии чистого долга укажите 0.'),
 'required_hint':('必填：请填写此项。','Required: enter a value.','Обязательно: заполните поле.'),
 'example_rationale':('例如：仅用于功能测试，参数为假设值。','Example: for functional testing only; inputs are hypothetical.','Например: только для проверки функции; параметры условные.'),
 'issues_title':('请先修正以下 {count} 个位置，再确认并计算：','Correct the following {count} input sections, then confirm and calculate:','Исправьте следующие поля ({count}), затем подтвердите и рассчитайте:'),
 'input_error':('请核对该项的格式、取值范围及关联参数。','Check this input’s format, range and related assumptions.','Проверьте формат, диапазон и связанные допущения.'),
 'state_error':('计算未完成：当前分析版本、估值选择或文件状态不一致。请刷新项目后重试；参数仍需重新确认。','Calculation did not complete because the analysis version, valuation choice or files no longer match. Refresh the project and confirm inputs again.','Расчет не завершен: версия анализа, выбор оценки или файлы не совпадают. Обновите проект и повторно подтвердите параметры.'),
 'save_error':('草稿暂未保存，请检查项目文件夹是否可写。','The draft could not be saved. Check that the project folder is writable.','Не удалось сохранить черновик. Проверьте доступ на запись к папке проекта.'),
 'forecast_required':('每个预测年度的增长、利润率、税率、再投资假设和判断依据均为必填。下方红字按年度和列指出遗漏。','Every forecast year requires growth, margins, tax, reinvestment assumptions and a rationale. Red messages below identify the year and column.','Для каждого года обязательны рост, маржа, налог, допущения о реинвестициях и основания. Красные сообщения указывают год и столбец.'),
 'Base':('基准（Base）','Base','Базовый'),
 'Bear':('悲观（Bear）','Bear','Пессимистичный'),
 'Bull':('乐观（Bull）','Bull','Оптимистичный'),
 'revenue':('营业收入','Revenue','Выручка'),
 'ebit':('EBIT','EBIT','EBIT'),
 'fcff':('FCFF','FCFF','FCFF'),
 'pv_fcff':('FCFF 现值','Present value of FCFF','Приведенная стоимость FCFF'),
 'value':('数值','Value','Значение'),
 'reason':('原因','Reason','Причина'),
 'invalid_trial_grid':('WACC 或长期增长率组合无效','Invalid WACC / perpetual-growth combination','Недопустимое сочетание WACC и постоянного роста'),
 'invalid_full_grid':('WACC ≤ g 或 g ≥ 终值 ROIC；不计算该组合','WACC ≤ g or g ≥ terminal ROIC; this combination is not calculated','WACC ≤ g или g ≥ терминальной ROIC; сочетание не рассчитывается'),
 'nonpositive_equity':('权益残值不为正，因此不显示可解释为交易价格的每股价值；计算本身已完成。','Residual equity is not positive, so no per-share value interpretable as a trading price is shown. The calculation has completed.','Остаточная стоимость капитала неположительна: цена акции, интерпретируемая как торговая, не выводится. Сам расчет завершен.'),
 'trial_limit_base':('简易试算模型：基期 FCFF 与其增长由用户核实和确认，不从历史简化 FCF 自动代入。','Trial model: the user verifies base FCFF and growth; historical simplified FCF is not substituted automatically.','Упрощенная модель: пользователь подтверждает базовый FCFF и рост; исторический упрощенный FCF не подставляется автоматически.'),
 'trial_limit_operating':('本模型不单独预测 EBIT、税、再投资或营运资本，不能冒称完整经营驱动 DCF。','This model does not forecast EBIT, tax, reinvestment or working capital separately; it is not a full operating-driver DCF.','Модель не прогнозирует EBIT, налог, реинвестиции и оборотный капитал отдельно и не является полной операционной DCF.'),
 'trial_limit_scope':('净债务口径和股数由用户确认；结果为该模型和所填假设下的条件性试算。','The user confirms net-debt scope and share count. Results are conditional on this model and the supplied assumptions.','Пользователь подтверждает состав чистого долга и количество акций. Результат зависит от модели и заданных допущений.'),
 'full_limit_timing':('完整财年末估值，年末折现；不处理期中现金流或短财年。','Fiscal year-end valuation and year-end discounting; interim cash flows and short fiscal years are not modeled.','Оценка и дисконтирование на конец финансового года; промежуточные потоки и короткие годы не моделируются.'),
 'full_limit_tax':('负 EBIT 不假定即期抵税或结转亏损；税率作用于正 EBIT。','Negative EBIT does not create assumed immediate tax credits or loss carryforwards; tax applies to positive EBIT.','Отрицательная EBIT не создает предполагаемую немедленную налоговую выгоду или перенос убытков; налог применяется к положительной EBIT.'),
 'full_limit_terminal':('终值以用户确认的长期利润率、税率及 ROIC 计算再投资，不机械延长最后一年 FCFF。','Terminal reinvestment uses confirmed long-term margins, tax and ROIC, rather than mechanically extending the final forecast FCFF.','Терминальные реинвестиции рассчитываются по подтвержденным марже, налогу и ROIC, а не простым продлением последнего FCFF.'),
 'full_limit_bridge':('债务、租赁、受限现金与非经营资产的边界由用户在桥接依据中核实，禁止重复调整。','The user verifies debt, leases, restricted cash and non-operating assets in the bridge rationale to avoid double counting.','Пользователь уточняет долг, аренду, ограниченные средства и неоперационные активы в обосновании перехода, исключая двойной учет.'),
 'observation_negative_fcff':('存在预测期 FCFF 为负的年度，请核查增长、再投资和营运资本融资需求。','Some forecast years have negative FCFF. Check growth, reinvestment and working-capital funding needs.','В отдельные прогнозные годы FCFF отрицателен. Проверьте рост, реинвестиции и потребность в финансировании оборотного капитала.'),
 'observation_equity':('模型权益残值非正，不输出可解释为交易价格的每股价值。','Residual model equity is not positive; no per-share value interpretable as a trading price is produced.','Остаточная стоимость капитала модели неположительна; интерпретируемая как торговая цена акции не выводится.'),
 'observation_terminal':('终值现值占经营资产价值 {value}；请结合敏感性结果核对长期假设。','Present value of the terminal value is {value} of operating value. Review long-term assumptions alongside sensitivity results.','Приведенная терминальная стоимость составляет {value} стоимости операций. Проверьте долгосрочные допущения с учетом чувствительности.'),
 'observation_price':('每股模型值相对用户提供估值日价格的差异为 {value}；该差异取决于所确认假设，不构成自动买卖结论。','Model value per share differs from the supplied valuation-date price by {value}. This depends on confirmed assumptions and is not an automatic trading conclusion.','Модельная стоимость акции отличается от заданной цены на дату оценки на {value}. Разница зависит от подтвержденных допущений и не является автоматическим торговым выводом.'),
 'conclusion_range':('所提交情景的每股模型值范围为 {low} 至 {high} {currency}；范围仅覆盖用户选择的情景。','Submitted scenarios give per-share model values from {low} to {high} {currency}. The range covers only selected scenarios.','Заданные сценарии дают модельную стоимость акции от {low} до {high} {currency}. Диапазон охватывает только выбранные сценарии.'),
 'conclusion_order':('情景结果顺序与 Bear/Base/Bull 名称不一致，请核对增长、再投资和折现参数的组合；程序不自动重排或修改假设。','Scenario results do not follow the Bear/Base/Bull ordering. Check growth, reinvestment and discount inputs; the program does not reorder or alter assumptions.','Результаты не соответствуют порядку Bear/Base/Bull. Проверьте рост, реинвестиции и дисконтирование; программа не меняет порядок и допущения.'),
})

FORECAST_KEYS=('revenue_growth','ebit_margin','cash_tax_rate','depreciation_to_revenue',
               'capex_to_revenue','operating_nwc_to_revenue')
BRIDGE_KEYS=('excess_cash','non_operating_assets','interest_bearing_debt','minority_interest',
             'preferred_equity','other_claims','diluted_shares','market_price')


def language_token(language):
    return 'en' if language in ('EN','English','en') else 'ru' if language in ('RU','Русский','ru') else 'zh'


def translator(language):
    token=language_token(language); index={'zh':0,'en':1,'ru':2}[token]
    def translate(key): return COPY[key][index] if key in COPY else key
    translate.language_token=token
    return translate


def field_label(label,t,*,optional=False):
    return label+' ('+t('optional' if optional else 'required')+')'


def mark_touched(scope,name):
    key=scope+'_touched'
    st.session_state[key]=sorted(set(st.session_state.get(key,[]))|{name})


def visible_issues(issues,scope):
    if st.session_state.get(scope+'_show_errors'): return issues
    touched=st.session_state.get(scope+'_touched',[])
    return {key:notes for key,notes in issues.items() if key in touched}


def render_issues(issues,slots):
    """Fill placeholders where the matching field/grid was rendered."""
    for key,slot in slots.items():
        notes=issues.get(key,[])
        if notes: slot.markdown('\n\n'.join(':red['+note+']' for note in notes))
        else: slot.empty()


def issue_summary(issues,labels,t):
    st.error(t('issues_title').format(count=len(issues)))
    for key,notes in issues.items():
        st.markdown('**'+labels.get(key,t('forecast'))+'** — '+' '.join(notes))


def result_text(value,t):
    """Translate program-generated notes; preserve human-authored inputs."""
    for key,translations in COPY.items():
        if value==translations[0]: return t(key)
    patterns=[
        (r'终值现值占经营资产价值 (.+)；请结合敏感性结果核对长期假设。','observation_terminal',('value',)),
        (r'每股模型值相对用户提供估值日价格的差异为 (.+)；该差异取决于所确认假设，不构成自动买卖结论。','observation_price',('value',)),
        (r'所提交情景的每股模型值范围为 (.+) 至 (.+) ([A-Z]{3})；范围仅覆盖用户选择的情景。','conclusion_range',('low','high','currency')),
    ]
    for pattern,key,names in patterns:
        match=re.fullmatch(pattern,value)
        if match: return t(key).format(**dict(zip(names,match.groups())))
    return value


def local_frame(rows,keys,t):
    return pd.DataFrame(rows)[keys].rename(columns={key:t('year_column' if key=='year' else 'pv_fcff' if key=='pv' else key) for key in keys})


def localized_choice(label,options,*,key,t,radio=False,default=None):
    """Streamlit serializes displayed labels; isolate widget IDs per language.

    Canonical business values live outside widget state, so switching languages
    cannot turn a selected trial into a translated string or another model.
    """
    state=st.session_state; canonical_key=key+'_canonical'
    def canonical(value,fallback):
        if value in options: return value
        return next((option for option in options if value in COPY.get(option,())),fallback)
    previous=canonical(state.get(canonical_key,default),options[0])
    widget_key=key+'_'+getattr(t,'language_token','zh')
    active_key=key+'_active_language'
    if state.get(active_key)!=getattr(t,'language_token','zh') or widget_key not in state:
        state[widget_key]=previous
        state[active_key]=getattr(t,'language_token','zh')
    widget=st.radio if radio else st.selectbox
    kwargs={'horizontal':True} if radio else {}
    selected=widget(label,options,index=None,format_func=t,key=widget_key,**kwargs)
    selected=canonical(selected,previous)
    state[canonical_key]=selected
    return selected


def localized_scenarios(label,*,key,t):
    state=st.session_state; options=['Base','Bear','Bull']
    widget_key=key+'_widget_'+t.language_token
    previous=state.get(key,['Base'])
    if state.get(key+'_active_language')!=t.language_token or widget_key not in state:
        state[widget_key]=previous
        state[key+'_active_language']=t.language_token
    selected=st.multiselect(label,options,format_func=t,key=widget_key,on_change=mark_touched,
        args=(key.removesuffix('_scenario_names'),'scenarios'))
    state[key]=[value if value in options else next((option for option in options if value in COPY[option]),'Base') for value in selected]
    return state[key]


def numeric(value, *, percentage=False):
    """Blank inputs stay missing. No silent zero filling or binary-money math."""
    if value is None or isinstance(value,float) and pd.isna(value): return None
    if isinstance(value,str) and not value.strip(): return None
    if isinstance(value,bool): raise ValueError('Boolean is not a financial number')
    try: number=Decimal(str(value).strip())
    except InvalidOperation: raise ValueError('Invalid financial number') from None
    if not number.is_finite(): raise ValueError('Non-finite financial number')
    return str(number/100 if percentage else number)


def percentage_list(value):
    if not value.strip(): return []
    parts=value.replace('，',',').replace(';',',').split(',')
    result=[numeric(x,percentage=True) for x in parts]
    if any(x is None for x in result): raise ValueError('Empty sensitivity item')
    return result


def valuation_scope(project,company_id,bundle):
    return 'uv_'+digest({'project':str(Path(project).resolve()),'company':company_id,
        'dataset':bundle['state']['dataset_fingerprint'],'analysis':digest(bundle['analysis'])})[:18]


def build_request(template,values,grids,scenarios,base_year,valuation_date):
    """Pure view-to-model conversion, used by tests and the page."""
    request={**template,'base_year':base_year,'valuation_date':valuation_date,
        'initial_operating_nwc':numeric(values['nwc']),
        'initial_operating_nwc_evidence':values['nwc_basis'],'scenarios':[],
        'bridge':{'as_of':valuation_date,'rationale':values['bridge_basis'],
                  **{k:numeric(values[k]) for k in BRIDGE_KEYS}},
        'confirmed':False,'confirmed_by':values['actor'],'rationale':values['overall_basis']}
    for name in scenarios:
        mode=values[name+'_mode']; rate={'mode':mode,'rationale':values[name+'_rate_basis']}
        if mode=='direct': rate['wacc']=numeric(values[name+'_wacc'],percentage=True)
        else:
            for key in ('risk_free_rate','beta','equity_risk_premium','country_risk_premium',
                        'pretax_cost_of_debt','debt_tax_rate','market_equity','market_debt'):
                rate[key]=numeric(values[name+'_'+key],percentage=key not in ('beta','market_equity','market_debt'))
        rows=grids[name].to_dict('records') if hasattr(grids[name],'to_dict') else grids[name]
        forecasts=[]
        for row in rows:
            rationale=row.get('rationale')
            if rationale is None or isinstance(rationale,float) and pd.isna(rationale): rationale=''
            forecasts.append({'year':int(row['year']),**{k:numeric(row[k],percentage=True) for k in FORECAST_KEYS},
                              'rationale':str(rationale)})
        terminal={k:numeric(values[name+'_terminal_'+k],percentage=True)
                  for k in ('growth','ebit_margin','cash_tax_rate','return_on_invested_capital')}
        terminal['rationale']=values[name+'_terminal_basis']
        request['scenarios'].append({'name':name,'discount_rate':rate,'forecasts':forecasts,
            'terminal':terminal,'sensitivity_wacc':percentage_list(values[name+'_sensitivity_wacc']),
            'sensitivity_growth':percentage_list(values[name+'_sensitivity_growth'])})
    return request


def list_saved_versions(invitation_dir,bundle,model='full'):
    folder=Path(invitation_dir).resolve(); output=[]
    for path in folder.glob('valuation_*/valuation.json'):
        try:
            if not path.resolve().is_relative_to(folder): continue
            result=read_json(path)
            if (result.get('model')=='fcff_growth_trial')!=(model=='trial'): continue
            if (result['dataset_fingerprint']!=bundle['state']['dataset_fingerprint'] or
                result['analysis_fingerprint']!=digest(bundle['analysis'])): continue
            output.append({'folder':str(path.parent),'label':path.parent.name,'result':result})
        except (OSError,ValueError,KeyError): continue
    output.sort(key=lambda r:Path(r['folder']).stat().st_mtime_ns,reverse=True)
    return output


def build_trial_request(bundle,company_id,values,base_year,stamp):
    return {'company_id':company_id,'dataset_fingerprint':bundle['state']['dataset_fingerprint'],
        'analysis_fingerprint':digest(bundle['analysis']),'currency':bundle['currency'],'unit':'currency_base_unit',
        'base_year':base_year,'valuation_date':stamp,'base_fcff':numeric(values['base_fcff']),
        'growth':numeric(values['growth'],percentage=True),'wacc':numeric(values['wacc'],percentage=True),
        'terminal_growth':numeric(values['terminal_growth'],percentage=True),'years':values['years'],
        'net_debt':numeric(values['net_debt']),'shares':numeric(values['shares']),
        'confirmed':False,'confirmed_by':values['actor'],'rationale':values['rationale']}


def _show_trial(version,scope,t):
    result=version['result']; folder=Path(version['folder']); currency=result['currency']
    st.subheader(t('result')); st.caption(t('trial_note'))
    for column,key in zip(st.columns(3),('operating_value','equity_value','per_share_value')):
        column.metric(t(key)+' · '+currency,'—' if result[key] is None else f'{Decimal(result[key]):,.2f}')
    if result['per_share_value'] is None: st.caption(t('nonpositive_equity'))
    left,right=st.columns(2)
    with left:
        st.markdown('**'+t('forecast_detail')+'**')
        st.dataframe(local_frame(result['forecasts'],['year','fcff','pv'],t),hide_index=True,width='stretch')
    with right:
        st.markdown('**'+t('sensitivity')+'**')
        rows=[{'WACC':float(r['wacc'])*100,'g':float(r['growth'])*100,
               'Value':float(r['operating_value']) if r['operating_value'] is not None else None,'Reason':result_text(r['reason'],t)}
              for r in result['sensitivity']]
        chart=alt.Chart(pd.DataFrame(rows)).mark_rect().encode(
            x=alt.X('g:O',title=t('terminal_growth')+' (%)'),y=alt.Y('WACC:O',title='WACC (%)'),
            color=alt.Color('Value:Q',scale=alt.Scale(scheme='yelloworangered'),title=currency),
            tooltip=[alt.Tooltip('WACC:O',title='WACC (%)'),alt.Tooltip('g:O',title=t('terminal_growth')+' (%)'),
                alt.Tooltip('Value:Q',format=',.2f',title=t('operating_value')),alt.Tooltip('Reason:N',title=t('reason'))])
        st.altair_chart(chart,width='stretch')
    for limitation in result.get('limitations',[]): st.caption(result_text(limitation,t))
    for file in folder.glob('*.xlsx'):
        if file.resolve().is_relative_to(folder.resolve()):
            st.download_button(t('download'),file.read_bytes(),file_name='Ultra007_FCFF_trial.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',on_click='ignore',key=scope+'_download')
            break


def _render_trial(project,company_id,bundle,metadata,offer,invitation,scope,t):
    from .trial_valuation import TrialRequest
    state=st.session_state; workflow=ResearchWorkflow()
    path=invitation/'trial_web_draft.json'
    if scope+'_restored' not in state:
        try: restored=read_json(path)
        except (ValueError,OSError): restored={}
        state[scope+'_restored']=restored if restored.get('scope')==scope else {}
    restored=state[scope+'_restored']; values={}; slots={}; labels={}
    st.info(t('trial_note')); st.caption(t('units')+' · '+bundle['currency'])
    st.caption(t('trial_legend'))
    def text(name,label,default=''):
        key=scope+'_'+name
        if key not in state:
            state[key]=state.get(scope+'_latest_values',restored.get('values',{})).get(name,default)
        labels[name]=label
        values[name]=st.text_input(field_label(label,t),key=key,on_change=mark_touched,args=(scope,name),
            placeholder=t('example_rationale') if name=='rationale' else None)
        slots[name]=st.empty()
    years=bundle['analysis']['years']
    if scope+'_year' not in state:
        state[scope+'_year']=state.get(scope+'_latest_base',restored.get('base_year',years[-1]))
    base_year=st.selectbox(field_label(t('year'),t),years,index=None,key=scope+'_year')
    if base_year is None: st.markdown(':red['+t('year_required')+']'); return
    stamp=f"{base_year}-{metadata['fiscal_year_end']}"
    st.caption(t('valuation_date')+' · '+stamp)
    left,right=st.columns([1.25,1])
    with left,st.container(border=True):
        text('actor',t('actor'),offer.get('decided_by',''))
        columns=st.columns(2)
        for i,(name,label) in enumerate([('base_fcff',t('base_fcff')+' · '+bundle['currency']),
            ('growth',t('trial_growth')+' (%)'),('wacc','WACC (%)'),('terminal_growth',t('terminal_growth')+' (%)'),
            ('net_debt',t('net_debt')+' · '+bundle['currency']),('shares',t('shares'))]):
            with columns[i%2]: text(name,label)
        if scope+'_years' not in state:
            state[scope+'_years']=state.get(scope+'_latest_values',restored.get('values',{})).get('years')
        values['years']=st.number_input(field_label(t('horizon'),t),min_value=1,max_value=15,value=None,step=1,key=scope+'_years',on_change=mark_touched,args=(scope,'years'))
        slots['years']=st.empty(); labels['years']=t('horizon')
        text('rationale',t('overall_basis'))
    with right,st.container(border=True):
        st.subheader(t('method'))
        st.latex(r'FCFF_t=FCFF_0(1+h)^t')
        st.latex(r'TV_N=\frac{FCFF_N(1+g)}{WACC-g}')
        st.latex(r'V_{operations}=\sum_{t=1}^{N}\frac{FCFF_t}{(1+WACC)^t}+\frac{TV_N}{(1+WACC)^N}')
        st.caption('WACC > g')
        st.caption(t('year_end'))
    issues=trial_issues(values,t)
    render_issues(visible_issues(issues,scope),slots)
    state[scope+'_latest_values']=values.copy(); state[scope+'_latest_base']=base_year
    draft={'scope':scope,'base_year':base_year,'values':values}; signature=digest(draft)
    if state.get(scope+'_signature')!=signature:
        state[scope+'_confirmed']=False; state[scope+'_signature']=signature
        try: _write_json(path,draft,replace=True)
        except OSError: st.warning(t('save_error'))
    confirmed=st.checkbox(field_label(t('confirmation'),t),key=scope+'_confirmed')
    if st.button(t('trial_calculate'),type='primary',disabled=not confirmed,key=scope+'_calculate'):
        if issues:
            state[scope+'_show_errors']=True
            st.rerun()
        else:
            try:
                raw=build_trial_request(bundle,company_id,values,base_year,stamp)
                model=TrialRequest.model_validate({**raw,'confirmed':True})
                output=workflow.value_trial(project,company_id,model.model_dump(mode='json'))
                folder=Path(output['output_dir']).resolve()
                if not folder.is_relative_to(invitation): raise ValueError('Unexpected valuation location')
                state[scope+'_result']={'folder':str(folder),'result':read_json(folder/'valuation.json')}
                state[scope+'_result_signature']=signature
                st.success(t('computed'))
            except ValidationError: st.error(t('input_error'))
            except (ValueError,OSError): st.error(t('state_error'))
    if state.get(scope+'_show_errors') and issues: issue_summary(issues,labels,t)
    if state.get(scope+'_result'):
        if state.get(scope+'_result_signature')==signature:
            _show_trial(state[scope+'_result'],scope+'_current',t)
        else: st.info(t('changed'))
    versions=list_saved_versions(invitation,bundle,'trial')
    if versions:
        with st.expander(t('history')):
            st.caption(t('history_note'))
            index=st.selectbox(t('select_version'),range(len(versions)),format_func=lambda i:versions[i]['label'],key=scope+'_version')
            _show_trial(versions[index],scope+'_saved_'+versions[index]['label'],t)


def _show_result(version,scope,t,theme):
    result=version['result']; folder=Path(version['folder'])
    st.subheader(t('result'))
    names=[r['name'] for r in result['scenarios']]
    selected=localized_choice(t('scenario_result'),names,key=scope+'_result_scenario',t=t)
    scenario=next(r for r in result['scenarios'] if r['name']==selected)
    currency=result['currency']; columns=st.columns(3)
    for column,metric in zip(columns,('operating_value','equity_value','per_share_value')):
        value=scenario['valuation'][metric]
        column.metric(t(metric)+' · '+currency,'—' if value is None else f'{Decimal(value):,.2f}')
    st.caption(t('valuation_date')+' '+result['valuation_date'])
    left,right=st.columns(2)
    with left:
        st.markdown('**'+t('forecast_detail')+'**')
        frame=pd.DataFrame(scenario['forecast'])
        st.dataframe(local_frame(scenario['forecast'],['year','revenue','ebit','fcff','pv_fcff'],t),hide_index=True,width='stretch')
        plot=pd.DataFrame([{'Year':r['year'],'FCFF':float(r['fcff'])} for r in scenario['forecast']])
        st.altair_chart(alt.Chart(plot).mark_line(point=True,color='#F27830').encode(
            x=alt.X('Year:O',axis=alt.Axis(labelAngle=0),title=t('year_column')),y=alt.Y('FCFF:Q',title=currency),
            tooltip=[alt.Tooltip('Year:O',title=t('year_column')),alt.Tooltip('FCFF:Q',title='FCFF',format=',.2f')]),width='stretch')
    with right:
        st.markdown('**'+t('sensitivity')+'**')
        choices=['equity_value','per_share_value']
        if scenario['sensitivity'] and 'operating_value' in scenario['sensitivity'][0]: choices.insert(0,'operating_value')
        metric=localized_choice(t('heatmap_value'),choices,key=scope+'_sensitivity_metric',t=t)
        rows=[{'WACC':float(r['wacc'])*100,'g':float(r['growth'])*100,
               'Value':float(r[metric]) if r.get(metric) is not None else None,'Reason':result_text(r['reason'],t)}
              for r in scenario['sensitivity']]
        if rows:
            grid=pd.DataFrame(rows)
            chart=alt.Chart(grid).mark_rect().encode(
                x=alt.X('g:O',title=t('growth')+' (%)'),y=alt.Y('WACC:O',title='WACC (%)'),
                color=alt.Color('Value:Q',scale=alt.Scale(scheme='yelloworangered'),title=currency),
                tooltip=[alt.Tooltip('WACC:O',title='WACC (%)'),alt.Tooltip('g:O',title=t('growth')+' (%)'),
                    alt.Tooltip('Value:Q',format=',.2f',title=t(metric)),alt.Tooltip('Reason:N',title=t('reason'))]).properties(height=235)
            st.altair_chart(chart,width='stretch')
            pivot=grid.pivot(index='WACC',columns='g',values='Value')
            pivot.index.name='WACC (%)'; pivot.columns.name=t('growth')+' (%)'
            st.dataframe(pivot,width='stretch')
            invalid=[r for r in rows if r['Reason']]
            if invalid: st.caption(' · '.join(dict.fromkeys(r['Reason'] for r in invalid)))
    for observation in scenario.get('observations',[]): st.write(result_text(observation,t))
    for conclusion in result.get('conclusions',[]): st.caption(result_text(conclusion,t))
    for limitation in result.get('limitations',[]): st.caption(result_text(limitation,t))
    actions=st.columns(2)
    workbook=folder/'DCF估值.xlsx'; params=folder/'assumptions.json'
    if workbook.is_file():
        actions[0].download_button(t('download'),workbook.read_bytes(),file_name='Ultra007_DCF.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key=scope+'_download_xlsx',on_click='ignore')
    if params.is_file():
        actions[1].download_button(t('parameters'),params.read_bytes(),file_name='Ultra007_assumptions.json',
                                  mime='application/json',key=scope+'_download_parameters',on_click='ignore')


def render_valuation(project:Path,company_id:str,bundle:dict,theme:str='light',language:str='中文') -> None:
    t=translator(language); project=Path(project).resolve(); scope=valuation_scope(project,company_id,bundle)
    workflow=ResearchWorkflow()
    st.title(t('title')); st.caption(t('intro'))
    state=st.session_state
    try:
        metadata=load_project(project)['companies'][company_id]['metadata']
        if metadata['business_type']!='non_financial': st.info(t('financial')); return
        if scope+'_offer' not in state: state[scope+'_offer']=workflow.offer(project,company_id)
        offer=state[scope+'_offer']
        cached_location=Path(offer['invitation_dir']).resolve()
        if cached_location.is_relative_to(project) and (cached_location/'invitation.json').is_file():
            recorded=read_json(cached_location/'invitation.json')
            if (recorded.get('dataset_fingerprint')==bundle['state']['dataset_fingerprint'] and
                recorded.get('analysis_fingerprint')==digest(bundle['analysis'])):
                offer={**recorded,'invitation_dir':str(cached_location)}
                state[scope+'_offer']=offer
    except (ValueError,KeyError,OSError): st.error(t('state_error')); return
    if offer['status']=='declined': st.info(t('stopped')); return
    if offer['status']=='awaiting_user_choice':
        with st.container(border=True):
            st.subheader(t('choice'))
            actor=st.text_input(field_label(t('actor'),t),key=scope+'_choice_actor')
            actor_issue=st.empty()
            left,right=st.columns(2)
            proceed=left.button(t('proceed'),type='primary',key=scope+'_proceed')
            stop=right.button(t('stop'),key=scope+'_stop')
            if proceed or stop:
                if not actor.strip():
                    actor_issue.markdown(':red['+t('required_hint')+']')
                    st.warning(t('actor_required')); return
                try:
                    state[scope+'_offer']=workflow.decide(project,company_id,proceed=proceed,decided_by=actor)
                    st.rerun()
                except (ValueError,OSError): st.error(t('state_error'))
        return
    invitation=Path(offer['invitation_dir']).resolve()
    if not invitation.is_relative_to(project): st.error(t('state_error')); return
    model_path=invitation/'web_model_choice.json'
    canonical_model_key=scope+'_model_canonical'
    if canonical_model_key not in state:
        try: preference=read_json(model_path)
        except (OSError,ValueError): preference={}
        state[canonical_model_key]=(preference['model'] if preference.get('scope')==scope and
                                    preference.get('model') in ('full','trial') else 'full')
    mode=localized_choice(t('model'),['full','trial'],key=scope+'_model',t=t,radio=True)
    if state.get(scope+'_persisted_model')!=mode:
        try:
            _write_json(model_path,{'scope':scope,'model':mode},replace=True)
            state[scope+'_persisted_model']=mode
        except OSError: pass  # UI preference persistence never grants financial confirmation.
    if mode=='trial':
        _render_trial(project,company_id,bundle,metadata,offer,invitation,scope+'_trial',t)
        return
    scope+='_full'
    template=workflow._template(metadata,bundle)
    draft_path=invitation/'web_draft.json'
    if scope+'_restored' not in state:
        try: previous=read_json(draft_path)
        except (ValueError,OSError): previous={}
        # Restore only draft values with the same scope, never a saved confirmation.
        state[scope+'_restored']=previous if previous.get('scope')==scope else {}
    restored=state[scope+'_restored']; values={}; slots={}; labels={}
    def text(name,label,*,multiline=False,default=''):
        key=scope+'_'+name
        if key not in state:
            state[key]=state.get(scope+'_latest_values',restored.get('values',{})).get(name,default)
        widget=st.text_area if multiline else st.text_input
        scenario=name.split('_',1)[0]
        labels[name]=(t(scenario)+' · ' if scenario in ('Base','Bear','Bull') else '')+label
        value=widget(field_label(label,t,optional=name=='market_price'),key=key,
            on_change=mark_touched,args=(scope,name),placeholder=t('example_rationale') if name=='overall_basis' else None)
        slots[name]=st.empty()
        values[name]=value; return value
    years=bundle['analysis']['years']
    st.caption(t('units')+' · '+bundle['currency'])
    st.caption(t('field_legend'))
    with st.expander(t('base'),expanded=True):
        if scope+'_base_year' not in state:
            state[scope+'_base_year']=state.get(scope+'_ui_config',restored).get('base_year',years[-1])
        year=st.selectbox(field_label(t('year'),t),years,index=None,key=scope+'_base_year')
        if year is None: st.markdown(':red['+t('year_required')+']'); return
        stamp=f"{year}-{metadata['fiscal_year_end']}"
        st.write(t('valuation_date')+' · '+stamp)
        st.caption(t('year_end'))
        text('actor',t('actor'),default=offer.get('decided_by',''))
        text('nwc',t('nwc')+' · '+bundle['currency'])
        text('nwc_basis',t('nwc_basis'),multiline=True)
    with st.expander(t('bridge'),expanded=bool(state.get(scope+'_show_errors'))):
        columns=st.columns(2)
        for i,key in enumerate(BRIDGE_KEYS):
            with columns[i%2]: text(key,t(key)+(' · '+bundle['currency'] if key!='diluted_shares' else ''))
        text('bridge_basis',t('bridge_basis'),multiline=True)
    forecast_column,method_column=st.columns([1.55,1])
    with forecast_column:
        st.subheader(t('forecast'))
        if scope+'_scenario_names' not in state:
            state[scope+'_scenario_names']=state.get(scope+'_ui_config',restored).get('scenarios',['Base'])
        if scope+'_horizon' not in state:
            state[scope+'_horizon']=state.get(scope+'_ui_config',restored).get('horizon')
        scenarios=localized_scenarios(field_label(t('scenarios'),t),key=scope+'_scenario_names',t=t)
        slots['scenarios']=st.empty(); labels['scenarios']=t('scenarios')
        horizon=st.number_input(field_label(t('horizon'),t),min_value=1,max_value=15,value=None,step=1,key=scope+'_horizon',
            on_change=mark_touched,args=(scope,'horizon'))
        slots['horizon']=st.empty(); labels['horizon']=t('horizon')
        grids={}
        for name in scenarios:
            with st.expander(t(name),expanded=len(scenarios)==1 or bool(state.get(scope+'_show_errors'))):
                st.markdown('**'+t('discount')+'**')
                previous_mode=state.get(scope+'_latest_values',restored.get('values',{})).get(name+'_mode','direct')
                mode=localized_choice(field_label(t('discount'),t),['direct','components'],t=t,radio=True,
                                      key=scope+'_'+name+'_mode',default=previous_mode)
                values[name+'_mode']=mode
                if mode=='direct': text(name+'_wacc','WACC (%)')
                else:
                    columns=st.columns(2)
                    for i,key in enumerate(('risk_free_rate','beta','equity_risk_premium','country_risk_premium',
                        'pretax_cost_of_debt','debt_tax_rate','market_equity','market_debt')):
                        suffix=' (%)' if key not in ('beta','market_equity','market_debt') else ''
                        with columns[i%2]: text(name+'_'+key,t(key)+suffix)
                text(name+'_rate_basis',t('rate_basis'),multiline=True)
                if horizon is None:
                    grids[name]=[]
                    st.info(t('horizon_required'))
                else:
                    seed_key=scope+f'_{name}_grid_seed_{year}_{horizon}'
                    editor_key=scope+f'_{name}_forecast_{year}_{horizon}'
                    if seed_key not in state or editor_key not in state:
                        old=state.get(scope+'_latest_grids',restored.get('grids',{})).get(name,[])
                        by_year={r['year']:r for r in old}
                        state[seed_key]=[by_year.get(y,{'year':y,**{k:None for k in FORECAST_KEYS},'rationale':''})
                                         for y in range(year+1,year+1+int(horizon))]
                    frame=pd.DataFrame(state[seed_key])
                    for key in FORECAST_KEYS: frame[key]=pd.to_numeric(frame[key],errors='coerce')
                    config={'year':st.column_config.NumberColumn(t('year_column'),format='%d'),
                            'rationale':st.column_config.TextColumn(field_label(t('rationale'),t),required=True),
                            **{k:st.column_config.NumberColumn(field_label(t(k),t),format='%.4f',required=True) for k in FORECAST_KEYS}}
                    st.caption(t('forecast_required'))
                    grids[name]=st.data_editor(frame,disabled=['year'],column_config=config,hide_index=True,
                        num_rows='fixed',width='stretch',key=editor_key,on_change=mark_touched,args=(scope,name+'_forecast'))
                slots[name+'_forecast']=st.empty(); labels[name+'_forecast']=t(name)+' · '+t('forecast')
                st.markdown('**'+t('terminal')+'**')
                columns=st.columns(2)
                for i,key in enumerate(('growth','ebit_margin','cash_tax_rate','return_on_invested_capital')):
                    with columns[i%2]: text(name+'_terminal_'+key,t(key).replace(' %','')+' (%)')
                text(name+'_terminal_basis',t('terminal_basis'),multiline=True)
                columns=st.columns(2)
                with columns[0]: text(name+'_sensitivity_wacc',t('sensitivity_wacc'))
                with columns[1]: text(name+'_sensitivity_growth',t('sensitivity_growth'))
    with method_column,st.container(border=True):
        st.subheader(t('method'))
        st.latex(r'FCFF_t=EBIT_t-CashTax_t+D\&A_t-CapEx_t-\Delta NWC_t')
        st.latex(r'V_{operations}=\sum_{t=1}^{N}\frac{FCFF_t}{(1+WACC)^t}+\frac{TV_N}{(1+WACC)^N}')
        st.latex(r'TV_N=\frac{NOPAT_{N+1}(1-g/ROIC)}{WACC-g}')
        st.caption('WACC > g · ROIC > g')
    text('overall_basis',t('overall_basis'),multiline=True)
    issues=full_issues(values,grids,scenarios,horizon,year,t)
    render_issues(visible_issues(issues,scope),slots)
    raw=None; draft_error=False
    try: raw=build_request(template,values,grids,scenarios,year,stamp)
    except (ValueError,TypeError,KeyError): draft_error=True
    grid_snapshot={name:[{k:(None if isinstance(v,float) and pd.isna(v) else v) for k,v in r.items()}
                          for r in (grid.to_dict('records') if hasattr(grid,'to_dict') else grid)]
                   for name,grid in grids.items()}
    state[scope+'_latest_values']={**state.get(scope+'_latest_values',restored.get('values',{})),**values}
    state[scope+'_latest_grids']={**state.get(scope+'_latest_grids',restored.get('grids',{})),
                                 **(grid_snapshot if horizon is not None else {})}
    state[scope+'_ui_config']={'base_year':year,'horizon':int(horizon) if horizon is not None else None,'scenarios':scenarios}
    draft={'scope':scope,'values':state[scope+'_latest_values'],'grids':state[scope+'_latest_grids'],
           'base_year':year,'horizon':int(horizon) if horizon is not None else None,'scenarios':scenarios}
    signature=digest(draft)
    confirm_key=scope+'_confirmed'
    if state.get(scope+'_signature')!=signature:
        state[confirm_key]=False
        state[scope+'_signature']=signature
        try: _write_json(draft_path,draft,replace=True)
        except OSError: st.warning(t('save_error'))
    confirmed=st.checkbox(field_label(t('confirmation'),t),key=confirm_key)
    st.caption(t('draft'))
    if st.button(t('calculate'),type='primary',disabled=not confirmed or not scenarios,key=scope+'_calculate'):
        if issues:
            state[scope+'_show_errors']=True
            st.rerun()
        elif draft_error or raw is None:
            st.error(t('bad_numbers'))
        else:
            try:
                request=ValuationRequest.model_validate({**raw,'confirmed':True})
                path=invitation/('web_parameters_'+uuid.uuid4().hex[:12]+'.json')
                _write_json(path,request.model_dump(mode='json'))
                output=workflow.value(project,company_id,path)
                folder=Path(output['output_dir']).resolve()
                if not folder.is_relative_to(invitation): raise ValueError('Unexpected valuation location')
                state[scope+'_result']={'folder':str(folder),'result':read_json(folder/'valuation.json')}
                state[scope+'_result_signature']=signature
                st.success(t('computed'))
            except ValidationError: st.error(t('input_error'))
            except (ValueError,OSError): st.error(t('state_error'))
    if state.get(scope+'_show_errors') and issues: issue_summary(issues,labels,t)
    current=state.get(scope+'_result')
    if current and state.get(scope+'_result_signature')==signature:
        _show_result(current,scope+'_current',t,theme)
    elif current: st.info(t('changed'))
    versions=list_saved_versions(invitation,bundle)
    if versions:
        with st.expander(t('history'),expanded=False):
            st.caption(t('history_note'))
            index=st.selectbox(t('select_version'),range(len(versions)),format_func=lambda i:versions[i]['label'],key=scope+'_history_version')
            _show_result(versions[index],scope+'_historical_'+versions[index]['label'],t,theme)
