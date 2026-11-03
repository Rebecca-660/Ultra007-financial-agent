"""Local UI translations; identifiers, sources and financial values stay intact.

No LLM or external service runs for translation. Optional company display names
are user-supplied metadata. Known aliases are verified presentation names, not
a change of company identity or a guessed translation of an unknown company.
"""
from __future__ import annotations

import re
import unicodedata


COPY = {
 '任务在后台继续运行。刷新不会重新提交。':('The task continues in the background. Refreshing does not resubmit it.','Задача выполняется в фоне. Обновление страницы не отправляет её повторно.'),
 '重试任务':('Retry task','Повторить задачу'),
 '开始 / 继续自动分析':('Start / resume automatic analysis','Начать / продолжить автоматический анализ'),
 '请打开一个包含多家公司的研究项目。':('Open a research project containing multiple companies.','Откройте исследование с несколькими компаниями.'),
 '已有历史结果可查看和下载。进行新的估值研究，请从上传入口建立研究项目。':('Saved historical results are available to view and download. Create a research project from the upload page to start a new valuation.','Исторические результаты доступны для просмотра и скачивания. Для новой оценки создайте исследование на странице загрузки.'),
 'Ultra 007 · 年报分析与人工假设驱动估值':('Ultra 007 · Annual-report analysis and valuation with user assumptions','Ultra 007 · Анализ годовых отчётов и оценка на основе допущений пользователя'),
 '清晰财务':('FINANCIAL CLARITY','ФИНАНСОВАЯ ЯСНОСТЬ'),
 '新建研究':('New research','Новое исследование'),
 '已上传':('Uploaded','Загружено'),
 '等待处理':('Queued','В очереди'),
 '正在处理':('Processing','Выполняется'),
 '已完成':('Completed','Завершено'),
 '提取未完成':('Extraction incomplete','Извлечение не завершено'),
 '校验未完成':('Validation incomplete','Проверка не завершена'),
 '等待系统校验':('Awaiting system validation','Ожидает системной проверки'),
 '正在校验':('Validating','Выполняется проверка'),
 '估值已接受':('Valuation accepted','Оценка выбрана'),
 '本次不估值':('Finished without valuation','Завершено без оценки'),
 '等待估值选择':('Awaiting valuation choice','Ожидается решение об оценке'),
 '未知状态':('Unknown status','Неизвестное состояние'),
 '操作未完成，请查看任务状态后重试。':('The operation did not complete. Check task status before retrying.','Операция не завершена. Проверьте состояние задачи перед повтором.'),
 '输入资料不完整或格式不正确，请核对公司、年度和文件配置。':('Some input is missing or invalid. Check the company, year and report settings.','Некоторые данные отсутствуют или неверны. Проверьте компанию, год и параметры отчёта.'),
 '请填写此必填项。':('Complete this required field.','Заполните это обязательное поле.'),
 '请填写有效数值。':('Enter a valid number.','Введите корректное число.'),
 '请填写整数。':('Enter a whole number.','Введите целое число.'),
 '数值超出允许范围。':('The value is outside the allowed range.','Значение вне допустимого диапазона.'),
 '请选择一个支持的选项。':('Select one of the supported options.','Выберите один из допустимых вариантов.'),
 '输入格式不正确。':('The input format is invalid.','Неверный формат данных.'),
 '信息不一致，请核对所选报告与任务状态。':('The information is inconsistent. Check the selected reports and task state.','Данные не согласованы. Проверьте выбранные отчёты и состояние задачи.'),
 '请填写公司名称。':('Enter the company name.','Укажите название компании.'),
 '请为每家公司填写行业与已核实的会计准则。':('Enter the industry and verified accounting standard for every company.','Укажите отрасль и подтверждённый стандарт учёта для каждой компании.'),
 '请选择金融或非金融企业类型。':('Select financial or non-financial company type.','Выберите финансовый или нефинансовый тип компании.'),
 '请填写完整报告年度。':('Enter a complete report year.','Укажите полный год отчёта.'),
 '同一家公司的行业、准则与财年末必须一致。':('Use consistent industry, accounting standard and fiscal year-end for the same company.','Для одной компании отрасль, стандарт и конец финансового года должны совпадать.'),
 '文件与报告信息不匹配。':('The files do not match the report assignments.','Файлы не соответствуют указанным сведениям об отчётах.'),
 '上传内容缺失。':('Uploaded file content is missing.','Содержимое загруженного файла отсутствует.'),
 '文件不是有效 PDF。':('The file is not a valid PDF.','Файл не является корректным PDF.'),
 '空白或加密 PDF 不支持。':('Empty or encrypted PDFs are not supported.','Пустые и зашифрованные PDF не поддерживаются.'),
 'PDF 没有可提取文本；扫描件需要 OCR，本版尚不支持。':('This PDF has no extractable text. Scans require OCR, which this version does not support.','В PDF нет извлекаемого текста. Для сканов нужен OCR, который пока не поддерживается.'),
 '同公司同年度请只选一个主年报版本。':('Select one main annual report per company and year.','Выберите один основной годовой отчёт на компанию и год.'),
 '同一 PDF 不能重复指定给不同年度或公司。':('Do not assign the same PDF to different years or companies.','Нельзя назначать один PDF разным годам или компаниям.'),
 '文件合计超过 500 MB。':('The combined file size exceeds 500 MB.','Общий размер файлов превышает 500 МБ.'),
 '单份 PDF 不得超过 100 MB。':('Each PDF must be no larger than 100 MB.','Размер каждого PDF не должен превышать 100 МБ.'),
 '上传内容无效，或单份超过 100 MB、合计超过 500 MB。':('Invalid upload, a file over 100 MB, or a total over 500 MB.','Неверная загрузка, файл больше 100 МБ или общий размер больше 500 МБ.'),
 '请由用户确认公司、会计准则和完整财年口径。':('Confirm the company, accounting standard and full fiscal-year scope.','Подтвердите компанию, стандарт учёта и полный финансовый год.'),
 '列报币种需选择支持的大写 ISO 代码，例如 CNY、USD；不确定时请留空。':('Choose a supported uppercase ISO currency code such as CNY or USD; leave blank if uncertain.','Выберите поддерживаемый код валюты ISO заглавными буквами, например CNY или USD; если не уверены, оставьте поле пустым.'),
 '研究项目不存在。':('The research project does not exist.','Исследование не найдено.'),
 '研究任务正在提交，请稍后刷新。':('The task is being submitted. Refresh shortly.','Задача отправляется. Обновите страницу немного позже.'),
 '研究任务正在运行，不能重复提交。异常退出后先确认进程已结束。':('A task is already running. Confirm that it has stopped before resubmitting after an interruption.','Задача уже выполняется. После прерывания убедитесь, что процесс завершён, прежде чем отправлять её снова.'),
 '后台任务记录无效。':('The background-task record is invalid.','Неверная запись фоновой задачи.'),
 '后台进程已退出，任务未保存完成。可以检查现有结果后重新启动。':('The background process exited before completion. Check saved results before restarting.','Фоновый процесс завершился до окончания задачи. Проверьте сохранённые результаты перед повтором.'),
 '后台启动状态无法确认，请先检查后台进程，避免重复运行。':('The background startup state is unknown. Check the process before starting another task.','Состояние запуска неизвестно. Проверьте процесс перед запуском новой задачи.'),
 '尚无法证明原后台进程已经退出，请检查后台进程后恢复；不重复启动付费分析。':('The previous background process may still be running. Check its state before resuming.','Предыдущий фоновый процесс ещё может работать. Проверьте его состояние перед продолжением.'),
 '后台分析已开始。':('Background analysis has started.','Фоновый анализ запущен.'),
 '分析已完成，可以查看图表和下载结果。':('Analysis is complete. View the charts and download results.','Анализ завершён. Можно просмотреть графики и скачать результаты.'),
 '正在处理当前分析步骤。':('Processing the current analysis stage.','Выполняется текущий этап анализа.'),
 '正在预检年报主表、年度列与跨页版式；通过后才建立 RAG 索引。':('Checking main statements, year columns and page continuations before building the RAG index.','Проверяются основные формы, столбцы годов и продолжения таблиц перед созданием индекса RAG.'),
 '报表版式与来源预检通过，开始建立或复用检索索引。':('Layout and source checks passed. Building or reusing the retrieval index.','Проверка структуры и источников пройдена. Создаётся или используется готовый индекс поиска.'),
 '核验并建立/复用当前报告集合的 RAG 索引。':('Verifying and building or reusing the RAG index for these reports.','Проверяется и создаётся либо используется готовый индекс RAG для этих отчётов.'),
 '主 Agent 正在调用取证与财务表提取子 Agent。':('The orchestrator is running the evidence and statement-extraction agents.','Координатор запускает агентов поиска источников и извлечения отчётности.'),
 '候选报表已提取，正在保存来源记录与中间工作簿。':('Statements extracted. Saving source records and the intermediate workbook.','Отчётность извлечена. Сохраняются источники и промежуточная книга.'),
 '系统正在重新核对 PDF 来源、完整三表、单位和基础勾稽。':('Rechecking PDF sources, all three statements, units and basic reconciliations.','Повторно проверяются PDF, три основные формы, единицы и базовые балансовые равенства.'),
 '系统校验完成，使用固定公式计算历史指标。':('System checks passed. Computing historical metrics with fixed formulas.','Системная проверка завершена. Исторические показатели рассчитываются по заданным формулам.'),
 '历史分析和 Excel 已生成；数据经过系统校验，未记为人工批准。':('Historical analysis and Excel are ready. The data is system-validated, without a human approval record.','Исторический анализ и Excel готовы. Данные прошли системную проверку без записи ручного одобрения.'),
 '正在核对所选公司的可比年度并生成比较结果。':('Checking comparable years and generating the selected-company comparison.','Проверяются сопоставимые годы и создаётся сравнение выбранных компаний.'),
 '导入你填写的审核副本，核对原始来源与修正记录。':('Importing the historical review copy and checking original sources and corrections.','Импортируется историческая копия проверки, сверяются исходные данные и исправления.'),
 '主 Agent 正在调用来源复核、历史分析和 Excel 导出工具。':('The orchestrator is running source validation, historical analysis and Excel export.','Координатор выполняет проверку источников, исторический анализ и экспорт Excel.'),
}

