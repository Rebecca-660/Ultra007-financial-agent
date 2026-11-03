"""Presentation helpers for Ultra 007. Financial computation stays in services."""
from __future__ import annotations
from html import escape
import json
from pathlib import Path

import streamlit as st
from .web_i18n import text,validation_error_text,error_text,download_filename

ROOT=Path(__file__).resolve().parents[1]
COPY={
 'upload':('上传年报','Upload reports','Загрузить отчёты'),
 'overview':('财务概览','Financial overview','Финансовый обзор'),
 'compare':('公司对比','Compare companies','Сравнение компаний'),
 'valuation':('估值工作台','Valuation workspace','Оценка стоимости'),
 'summary':('摘要与导出','Summary and exports','Итоги и экспорт'),
 'welcome':('欢迎使用 Ultra 007','Welcome to Ultra 007','Добро пожаловать в Ultra 007'),
 'intro':('从公司的年报出发，理解经营表现，再用你的专业判断探索企业价值。',
          'Understand company performance from annual reports, then explore value with your own assumptions.',
          'Изучайте результаты компании по годовым отчётам и оценивайте стоимость на основе своих предположений.'),
 'workspace':('投资分析工作台','Investment research workspace','Рабочее пространство аналитика'),
 'project':('研究项目','Research project','Исследовательский проект'),
 'new_project':('新建研究','New research','Новое исследование'),
 'company':('选择公司','Select company','Выберите компанию'),
 'run':('分析记录','Saved analysis','Сохранённый анализ'),
 'theme':('外观：右上角菜单可选浅色、深色或跟随系统。','Appearance: choose Light, Dark or System in the top-right menu.',
          'Оформление: светлая, тёмная или системная тема в меню справа вверху.'),
 'data_note':('文件保存在本机；调用 AI 时，相关原文片段会发送给配置的模型服务。',
              'Files stay on this machine. Relevant excerpts are sent to the configured AI provider during analysis.',
              'Файлы хранятся локально. При анализе нужные фрагменты отправляются выбранному поставщику ИИ.'),
 'scope':('由数据出发，由你决策','Evidence first. Your judgment next.','Данные — основа. Решение — за вами.'),
 'download':('下载分析 Excel','Download analysis Excel','Скачать анализ Excel'),
 'source':('公式与来源','Formulas and sources','Формулы и источники'),
 'metrics':('财务指标','Financial metrics','Финансовые показатели'),
 'charts':('趋势图表','Trend charts','Графики динамики'),
 'next':('把分析推进一步','Take the next step','Следующий шаг анализа'),
 'to_valuation':('填写参数，计算 DCF','Provide assumptions and value','Параметры и расчёт DCF'),
 'finish':('本次只看分析','Finish with historical analysis','Завершить историческим анализом'),
 'refresh':('刷新结果列表','Refresh results','Обновить результаты'),
 'no_results':('还没有可展示的分析。请上传年报并开始分析，或打开已有研究项目。',
                'No analysis yet. Upload reports and start, or open a saved project.',
                'Анализ пока отсутствует. Загрузите отчёты или откройте сохранённый проект.'),
 'revenue':('营业收入','Revenue','Выручка'),
 'net_income':('合并净利润','Consolidated net income','Консолидированная чистая прибыль'),
 'yoy':('营业收入同比','Revenue growth YoY','Рост выручки год к году'),
 'debt':('资产负债率','Liabilities / assets','Обязательства / активы'),
 'cfo':('经营活动现金流量净额','Operating cash flow','Операционный денежный поток'),
 'system':('系统校验完成，未经人工逐项复核','System validated; not manually reviewed','Системная проверка без ручной сверки'),
 'human':('保留的历史人工审核记录','Existing human-reviewed analysis','Ранее проверенный вручную анализ'),
 'select_year':('指标卡年度','Headline year','Год основных показателей'),
 'chart_years':('图表和表格年度','Chart and table years','Годы графиков и таблиц'),
 'categories':('指标类别','Metric categories','Категории показателей'),
 'thanks':('谢谢使用 Ultra 007','Thank you for using Ultra 007','Спасибо за использование Ultra 007'),
 'return':('返回查看结果','Back to results','Вернуться к результатам'),
 'new':('分析新的公司','Analyze another company','Анализ другой компании'),
 'export_summary':('下载本次摘要 JSON','Download summary JSON','Скачать итоговый JSON'),
 'historical':('历史财务分析','Historical financial analysis','Исторический финансовый анализ'),
 'processing':('正在处理年报','Processing annual reports','Обработка годовых отчётов'),
 'ready':('已完成','Completed','Завершено'),
 'failed':('处理未完成','Processing did not complete','Обработка не завершена'),
}


