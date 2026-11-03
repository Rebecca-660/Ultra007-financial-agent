"""Financial display translations; canonical data and formulas are unchanged.

Source labels, source headings and uploaded filenames remain in their original
language. Application labels, metric names, units and explanations are rendered
in the selected language without making any model or network calls.
"""
from __future__ import annotations

import re
import streamlit as st


COPY={
 '增长':('Growth','Рост'),
 '盈利':('Profitability','Рентабельность'),
 '偿债与流动性':('Solvency and liquidity','Платёжеспособность и ликвидность'),
 '周转效率':('Operating efficiency','Эффективность оборота'),
 '现金流':('Cash flow','Денежный поток'),
 '营业收入':('Revenue','Выручка'),
 '营业成本':('Cost of sales','Себестоимость продаж'),
 '营业利润':('Operating profit','Операционная прибыль'),
 '合并净利润':('Consolidated net income','Консолидированная чистая прибыль'),
 '归母净利润':('Net income attributable to parent owners','Прибыль владельцев материнской компании'),
 '总资产':('Total assets','Активы всего'),
 '总负债':('Total liabilities','Обязательства всего'),
 '全部股东权益':('Total equity','Капитал всего'),
 '归母股东权益':('Equity attributable to parent owners','Капитал владельцев материнской компании'),
 '流动资产':('Current assets','Оборотные активы'),
 '流动负债':('Current liabilities','Краткосрочные обязательства'),
 '存货':('Inventories','Запасы'),
 '应收账款':('Trade receivables','Торговая дебиторская задолженность'),
 '经营活动现金流量净额':('Operating cash flow','Операционный денежный поток'),
 '投资活动现金流量净额':('Investing cash flow','Инвестиционный денежный поток'),
 '筹资活动现金流量净额':('Financing cash flow','Финансовый денежный поток'),
 '购建长期资产支付现金':('Cash paid for long-term assets','Денежные затраты на долгосрочные активы'),
 '期初总资产':('Opening total assets','Активы на начало периода'),
 '期初归母权益':('Opening parent equity','Капитал владельцев на начало периода'),
 '期初存货':('Opening inventories','Запасы на начало периода'),
 '期初应收账款':('Opening trade receivables','Дебиторская задолженность на начало периода'),
 '上年营业收入':('Prior-year revenue','Выручка предыдущего года'),
 '上年合并净利润':('Prior-year consolidated net income','Консолидированная прибыль предыдущего года'),
 '营业收入同比':('Revenue growth YoY','Рост выручки год к году'),
 '合并净利润同比':('Net income growth YoY','Рост чистой прибыли год к году'),
 '营业收入变动额':('Revenue change','Изменение выручки'),
 '合并净利润变动额':('Net income change','Изменение чистой прибыли'),
 '毛利':('Gross profit','Валовая прибыль'),
 '毛利率':('Gross margin','Валовая рентабельность'),
 '营业利润率':('Operating margin','Операционная рентабельность'),
 '净利率':('Net margin','Чистая рентабельность'),
 'ROA':('ROA','ROA'), 'ROE':('ROE','ROE'),
 '资产负债率':('Liabilities / assets','Обязательства / активы'),
 '负债权益比':('Liabilities / equity','Обязательства / капитал'),
 '流动比率':('Current ratio','Коэффициент текущей ликвидности'),
 '简化速动比率':('Simplified quick ratio','Упрощённый коэффициент быстрой ликвидности'),
 '存货周转率':('Inventory turnover','Оборачиваемость запасов'),
 '应收账款周转率':('Receivables turnover','Оборачиваемость дебиторской задолженности'),
 '总资产周转率':('Asset turnover','Оборачиваемость активов'),
 '经营现金流/净利润':('Operating cash flow / net income','Операционный поток / чистая прибыль'),
 '经营现金流利润率':('Operating cash flow margin','Рентабельность операционного денежного потока'),
 '简化自由现金流':('Simplified free cash flow','Упрощённый свободный денежный поток'),
 '利息保障倍数':('Interest coverage','Покрытие процентов'),
 '有息负债率':('Interest-bearing debt ratio','Доля процентного долга'),
 'EBITDA margin':('EBITDA margin','Рентабельность EBITDA'),
 'PE / PB / EV multiples':('PE / PB / EV multiples','Мультипликаторы PE / PB / EV'),
 '年度':('Year','Год'), '类别':('Category','Категория'), '指标':('Metric','Показатель'),
 '数值':('Value','Значение'),
 '结果':('Result','Результат'), '状态':('Status','Состояние'),
 '说明':('Explanation','Пояснение'), '公式':('Formula','Формула'),
 '输入':('Input','Входной показатель'), '原始项目':('Source item (original)','Статья источника (оригинал)'),
 '报告':('Source report','Исходный отчёт'), 'PDF物理页':('Physical PDF page','Физическая страница PDF'),
 '报告年度':('Report year','Отчётный год'), '数据年度':('Data year','Год данных'),
 '原列头':('Source heading (original)','Заголовок источника (оригинал)'),
 '原披露单位':('Disclosed units (original)','Единицы источника (оригинал)'),
 '标准化金额':('Normalized amount','Нормализованная сумма'), '币种':('Currency','Валюта'),
 '可计算':('Available','Доступно'), '不可计算':('Unavailable','Недоступно'),
 '收入与利润':('Revenue and net income','Выручка и чистая прибыль'),
 '年度增长率':('Annual growth','Годовой рост'), '盈利能力':('Profitability','Рентабельность'),
 '营业收入趋势':('Revenue trend','Динамика выручки'), '净利润趋势':('Net income trend','Динамика чистой прибыли'),
 '净利率对比':('Net margin comparison','Сравнение чистой рентабельности'),
 '资产负债率对比':('Liabilities / assets comparison','Сравнение обязательств и активов'),
 '所选年度没有可计算数据。':('No computable data for the selected years.','Для выбранных лет нет рассчитываемых данных.'),
 '请在侧栏至少选择一个年度。':('Select at least one year in the sidebar.','Выберите хотя бы один год на боковой панели.'),
 '请选择至少一个年度和指标类别。':('Select at least one year and metric category.','Выберите хотя бы один год и категорию показателей.'),
 '所选范围有 {count} 个项目不可计算，原因已列在说明栏。':('The selection includes {count} unavailable metrics; see the explanation column.','В выбранных данных недоступно показателей: {count}. Причины указаны в пояснениях.'),
 '公式在代码中预先定义，页面不由 AI 重新计算。比较数按各年原报本年数处理，不自动统一重述。':(
   'Formulas are predefined in code. Comparisons use each annual report’s current-year figures; restatements are not automatically reconciled.',
   'Формулы заданы в коде. Для сравнения используются данные текущего года каждого отчёта; пересчитанные данные автоматически не согласуются.'),
 '{year} 年输入来源':('Input sources for {year}','Источники входных данных за {year} год'),
 '原年报页 / Original annual report':('Original annual report page','Страница исходного годового отчёта'),
 '数据处理记录 / Data validation':('Data validation record','Запись проверки данных'),
 '旧版保留的人工记录；本次未新增人工批准。':('Historical human review is preserved; no new human approval was added.','Сохранена прежняя ручная проверка; новых ручных подтверждений нет.'),
 '尚不可计算的其他指标':('Other unavailable metrics','Прочие недоступные показатели'),
 '由你决定是否提供经验参数，代码负责计算和保留依据。':('You decide whether to supply judgment-based assumptions; code calculates and preserves their basis.','Вы решаете, задавать ли экспертные допущения; код выполняет расчёт и сохраняет основания.'),
 '原报表 / Source statement':('Source statement','Исходная форма отчётности'),
 'PDF 物理页 / Physical PDF page':('Physical PDF page','Физическая страница PDF'),
 '查看原年报页 / Preview page':('Preview original page','Показать исходную страницу'),
 '来源文件不唯一。':('The source file is not uniquely identified.','Исходный файл не определён однозначно.'),
 '来源已改变，请重新分析。':('The source changed. Run analysis again.','Источник изменился. Выполните анализ заново.'),
 '请先完成至少两家公司的年报分析。':('Complete annual-report analysis for at least two companies first.','Сначала завершите анализ отчётов хотя бы двух компаний.'),
 '选择比较公司 / Companies':('Companies to compare','Компании для сравнения'),
 '共同报告年度 / Common years':('Common report years','Общие отчётные годы'),
 '只比较共同年度、相同币种、兼容准则和完整财年；样本统计不代表全行业。':('Only common years, matching currencies and compatible accounting and fiscal periods are compared. Selected-sample statistics do not represent the whole industry.','Сравниваются общие годы, одинаковая валюта и сопоставимые стандарты и финансовые периоды. Статистика выборки не представляет всю отрасль.'),
 '生成公司对比 / Compare':('Generate company comparison','Сформировать сравнение компаний'),
 '正在核对来源并生成对比…':('Checking sources and generating comparison…','Проверка источников и формирование сравнения…'),
 '比较选择已变化，请重新生成；旧文件继续保留。':('The comparison selection changed. Generate again; previous files are preserved.','Параметры сравнения изменились. Сформируйте его заново; прежние файлы сохранены.'),
 '下载公司对比 Excel / Download peers':('Download comparison Excel','Скачать сравнение в Excel'),
 '收入指数和样本统计 / Index and sample statistics':('Revenue index and sample statistics','Индекс выручки и статистика выборки'),
 '本次尚未生成估值；历史分析可独立使用。':('No valuation has been generated for this analysis. Historical results can be used independently.','Оценка стоимости ещё не выполнена. Исторический анализ доступен отдельно.'),
 '公司对比 Excel / Peer comparison':('Company comparison Excel','Сравнение компаний в Excel'),
 '估值选择 / Valuation choice: ':('Valuation choice: ','Решение об оценке: '),
 'accepted':('Continue to valuation','Продолжить оценку'), 'declined':('Historical analysis only','Только исторический анализ'),
 'awaiting_user_choice':('Awaiting your choice','Ожидается ваше решение'),
 'THE BIG PICTURE.':('THE BIG PICTURE.','ОБЩАЯ КАРТИНА.'),
 'UNTIL YOUR NEXT CLEAR MOVE.':('UNTIL YOUR NEXT CLEAR MOVE.','ДО СЛЕДУЮЩЕГО ОБОСНОВАННОГО РЕШЕНИЯ.'),
 'consolidated_count':('{count} consolidated statements','Консолидированных форм: {count}'),
 'company':('Company','Компания'), 'company_id':('Company ID','Идентификатор компании'),
 'year':('Year','Год'), 'metric':('Metric','Показатель'), 'value':('Value','Значение'),
 'format':('Format','Формат'), 'reason':('Explanation','Пояснение'),
 'revenue_index':('Revenue index','Индекс выручки'), 'base_year':('Base year','Базовый год'),
 'count':('Valid observations','Число наблюдений'), 'selected_count':('Selected companies','Выбрано компаний'),
 'median':('Sample median','Медиана выборки'), 'label':('Scope','Область применения'),
 'name':('Metric','Показатель'), 'statement_id':('Statement ID','Идентификатор формы'),
 'statement_digest':('Statement fingerprint','Отпечаток формы'), 'decision':('Decision','Решение'),
 'reviewer':('Reviewer','Проверяющий'), 'reviewed_at':('Review time','Время проверки'),
 'note':('Note (original)','Примечание (оригинал)'), 'conflict_resolution':('Comparative policy','Политика сравнений'),
 'column':('Column index','Индекс столбца'), 'difference':('Difference','Разница'),
 'status':('Status','Состояние'), 'approved':('Approved','Подтверждено'),
 'pass':('Passed','Пройдено'), 'fail':('Failed','Не пройдено'), 'unavailable':('Unavailable','Недоступно'),
 'identity_units_columns':('Source identity, units and columns','Идентичность источника, единицы и столбцы'),
 'original_pdf_reparse':('Original PDF reread','Повторное чтение исходного PDF'),
 'assets':('Total assets','Активы всего'), 'cash_closing':('Closing cash and cash equivalents','Деньги и эквиваленты на конец периода'),
 'amount':('Amount','Сумма'), 'percent':('Percentage','Проценты'), 'multiple':('Multiple','Коэффициент'),
 'as_reported':('Current-year figures as originally reported','Данные текущего года в исходном отчёте'),
 '用户选择公司样本中位数，不代表全行业':('Median of selected companies; not the whole industry','Медиана выбранных компаний, не всей отрасли'),
 '基准收入缺失或非正':('Base revenue is missing or non-positive','Базовая выручка отсутствует или неположительна'),
 '系统校验仅检查可验证的来源和规则，未经人工财务复核。':('System validation checks verifiable sources and rules; no manual financial review was performed.','Системная проверка проверяет доступные источники и правила; ручная финансовая сверка не выполнялась.'),
 'Validation completed at':('Validation completed at','Проверка завершена'),
}

