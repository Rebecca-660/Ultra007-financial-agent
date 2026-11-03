"""UI language boundaries and canonical selection state, with offline fixtures."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from financial_workbook.research_models import Company
from financial_workbook.web_i18n import (company_name,error_text,progress_text,
    status_text,text,validation_error_text)
from test_research import metadata
from test_ultra_web import completed_project

ROOT=Path(__file__).resolve().parents[1]


class TranslationHelpersTests(unittest.TestCase):
    def test_company_original_and_verified_or_supplied_alias_stay_together(self):
        self.assertEqual(company_name('立讯精密','中文'),'立讯精密')
        self.assertEqual(company_name('立讯精密','EN'),'立讯精密 (LUXSHARE-ICT)')
        self.assertEqual(company_name('未知公司','RU'),'未知公司')
        self.assertEqual(company_name('Acme','EN',{'EN':'ACME'}),'Acme')
        self.assertEqual(company_name('原公司','RU',{'display_names':{'RU':'Компания А'}}),'原公司 (Компания А)')

    def test_optional_company_names_do_not_replace_company_identity(self):
        original=metadata()
        parsed=Company.model_validate({**original,'display_names':{'EN':'Example Corp','RU':'Пример'}})
        self.assertEqual(parsed.company_id,original['company_id'])
        self.assertEqual(parsed.name,original['name'])
        self.assertEqual(Company.model_validate(original).display_names,{})
        for invalid in ({'EN':''},{'EN':'  '},{'DE':'Beispiel'}):
            with self.subTest(names=invalid),self.assertRaises(ValidationError):
                Company.model_validate({**original,'display_names':invalid})

    def test_meta_validation_uses_local_labels_and_excludes_input_payload(self):
        try: Company.model_validate({**metadata(),'industry':''})
        except ValidationError as error:
            english=validation_error_text(error,'EN')
            russian=validation_error_text(error,'RU')
        self.assertIn('Industry',english)
        self.assertIn('required',english)
        self.assertIn('Отрасль',russian)
        self.assertNotIn('String should',english)
        self.assertNotIn('行业',english+russian)

    def test_provider_secrets_are_never_translated_into_visible_errors(self):
        for language in ('中文','EN','RU'):
            message=error_text('Authorization Bearer sk-PRIVATE-TEST-ONLY',language)
            self.assertNotIn('PRIVATE',message)
            self.assertNotIn('Bearer',message)
            self.assertNotIn('sk-',message)

    def test_background_stage_and_status_are_translated_without_changing_data(self):
        message='正在校验并计算 立讯精密。'
        self.assertEqual(progress_text(message,'中文'),message)
        self.assertEqual(progress_text(message,'EN'),'Validating and calculating 立讯精密 (LUXSHARE-ICT).')
        self.assertNotIn('正在',progress_text('未来新增阶段','RU'))
        self.assertEqual(status_text('uploaded','EN'),'Uploaded')
        self.assertEqual(status_text('completed','RU'),'Завершено')

    def test_error_file_and_physical_page_survive_translated_diagnostic(self):
        error='报表预检失败：example.pdf, PDF 109, BS: 无列头续页的金额栏位置发生变化。'
        rendered=error_text(error,'EN')
        self.assertIn('example.pdf',rendered)
        self.assertIn('109',rendered)
        self.assertNotIn('预检',rendered)

    def test_upload_specific_conflict_keeps_actionable_localized_reason(self):
        from financial_workbook.web_upload import upload_failure_message
        for language in ('EN','RU'):
            message=upload_failure_message(ValueError('同一家公司的同一语言译名必须一致。'),language)
            self.assertNotIn('译名',message)
            self.assertNotIn('report could not be processed',message)
            self.assertTrue('name' in message.lower() if language=='EN' else 'назван' in message.lower())


class RootLanguageStateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.projects=self.root/'projects'; self.projects.mkdir()
        self.runs=self.root/'runs'; self.runs.mkdir()
        self.project=completed_project(self.projects)
        path=self.project/'project.json'
        state=json.loads(path.read_text(encoding='utf-8'))
        for cid,entry in state['companies'].items():
            entry['metadata']['name']='原始公司 '+cid[-1]
            entry['metadata']['display_names']={'EN':'Example '+cid[-1],'RU':'Пример '+cid[-1]}
        path.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
        self.env=patch.dict(os.environ,{'AIF_UI_PROJECTS_DIR':str(self.projects),'AIF_UI_RUNS_DIR':str(self.runs)})
        self.env.start()

    def tearDown(self): self.env.stop(); self.temp.cleanup()

    def app(self,language='EN'):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=30)
        app.query_params['project']=self.project.name
        app.query_params['page']='overview'; app.query_params['lang']=language
        return app

    def test_company_selection_survives_language_cycles_and_refresh(self):
        with patch('financial_workbook.service.FinancialAnalysisAgent._llm',side_effect=AssertionError('UI called a model')):
            app=self.app().run()
            self.assertFalse(app.exception)
            key='company_'+self.project.name
            app.selectbox(key=key+'_view_EN').set_value('SYNTHETIC_B').run()
            original_values=[metric.value for metric in app.metric]
            for language in ('RU','中文','EN'):
                app.selectbox(key='language').set_value(language).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.selectbox(key=key+'_view_'+language).value,'SYNTHETIC_B')
                self.assertEqual(app.session_state[key],'SYNTHETIC_B')
                self.assertEqual([metric.value for metric in app.metric],original_values)
            fresh=self.app('RU'); fresh.query_params['company']='SYNTHETIC_B'; fresh.run()
            self.assertFalse(fresh.exception)
            self.assertEqual(fresh.selectbox(key=key+'_view_RU').value,'SYNTHETIC_B')

    def test_sidebar_and_background_progress_follow_language_without_relaunch(self):
        active={'status':'running','job_id':'synthetic-i18n-job',
            'progress':[{'message':'系统校验完成，使用固定公式计算历史指标。'}],
            'action':'analyze','companies':['SYNTHETIC_A']}
        with patch('financial_workbook.web_tasks.job_status',return_value=active),\
             patch('financial_workbook.web_tasks.start_job',side_effect=AssertionError('Language reran analysis')):
            app=self.app().run()
            self.assertFalse(app.exception)
            self.assertTrue(any('Computing historical metrics' in value.value for value in app.markdown))
            app.selectbox(key='language').set_value('RU').run()
            self.assertFalse(app.exception)
            self.assertTrue(any('Исторические показатели' in value.value for value in app.markdown))
            self.assertFalse(any('系统校验完成' in value.value for value in app.markdown))


if __name__=='__main__': unittest.main()
