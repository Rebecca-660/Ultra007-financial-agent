"""Financial overview, comparable peers and exports backed by saved results."""
from __future__ import annotations
from io import BytesIO
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from .models import digest
from .research import ResearchWorkflow
from .research_io import read_json
from .service import _inside
from .ui_data import (CATEGORIES,chart_rows,metric_rows,result_for,source_rows,number)
from .web_ui import tr,safe_error,navigate,download_file,serializable_summary
from .web_financial_i18n import (text as ft,metric_name,unit_label,display_value,
                                 table_rows,company_label,language)


def display_scale(values,currency,language='中文'):
    largest=max((abs(number(v)) for v in values if v is not None),default=0)
    if largest>=1e8: return 1e8,unit_label(1e8,currency,language)
    if largest>=1e6: return 1e6,unit_label(1e6,currency,language)
    if largest>=1e3: return 1e3,unit_label(1e3,currency,language)
    return 1,currency


def money_scale(bundle):
    return display_scale([item['value'] for annual in bundle['analysis']['inputs'].values() for item in annual.values()],bundle['currency'],language())


def money(value,bundle,include_unit=True):
    if value is None: return ft('不可计算')
    scale,unit=money_scale(bundle)
    return f'{number(value)/scale:,.2f}'+(' '+unit if include_unit else '')


def visible_metrics(bundle,years,categories):
    rows=metric_rows(bundle,years,categories)
    results={(r['year'],r['name']):r for r in bundle['analysis']['results']}
    for row in rows:
        item=results[row['年度'],row['指标']]
        row['结果']=money(item['value'],bundle) if item['format']=='amount' else display_value(item['value'],item['format'],bundle['currency'])
    return rows


def _remember_selection(widget_key,canonical_key):
    st.session_state[canonical_key]=list(st.session_state[widget_key])


def localized_multiselect(label,options,*,key,default,format_func):
    """Keep canonical choices while localized option labels change."""
    state=st.session_state
    if key not in state: state[key]=list(default)
    chosen=[item for item in state[key] if item in options]
    widget_key=key+'_'+language()
    if state.get(widget_key)!=chosen: state[widget_key]=chosen
    result=st.multiselect(label,options,key=widget_key,format_func=format_func,
        on_change=_remember_selection,args=(widget_key,key))
    state[key]=list(result)
    return result


def draw_chart(bundle,years,title,metrics,percent=False):
    st.subheader(ft(title))
    rows=chart_rows(bundle,years,metrics,percent)
    if not any(row['数值'] is not None for row in rows): st.info(ft('所选年度没有可计算数据。')); return
    scale,unit=money_scale(bundle)
    if not percent:
        for row in rows:
            if row['数值'] is not None: row['数值']*=1e8/scale
    frame=pd.DataFrame([{'year':row['年度'],'metric':metric_name(row['指标']),'value':row['数值']} for row in rows])
    chart=alt.Chart(frame).mark_line(point=True).encode(
        x=alt.X('year:O',title=None,axis=alt.Axis(labelAngle=0)),
        y=alt.Y('value:Q',title='%' if percent else unit,
                axis=alt.Axis(format='.0%' if percent else ',.1f'),scale=alt.Scale(zero=True)),
        color=alt.Color('metric:N',legend=alt.Legend(orient='bottom',title=None),
                        scale=alt.Scale(range=['#F27830','#E5BD48','#69947B'])),
        tooltip=[alt.Tooltip('year:O',title=ft('年度')),alt.Tooltip('metric:N',title=ft('指标')),
                 alt.Tooltip('value:Q',title=ft('数值'),format='.1%' if percent else ',.2f')],
    ).properties(height=260).configure_view(strokeWidth=0)
    st.altair_chart(chart,width='stretch')