# Explanations are keyed by their original stored strings; source results and
# schema fingerprints are never altered by a display-language change.
EXPLANATIONS={
 '上年收入必须为正；优先引用上年原报主列。':('Prior-year revenue must be positive; the prior report’s current-year column takes precedence.','Выручка предыдущего года должна быть положительной; приоритет имеет основной столбец исходного отчёта.'),
 '亏损或零基数不显示普通同比。':('Ordinary YoY growth is unavailable for a loss or zero base.','Обычный темп роста не показывается при убытке или нулевой базе.'),
 '本年营业收入减上年营业收入。':('Current-year revenue less prior-year revenue.','Выручка текущего года минус выручка предыдущего года.'),
 '负基数时仍可观察金额变化。':('The absolute change remains informative with a negative base.','Абсолютное изменение можно оценивать и при отрицательной базе.'),
 '营业收入减匹配的营业成本，不采用营业总成本。':('Revenue less matching cost of sales; total operating expenses are not substituted.','Выручка минус соответствующая себестоимость продаж, без подмены общими операционными расходами.'),
 '营业收入与成本采用相同业务口径。':('Revenue and costs use the same business scope.','Выручка и расходы относятся к одной области деятельности.'),
 '年报营业利润/营业收入；营业利润可能包含投资等收益。':('Reported operating profit / revenue; operating profit may include investment income.','Операционная прибыль отчёта / выручка; прибыль может включать инвестиционные доходы.'),
 '合并净利润/营业收入。':('Consolidated net income / revenue.','Консолидированная чистая прибыль / выручка.'),
 '合并净利润/期初期末平均总资产。':('Consolidated net income / average opening and closing total assets.','Консолидированная чистая прибыль / средние активы на начало и конец периода.'),
 '归母净利润/平均归母权益，不等同于加权平均 ROE。':('Parent-attributable net income / average parent equity; this is not weighted-average ROE.','Прибыль владельцев материнской компании / их средний капитал; это не средневзвешенная ROE.'),
 '总负债/总资产，包含非付息经营性负债。':('Total liabilities / total assets, including non-interest-bearing operating liabilities.','Все обязательства / все активы, включая беспроцентные операционные обязательства.'),
 '总负债/全部权益，区别于有息债务/权益。':('Total liabilities / total equity; distinct from interest-bearing debt / equity.','Все обязательства / весь капитал; не равно процентному долгу / капиталу.'),
 '流动资产/流动负债。':('Current assets / current liabilities.','Оборотные активы / краткосрочные обязательства.'),
 '仅剔除存货，仍可能包含预付款、受限等非速动项目。':('Only inventories are excluded; prepayments or restricted assets may remain.','Исключаются только запасы; авансы и ограниченные активы могут оставаться.'),
 '营业成本/期初期末平均存货，单位次/年。':('Cost of sales / average opening and closing inventories, turns per year.','Себестоимость продаж / средние запасы, оборотов в год.'),
 '营业收入代理赊销收入/平均应收账款，单位次/年。':('Revenue as a proxy for credit sales / average receivables, turns per year.','Выручка как замена продаж в кредит / средняя дебиторская задолженность, оборотов в год.'),
 '营业收入/平均总资产，单位次/年。':('Revenue / average total assets, turns per year.','Выручка / средние активы, оборотов в год.'),
 '净利润非正时不可作通常现金含量比较。':('Ordinary cash-conversion comparisons are unavailable when net income is non-positive.','Обычное сравнение денежного обеспечения прибыли недоступно при неположительной прибыли.'),
 '经营现金流/营业收入。':('Operating cash flow / revenue.','Операционный денежный поток / выручка.'),
 '经营现金流减购建长期资产现金支出，不等同于 FCFF。':('Operating cash flow less cash spent on long-term assets; this is not FCFF.','Операционный поток минус денежные затраты на долгосрочные активы; это не FCFF.'),
 '尚未从附注核实完整折旧、摊销及 EBITDA 定义。':('Complete depreciation, amortization and the EBITDA definition have not been verified from notes.','Полная амортизация и определение EBITDA ещё не проверены по примечаниям.'),
 '财务费用净额和金融子公司利息支出不能替代统一口径的利息费用。':('Net finance costs and financial-subsidiary interest cannot substitute for consistently defined interest expense.','Чистые финансовые расходы и проценты финансовых дочерних компаний не заменяют сопоставимые процентные расходы.'),
 '仅保留资产负债率；尚未核实全部有息负债组成项和租赁口径。':('Only liabilities / assets is available; interest-bearing debt components and lease scope remain unverified.','Доступно только отношение обязательств к активам; состав процентного долга и учёт аренды ещё не проверены.'),
 '仅输入年报，缺少估值日股价与市场价值。':('Annual reports alone do not supply the valuation-date share price or market value.','В годовых отчётах нет цены акции и рыночной стоимости на дату оценки.'),
 '来源报表未获人工批准':('The source statement has not been approved','Исходная форма не подтверждена'),
 '原表缺少该指标、映射或期间列不唯一':('The item is missing or its mapping or period column is ambiguous','Статья отсутствует либо её сопоставление или столбец периода неоднозначны'),
 '原单元格空白、单位缺失或期初/比较年度不匹配':('The source cell is blank, units are missing, or opening/comparative periods do not match','Исходная ячейка пуста, единицы отсутствуют либо начальный/сравнительный период не совпадает'),
 '输入币种不同，未进行外汇换算':('Input currencies differ; no FX conversion was applied','Валюты входных данных различаются; конвертация не выполнялась'),
 '分母或同比基数非正：':('Non-positive denominator or growth base: ','Неположительный знаменатель или база роста: '),
 '分母为零或计算输入无效':('Zero denominator or invalid calculation input','Нулевой знаменатель или некорректные входные данные'),
 '支出为负且与配置口径不符；请核实 outflow_signs 后重新提取并审核，不直接猜取绝对值':('The outflow sign conflicts with the configured convention. Verify outflow_signs and extract again; no absolute value is guessed.','Знак оттока не соответствует настройке. Проверьте outflow_signs и повторите извлечение; модуль значения не подставляется.'),
 '需要全部连续年度收入已批准且起止收入为正':('All consecutive annual revenues must be approved and the first and last values positive','Нужна подтверждённая выручка за все последовательные годы с положительными начальным и конечным значениями'),
 '需要全部连续年度收入通过系统校验且起止收入为正':('All consecutive annual revenues must pass system validation and the first and last values be positive','Нужна системно проверенная выручка за все последовательные годы с положительными начальным и конечным значениями'),
}
COPY.update(EXPLANATIONS)

