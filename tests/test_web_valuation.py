"""Valuation views use synthetic facts and explicit decisions only."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from financial_workbook.research_models import ValuationRequest
from financial_workbook.web_valuation import (build_request,numeric,percentage_list,
    valuation_scope,list_saved_versions,build_trial_request)
from test_research import synthetic_bundle,assumptions,metadata


class ValuationConversionTests(unittest.TestCase):
    def test_percentages_blank_zero_and_nonfinite(self):
        self.assertEqual(numeric('5',percentage=True),'0.05')
        self.assertEqual(numeric('0'),'0'); self.assertIsNone(numeric(''))
        self.assertEqual(percentage_list('8，9.5,11'),['0.08','0.095','0.11'])
        for value in ('NaN','Infinity',True,'5%'):
            with self.assertRaises(ValueError): numeric(value)

    def test_complete_draft_preserves_inputs_and_requires_new_confirmation(self):
        raw=assumptions(synthetic_bundle()); scenario=raw['scenarios'][0]
        values={'actor':'synthetic-tester','nwc':'12','nwc_basis':'SYNTHETIC','bridge_basis':'SYNTHETIC',
            'overall_basis':'SYNTHETIC',**{k:str(v) if v is not None else '' for k,v in raw['bridge'].items()},
            'Base_mode':'direct','Base_wacc':'10','Base_rate_basis':'SYNTHETIC','Base_terminal_basis':'SYNTHETIC',
            'Base_sensitivity_wacc':'10,12','Base_sensitivity_growth':'2,3'}
        for key,value in scenario['terminal'].items():
            if key!='rationale': values['Base_terminal_'+key]=str(Decimal(value)*100)
        grid=[{k:(str(Decimal(v)*100) if k not in ('year','rationale') else v) for k,v in row.items()}
              for row in scenario['forecasts']]
        draft=build_request(raw,values,{'Base':grid},['Base'],2020,'2020-12-31')
        self.assertFalse(draft['confirmed'])
        self.assertEqual(draft['scenarios'][0]['forecasts'][0]['revenue_growth'],'0.1')
        self.assertEqual(draft['bridge']['diluted_shares'],'10')
        with self.assertRaises(ValidationError): ValuationRequest.model_validate(draft)
        ValuationRequest.model_validate({**draft,'confirmed':True})

    def test_scope_isolates_company_and_analysis_version(self):
        bundle=synthetic_bundle(); first=valuation_scope(Path.cwd(),'A',bundle)
        self.assertNotEqual(first,valuation_scope(Path.cwd(),'B',bundle))
        other=deepcopy(bundle); other['analysis']['cagr']['reason']='different'
        self.assertNotEqual(first,valuation_scope(Path.cwd(),'A',other))

    def test_saved_model_versions_and_stale_inputs_are_separated(self):
        bundle=synthetic_bundle()
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            for name,model,fingerprint in [('full','',bundle['state']['dataset_fingerprint']),
                ('trial','fcff_growth_trial',bundle['state']['dataset_fingerprint']),('old','','stale')]:
                target=folder/('valuation_'+name); target.mkdir()
                result={'model':model,'dataset_fingerprint':fingerprint,'analysis_fingerprint':__import__('financial_workbook.models',fromlist=['digest']).digest(bundle['analysis'])}
                (target/'valuation.json').write_text(json.dumps(result),encoding='utf-8')
            self.assertEqual(len(list_saved_versions(folder,bundle)),1)
            self.assertEqual(len(list_saved_versions(folder,bundle,'trial')),1)


class ValuationPageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.project=Path(self.temp.name)
        self.bundle=synthetic_bundle(); self.cid=self.bundle['state']['company_id']
        self.scope=valuation_scope(self.project,self.cid,self.bundle)
        self.formscope=self.scope+'_full'
        state={'schema_version':'finance-research-project-v1','companies':{self.cid:{
            'metadata':metadata(),'manifest':'sources.json','profile':None,'run_dir':None}}}
        (self.project/'project.json').write_text(json.dumps(state),encoding='utf-8')
        self.invitation=self.project/'investment'/'synthetic'; self.invitation.mkdir(parents=True)
        self.offer={'status':'accepted','decided_by':'synthetic-tester','invitation_dir':str(self.invitation),
                    'eligible':True,'company_id':self.cid}

    def tearDown(self): self.temp.cleanup()

    def app(self):
        from streamlit.testing.v1 import AppTest
        code='''import json
from pathlib import Path
import streamlit as st
from financial_workbook.web_valuation import render_valuation
language=st.selectbox("test language",["中文","EN","RU"],key="test_language")
theme=st.selectbox("test theme",["light","dark"],key="test_theme")
render_valuation(Path(PROJECT),COMPANY,json.loads(BUNDLE),theme=theme,language=language)
'''.replace('PROJECT',repr(str(self.project))).replace('COMPANY',repr(self.cid)).replace('BUNDLE',repr(json.dumps(self.bundle)))
        return AppTest.from_string(code,default_timeout=30)

    def test_pending_choice_requires_actor_and_does_not_invoke_valuation(self):
        self.offer['status']='awaiting_user_choice'
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.offer),\
             patch('financial_workbook.research.ResearchWorkflow.decide') as decide,\
             patch('financial_workbook.research.ResearchWorkflow.value') as value:
            app=self.app().run(); self.assertFalse(app.exception)
            app.button(key=self.scope+'_proceed').click().run()
            self.assertTrue(app.warning); decide.assert_not_called(); value.assert_not_called()

    def test_declined_never_renders_or_reads_parameters(self):
        self.offer['status']='declined'
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.offer),\
             patch('financial_workbook.research.ResearchWorkflow.value') as value:
            app=self.app().run(); self.assertFalse(app.exception)
            self.assertFalse(app.text_input); self.assertFalse(app.checkbox); value.assert_not_called()

    def test_draft_confirmation_invalidation_and_language_theme_preserve_inputs(self):
        scope=self.formscope
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.offer),\
             patch('financial_workbook.research.ResearchWorkflow.value') as value:
            app=self.app().run(); self.assertFalse(app.exception)
            self.assertEqual(app.text_input(key=scope+'_nwc').value,'')
            app.text_input(key=scope+'_nwc').set_value('123.45').run()
            app.checkbox(key=scope+'_confirmed').check().run()
            self.assertTrue(app.checkbox(key=scope+'_confirmed').value)
            app.selectbox(key='test_language').set_value('EN').run()
            self.assertEqual(app.text_input(key=scope+'_nwc').value,'123.45')
            app.selectbox(key='test_theme').set_value('dark').run()
            self.assertEqual(app.text_input(key=scope+'_nwc').value,'123.45')
            app.text_input(key=scope+'_nwc').set_value('124').run()
            self.assertFalse(app.checkbox(key=scope+'_confirmed').value)
            value.assert_not_called()

    def test_incomplete_parameters_do_not_execute_valuation(self):
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.offer),\
             patch('financial_workbook.research.ResearchWorkflow.value') as value:
            app=self.app().run(); app.checkbox(key=self.formscope+'_confirmed').check().run()
            app.button(key=self.formscope+'_calculate').click().run()
            self.assertFalse(app.exception); self.assertTrue(app.error); value.assert_not_called()

    def test_saved_draft_recovers_after_new_session_and_model_navigation(self):
        scope=self.formscope
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.offer):
            app=self.app().run()
            app.text_input(key=scope+'_nwc').set_value('987.65').run()
            app.number_input(key=scope+'_horizon').set_value(3).run()
            app.radio(key=self.scope+'_model_zh').set_value('trial').run()
            app.radio(key=self.scope+'_model_zh').set_value('full').run()
            self.assertEqual(app.text_input(key=scope+'_nwc').value,'987.65')
            self.assertEqual(app.number_input(key=scope+'_horizon').value,3)
            fresh=self.app().run()
            self.assertFalse(fresh.exception)
            self.assertEqual(fresh.text_input(key=scope+'_nwc').value,'987.65')
            self.assertEqual(fresh.number_input(key=scope+'_horizon').value,3)
            self.assertFalse(fresh.checkbox(key=scope+'_confirmed').value)

    def test_trial_form_submits_explicit_confirmed_parameters_and_invalidates(self):
        from financial_workbook.trial_valuation import TrialRequest,calculate_trial
        scope=self.scope+'_trial'
        captured=[]
        def value_trial(project,cid,parameters):
            captured.append(parameters)
            result=calculate_trial(self.bundle,metadata(),TrialRequest.model_validate(parameters))
            folder=self.invitation/'valuation_trial_fixture'; folder.mkdir()
            (folder/'valuation.json').write_text(json.dumps(result),encoding='utf-8')
            return {'output_dir':str(folder),'workbook':str(folder/'trial.xlsx')}
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.offer),\
             patch('financial_workbook.research.ResearchWorkflow.value_trial',side_effect=value_trial):
            app=self.app().run()
            app.radio(key=self.scope+'_model_zh').set_value('trial').run()
            app.number_input(key=scope+'_years').set_value(5).run()
            for key,value in {'base_fcff':'120','growth':'6','wacc':'9.5','terminal_growth':'2.5',
                              'net_debt':'240','shares':'160','rationale':'SYNTHETIC ONLY'}.items():
                app.text_input(key=scope+'_'+key).set_value(value)
            app.run(); app.checkbox(key=scope+'_confirmed').check().run()
            app.button(key=scope+'_calculate').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(captured),1)
            self.assertTrue(captured[0]['confirmed'])
            self.assertEqual(captured[0]['wacc'],'0.095')
            self.assertEqual(len(app.metric),6)  # current result and saved historical version
            app.text_input(key=scope+'_growth').set_value('7').run()
            self.assertFalse(app.checkbox(key=scope+'_confirmed').value)
            self.assertTrue(any('参数已变化' in x.value for x in app.info))

    def test_trial_model_and_inputs_survive_english_and_russian_switches(self):
        scope=self.scope+'_trial'
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.offer):
            app=self.app().run()
            app.radio(key=self.scope+'_model_zh').set_value('trial').run()
            app.text_input(key=scope+'_base_fcff').set_value('123.45').run()
            app.number_input(key=scope+'_years').set_value(5).run()
            for language,token in [('EN','en'),('RU','ru'),('中文','zh')]:
                app.selectbox(key='test_language').set_value(language).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state[self.scope+'_model_canonical'],'trial')
                self.assertEqual(app.radio(key=self.scope+'_model_'+token).value,'trial')
                self.assertEqual(app.text_input(key=scope+'_base_fcff').value,'123.45')
                self.assertEqual(app.number_input(key=scope+'_years').value,5)

    def test_discount_components_remain_selected_when_language_changes(self):
        scope=self.formscope
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.offer):
            app=self.app().run()
            app.radio(key=scope+'_Base_mode_zh').set_value('components').run()
            app.text_input(key=scope+'_Base_risk_free_rate').set_value('3.5').run()
            for language,token in [('EN','en'),('RU','ru'),('中文','zh')]:
                app.selectbox(key='test_language').set_value(language).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.radio(key=scope+'_Base_mode_'+token).value,'components')
                self.assertEqual(app.session_state[scope+'_Base_mode_canonical'],'components')
                self.assertEqual(app.text_input(key=scope+'_Base_risk_free_rate').value,'3.5')

    def test_model_choice_recovers_fresh_session_without_confirmation(self):
        scope=self.scope+'_trial'
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.offer):
            app=self.app().run()
            app.radio(key=self.scope+'_model_zh').set_value('trial').run()
            app.text_input(key=scope+'_base_fcff').set_value('456.78').run()
            app.checkbox(key=scope+'_confirmed').check().run()
            self.assertTrue(app.checkbox(key=scope+'_confirmed').value)
            preference=json.loads((self.invitation/'web_model_choice.json').read_text(encoding='utf-8'))
            self.assertEqual(preference,{'scope':self.scope,'model':'trial'})
            fresh=self.app().run()
            self.assertFalse(fresh.exception)
            self.assertEqual(fresh.radio(key=self.scope+'_model_zh').value,'trial')
            self.assertEqual(fresh.text_input(key=scope+'_base_fcff').value,'456.78')
            self.assertFalse(fresh.checkbox(key=scope+'_confirmed').value)


if __name__=='__main__': unittest.main()
