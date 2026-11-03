"""Machine validation is not a human decision. All facts are synthetic."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from financial_workbook.analysis import analyze
from financial_workbook.automatic import check_dataset,validate_sources
from financial_workbook.cli import export_payload,export_workbook
from financial_workbook.models import Dataset, SystemValidation, digest
from financial_workbook.research import ResearchWorkflow
from financial_workbook.research_io import load_project,read_json,approved_bundle,project_lock
from financial_workbook.ui_data import load_run
from financial_workbook.extract import extract
from rag_step1.report import load_report_set
from test_research import make_pdf,metadata
from test_agents import FakeRetriever,ScriptedToolLLM
from test_finance_application import prepare_script
from test_financial_workbook import synthetic_dataset
from test_research import synthetic_bundle


def trial_inputs(bundle):
    return {'company_id':bundle['state']['company_id'],'dataset_fingerprint':bundle['state']['dataset_fingerprint'],
        'analysis_fingerprint':digest(bundle['analysis']),'currency':bundle['currency'],'unit':'currency_base_unit',
        'base_year':2020,'valuation_date':'2020-12-31','base_fcff':'120','growth':'.06','wacc':'.095',
        'terminal_growth':'.025','years':5,'net_debt':'240','shares':'160','confirmed':True,
        'confirmed_by':'SYNTHETIC_TEST_ONLY','rationale':'Synthetic prototype-equivalence test'}


class AutomaticValidationTests(unittest.TestCase):
    def test_validation_is_not_a_human_review(self):
        dataset=synthetic_dataset(); checks,warnings=check_dataset(dataset)
        proof=SystemValidation(dataset_fingerprint=dataset.fingerprint,company_id=dataset.company_id,
            report_set_id=dataset.report_set_id,statement_digests={s.statement_id:digest(s) for s in dataset.statements},checks=checks,warnings=warnings)
        result=analyze(dataset,proof)
        self.assertEqual(result['status'],'validated'); self.assertEqual(result['approved_statements'],0)
        self.assertEqual(result['validated_statements'],6)
        self.assertNotIn('reviewer',proof.model_dump()); self.assertNotIn('decisions',proof.model_dump())
        with tempfile.TemporaryDirectory() as temporary:
            workbook=Path(temporary)/'automatic.xlsx'
            export_workbook(export_payload(dataset,proof,True),workbook)
            from financial_workbook.review import read_xlsx
            sheets=read_xlsx(workbook)
            self.assertIn('系统校验',sheets); self.assertNotIn('审核',sheets)
            with zipfile.ZipFile(workbook) as archive:
                self.assertEqual(len([n for n in archive.namelist() if n.startswith('xl/charts/chart') and n.endswith('.xml')]),5)

    def test_broken_balance_stale_proof_unknown_units_are_rejected(self):
        dataset=synthetic_dataset()
        next(r for s in dataset.statements if s.kind=='BS' for r in s.rows if r.canonical_metric=='assets').values[0]+=1
        with self.assertRaisesRegex(ValueError,'勾稽'): check_dataset(dataset)
        dataset=synthetic_dataset(); dataset.statements[0].currency=None
        with self.assertRaises(ValueError): check_dataset(dataset)
        dataset=synthetic_dataset(); checks,warnings=check_dataset(dataset)
        proof=SystemValidation(dataset_fingerprint='old',company_id=dataset.company_id,report_set_id=dataset.report_set_id,
            statement_digests={},checks=checks)
        with self.assertRaises(ValueError): analyze(dataset,proof)

    def test_dead_project_lock_reclaimed_but_live_lock_is_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary); lock=folder/'.research.lock'
            lock.write_text(json.dumps({'pid':123,'created_at':'SYNTHETIC'}))
            with patch('financial_workbook.research_io.process_alive',return_value=False):
                with project_lock(folder): self.assertTrue(lock.exists())
            with project_lock(folder):
                with self.assertRaises(ValueError):
                    with project_lock(folder): pass

    def test_dead_finalize_lock_reclaimed_but_unknown_owner_is_preserved(self):
        from financial_workbook.service import _exclusive_run
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary); lock=folder/'.finalize.lock'
            lock.write_text(json.dumps({'pid':123,'created_at':'SYNTHETIC'}))
            with patch('financial_workbook.research_io.process_alive',return_value=False):
                with _exclusive_run(folder): self.assertTrue(lock.exists())
            lock.write_text(json.dumps({'pid':123,'created_at':'SYNTHETIC'}))
            with patch('financial_workbook.research_io.process_alive',return_value=None):
                with self.assertRaises(ValueError):
                    with _exclusive_run(folder): pass


class AutomaticWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_pipeline_export_reload_comparison_and_offer_without_human(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary); make_pdf(folder/'A2020.pdf','SYNTHETIC_A',2020,1.2)
            manifest={'confirmed_by':'SYNTHETIC_METADATA_ONLY','companies':[metadata('SYNTHETIC_A')],
                'reports':[{'company_id':'SYNTHETIC_A','report_year':2020,'file_name':'A2020.pdf'}]}
            path=folder/'input.json'; path.write_text(json.dumps(manifest))
            workflow=ResearchWorkflow(); created=workflow.create(path,folder/'projects'); project=Path(created['project_dir'])
            entry=load_project(project)['companies']['SYNTHETIC_A']
            dataset=extract(load_report_set(project/entry['manifest']))
            workflow.llm_factory=lambda:ScriptedToolLLM(prepare_script(dataset))
            with patch('financial_workbook.service.FinancialAnalysisAgent._retriever',return_value=FakeRetriever()),\
                 patch('financial_workbook.agents.extract',return_value=dataset):
                finished=await workflow.analyze_automatically(project,['SYNTHETIC_A'])
            run=project/finished['companies']['SYNTHETIC_A']['run_dir']; state=read_json(run/'run.json')
            self.assertEqual(state['status'],'completed'); self.assertEqual(state['validation_method'],'system')
            self.assertFalse((run/state['last_attempt']/'review.json').exists())
            bundle=load_run(run); self.assertIsNone(bundle['review']); self.assertEqual(bundle['validation']['method'],'system')
            self.assertEqual(approved_bundle(run)['analysis']['status'],'validated')
            self.assertEqual(workflow.history(project,['SYNTHETIC_A'])['mode'],'single_report')
            offer=workflow.offer(project,'SYNTHETIC_A'); self.assertEqual(offer['status'],'awaiting_user_choice')
            with self.assertRaises(ValueError): workflow.value_trial(project,'SYNTHETIC_A',trial_inputs(bundle))
            workflow.decide(project,'SYNTHETIC_A',proceed=True,decided_by='SYNTHETIC_TEST_ONLY')
            trial=workflow.value_trial(project,'SYNTHETIC_A',trial_inputs(bundle))
            self.assertEqual(trial['model'],'fcff_growth_trial')
            self.assertEqual(workflow.list_valuations(project,'SYNTHETIC_A')[0]['result']['model'],'fcff_growth_trial')
            workflow.llm_factory=lambda:self.fail('Completed task repeated paid work')
            await workflow.analyze_automatically(project,['SYNTHETIC_A'])


class TrialTests(unittest.TestCase):
    def test_simplified_trial_matches_independent_prototype_example(self):
        from decimal import Decimal as D
        from financial_workbook.trial_valuation import TrialRequest,calculate_trial
        bundle=synthetic_bundle(); raw=trial_inputs(bundle)
        result=calculate_trial(bundle,metadata(),TrialRequest.model_validate(raw))
        q=D('1.06')/D('1.095')
        expected=D(120)*sum(q**t for t in range(1,6))+D(120)*D('1.06')**5*D('1.025')/(D('.095')-D('.025'))/D('1.095')**5
        self.assertAlmostEqual(float(result['operating_value']),float(expected),places=9)
        self.assertEqual(result['forecasts'][0]['year'],2021)
        self.assertEqual(len(result['sensitivity']),9)

    def test_trial_requires_confirmed_values_and_valid_spread(self):
        from financial_workbook.trial_valuation import TrialRequest
        raw=trial_inputs(synthetic_bundle())
        for key,value in [('confirmed',False),('confirmed',1),('shares',0),('wacc','.01')]:
            with self.assertRaises(ValueError): TrialRequest.model_validate({**raw,key:value})


if __name__=='__main__': unittest.main()