FIELDS={
 'companies':('公司','Companies','Компании'), 'reports':('报告','Reports','Отчёты'),
 'company_id':('公司标识','Company ID','Идентификатор компании'), 'name':('公司名称','Company name','Название компании'),
 'industry':('行业','Industry','Отрасль'), 'business_type':('企业类型','Company type','Тип компании'),
 'accounting_standard':('会计准则','Accounting standard','Стандарт учёта'),
 'fiscal_year_end':('财年末','Fiscal year-end','Конец финансового года'),
 'report_year':('报告年度','Report year','Год отчёта'), 'file_name':('报告文件','Report file','Файл отчёта'),
 'reporting_currency':('列报币种','Presentation currency','Валюта представления'),
 'confirmed_by':('确认人','Confirmed by','Подтверждающее лицо'),
 'display_names':('公司外文名称','Company display names','Названия компании на других языках'),
}

_STATUS={'uploaded':'已上传','queued':'等待处理','running':'正在处理','preparing':'正在处理',
 'completed':'已完成','prepare_failed':'提取未完成','validation_failed':'校验未完成',
 'finalize_failed':'校验未完成','needs_human_review':'等待系统校验','validating':'正在校验',
 'finalizing':'正在校验','accepted':'估值已接受','declined':'本次不估值','awaiting_user_choice':'等待估值选择'}

