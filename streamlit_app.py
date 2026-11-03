"""Ultra 007: uploads, automatic financial analysis, peers and human-led valuation."""
from __future__ import annotations
import os
from pathlib import Path

import streamlit as st

from financial_workbook.ui_data import DEFAULT_RUNS,discover_runs,load_run,run_signature
from financial_workbook.research import ResearchWorkflow
from financial_workbook.service import _inside
from financial_workbook.web_ui import ROOT,brand,styles,tr,stepper,safe_error,navigate
from financial_workbook.web_upload import render_upload
from financial_workbook.web_pages import render_overview,render_comparison,render_summary,draw_chart
from financial_workbook.web_tasks import job_status,start_job
from financial_workbook.web_i18n import text,company_name,status_text,progress_text,error_text

PAGES=['upload','overview','compare','valuation','summary']


@st.cache_data(show_spinner=False)
def cached_run(folder:str,signature:tuple)->dict:
    return load_run(Path(folder))


@st.cache_data(show_spinner=False)
def workbook_bytes(path:str,signature:tuple)->bytes:
    return Path(path).read_bytes()


def projects_under(root:Path,language=None):
    projects=[]
    if not root.is_dir(): return projects
    for file in root.glob('*/project.json'):
        if not file.resolve().is_relative_to(root.resolve()): continue
        try:
            state=ResearchWorkflow.status(file.parent)
            name=' / '.join(company_name(c['metadata']['name'],language,c['metadata'].get('display_names')) for c in state['companies'].values())
            projects.append({'path':str(file.parent.resolve()),'state':state,
                             'label':f"{name} · {state['created_at'][:10]} · {state['project_id'][-6:]}"})
        except (ValueError,KeyError,OSError): continue
    return sorted(projects,key=lambda p:p['state']['created_at'],reverse=True)


def _switch_project(key):
    selected=st.session_state[key]
    if selected and not Path(selected).is_dir(): return
    st.session_state.selected_project=selected
    if 'company' in st.query_params: del st.query_params['company']
    if st.session_state.selected_project:
        st.query_params['project']=Path(st.session_state.selected_project).name
        navigate('overview')
    else:
        if 'project' in st.query_params: del st.query_params['project']
        navigate('upload')


def _switch_page(key):
    value=st.session_state[key]
    if value in PAGES: navigate(value)


def _switch_language():
    st.query_params['lang']=st.session_state.language


def _switch_run():
    st.session_state.selected_project=''; navigate('overview')
    if 'project' in st.query_params: del st.query_params['project']
    if 'company' in st.query_params: del st.query_params['company']
    st.query_params['run']=Path(st.session_state.selected_run).name


def _switch_company(key,canonical_key):
    st.session_state[canonical_key]=st.session_state[key]
    st.query_params['company']=st.session_state[key]


@st.fragment(run_every='2s')
def task_panel(project_text):
    project=Path(project_text)
    try: job=job_status(project)
    except (ValueError,OSError): job=None
    if not job: return
    status=job['status']
    if status in ('queued','running'):
        with st.status(tr('processing'),state='running',expanded=True):
            for event in job.get('progress',[])[-10:]: st.write(progress_text(event['message']))
            st.caption(text('任务在后台继续运行。刷新不会重新提交。'))
    elif status in ('failed','interrupted'):
        st.error(tr('failed')+': '+error_text(job.get('message','')))
        for event in job.get('progress',[])[-5:]: st.caption(progress_text(event['message']))
        if job.get('restart_safe',True) and st.button(text('重试任务'),key='retry_'+job['job_id']):
            try:
                start_job(project,job['action'],job.get('companies'),restart=True); st.rerun(scope='app')
            except Exception as exc: st.error(safe_error(exc))
    elif status=='completed':
        seen=st.session_state.get('last_job_completion')
        if seen!=job['job_id']:
            st.session_state.last_job_completion=job['job_id']
            if st.session_state.get('page')=='upload': navigate('overview')
            st.rerun(scope='app')