INPUT_KEY_LABELS={
 'revenue':'营业收入','cost_of_sales':'营业成本','operating_profit':'营业利润',
 'net_income':'合并净利润','parent_net_income':'归母净利润','assets':'总资产',
 'liabilities':'总负债','equity':'全部股东权益','parent_equity':'归母股东权益',
 'current_assets':'流动资产','current_liabilities':'流动负债','inventory':'存货',
 'receivables':'应收账款','cfo':'经营活动现金流量净额','cfi':'投资活动现金流量净额',
 'cff':'筹资活动现金流量净额','capex':'购建长期资产支付现金',
}

CHINESE_KEYS={
 'company':'公司','company_id':'公司标识','year':'年度','metric':'指标','value':'数值',
 'format':'格式','reason':'说明','revenue_index':'收入指数','base_year':'基准年度',
 'count':'有效样本数','selected_count':'所选公司数','median':'样本中位数','label':'适用范围',
 'name':'指标','statement_id':'报表标识','statement_digest':'报表指纹','decision':'审核决定',
 'reviewer':'审核人','reviewed_at':'审核时间','note':'备注（原文）','conflict_resolution':'比较差异口径',
 'column':'列索引','difference':'差额','status':'状态','approved':'已批准','pass':'通过',
 'fail':'未通过','unavailable':'不可计算','amount':'金额','percent':'百分比','multiple':'倍数',
 'accepted':'继续估值','declined':'仅历史分析','awaiting_user_choice':'等待选择',
 'Validation completed at':'校验完成时间','identity_units_columns':'来源身份、单位和年度列',
 'original_pdf_reparse':'原 PDF 重新读取','assets':'总资产','cash_closing':'期末现金及等价物',
 'consolidated_count':'{count} 张合并主表',
}


