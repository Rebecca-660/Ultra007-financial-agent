"""File assignment UI. Clicking Start is the only analysis trigger."""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import re
import unicodedata

import pandas as pd
import streamlit as st

from .models import digest
from .research import ResearchWorkflow
from .research_models import REPORTING_CURRENCIES
from .web_ui import ROOT,tr,safe_error,navigate
from .web_tasks import start_job


STANDARD_LABELS={
    '':('未指定','Not specified','Не указан'),
    '中国企业会计准则':('中国企业会计准则','Chinese Accounting Standards','Китайские стандарты бухгалтерского учёта'),
    'IFRS':('IFRS','IFRS','МСФО (IFRS)'),
    'US GAAP':('US GAAP','US GAAP','ОПБУ США (US GAAP)'),
    '其他':('其他','Other','Другой стандарт'),
}
TYPE_LABELS={
    'non_financial':('非金融企业','Non-financial company','Нефинансовая компания'),
    'financial':('金融企业','Financial company','Финансовая компания'),
}
UPLOAD_ERRORS={
    '请填写公司名称。':('请填写公司名称。','Enter a company name.','Укажите название компании.'),
    '请为每家公司填写行业与已核实的会计准则。':('请为每家公司填写行业与已核实的会计准则。','Enter the industry and verified accounting standard for each company.','Укажите отрасль и проверенный стандарт отчётности для каждой компании.'),
    '请选择金融或非金融企业类型。':('请选择金融或非金融企业类型。','Choose whether each company is financial or non-financial.','Выберите финансовый или нефинансовый тип компании.'),
    '请填写完整报告年度。':('请填写完整报告年度。','Enter a whole-number report year.','Укажите год отчёта целым числом.'),
    '同一家公司的行业、准则与财年末必须一致。':('同一家公司的行业、准则与财年末必须一致。','Industry, accounting standard and fiscal year-end must match for the same company.','Для одной компании отрасль, стандарт отчётности и конец финансового года должны совпадать.'),
    '同一家公司的同一语言译名必须一致。':('同一家公司的同一语言译名必须一致。','Use the same translated name for each language of the same company.','Для одной компании используйте одно и то же название на каждом языке.'),
    '列报币种需选择支持的大写 ISO 代码，例如 CNY、USD；不确定时请留空。':('列报币种需选择支持的大写 ISO 代码，例如 CNY、USD；不确定时请留空。','Choose a supported uppercase ISO currency code, such as CNY or USD; leave it blank if unknown.','Выберите поддерживаемый код валюты ISO заглавными буквами, например CNY или USD; если валюта неизвестна, оставьте поле пустым.'),
    '文件与报告信息不匹配。':('文件与报告信息不匹配。','The files and report assignments do not match.','Файлы не соответствуют сведениям об отчётах.'),
    '文件合计超过 500 MB。':('文件合计超过 500 MB。','The files exceed the 500 MB total limit.','Общий размер файлов превышает 500 МБ.'),
    '只接受文件名唯一的 PDF 年报。':('只接受文件名唯一的 PDF 年报。','Only annual-report PDFs with unique file names are accepted.','Принимаются только годовые отчёты PDF с уникальными именами файлов.'),
    '上传内容缺失。':('上传内容缺失。','An uploaded file is missing.','Загруженный файл отсутствует.'),
    '单份 PDF 不得超过 100 MB。':('单份 PDF 不得超过 100 MB。','Each PDF must be no larger than 100 MB.','Размер каждого PDF не должен превышать 100 МБ.'),
    '上传内容无效，或单份超过 100 MB、合计超过 500 MB。':('上传内容无效，或单份超过 100 MB、合计超过 500 MB。','Invalid upload, a file exceeds 100 MB, or the total exceeds 500 MB.','Недопустимая загрузка: файл превышает 100 МБ либо общий размер превышает 500 МБ.'),
    '文件不是有效 PDF。':('文件不是有效 PDF。','The file is not a valid PDF.','Файл не является корректным PDF.'),
    '同一 PDF 不能重复指定给不同年度或公司。':('同一 PDF 不能重复指定给不同年度或公司。','The same PDF cannot be assigned to multiple years or companies.','Один PDF нельзя назначить разным годам или компаниям.'),
    '空白或加密 PDF 不支持。':('空白或加密 PDF 不支持。','Empty or encrypted PDFs are not supported.','Пустые или зашифрованные PDF не поддерживаются.'),
    'PDF 没有可提取文本；扫描件需要 OCR，本版尚不支持。':('PDF 没有可提取文本；扫描件需要 OCR，本版尚不支持。','The PDF has no extractable text. Scanned reports require OCR, which is not supported in this version.','В PDF нет извлекаемого текста. Сканированным отчётам требуется OCR, который пока не поддерживается.'),
}