def source_preview(bundle):
    """Render an original page locally. Never use browser file:// paths."""
    state=bundle['state']; statements=bundle['dataset']['statements']
    options=list(range(len(statements)))
    scope=digest([state['company_id'],state['dataset_fingerprint']])[:10]
    index=st.selectbox(ft('原报表 / Source statement'),options,
        format_func=lambda i:f"{statements[i]['report_year']} · {statements[i]['kind']} · {statements[i]['file_name']}",key='pdf_statement_'+scope)
    statement=statements[index]
    page=st.selectbox(ft('PDF 物理页 / Physical PDF page'),statement['pdf_pages'],key='pdf_page_'+scope+'_'+str(index))
    if st.button(ft('查看原年报页 / Preview page'),key='show_pdf_'+scope):
        try:
            import pymupdf
            folder=Path(state['run_dir'])
            manifest=read_json(_inside(folder,state['files']['sources']))
            matches=[r for r in manifest['reports'] if Path(r['file_name']).name==statement['file_name']]
            if len(matches)!=1: raise ValueError(ft('来源文件不唯一。'))
            path=Path(matches[0]['file_name']); path=path if path.is_absolute() else folder/path
            from rag_step1.report import sha256_file
            if sha256_file(path)!=statement['file_hash']: raise ValueError(ft('来源已改变，请重新分析。'))
            with pymupdf.open(path) as pdf:
                pixmap=pdf[int(page)-1].get_pixmap(matrix=pymupdf.Matrix(1.35,1.35))
                st.image(pixmap.tobytes('png'),caption=f"{statement['file_name']} · PDF {page}",width='stretch')
        except Exception as exc: st.error(safe_error(exc))


def render_overview(bundle, project:Path|None=None, company_id:str|None=None):
    analysis=bundle['analysis']; years=analysis['years']; state=bundle['state']
    identity=state['dataset_fingerprint']
    if st.session_state.get('active_run')!=state['run_dir']:
        st.session_state.active_run=state['run_dir']
        st.session_state.visible_years=years[:]; st.session_state.focus_year=years[-1]
        st.session_state.categories=list(CATEGORIES)
    with st.sidebar:
        visible=st.multiselect(tr('chart_years'),years,key='visible_years')
        focus=st.selectbox(tr('select_year'),years,key='focus_year')
        categories=localized_multiselect(tr('categories'),list(CATEGORIES),key='categories',
            default=list(CATEGORIES),format_func=lambda value,lang=language():ft(value,lang))
    st.markdown('<div class="ultra-eyebrow">'+ft('THE BIG PICTURE.')+'</div>',unsafe_allow_html=True)
    title=company_label(st.session_state.get('company_display_name') or state['company_id'])
    heading,download=st.columns([3,1])
    with heading:
        st.subheader(f"{title} · {min(years)}—{max(years)}")
        st.caption(bundle['currency']+' · '+ft('consolidated_count',count=len(bundle['dataset']['statements']))+' · '+tr('system' if state.get('validation_method')=='system' else 'human'))
    with download: download_file(tr('download'),bundle['workbook'],'download_excel')
    top=st.columns(4)
    cards=[(tr('revenue'),analysis['inputs'][str(focus)]['revenue']['value'],'amount'),
           (tr('net_income'),analysis['inputs'][str(focus)]['net_income']['value'],'amount'),
           (tr('yoy'),result_for(bundle,focus,'营业收入同比')['value'],'percent'),
           (tr('debt'),result_for(bundle,focus,'资产负债率')['value'],'percent')]
    for column,(label,value,kind) in zip(top,cards):
        shown=display_value(value,kind,bundle['currency'])
        if kind=='amount': label+=' ('+money_scale(bundle)[1]+')'; shown=money(value,bundle,False)
        column.metric(label,shown)
    st.caption(f"{focus} · {tr('cfo')}: {money(analysis['inputs'][str(focus)]['cfo']['value'],bundle)}  ·  CAGR {years[0]}—{years[-1]}: {display_value(analysis['cagr']['value'],'percent')}")
    tabs=st.tabs([tr('charts'),tr('metrics'),tr('source')])
    with tabs[0]:
        if not visible: st.info(ft('请在侧栏至少选择一个年度。'))
        else:
            a,b=st.columns(2)
            with a,st.container(border=True): draw_chart(bundle,visible,'收入与利润',['revenue','net_income'])
            with b,st.container(border=True): draw_chart(bundle,visible,'年度增长率',['营业收入同比','合并净利润同比'],True)
            a,b=st.columns(2)
            with a,st.container(border=True): draw_chart(bundle,visible,'盈利能力',['毛利率','净利率','ROE'],True)
            with b,st.container(border=True): draw_chart(bundle,visible,'资产负债率',['资产负债率'],True)
            with st.container(border=True): draw_chart(bundle,visible,'现金流',['cfo','简化自由现金流'])
    with tabs[1]:
        rows=visible_metrics(bundle,visible,categories)
        if rows:
            st.dataframe(pd.DataFrame(table_rows([{k:v for k,v in row.items() if k!='公式'} for row in rows])),hide_index=True,width='stretch')
            missing=[r for r in rows if r['状态']=='不可计算']
            if missing: st.warning(ft('所选范围有 {count} 个项目不可计算，原因已列在说明栏。',count=len(missing)))
        else: st.info(ft('请选择至少一个年度和指标类别。'))
    with tabs[2]:
        st.caption(ft('公式在代码中预先定义，页面不由 AI 重新计算。比较数按各年原报本年数处理，不自动统一重述。'))
        rows=visible_metrics(bundle,[focus],list(CATEGORIES))
        st.dataframe(pd.DataFrame(table_rows([{key:row[key] for key in ('指标','公式','说明')} for row in rows])),hide_index=True,width='stretch')
        with st.expander(ft('{year} 年输入来源',year=focus)):
            st.dataframe(pd.DataFrame(table_rows(source_rows(bundle,focus),source=True)),hide_index=True,width='stretch')
        with st.expander(ft('原年报页 / Original annual report')):
            source_preview(bundle)
        with st.expander(ft('数据处理记录 / Data validation')):
            if bundle.get('validation'):
                validation=bundle['validation']
                st.caption(ft('Validation completed at')+': '+validation.get('validated_at',''))
                st.dataframe(pd.DataFrame(table_rows(validation.get('checks',[]))),hide_index=True,width='stretch')
                for warning in validation.get('warnings',[]): st.caption(ft(warning))
            else:
                st.caption(ft('旧版保留的人工记录；本次未新增人工批准。'))
                decisions=[{k:v for k,v in row.items() if k!='corrections'} for row in (bundle.get('review') or {}).get('decisions',[])]
                st.dataframe(pd.DataFrame(table_rows(decisions)),hide_index=True,width='stretch')
        with st.expander(ft('尚不可计算的其他指标')):
            st.dataframe(pd.DataFrame(table_rows(analysis['unavailable'])),hide_index=True,width='stretch')
    if project and company_id:
        with st.container(border=True):
            st.subheader(tr('next')); st.caption(ft('由你决定是否提供经验参数，代码负责计算和保留依据。'))
            a,b=st.columns(2)
            with a:
                if st.button(tr('to_valuation'),type='primary',key='open_valuation',width='stretch'):
                    navigate('valuation'); st.rerun()
            with b:
                if st.button(tr('finish'),key='finish_history',width='stretch'):
                    try:
                        workflow=ResearchWorkflow(); offer=workflow.offer(project,company_id)
                        if offer['status']=='awaiting_user_choice':
                            workflow.decide(project,company_id,proceed=False,decided_by='网页使用者')
                        navigate('summary'); st.rerun()
                    except Exception as exc: st.error(safe_error(exc))