def main():
    language_hint=st.session_state.get('language',st.query_params.get('lang','中文'))
    st.set_page_config(page_title='Ultra 007 · Financial clarity',page_icon=str(ROOT/'assets/ultra007/logo.svg'),
        layout='wide',initial_sidebar_state='auto',menu_items={'About':text('Ultra 007 · 年报分析与人工假设驱动估值',language_hint)})
    styles()
    runs_root=Path(os.environ.get('AIF_UI_RUNS_DIR',str(DEFAULT_RUNS))).resolve()
    project_root=Path(os.environ.get('AIF_UI_PROJECTS_DIR',str(ROOT/'outputs/research_projects'))).resolve()
    records,invalid=discover_runs(runs_root)
    projects=projects_under(project_root,language_hint)
    paths=['']+[p['path'] for p in projects]; labels={p['path']:p['label'] for p in projects}
    if not st.session_state.get('initialized_ultra'):
        st.session_state.initialized_ultra=True
        lang=st.query_params.get('lang','中文'); st.session_state.language=lang if lang in ('中文','EN','RU') else '中文'
        requested=st.query_params.get('project','')
        selected=next((p['path'] for p in projects if Path(p['path']).name==requested),'')
        st.session_state.selected_project=selected
        requested_run=st.query_params.get('run','')
        matching_run=next((r['path'] for r in records if Path(r['path']).name==requested_run),None)
        if matching_run: st.session_state.selected_run=matching_run
        default='overview' if selected or (os.environ.get('AIF_UI_RUNS_DIR') and records) else 'upload'
        page=st.query_params.get('page',default); st.session_state.page=page if page in PAGES else default
    selected_project=st.session_state.get('selected_project','')
    if selected_project not in paths:
        selected_project=''; st.session_state.selected_project=''
    picker_key='project_picker_'+st.session_state.language
    if st.session_state.get(picker_key)!=selected_project:
        st.session_state[picker_key]=selected_project
    nav_key='nav_page_'+st.session_state.language
    if st.session_state.get(nav_key)!=st.session_state.page:
        st.session_state[nav_key]=st.session_state.page
    with st.sidebar:
        brand()
        st.selectbox('Language / 语言 / Язык',['中文','EN','RU'],key='language',on_change=_switch_language)
        st.caption(tr('theme'))
        empty_project_label=tr('new_project')
        st.selectbox(tr('project'),paths,format_func=lambda x:labels.get(x,empty_project_label),key=picker_key,on_change=_switch_project,args=(picker_key,))
        nav_labels={page:tr(page) for page in PAGES}
        st.radio(tr('workspace'),PAGES,format_func=lambda page:nav_labels[page],key=nav_key,on_change=_switch_page,args=(nav_key,),label_visibility='collapsed')
        if st.button(tr('refresh'),key='refresh_results'):
            cached_run.clear(); workbook_bytes.clear(); st.rerun()
        st.divider(); st.markdown('**'+tr('scope')+'**'); st.caption(tr('data_note'))
    page=st.session_state.page
    st.caption(tr('workspace')+' / '+tr(page))
    stepper(page)
    state=None; bundle=None; company_id=None; project=Path(selected_project) if selected_project else None
    if project:
        task_panel(str(project))
        try:
            state=ResearchWorkflow.status(project)
            ids=list(state['companies'])
            company_key='company_'+project.name
            if st.session_state.get(company_key) not in ids:
                requested_company=st.query_params.get('company')
                st.session_state[company_key]=requested_company if requested_company in ids else ids[0]
            company_widget_key=company_key+'_view_'+st.session_state.language
            if st.session_state.get(company_widget_key)!=st.session_state[company_key]:
                st.session_state[company_widget_key]=st.session_state[company_key]
            company_labels={cid:company_name(entry['metadata']['name'],st.session_state.language,
                entry['metadata'].get('display_names')) for cid,entry in state['companies'].items()}
            with st.sidebar:
                company_id=st.selectbox(tr('company'),ids,
                    format_func=lambda cid:company_labels[cid],key=company_widget_key,
                    on_change=_switch_company,args=(company_widget_key,company_key))
            entry=state['companies'][company_id]
            st.session_state.company_display_name=company_name(entry['metadata']['name'],translations=entry['metadata'].get('display_names'))
            if entry.get('run_dir') and entry['status']=='completed':
                folder=_inside(project,entry['run_dir']); bundle=cached_run(str(folder),run_signature(folder))
                bundle['state']['run_dir']=str(folder)
        except Exception as exc: st.error(safe_error(exc))
    elif page!='upload' and records:
        run_paths=[record['path'] for record in records]; run_labels={r['path']:r['label'] for r in records}
        if st.session_state.get('selected_run') not in run_paths: st.session_state.selected_run=run_paths[0]
        with st.sidebar:
            selected=st.selectbox(tr('run'),run_paths,format_func=lambda p:run_labels[p],key='selected_run',on_change=_switch_run)
        try:
            bundle=cached_run(selected,run_signature(Path(selected))); bundle['state']['run_dir']=selected
            st.session_state.company_display_name=company_name(bundle['state']['company_id'])
        except Exception as exc: st.error(safe_error(exc))
    if page=='upload':
        if not records and not projects: st.info(tr('no_results'))
        render_upload(project_root,records)
    elif page=='overview':
        if bundle: render_overview(bundle,project,company_id)
        else:
            st.title(tr('overview')); st.info(tr('no_results'))
            if state and company_id:
                entry=state['companies'][company_id]
                st.caption(f"{company_name(entry['metadata']['name'],translations=entry['metadata'].get('display_names'))} · {status_text(entry['status'])}")
                if entry['status'] in ('uploaded','prepare_failed','needs_human_review','finalize_failed'):
                    if st.button(text('开始 / 继续自动分析'),key='resume_analysis',type='primary'):
                        try: start_job(project,'analyze',[company_id]); st.rerun()
                        except Exception as exc: st.error(safe_error(exc))
    elif page=='compare':
        if project and state: render_comparison(project,state)
        else: st.info(text('请打开一个包含多家公司的研究项目。'))
    elif page=='valuation':
        if project and bundle and company_id:
            from financial_workbook.web_valuation import render_valuation
            theme=getattr(st.context.theme,'type','light')
            render_valuation(project,company_id,bundle,theme=theme,language=st.session_state.language)
        elif bundle:
            st.info(text('已有历史结果可查看和下载。进行新的估值研究，请从上传入口建立研究项目。'))
        else: st.info(tr('no_results'))
    else: render_summary(bundle,project,company_id)
    st.divider(); st.caption('Ultra 007 · '+tr('scope')+' · ZH / EN / RU')


if __name__=='__main__': main()