def language(language=None):
    return language or st.session_state.get('language','中文')


def text(value,lang=None,**parameters):
    """Translate controlled financial UI strings without changing source data."""
    if value is None: return ''
    value=str(value); lang=language(lang)
    if lang=='中文':
        result=CHINESE_KEYS.get(value,value)
        return result.format(**parameters) if parameters else result
    if value in COPY:
        result=COPY[value][0 if lang=='EN' else 1]
    else:
        result=value
        matched=re.fullmatch(r'(\d+) 处跨报告比较差异保留；系统按各年原报本年数分析，不自动覆盖重述。',value)
        mapped=re.fullmatch(r'(.+?) 指标映射不唯一：(.+?)；该指标不自动补值。',value)
        if matched:
            count=matched.group(1)
            return (f'{count} comparative differences are preserved; analysis uses each original report’s current-year figures.' if lang=='EN'
                    else f'Сохранено сравнительных различий: {count}; анализ использует данные текущего года каждого исходного отчёта.')
        if mapped:
            return (f'{mapped[1]}: ambiguous metric mapping for {mapped[2]}; no value is filled automatically.' if lang=='EN'
                    else f'{mapped[1]}: неоднозначное сопоставление {mapped[2]}; значение автоматически не заполняется.')
        # Compound missing-input explanations consist of registered labels and
        # registered reasons. Longest-first replacement avoids partial matches.
        for original in sorted(COPY,key=len,reverse=True):
            if re.search(r'[\u4e00-\u9fff]',original) and original in result:
                result=result.replace(original,COPY[original][0 if lang=='EN' else 1])
        result=result.replace('；','; ').replace('：',': ').replace('、',', ')
        if re.search(r'[\u4e00-\u9fff]',result):
            try:
                from .web_i18n import text as general_text
                result=general_text(result,language=lang)
            except ImportError: pass
        if re.search(r'[\u3400-\u9fff]',result):
            result=('Additional source-specific details are preserved in the downloadable records.' if lang=='EN'
                    else 'Дополнительные сведения об источнике сохранены в скачиваемых записях.')
    return result.format(**parameters) if parameters else result