# The Luxshare foreign abbreviation is printed in the 2022 uploaded report,
# PDF physical page 7. Foreign proper names stay in their registered spelling.
KNOWN_COMPANIES={
 '立讯精密':{'EN':'LUXSHARE-ICT','RU':'LUXSHARE-ICT'},
 '立讯精密工业股份有限公司':{'EN':'Luxshare Precision Industry Co., LTD.','RU':'Luxshare Precision Industry Co., LTD.'},
 '演示 A（合成数据）':{'EN':'Demo A (synthetic data)','RU':'Демо A (синтетические данные)'},
 '演示 B（合成数据）':{'EN':'Demo B (synthetic data)','RU':'Демо B (синтетические данные)'},
}


def language_code(language=None):
    if language is None:
        import streamlit as st
        language=st.session_state.get('language','中文')
    return {'English':'EN','en':'EN','Русский':'RU','ru':'RU','zh':'中文','CN':'中文'}.get(language,language) if language else '中文'


def text(source, language=None, **params):
    language=language_code(language)
    translation=source if language=='中文' else COPY.get(source,(source,source))[1 if language=='RU' else 0]
    return translation.format(**params) if params else translation


def company_name(original,language=None,translations=None):
    language=language_code(language)
    if language=='中文': return original
    names=translations or {}
    if 'display_names' in names: names=names.get('display_names') or {}
    alias=names.get(language) or names.get(language.lower()) or KNOWN_COMPANIES.get(original,{}).get(language)
    normalize=lambda value:re.sub(r'\W+','',unicodedata.normalize('NFKC',str(value))).casefold()
    return f'{original} ({alias})' if alias and normalize(alias)!=normalize(original) else original


