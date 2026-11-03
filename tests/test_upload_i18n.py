"""Upload labels and language switches preserve canonical report assignments."""
from dataclasses import dataclass
from pathlib import Path
import unittest
from unittest.mock import patch

from financial_workbook.research_models import ResearchManifest
from financial_workbook.web_upload import (build_upload_request,canonical_editor_records,
    company_identifier,editor_records,standard_label,upload_column_config,upload_error_message)


@dataclass
class Upload:
    name: str='SYNTHETIC_2020.pdf'
    content: bytes=b'%PDF-SYNTHETIC-UI-ONLY'
    @property
    def size(self): return len(self.content)
    def getvalue(self): return self.content


def assignment(**changes):
    return {'文件':'SYNTHETIC_2020.pdf','公司':'原始公司','报告年度':2020,
        '行业':'原始行业','会计准则':'中国企业会计准则','财年末':'12-31',
        '类型':'non_financial','列报币种':'CNY','公司英文名':'','公司俄文名':'',**changes}


class UploadTranslationTests(unittest.TestCase):
    def test_localized_editor_values_round_trip_without_translating_source_facts(self):
        original=assignment(公司英文名='SOURCE COMPANY',公司俄文名='ИСТОЧНИК')
        for language in ('中文','EN','RU'):
            shown=editor_records([original],language)
            self.assertEqual(shown[0]['公司'],'原始公司')
            self.assertEqual(shown[0]['行业'],'原始行业')
            self.assertEqual(shown[0]['文件'],'SYNTHETIC_2020.pdf')
            self.assertEqual(canonical_editor_records(shown),[original])
        self.assertEqual(standard_label('中国企业会计准则','EN'),'Chinese Accounting Standards')
        self.assertEqual(standard_label('USER-SPECIFIC GAAP','RU'),'USER-SPECIFIC GAAP')
        for language in ('中文','EN','RU'):
            self.assertEqual(editor_records([assignment(会计准则='')],language)[0]['会计准则'],'')

    def test_headers_and_required_optional_marks_use_selected_language(self):
        for language in ('EN','RU'):
            configuration=upload_column_config(language)
            for column in configuration.values():
                self.assertNotRegex(column['label'],r'[\u4e00-\u9fff]')
            expected='Required' if language=='EN' else 'Обязательно'
            optional='Optional' if language=='EN' else 'Необязательно'
            self.assertIn(expected,configuration['报告年度']['label'])
            self.assertIn(optional,configuration['列报币种']['label'])
            self.assertIn(optional,configuration['公司英文名']['label'])
            self.assertTrue(configuration['公司']['required'])
            self.assertFalse(configuration['公司俄文名']['required'])

    def test_localized_business_type_values_return_to_canonical_metadata(self):
        for localized in ('Financial company','Финансовая компания','金融企业'):
            self.assertEqual(canonical_editor_records([assignment(类型=localized)])[0]['类型'],'financial')

    def test_validation_errors_are_localized_and_do_not_show_native_conversion_errors(self):
        for invalid in ('not-a-year',float('inf'),True,2020.5):
            with self.assertRaisesRegex(ValueError,'请填写完整报告年度') as failure:
                build_upload_request([assignment(报告年度=invalid)],[Upload()],'SYNTHETIC')
            for language in ('EN','RU'):
                message=upload_error_message(str(failure.exception),language)
                self.assertNotRegex(message,r'[\u4e00-\u9fff]')
                self.assertNotIn('invalid literal',message)

    def test_display_names_merge_per_company_without_changing_company_identity(self):
        records=[assignment(公司英文名='SOURCE COMPANY'),assignment(报告年度=2021,公司俄文名='КОМПАНИЯ')]
        manifest,_=build_upload_request(records,[Upload(),Upload('SYNTHETIC_2021.pdf',b'%PDF-OTHER')],'SYNTHETIC')
        self.assertEqual(len(manifest['companies']),1)
        company=manifest['companies'][0]
        self.assertEqual(company['company_id'],company_identifier('原始公司'))
        self.assertEqual(company['name'],'原始公司')
        self.assertEqual(company['display_names'],{'EN':'SOURCE COMPANY','RU':'КОМПАНИЯ'})
        self.assertEqual(ResearchManifest.model_validate(manifest).companies[0].display_names,
                         {'EN':'SOURCE COMPANY','RU':'КОМПАНИЯ'})
        self.assertEqual([report['report_year'] for report in manifest['reports']],[2020,2021])

    def test_contradictory_translations_are_rejected_instead_of_changing_company_id(self):
        with self.assertRaisesRegex(ValueError,'译名必须一致'):
            build_upload_request([assignment(公司英文名='ONE'),assignment(公司英文名='TWO')],
                [Upload(),Upload('SECOND.pdf',b'%PDF-SECOND')],'SYNTHETIC')


