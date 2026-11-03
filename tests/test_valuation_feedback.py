"""User-facing validation uses synthetic data and never confirms real inputs."""
from copy import deepcopy
from decimal import Decimal as D
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from financial_workbook.web_valuation import (translator,build_trial_request,result_text,
    COPY,FORECAST_KEYS,build_request)
from financial_workbook.web_valuation_validation import trial_issues,full_issues
from financial_workbook.trial_valuation import TrialRequest,calculate_trial
from financial_workbook.research_models import ValuationRequest
from financial_workbook.valuation import value_company
from test_research import synthetic_bundle,assumptions,metadata


def screenshot_values():
    return {'actor':'A','base_fcff':'4','growth':'12','wacc':'11','terminal_growth':'3',
        'net_debt':'40000000','shares':'2000','years':2,'rationale':''}


def full_inputs():
    raw=assumptions(synthetic_bundle()); scenario=raw['scenarios'][0]
    values={'actor':'SYNTHETIC TEST','nwc':'12','nwc_basis':'SYNTHETIC TEST',
        'bridge_basis':'SYNTHETIC TEST','overall_basis':'SYNTHETIC TEST',
        'Base_mode':'direct','Base_wacc':'10','Base_rate_basis':'SYNTHETIC TEST',
        'Base_terminal_basis':'SYNTHETIC TEST','Base_sensitivity_wacc':'1,10,12',
        'Base_sensitivity_growth':'2,3'}
    for key,value in raw['bridge'].items():
        if key not in ('as_of','rationale'): values[key]='' if key=='market_price' else str(value)
    for key,value in scenario['terminal'].items():
        if key!='rationale': values['Base_terminal_'+key]=str(D(value)*100)
    grid=[{key:(str(D(value)*100) if key not in ('year','rationale') else value)
           for key,value in row.items()} for row in scenario['forecasts']]
    return values,{'Base':grid}


class ValuationFieldValidationTests(unittest.TestCase):
    def test_exact_screenshot_only_lacks_required_rationale(self):
        for language in ('中文','EN','RU'):
            issues=trial_issues(screenshot_values(),translator(language))
            self.assertEqual(set(issues),{'rationale'})
            if language!='中文': self.assertFalse(re.search('[\u4e00-\u9fff]',str(issues)))
        bundle=synthetic_bundle()
        raw=build_trial_request(bundle,bundle['state']['company_id'],screenshot_values(),2020,'2020-12-31')
        with self.assertRaises(ValidationError): TrialRequest.model_validate({**raw,'confirmed':True})

    def test_same_numbers_with_explicit_test_rationale_calculate_negative_equity(self):
        values={**screenshot_values(),'rationale':'Synthetic functional test only'}
        self.assertEqual(trial_issues(values,translator('EN')),{})
        bundle=synthetic_bundle()
        raw=build_trial_request(bundle,bundle['state']['company_id'],values,2020,'2020-12-31')
        result=calculate_trial(bundle,metadata(),TrialRequest.model_validate({**raw,'confirmed':True}))
        self.assertGreater(D(result['operating_value']),0)
        self.assertLess(D(result['equity_value']),0)
        self.assertIsNone(result['per_share_value'])

    def test_range_and_cross_field_errors_point_to_inputs(self):
        values={**screenshot_values(),'rationale':'Synthetic test','wacc':'3','shares':'0','growth':'NaN'}
        issues=trial_issues(values,translator('EN'))
        self.assertEqual(set(issues),{'wacc','terminal_growth','shares','growth'})
        self.assertIn('WACC must exceed',issues['wacc'][0])
        self.assertIn('greater than 0',issues['shares'][0])

    def test_full_optional_price_can_stay_blank_and_absent_bridge_amounts_require_zero(self):
        values,grids=full_inputs()
        self.assertEqual(full_issues(values,grids,['Base'],1,2020,translator('EN')),{})
        values['non_operating_assets']=''
        issues=full_issues(values,grids,['Base'],1,2020,translator('EN'))
        self.assertIn('non_operating_assets',issues)
        self.assertNotIn('market_price',issues)
        values['non_operating_assets']='0'; values['market_price']='-1'
        self.assertIn('market_price',full_issues(values,grids,['Base'],1,2020,translator('EN')))

    def test_forecast_cell_feedback_names_year_and_column_in_each_language(self):
        values,grids=full_inputs()
        grids['Base'][0]['cash_tax_rate']=None
        grids['Base'][0]['rationale']=''
        for language in ('中文','EN','RU'):
            t=translator(language)
            issues=full_issues(values,grids,['Base'],1,2020,t)
            self.assertEqual(set(issues),{'Base_forecast'})
            self.assertTrue(any('2021' in message and t('cash_tax_rate') in message for message in issues['Base_forecast']))
            if language!='中文': self.assertFalse(re.search('[\u4e00-\u9fff]',str(issues)))

    def test_components_use_existing_wacc_calculator_and_report_required_parts(self):
        values,grids=full_inputs(); values['Base_mode']='components'
        component_values={'risk_free_rate':'3','beta':'1','equity_risk_premium':'5','country_risk_premium':'0',
            'pretax_cost_of_debt':'4','debt_tax_rate':'25','market_equity':'100','market_debt':'50'}
        values.update({'Base_'+key:value for key,value in component_values.items()})
        self.assertEqual(full_issues(values,grids,['Base'],1,2020,translator('EN')),{})
        values['Base_country_risk_premium']=''
        self.assertIn('Base_country_risk_premium',full_issues(values,grids,['Base'],1,2020,translator('EN')))
        values['Base_country_risk_premium']='0'; values['Base_terminal_growth']='7'
        issues=full_issues(values,grids,['Base'],1,2020,translator('EN'))
        self.assertIn('Base_rate_basis',issues); self.assertIn('Base_terminal_growth',issues)

    def test_full_grid_duplicates_and_roic_constraint_have_field_locations(self):
        values,grids=full_inputs()
        values['Base_sensitivity_wacc']='10,10'
        values['Base_terminal_return_on_invested_capital']='1'
        issues=full_issues(values,grids,['Base'],1,2020,translator('RU'))
        self.assertIn('Base_sensitivity_wacc',issues)
        self.assertIn('Base_terminal_return_on_invested_capital',issues)
        self.assertIn('Base_terminal_growth',issues)
        self.assertFalse(re.search('[\u4e00-\u9fff]',str(issues)))

    def test_program_generated_result_notes_are_localized(self):
        bundle=synthetic_bundle()
        trial_raw=build_trial_request(bundle,bundle['state']['company_id'],
            {**screenshot_values(),'rationale':'SYNTHETIC ONLY'},2020,'2020-12-31')
        trial=calculate_trial(bundle,metadata(),TrialRequest.model_validate({**trial_raw,'confirmed':True}))
        full=value_company(bundle,metadata(),ValuationRequest.model_validate(assumptions(bundle)))
        strings=trial['limitations']+full['limitations']+full['conclusions']
        strings.extend(note for scenario in full['scenarios'] for note in scenario['observations'])
        strings.extend(cell['reason'] for scenario in full['scenarios'] for cell in scenario['sensitivity'])
        for language in ('EN','RU'):
            self.assertTrue(all(not re.search('[\u4e00-\u9fff]',result_text(value,translator(language))) for value in strings))