def upload_language_index(language):
    return {'中文':0,'EN':1,'RU':2}.get(language,0)


def standard_label(value,language):
    return STANDARD_LABELS.get(value,(value,value,value))[upload_language_index(language)]


def canonical_standard(value):
    return next((key for key,labels in STANDARD_LABELS.items() if value in labels),value)


def editor_records(records,language):
    """Translate only known enum values; company names and source facts stay intact."""
    return [{**row,'会计准则':standard_label(row.get('会计准则'),language) if row.get('会计准则') else ''}
            for row in records]


def canonical_editor_records(records):
    result=[]
    for row in records:
        row={**row,'会计准则':canonical_standard(row.get('会计准则',''))}
        row['类型']=next((key for key,labels in TYPE_LABELS.items() if row.get('类型') in labels),row.get('类型'))
        result.append(row)
    return result


def upload_error_message(message,language):
    return UPLOAD_ERRORS.get(message,(message,message,message))[upload_language_index(language)]


def upload_failure_message(error,language):
    # Match only controlled local diagnostics before the generic safe fallback.
    # Provider exceptions and arbitrary input payloads still pass through it.
    if isinstance(error,ValueError) and str(error) in UPLOAD_ERRORS:
        return upload_error_message(str(error),language)
    return safe_error(error)


def upload_column_config(language):
    index=upload_language_index(language)
    def label(c,e,r): return (c,e,r)[index]
    required=label('（必填）',' (Required)',' (Обязательно)')
    optional=label('（选填）',' (Optional)',' (Необязательно)')
    return {
        '文件':st.column_config.TextColumn(label('文件','File','Файл'),disabled=True),
        '公司':st.column_config.TextColumn(label('公司','Company','Компания')+required,required=True),
        '公司英文名':st.column_config.TextColumn(label('公司英文名','Company name in English','Название компании на английском')+optional,required=False),
        '公司俄文名':st.column_config.TextColumn(label('公司俄文名','Company name in Russian','Название компании на русском')+optional,required=False),
        '报告年度':st.column_config.NumberColumn(label('报告年度','Report year','Год отчёта')+required,
            min_value=1900,max_value=2200,step=1,format='%d',required=True),
        '行业':st.column_config.TextColumn(label('行业','Industry','Отрасль')+required,required=True),
        '会计准则':st.column_config.TextColumn(label('会计准则','Accounting standard','Стандарт отчётности')+required,required=True),
        '财年末':st.column_config.TextColumn(label('财年末 MM-DD','Fiscal year-end MM-DD','Конец финансового года ММ-ДД')+required,required=True),
        '类型':st.column_config.SelectboxColumn(label('企业类型','Company type','Тип компании')+required,
            options=list(TYPE_LABELS),format_func=lambda value:TYPE_LABELS[value][index],required=True),
        '列报币种':st.column_config.SelectboxColumn(label('列报币种','Reporting currency','Валюта отчётности')+optional,
            options=['',*REPORTING_CURRENCIES],required=False),
    }