def render_comparison(project:Path,state:dict):
    st.title(tr('compare'))
    entries=state['companies']; available=[cid for cid,entry in entries.items() if entry.get('status')=='completed']
    if len(available)<2:
        st.info(ft('请先完成至少两家公司的年报分析。')); return
    scope=digest(str(project))[:10]
    labels={cid:company_label(entry['metadata']['name'],translations=entry['metadata'].get('display_names')) for cid,entry in entries.items()}
    selected=localized_multiselect(ft('选择比较公司 / Companies'),available,default=available,
        key='compare_companies_'+scope,format_func=lambda c:labels[c])
    common=sorted(set.intersection(*(set(entries[cid]['years']) for cid in selected))) if selected else []
    years=st.multiselect(ft('共同报告年度 / Common years'),common,default=common,key='compare_years_'+scope+'_'+digest(selected)[:6])
    st.caption(ft('只比较共同年度、相同币种、兼容准则和完整财年；样本统计不代表全行业。'))
    signature=digest([selected,years,[entries[cid]['run_dir'] for cid in selected]])
    record_key='comparison_result_'+scope
    if st.button(ft('生成公司对比 / Compare'),type='primary',key='compare_submit',disabled=len(selected)<2 or not years):
        try:
            with st.spinner(ft('正在核对来源并生成对比…')):
                result=ResearchWorkflow().history(project,selected,years)
            st.session_state[record_key]={'signature':signature,'result':result}
        except Exception as exc: st.error(safe_error(exc))
    saved=st.session_state.get(record_key)
    if not saved or saved['signature']!=signature:
        if saved: st.info(ft('比较选择已变化，请重新生成；旧文件继续保留。'))
        return
    result=read_json(Path(saved['result']['comparison']))
    download_file(ft('下载公司对比 Excel / Download peers'),saved['result']['workbook'],'download_comparison')
    frame=pd.DataFrame([{k:v for k,v in r.items() if k in ('company_id','year','metric','value','reason','format')} for r in result['rows']])
    frame['company']=frame['company_id'].map(labels)
    amount_scale,amount_unit=display_scale([r['value'] for r in result['rows'] if r['format']=='amount'],result['currency'],language())
    for metric,title,percent in [('revenue','营业收入趋势',False),('net_income','净利润趋势',False),('净利率','净利率对比',True),('资产负债率','资产负债率对比',True)]:
        part=frame[frame['metric']==metric].copy()
        part['value']=pd.to_numeric(part['value'],errors='coerce')/(1 if percent else amount_scale)
        part=part[['company','year','value']]
        chart=alt.Chart(part).mark_line(point=True).encode(x=alt.X('year:O',title=ft('年度'),axis=alt.Axis(labelAngle=0)),
            y=alt.Y('value:Q',title='%' if percent else amount_unit,axis=alt.Axis(format='.0%' if percent else ',.1f')),
            color=alt.Color('company:N',title=None,legend=alt.Legend(orient='bottom')),
            tooltip=[alt.Tooltip('company:N',title=ft('company')),alt.Tooltip('year:O',title=ft('年度')),
                     alt.Tooltip('value:Q',title=ft('数值'),format='.2%' if percent else ',.2f')]).properties(height=260,title=ft(title))
        st.altair_chart(chart,width='stretch')
    shown=frame.copy()
    shown['value']=[(f"{number(r['value'])/amount_scale:,.2f} {amount_unit}" if r['value'] is not None else ft('不可计算'))
                    if r['format']=='amount' else display_value(r['value'],r['format'],result['currency']) for r in result['rows']]
    st.dataframe(pd.DataFrame(table_rows(shown[['company','year','metric','value','format','reason']].to_dict('records'))),hide_index=True,width='stretch')
    with st.expander(ft('收入指数和样本统计 / Index and sample statistics')):
        indexed=[{'company':labels.get(row['company_id'],row['company_id']),**{k:v for k,v in row.items() if k!='company_id'}} for row in result['revenue_index']]
        st.dataframe(pd.DataFrame(table_rows(indexed)),hide_index=True,width='stretch')
        formats={row['metric']:row['format'] for row in result['rows']}
        sample=[]
        for row in result['sample_statistics']:
            kind=formats.get(row['metric'],'multiple'); value=row['median']
            shown_value=(ft('不可计算') if value is None else f'{number(value)/amount_scale:,.2f} {amount_unit}') if kind=='amount' else display_value(value,kind,result['currency'])
            sample.append({**row,'median':shown_value})
        st.dataframe(pd.DataFrame(table_rows(sample)),hide_index=True,width='stretch')