class ValuationFeedbackPageTests(unittest.TestCase):
    def setUp(self):
        from test_web_valuation import ValuationPageTests
        self.fixture=ValuationPageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def trial_app(self):
        app=self.fixture.app().run()
        app.radio(key=self.fixture.scope+'_model_zh').set_value('trial').run()
        return app,self.fixture.scope+'_trial'

    def fill_trial(self,app,scope,*,rationale=''):
        values={**screenshot_values(),'rationale':rationale}
        app.number_input(key=scope+'_years').set_value(values.pop('years'))
        for key,value in values.items(): app.text_input(key=scope+'_'+key).set_value(value)
        return app.run()

    def test_initial_form_has_markers_without_red_missing_warnings(self):
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.fixture.offer):
            app,scope=self.trial_app()
            self.assertFalse(app.exception)
            self.assertTrue(all('必填' in element.label for element in app.text_input))
            self.assertFalse(any(':red[' in element.value for element in app.markdown))

    def test_missing_rationale_is_red_next_to_field_and_blocks_backend(self):
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.fixture.offer),\
             patch('financial_workbook.research.ResearchWorkflow.value_trial') as value:
            app,scope=self.trial_app(); self.fill_trial(app,scope)
            app.checkbox(key=scope+'_confirmed').check().run()
            app.button(key=scope+'_calculate').click().run()
            self.assertFalse(app.exception); value.assert_not_called()
            self.assertEqual(len(app.error),1)
            self.assertTrue(any(':red[' in item.value and '必填' in item.value for item in app.markdown))
            self.assertTrue(any('整体假设与适用边界' in item.value for item in app.markdown))
            self.assertFalse(any('String should have' in item.value or 'rationale ·' in item.value for item in app.caption))
            app.selectbox(key='test_language').set_value('RU').run()
            self.assertFalse(app.exception)
            self.assertTrue(any(':red[' in item.value and 'Обязательно' in item.value for item in app.markdown))
            self.assertFalse(any(re.search('[\u4e00-\u9fff]',str(item.value)) for item in app.error))

    def test_after_entering_own_rationale_negative_equity_is_a_success(self):
        captured=[]
        def calculate(project,cid,parameters):
            captured.append(parameters)
            result=calculate_trial(self.fixture.bundle,metadata(),TrialRequest.model_validate(parameters))
            folder=self.fixture.invitation/'valuation_test_negative'; folder.mkdir()
            (folder/'valuation.json').write_text(json.dumps(result),encoding='utf-8')
            return {'output_dir':str(folder)}
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.fixture.offer),\
             patch('financial_workbook.research.ResearchWorkflow.value_trial',side_effect=calculate):
            app,scope=self.trial_app(); self.fill_trial(app,scope,rationale='Synthetic functional test only')
            app.checkbox(key=scope+'_confirmed').check().run()
            app.button(key=scope+'_calculate').click().run()
            self.assertFalse(app.exception); self.assertFalse(app.error)
            self.assertEqual(len(captured),1); self.assertTrue(app.success)
            self.assertTrue(any('权益残值不为正' in item.value for item in app.caption))
            self.assertTrue(any(element.value=='—' for element in app.metric))
            app.selectbox(key='test_language').set_value('EN').run()
            self.assertTrue(any('Residual equity is not positive' in item.value for item in app.caption))
            self.assertTrue(all(not re.search('[\u4e00-\u9fff]',item.value) for item in app.caption))

    def test_full_error_expands_sections_and_marks_price_optional(self):
        scope=self.fixture.formscope
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.fixture.offer),\
             patch('financial_workbook.research.ResearchWorkflow.value') as value:
            app=self.fixture.app().run()
            self.assertIn('选填',app.text_input(key=scope+'_market_price').label)
            app.checkbox(key=scope+'_confirmed').check().run()
            app.button(key=scope+'_calculate').click().run()
            self.assertFalse(app.exception); value.assert_not_called()
            bridge=next(element for element in app.expander if '普通股权益' in element.label)
            self.assertTrue(bridge.proto.expanded)
            self.assertTrue(any(':red[' in item.value for item in app.markdown))
            self.assertFalse(any('估值日参考股价' in item.value for item in app.markdown))

    def test_complete_full_form_accepts_blank_optional_price_and_localizes_results(self):
        values,grids=full_inputs(); captured=[]
        draft={'scope':self.fixture.formscope,'base_year':2020,'horizon':1,'scenarios':['Base'],
            'values':values,'grids':grids}
        (self.fixture.invitation/'web_draft.json').write_text(json.dumps(draft),encoding='utf-8')
        def calculate(project,cid,parameter_path):
            raw=json.loads(Path(parameter_path).read_text(encoding='utf-8'))
            captured.append(raw)
            result=value_company(self.fixture.bundle,metadata(),ValuationRequest.model_validate(raw))
            folder=self.fixture.invitation/'valuation_full_feedback'; folder.mkdir()
            (folder/'valuation.json').write_text(json.dumps(result),encoding='utf-8')
            return {'output_dir':str(folder)}
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.fixture.offer),\
             patch('financial_workbook.research.ResearchWorkflow.value',side_effect=calculate):
            app=self.fixture.app().run(); scope=self.fixture.formscope
            app.checkbox(key=scope+'_confirmed').check().run()
            app.button(key=scope+'_calculate').click().run()
            self.assertFalse(app.exception); self.assertFalse(app.error)
            self.assertEqual(len(captured),1)
            self.assertIsNone(captured[0]['bridge']['market_price'])
            self.assertTrue(app.success)
            for language in ('EN','RU'):
                app.selectbox(key='test_language').set_value(language).run()
                self.assertFalse(app.exception)
                self.assertTrue(all(not re.search('[\u4e00-\u9fff]',item.value) for item in app.caption))
                self.assertTrue(all(not re.search('[\u4e00-\u9fff]',item.value) for item in app.markdown))

    def test_scenario_choices_follow_latest_selection_across_language_round_trips(self):
        with patch('financial_workbook.research.ResearchWorkflow.offer',return_value=self.fixture.offer):
            app=self.fixture.app().run()
            app.selectbox(key='test_language').set_value('EN').run()
            app.multiselect[0].set_value(['Base','Bear']).run()
            app.selectbox(key='test_language').set_value('RU').run()
            self.assertEqual(app.multiselect[0].value,['Base','Bear'])
            app.multiselect[0].set_value(['Bull']).run()
            app.selectbox(key='test_language').set_value('EN').run()
            self.assertEqual(app.multiselect[0].value,['Bull'])
            self.assertFalse(app.exception)