def company_identifier(name):
    if not isinstance(name,str): raise ValueError('请填写公司名称。')
    normalized=unicodedata.normalize('NFKC',name).strip().casefold()
    if not normalized: raise ValueError('请填写公司名称。')
    return 'co_'+sha256(normalized.encode()).hexdigest()[:16]


def upload_hint(name):
    stem=Path(name).stem
    match=re.search(r'(?<!\d)(20\d{2}|19\d{2})(?!\d)',stem)
    year=int(match.group()) if match else None
    company=stem[:match.start()].rstrip('_- ：:') if match else ''
    return company,year


def build_upload_request(records,files,actor):
    companies={}; reports=[]; uploads={}
    def text(value):
        return '' if value is None or pd.isna(value) else str(value).strip()
    for i,(record,file) in enumerate(zip(records,files)):
        company=text(record.get('公司')); cid=company_identifier(company)
        standard=text(record.get('会计准则')); industry=text(record.get('行业'))
        if not standard or not industry: raise ValueError('请为每家公司填写行业与已核实的会计准则。')
        if record.get('类型') not in ('financial','non_financial'): raise ValueError('请选择金融或非金融企业类型。')
        year=record.get('报告年度')
        try: valid_year=year is not None and not pd.isna(year) and not isinstance(year,bool) and int(year)==float(year)
        except (ValueError,TypeError,OverflowError): valid_year=False
        if not valid_year: raise ValueError('请填写完整报告年度。')
        metadata={'company_id':cid,'name':company,'industry':industry,
            'business_type':'financial' if record.get('类型')=='financial' else 'non_financial',
            'accounting_standard':standard,'fiscal_year_end':text(record.get('财年末')),
            'comparability_confirmed':True}
        translated={language:text(record.get(column)) for language,column in [('EN','公司英文名'),('RU','公司俄文名')]
                    if text(record.get(column))}
        if cid in companies:
            prior=companies[cid]
            if {key:value for key,value in prior.items() if key!='display_names'}!=metadata:
                raise ValueError('同一家公司的行业、准则与财年末必须一致。')
            existing=prior.get('display_names',{})
            if any(language in existing and existing[language]!=value for language,value in translated.items()):
                raise ValueError('同一家公司的同一语言译名必须一致。')
            translated={**existing,**translated}
        if translated: metadata['display_names']=translated
        companies[cid]=metadata
        content=file.getvalue(); safe_name=Path(file.name.replace('\\','/')).name
        token=f'{i:02}_{sha256(content).hexdigest()[:10]}_{safe_name}'
        uploads[token]=content
        report={'company_id':cid,'report_year':int(year),'file_name':token}
        currency=text(record.get('列报币种'))
        if currency:
            if currency not in REPORTING_CURRENCIES:
                raise ValueError('列报币种需选择支持的大写 ISO 代码，例如 CNY、USD；不确定时请留空。')
            report['reporting_currency']=currency
        reports.append(report)
    if not reports or len(records)!=len(files): raise ValueError('文件与报告信息不匹配。')
    return {'confirmed_by':actor,'companies':list(companies.values()),'reports':reports},uploads