class UploadPageLanguageTests(unittest.TestCase):
    SCRIPT='''from pathlib import Path
import streamlit as st
from financial_workbook.web_upload import render_upload
st.selectbox('Language', ['中文','EN','RU'], key='language')
render_upload(Path('unused-synthetic-output'), [])
'''

    def test_form_and_editor_language_switch_keeps_saved_assignments(self):
        from streamlit.testing.v1 import AppTest
        captures=[]
        def capture(frame,**kwargs):
            captures.append((frame.copy(deep=True),kwargs))
            return frame
        with patch('financial_workbook.web_upload.st.file_uploader',return_value=[Upload()]),\
             patch('financial_workbook.web_upload.st.data_editor',side_effect=capture),\
             patch('financial_workbook.web_upload.start_job',side_effect=AssertionError('Language switch started analysis')) as start:
            app=AppTest.from_string(self.SCRIPT,default_timeout=30).run()
            self.assertFalse(app.exception)
            app.text_input(key='common_company').set_value('原始公司')
            app.text_input(key='common_industry').set_value('原始行业')
            app.selectbox(key='common_standard_中文').set_value('中国企业会计准则')
            next(button for button in app.button if button.label=='将已填写的通用信息应用到清单').click().run()
            self.assertFalse(app.exception)
            for language in ('EN','RU','中文'):
                app.selectbox(key='language').set_value(language).run()
                self.assertFalse(app.exception)
                frame,configuration=captures[-1]
                canonical=canonical_editor_records(frame.to_dict('records'))[0]
                self.assertEqual(canonical['公司'],'原始公司')
                self.assertEqual(canonical['行业'],'原始行业')
                self.assertEqual(canonical['会计准则'],'中国企业会计准则')
                self.assertEqual(app.selectbox(key='common_standard_'+language).value,'中国企业会计准则')
                self.assertTrue(configuration['key'].endswith('_'+language))
                if language!='中文':
                    self.assertNotRegex(configuration['column_config']['公司']['label'],r'[\u4e00-\u9fff]')
            start.assert_not_called()

    def test_invalid_upload_has_selected_language_feedback_and_no_background_job(self):
        from streamlit.testing.v1 import AppTest
        with patch('financial_workbook.web_upload.st.file_uploader',return_value=[Upload()]),\
             patch('financial_workbook.web_upload.st.data_editor',side_effect=lambda frame,**kwargs:frame),\
             patch('financial_workbook.web_upload.start_job',side_effect=AssertionError('Invalid upload started analysis')) as start:
            for language in ('EN','RU'):
                app=AppTest.from_string(self.SCRIPT,default_timeout=30).run()
                app.selectbox(key='language').set_value(language).run()
                app.button(key='start_upload_analysis').click().run()
                self.assertFalse(app.exception)
                self.assertEqual(len(app.error),1)
                self.assertNotRegex(app.error[0].value,r'[\u4e00-\u9fff]')
            start.assert_not_called()


if __name__=='__main__': unittest.main()