def render_summary(bundle,project:Path|None,company_id:str|None):
    st.markdown('<div class="ultra-eyebrow">'+ft('UNTIL YOUR NEXT CLEAR MOVE.')+'</div>',unsafe_allow_html=True)
    st.title(tr('thanks'))
    st.caption(tr('scope'))
    if bundle is None:
        st.info(tr('no_results')); return
    st.subheader(company_label(st.session_state.get('company_display_name') or bundle['state']['company_id']))
    download_file(tr('historical')+' Excel',bundle['workbook'],'summary_history_download')
    payload=serializable_summary(bundle)
    if project and company_id:
        try:
            workflow=ResearchWorkflow(); offer=workflow.offer(project,company_id)
            st.write(ft('估值选择 / Valuation choice: ')+ft(offer['status']))
            values=workflow.list_valuations(project,company_id)
            if values:
                last=values[0]; payload['valuation']=last['result']; payload['assumptions']=last['assumptions']
                download_file('DCF Excel',last['workbook'],'summary_dcf_download')
            else: st.caption(ft('本次尚未生成估值；历史分析可独立使用。'))
            comparisons=state_comparisons(project)
            if comparisons: download_file(ft('公司对比 Excel / Peer comparison'),comparisons[0],'summary_peer_download')
        except Exception as exc: st.error(safe_error(exc))
    st.download_button(tr('export_summary'),json.dumps(payload,ensure_ascii=False,indent=2).encode('utf-8'),
        file_name='Ultra007_summary.json',mime='application/json',key='summary_json',on_click='ignore',width='stretch')
    a,b=st.columns(2)
    with a:
        if st.button(tr('return'),key='summary_return',width='stretch'): navigate('overview'); st.rerun()
    with b:
        if st.button(tr('new'),key='summary_new',width='stretch'): navigate('upload'); st.rerun()


def state_comparisons(project):
    from .research_io import load_project
    state=load_project(project)
    files=[_inside(project,entry)/'公司对比.xlsx' for entry in state.get('history_exports',[])]
    return [p for p in reversed(files) if p.is_file()]