def metric_name(name,lang=None):
    return text(INPUT_KEY_LABELS.get(name,name),lang)


def unit_label(multiplier,currency,lang=None):
    lang=language(lang)
    units={1e8:('亿','100m','100 млн'),1e6:('百万','million','млн'),1e3:('千','thousand','тыс.')}
    if multiplier==1: return currency
    return units[multiplier][{'中文':0,'EN':1,'RU':2}.get(lang,0)]+' '+currency


def display_value(value,kind,currency='CNY',lang=None):
    from .ui_data import number
    if value is None: return text('不可计算',lang)
    amount=number(value)
    if kind=='percent': return f'{amount:.1%}'
    if kind=='multiple': return f'{amount:.2f} '+('倍' if language(lang)=='中文' else '×')
    return f'{amount/1e8:,.2f} '+unit_label(1e8,currency,lang)


def table_rows(rows,*,lang=None,source=False):
    """Translate display dictionaries while preserving original-source fields."""
    original_fields={'原始项目','报告','原列头','原披露单位','note','reviewer','statement_id','statement_digest','company_id','company'}
    result=[]
    for row in rows:
        result.append({text(key,lang):(value if key in original_fields else
                       metric_name(value,lang) if key in ('指标','输入','metric','name') else
                       text(value,lang) if isinstance(value,str) else value)
                       for key,value in row.items()})
    return result


def company_label(original,lang=None,translations=None):
    try:
        from .web_i18n import company_name
        return company_name(original,language=language(lang),translations=translations)
    except ImportError:
        return original
