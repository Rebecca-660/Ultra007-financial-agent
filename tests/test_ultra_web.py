"""Offline upload and root-page integration checks using synthetic facts only."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from financial_workbook.research_models import ResearchManifest
from financial_workbook.web_upload import build_upload_request,company_identifier,upload_hint
from financial_workbook.web_pages import display_scale
from financial_workbook.web_tasks import start_job
from test_research import make_pdf,metadata
from test_ui_data import saved_fixture

ROOT=Path(__file__).resolve().parents[1]


@dataclass
class Upload:
    name: str
    content: bytes

    @property
    def size(self): return len(self.content)
    def getvalue(self): return self.content


def row(company='SYNTHETIC A',year=2020):
    return {'公司':company,'报告年度':year,'行业':'SYNTHETIC manufacturing','会计准则':'SYNTHETIC GAAP',
            '财年末':'12-31','类型':'non_financial'}


def completed_project(root: Path):
    project=root/'synthetic_web_project'; project.mkdir()
    entries={}
    for cid in ('SYNTHETIC_A','SYNTHETIC_B'):
        run=saved_fixture(project/'runs',cid,cid)
        entries[cid]={'metadata':metadata(cid),'manifest':f'sources/{cid}.json','profile':None,
            'report_set_id':'synthetic','years':[2019,2020],
            'run_dir':str(run.relative_to(project)),'status':'completed'}
    state={'schema_version':'finance-research-project-v1','project_id':project.name,
           'created_at':'2026-10-28T00:00:00+00:00','updated_at':'2026-10-28T00:00:00+00:00',
           'confirmed_by':'SYNTHETIC TEST FIXTURE','companies':entries,'history_exports':[]}
    (project/'project.json').write_text(json.dumps(state),encoding='utf-8')
    return project


class UploadRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        make_pdf(self.root/'a.pdf','SYNTHETIC A',2020)
        make_pdf(self.root/'b.pdf','SYNTHETIC B',2020,1.2)
        self.files=[Upload('SYNTHETIC_A_2020.pdf',(self.root/'a.pdf').read_bytes()),
                    Upload('SYNTHETIC_B_2020.pdf',(self.root/'b.pdf').read_bytes())]

    def tearDown(self): self.temp.cleanup()

    def test_uploads_preserve_bytes_and_assign_company_year(self):
        manifest,content=build_upload_request([row(),row('SYNTHETIC B')],self.files,'SYNTHETIC uploader')
        parsed=ResearchManifest.model_validate(manifest)
        self.assertEqual(len(parsed.companies),2)
        self.assertEqual(parsed.reports[0].company_id,company_identifier('SYNTHETIC A'))
        self.assertEqual(parsed.reports[0].report_year,2020)
        self.assertEqual(content[parsed.reports[1].file_name],self.files[1].content)
        self.assertEqual(upload_hint('SYNTHETIC_A_2020.pdf'),('SYNTHETIC_A',2020))

    def test_small_values_do_not_round_to_zero_due_to_hundred_million_unit(self):
        self.assertEqual(display_scale(['120','-300',None],'CNY'),(1,'CNY'))
        self.assertEqual(display_scale(['1200000'],'CNY'),(1e6,'百万 CNY'))
        self.assertEqual(display_scale(['170447000000'],'CNY'),(1e8,'亿 CNY'))

    def test_same_company_inconsistent_metadata_and_duplicate_year_are_rejected(self):
        records=[row(),row()]; records[1]['会计准则']='OTHER SYNTHETIC GAAP'
        with self.assertRaisesRegex(ValueError,'一致'): build_upload_request(records,self.files,'SYNTHETIC')
        manifest,_=build_upload_request([row(),row()],self.files,'SYNTHETIC')
        with self.assertRaises(ValueError): ResearchManifest.model_validate(manifest)

    def test_missing_fields_years_actor_and_file_mismatch_are_rejected(self):
        for key,value in [('公司',''),('行业',''),('会计准则',''),('报告年度',None),('报告年度',2020.5),
                          ('公司',None),('行业',float('nan')),('会计准则',None)]:
            record=row(); record[key]=value
            with self.subTest(key=key,value=value):
                with self.assertRaises(ValueError):
                    manifest,_=build_upload_request([record],self.files[:1],'SYNTHETIC')
                    ResearchManifest.model_validate(manifest)
        manifest,_=build_upload_request([row()],self.files[:1],'')
        with self.assertRaises(ValueError): ResearchManifest.model_validate(manifest)
        with self.assertRaises(ValueError): build_upload_request([row()],self.files,'SYNTHETIC')


class UltraRootPageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.projects=self.root/'projects'; self.projects.mkdir()
        self.runs=self.root/'runs'; self.runs.mkdir()
        self.env=patch.dict(os.environ,{'AIF_UI_PROJECTS_DIR':str(self.projects),'AIF_UI_RUNS_DIR':str(self.runs)})
        self.env.start()

    def tearDown(self): self.env.stop(); self.temp.cleanup()

    def app(self):
        from streamlit.testing.v1 import AppTest
        return AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=30)

    def test_homepage_and_language_switch_never_launch_analysis(self):
        with patch('financial_workbook.web_upload.start_job',side_effect=AssertionError('Opening page launched a task')) as upload_job,\
             patch('financial_workbook.web_tasks.start_job',side_effect=AssertionError('Opening page launched a task')) as job,\
             patch('financial_workbook.service.FinancialAnalysisAgent._llm',side_effect=AssertionError('Opening page called a model')):
            app=self.app().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.page,'upload')
            app.selectbox(key='language').set_value('EN').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.page,'upload')
            self.assertTrue(any('Welcome to Ultra 007' in title.value for title in app.title))
            upload_job.assert_not_called(); job.assert_not_called()

    def test_saved_project_navigation_and_language_keep_scope(self):
        project=completed_project(self.projects)
        with patch('financial_workbook.service.FinancialAnalysisAgent._llm',side_effect=AssertionError('Navigation called model')):
            app=self.app().run()
            app.selectbox(key='project_picker_中文').set_value(str(project)).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.page,'overview'); self.assertEqual(len(app.metric),4)
            app.selectbox(key='language').set_value('RU').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.selected_project,str(project))
            self.assertEqual(app.session_state.page,'overview')
            self.assertEqual(app.selectbox(key='company_'+project.name+'_view_RU').value,'SYNTHETIC_A')

    def test_company_is_restored_from_verified_url_after_new_session(self):
        project=completed_project(self.projects)
        with patch('financial_workbook.service.FinancialAnalysisAgent._llm',side_effect=AssertionError('Restore called model')):
            app=self.app()
            app.query_params['project']=project.name
            app.query_params['company']='SYNTHETIC_B'
            app.query_params['page']='overview'
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key='company_'+project.name+'_view_中文').value,'SYNTHETIC_B')

    def test_peer_selection_does_not_compute_or_call_model_until_submit(self):
        project=completed_project(self.projects)
        with patch('financial_workbook.research.ResearchWorkflow.history',side_effect=AssertionError('Filters computed comparison')) as history,\
             patch('financial_workbook.service.FinancialAnalysisAgent._llm',side_effect=AssertionError('Filters called a model')):
            app=self.app().run()
            app.selectbox(key='project_picker_中文').set_value(str(project)).run()
            app.radio(key='nav_page_中文').set_value('compare').run()
            self.assertFalse(app.exception)
            company_widget=next(x for x in app.multiselect if x.key.startswith('compare_companies_'))
            company_widget.set_value(['SYNTHETIC_B']).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.button(key='compare_submit').disabled)
            history.assert_not_called()

    def test_summary_exposes_actual_saved_excel_and_json_download(self):
        saved_fixture(self.runs)
        with patch('financial_workbook.service.FinancialAnalysisAgent._llm',side_effect=AssertionError('Summary called a model')):
            app=self.app().run()
            app.radio(key='nav_page_中文').set_value('summary').run()
            self.assertFalse(app.exception)
            labels=[x.label for x in app.get('download_button')]
            self.assertEqual(len(labels),2)
            self.assertTrue(any('Excel' in label for label in labels))
            self.assertTrue(any('摘要' in label for label in labels))
            self.assertEqual(app.session_state.page,'summary')

    def test_task_polling_and_rerun_never_relaunch(self):
        project=completed_project(self.projects)
        active={'status':'running','job_id':'synthetic-job','progress':[{'message':'Synthetic source check'}],
                'action':'analyze','companies':['SYNTHETIC_A']}
        with patch('financial_workbook.web_tasks.job_status',return_value=active) as status,\
             patch('financial_workbook.web_tasks.start_job',side_effect=AssertionError('Polling relaunched work')) as start,\
             patch('financial_workbook.web_upload.start_job',side_effect=AssertionError('Polling uploaded work')):
            app=self.app().run()
            app.selectbox(key='project_picker_中文').set_value(str(project)).run()
            app.run()
            self.assertFalse(app.exception)
            self.assertGreaterEqual(status.call_count,2); start.assert_not_called()
            self.assertTrue(any('Synthetic source check' in x.value for x in app.markdown))


if __name__=='__main__': unittest.main()