def status_text(status,language=None):
    return text(_STATUS.get(status,'未知状态'),language)


def download_filename(original,language=None):
    language=language_code(language)
    names={
        '历史财务分析.xlsx':('Annual_financial_analysis.xlsx','Финансовый_анализ.xlsx'),
        '公司对比.xlsx':('Company_comparison.xlsx','Сравнение_компаний.xlsx'),
        'DCF估值.xlsx':('DCF_valuation.xlsx','Оценка_DCF.xlsx'),
    }
    return original if language=='中文' or original not in names else names[original][language=='RU']


def progress_text(message,language=None):
    language=language_code(language)
    if language=='中文' or message in COPY: return text(message,language)
    patterns=[
      (r'^正在校验并计算 (.+)。$',('Validating and calculating {0}.','Проверка и расчёт для {0}.'),True),
      (r'^运行未完成，记录保存在：(.+)$',('The run did not complete. Records: {0}','Выполнение не завершено. Записи: {0}'),False),
      (r'^(.+) 已有运行，保留并恢复，不重复调用。$',('Resuming the saved run for {0} without duplicate calls.','Возобновляется сохранённый запуск {0} без повторных вызовов.'),False),
    ]
    for pattern,translations,is_company in patterns:
        match=re.fullmatch(pattern,message)
        if match:
            value=company_name(match.group(1),language) if is_company else match.group(1)
            return translations[language=='RU'].format(value)
    return text('正在处理当前分析步骤。',language) if re.search(r'[\u3400-\u9fff]',message) else message


def error_text(message,language=None):
    """Translate known diagnostics without displaying provider secrets."""
    language=language_code(language)
    if re.search(r'(?i)bearer|authorization|api[_ -]?key|sk-[a-z0-9]|password|secret',str(message)):
        return text('操作未完成，请查看任务状态后重试。',language)
    if language=='中文' or message in COPY: return text(message,language)
    if not re.search(r'[\u3400-\u9fff]',message): return message
    match=re.fullmatch(r'任务未完成，请检查报告格式和模型服务配置。错误类型：([\w.]+)',message)
    if match:
        prefix=('The task did not complete. Check the report format and model configuration. Error type: ',
                'Задача не завершена. Проверьте формат отчёта и настройки модели. Тип ошибки: ')
        return prefix[language=='RU']+match.group(1)
    source=('The report could not be processed. Check its table layout, year columns and currency units.',
            'Не удалось обработать отчёт. Проверьте структуру таблиц, столбцы годов, валюту и единицы.')
    result=source[language=='RU']
    files=re.findall(r'([^\\/\n:：]+\.pdf)',message,re.I)
    pages=re.findall(r'PDF\s*(?:物理页\s*)?(\d+)',message,re.I)
    if files: result+=(' File: ' if language=='EN' else ' Файл: ')+files[0].strip()
    if pages: result+=' · PDF '+', '.join(dict.fromkeys(pages))
    return result


def validation_error_text(error,language=None):
    language=language_code(language); index={'中文':0,'EN':1,'RU':2}.get(language,0)
    output=[]
    for item in error.errors(include_input=False,include_context=False,include_url=False):
        names=[str(part+1) if isinstance(part,int) else FIELDS.get(part,(part,part,part))[index] for part in item['loc']]
        kind=item['type']
        message=('请填写此必填项。' if kind in ('missing','string_too_short','string_pattern_mismatch') else
                 '请填写有效数值。' if kind in ('float_parsing','decimal_parsing','finite_number','decimal_type') else
                 '请填写整数。' if kind.startswith('int_') else
                 '数值超出允许范围。' if kind in ('greater_than','greater_than_equal','less_than','less_than_equal') else
                 '请选择一个支持的选项。' if kind in ('literal_error','enum') else
                 '信息不一致，请核对所选报告与任务状态。' if kind=='value_error' else '输入格式不正确。')
        output.append(' / '.join(names)+': '+text(message,language))
    return '\n'.join(output)