def render_upload(project_root:Path,existing_records:list[dict]):
    language=st.session_state.get('language','中文')
    def text(c,e,r): return (c,e,r)[upload_language_index(language)]
    st.markdown('<div class="ultra-eyebrow">'+text('从年报中看清经营。','REPORTS INTO REASONS.','ОТ ОТЧЁТОВ К ВЫВОДАМ.')+'</div>',unsafe_allow_html=True)
    st.title(tr('welcome'))
    st.caption(tr('intro'))
    left,right=st.columns([1.45,1],gap='large')
    with right:
        art=(ROOT/'assets/ultra007/illustration.svg').read_text(encoding='utf-8')
        st.markdown('<div class="ultra-art"><h3>'+text('把复杂财报，变成清晰的下一步。','From complex reports to a clearer next step.','От сложных отчётов к ясному следующему шагу.')+'</h3>'+art+'</div>',unsafe_allow_html=True)
        st.caption(text('插图仅为界面示意，不代表公司业绩。','Illustration only, not company financial data.','Иллюстрация не отражает данные компании.'))
    with left,st.container(border=True):
        st.subheader(text('上传公司的年度报告','Upload annual reports','Загрузить годовые отчёты'))
        files=st.file_uploader(text('拖拽或选择 PDF 年报','Drop or choose PDF annual reports','Перетащите или выберите PDF'),type=['pdf'],accept_multiple_files=True,key='annual_reports')
        st.caption(text('支持单公司、多年度和多公司。每份不超过 100 MB，合计不超过 500 MB。',
            'One company, multiple years, or peers. Up to 100 MB per file, 500 MB total.',
            'Одна компания, несколько лет или компании-аналоги. До 100 МБ на файл, всего 500 МБ.'))
        if existing_records and st.button(text('打开已有年报分析','Open an existing analysis','Открыть готовый анализ'),key='open_existing',width='stretch'):
            st.session_state.selected_run=existing_records[0]['path']; st.session_state.selected_project=''
            if 'project' in st.query_params: del st.query_params['project']
            st.query_params['run']=Path(existing_records[0]['path']).name
            navigate('overview'); st.rerun()
    if files:
        st.subheader(text('补充公司与报告信息','Company and reporting information','Компания и отчётный период'))
        st.caption(text('文件名推测仅作提示。请指定公司、年度和口径后开始；不需要逐表人工审核。',
            'Filename hints are suggestions. Assign company, year and reporting basis, then start. No manual table review.',
            'Имя файла даёт лишь подсказку. Укажите компанию, год и стандарты. Ручная сверка таблиц не требуется.'))
        with st.form('common_report_fields'):
            a,b,c=st.columns(3)
            with a: common_name=st.text_input(text('公司名称（可在下表逐行修改）','Company name (editable per file below)','Компания (можно изменить по файлам)'),key='common_company')
            with b: common_industry=st.text_input(text('行业','Industry','Отрасль'),key='common_industry')
            with c:
                standard_key='common_standard_'+language
                selected=canonical_standard(st.session_state.get('common_standard',''))
                if selected not in STANDARD_LABELS: selected='其他'
                if st.session_state.get('common_standard_language')!=language or standard_key not in st.session_state:
                    st.session_state[standard_key]=selected
                common_standard=st.selectbox(text('会计准则','Accounting standard','Стандарт отчётности'),list(STANDARD_LABELS),
                    format_func=lambda value:standard_label(value,language),key=standard_key)
                common_standard=canonical_standard(common_standard)
                st.session_state.common_standard=common_standard
                st.session_state.common_standard_language=language
            other_standard=st.text_input(text('其他准则名称（选择其他时填写）','Other standard (if selected)','Другой стандарт (при необходимости)'),key='other_standard')
            apply_common=st.form_submit_button(text('将已填写的通用信息应用到清单','Apply filled common fields','Применить заполненные общие поля'))
        if common_standard=='其他': common_standard=other_standard
        identities=[(f.name,sha256(f.getvalue()).hexdigest()) for f in files]
        editor_version=digest(identities)[:12]
        rows_key='upload_rows_'+editor_version
        revision_key='upload_revision_'+editor_version
        defaults=[]
        for file in files:
            hint,year=upload_hint(file.name)
            defaults.append({'文件':file.name,'公司':hint,'报告年度':year,
                '公司英文名':'','公司俄文名':'','行业':'','会计准则':'','财年末':'12-31','类型':'non_financial','列报币种':''})
        if rows_key not in st.session_state: st.session_state[rows_key]=defaults
        st.session_state[rows_key]=[{**row,'列报币种':row.get('列报币种',''),
            '公司英文名':row.get('公司英文名',''),'公司俄文名':row.get('公司俄文名','')} for row in st.session_state[rows_key]]
        if revision_key not in st.session_state: st.session_state[revision_key]=0
        st.caption(text('可逐行填写，或点击应用通用信息。修改上方字段不会清除已有公司与年度分配。',
            'Edit each row, or apply common fields. Editing fields above does not erase file assignments.',
            'Заполните строки или примените общие поля. Изменение полей выше не сбрасывает компании и годы.'))
        st.caption(text('下表标有“必填”的项目必须完成；上方通用信息用于批量填写，可以留空后逐行编辑。公司名和文件名保留原文。',
            'Complete the fields marked Required below. Common fields above are optional bulk-entry aids. Company and file names retain their original text.',
            'Заполните отмеченные ниже обязательные поля. Общие поля выше необязательны и служат для массового заполнения. Названия компаний и файлов сохраняются в оригинале.'))
        if apply_common:
            updates={k:v for k,v in {'公司':common_name,'行业':common_industry,'会计准则':common_standard}.items() if v}
            st.session_state[rows_key]=[{**row,**updates} for row in st.session_state[rows_key]]
            st.session_state[revision_key]+=1
        frame=st.data_editor(pd.DataFrame(editor_records(st.session_state[rows_key],language)),hide_index=True,width='stretch',disabled=['文件'],
            column_config=upload_column_config(language),
            key='upload_assignments_'+editor_version+'_'+str(st.session_state[revision_key])+'_'+language)
        records=canonical_editor_records(frame.to_dict('records'))
        st.session_state[rows_key]=records
        st.caption(text('列报币种可留空，由系统读取原文。仅当你已核实报告币种时填写；系统不会默认人民币，也不会将币种选择作为换汇。',
            'Leave reporting currency blank to read it from the report. Fill it only if verified; no default CNY or currency conversion is applied.',
            'Валюта может быть пустой: система читает её из отчёта. Указывайте только проверенную валюту; значения по умолчанию и конвертации нет.'))
        st.caption(tr('data_note'))
        if st.button(text('按以上公司与年度开始分析','Start analysis with these assignments','Начать анализ с указанными данными'),type='primary',key='start_upload_analysis',width='stretch'):
            try:
                if sum(f.size for f in files)>500_000_000: raise ValueError('文件合计超过 500 MB。')
                manifest,uploads=build_upload_request(records,files,'网页上传使用者（确认报告归属、年度及手动填写的列报币种）')
                signature=digest([manifest,[(k,sha256(v).hexdigest()) for k,v in uploads.items()]])
                # The same explicit submission recovers its project instead of creating another paid job.
                previous=st.session_state.get('last_upload_submission')
                if previous and previous['signature']==signature and Path(previous['project']).is_dir():
                    project=Path(previous['project'])
                else:
                    created=ResearchWorkflow.create_from_uploads(manifest,uploads,project_root)
                    project=Path(created['project_dir'])
                    st.session_state.last_upload_submission={'signature':signature,'project':str(project)}
                job=start_job(project,'analyze')
                st.session_state.selected_project=str(project)
                st.query_params['project']=project.name
                st.session_state.last_started_job=job['job_id']
                st.rerun()
            except Exception as exc: st.error(upload_failure_message(exc,language))
    columns=st.columns(3)
    features=[('读懂经营表现','Understand performance','Понимание результатов'),
              ('原文来源一目了然','Trace each figure to its source','Источники каждого показателя'),
              ('把经验转化为假设','Turn judgment into assumptions','Предположения на основе опыта')]
    descriptions=[('三张主表、趋势、比率与公司比较。','Statements, trends, ratios and peer comparisons.','Отчётность, динамика, коэффициенты и сравнение.'),
                  ('保留页码、公式、单位和系统校验记录。','Pages, formulas, units and validation provenance.','Страницы, формулы, единицы и проверки.'),
                  ('由你决定是否估值，并确认关键参数。','You choose whether to value and confirm every assumption.','Вы решаете, выполнять ли оценку, и подтверждаете параметры.')]
    for col,heading,body in zip(columns,features,descriptions):
        with col,st.container(border=True): st.subheader(text(*heading)); st.caption(text(*body))