def tr(key: str, language: str | None=None) -> str:
    language=language or st.session_state.get('language','中文')
    return COPY.get(key,(key,key,key))[{'中文':0,'EN':1,'RU':2}.get(language,0)]


def styles():
    st.markdown('''<style>
    .block-container{max-width:1480px;padding-top:2.2rem;padding-bottom:3rem}
    h1{font-size:2.65rem!important;font-weight:700!important;letter-spacing:-.06rem}
    h2{font-size:1.4rem!important}h3{font-size:1.08rem!important}
    .ultra-brand{display:flex;align-items:center;gap:10px;margin:9px 0 24px;font-size:25px;font-weight:750}
    .ultra-brand svg{width:30px;height:35px}.ultra-brand small{display:block;font-size:9px;letter-spacing:2px;font-weight:400;opacity:.65}
    .ultra-eyebrow{font-size:10px;letter-spacing:2px;color:#C48C4E;margin:24px 0 12px}
    .ultra-subtitle{opacity:.68;line-height:1.8;font-size:14px;margin-bottom:22px}
    .ultra-art{border-radius:14px;background:rgba(244,198,78,.10);padding:30px 20px}
    .ultra-art svg{width:100%;height:auto;max-height:270px}
    [data-testid=stMetric]{border:1px solid rgba(128,128,128,.2);border-radius:12px;padding:17px;background:rgba(128,128,128,.035)}
    [data-testid=stMetricValue]{font-size:1.85rem}
    [data-testid=stVerticalBlockBorderWrapper]>div{border-radius:14px!important}
    .stButton button,.stDownloadButton button{border-radius:8px!important}
    [data-testid=stSidebar]{border-right:1px solid rgba(128,128,128,.14)}
    [data-testid=stSidebar] .stRadio label{font-size:14px}
    .ultra-step{display:flex;gap:16px;align-items:center;font-size:12px;opacity:.6;margin:18px 0 32px;flex-wrap:wrap}
    .ultra-step .active{opacity:1;color:#E58B43;font-weight:700}
    .ultra-small{font-size:12px;opacity:.65;line-height:1.7}
    @media(max-width:700px){h1{font-size:2rem!important}.block-container{padding-top:1.4rem;padding-left:1.1rem;padding-right:1.1rem}[data-testid=stMetricValue]{font-size:1.6rem}}
    </style>''',unsafe_allow_html=True)


def brand():
    svg=(ROOT/'assets/ultra007/logo.svg').read_text(encoding='utf-8')
    st.markdown(f'<div class="ultra-brand">{svg}<div>Ultra 007<small>{escape(text("清晰财务"))}</small></div></div>',unsafe_allow_html=True)


def stepper(page):
    pages=['upload','overview','compare','valuation','summary']
    parts=[f'<span class="{"active" if page==p else ""}">{i+1:02} &nbsp;{escape(tr(p))}</span>' for i,p in enumerate(pages)]
    st.markdown('<div class="ultra-step">'+'<span>—</span>'.join(parts)+'</div>',unsafe_allow_html=True)


def safe_error(exc):
    from pydantic import ValidationError
    if isinstance(exc,ValidationError):
        return validation_error_text(exc)
    if isinstance(exc,ValueError) and exc.__class__.__module__.startswith(('builtins','financial_workbook','rag_step1')):
        return error_text(str(exc))
    return text('操作未完成，请查看任务状态后重试。')


def navigate(page):
    st.session_state.page=page
    st.query_params['page']=page


def download_file(label,path,key):
    path=Path(path)
    if not path.is_file(): return
    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if path.suffix=='.xlsx' else 'application/json'
    st.download_button(label,path.read_bytes(),file_name=download_filename(path.name),mime=mime,key=key,on_click='ignore',width='stretch')


def serializable_summary(bundle):
    return {'app':'Ultra 007','company_id':bundle['state']['company_id'],'years':bundle['analysis']['years'],
            'currency':bundle['currency'],'validation_method':bundle['state'].get('validation_method','human'),
            'dataset_fingerprint':bundle['state']['dataset_fingerprint'],'analysis':bundle['analysis']}
