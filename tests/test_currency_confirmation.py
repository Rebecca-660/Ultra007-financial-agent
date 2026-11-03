"""Explicit, source-bound currency metadata; all reports contain synthetic facts."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from financial_workbook.currency_confirmation import confirm_report_currency,merge_report_currencies
from financial_workbook.research import ResearchWorkflow
from financial_workbook.research_io import load_project,read_json
from financial_workbook.research_models import ReportInput,ResearchManifest
from financial_workbook.web_upload import build_upload_request
from rag_step1.report import load_report_set
from test_research import make_pdf,metadata
from test_ultra_web import Upload,row


class CurrencyConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(); self.root=Path(self.temporary.name)
        self.pdf=self.root/'SYNTHETIC2020.pdf'; make_pdf(self.pdf,'SYNTHETIC',2020)
        self.manifest={'confirmed_by':'SYNTHETIC_METADATA_ACTOR','companies':[metadata('SYNTHETIC')],
            'reports':[{'company_id':'SYNTHETIC','report_year':2020,'file_name':self.pdf.name}]}

    def tearDown(self): self.temporary.cleanup()

    def create(self,manifest=None):
        path=self.root/'input.json'; path.write_text(json.dumps(manifest or self.manifest),encoding='utf-8')
        return Path(ResearchWorkflow.create(path,self.root/'projects')['project_dir'])

    def test_optional_currency_has_no_default_and_requires_supported_uppercase_code(self):
        raw=self.manifest['reports'][0]
        self.assertIsNone(ReportInput.model_validate(raw).reporting_currency)
        for invalid in ('cny','RMB','ZZZ',' CNY ',123,''):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError): ReportInput.model_validate({**raw,'reporting_currency':invalid})
        self.assertEqual(ReportInput.model_validate({**raw,'reporting_currency':'USD'}).reporting_currency,'USD')

    def test_upload_optional_currency_is_transmitted_without_guessing(self):
        file=Upload(self.pdf.name,self.pdf.read_bytes())
        blank,_=build_upload_request([row('SYNTHETIC')],[file],'SYNTHETIC_ACTOR')
        self.assertNotIn('reporting_currency',blank['reports'][0])
        filled={**row('SYNTHETIC'),'列报币种':'HKD'}
        chosen,_=build_upload_request([filled],[file],'SYNTHETIC_ACTOR')
        self.assertEqual(ResearchManifest.model_validate(chosen).reports[0].reporting_currency,'HKD')
        with self.assertRaises(ValueError): build_upload_request([{**filled,'列报币种':'RMB'}],[file],'SYNTHETIC_ACTOR')

    def test_intake_creates_hash_bound_profile_and_preserves_pdf(self):
        manifest=deepcopy(self.manifest); manifest['reports'][0]['reporting_currency']='CNY'
        project=self.create(manifest); entry=load_project(project)['companies']['SYNTHETIC']
        reports=load_report_set(project/entry['manifest']); source=reports.sources[0]
        profile=read_json(project/entry['profile'])
        confirmation=profile['report_currencies'][0]
        self.assertEqual(confirmation,{'file_name':source.file_name,'file_hash':source.file_hash,
            'report_year':2020,'currency':'CNY','confirmed_by':'SYNTHETIC_METADATA_ACTOR'})
        self.assertEqual(source.pdf_path.read_bytes(),self.pdf.read_bytes())
        audit=read_json((project/entry['profile']).parent/'currency_confirmation.intake.json')
        self.assertFalse(audit['financial_review'])

    def test_intake_without_currency_does_not_generate_confirmation(self):
        project=self.create(); entry=load_project(project)['companies']['SYNTHETIC']
        self.assertIsNone(entry['profile'])
        self.assertFalse(list(project.rglob('*currency_confirmation*')))

    def test_intake_merges_existing_profile_and_rejects_contradictory_confirmation(self):
        existing={'metric_aliases':{'Synthetic net sales':'revenue'},'report_currencies':[
            {'file_name':self.pdf.name,'file_hash':sha256(self.pdf.read_bytes()).hexdigest(),
             'report_year':2020,'currency':'CNY','confirmed_by':'ORIGINAL_SYNTHETIC_ACTOR'}]}
        (self.root/'adapter.json').write_text(json.dumps(existing),encoding='utf-8')
        manifest=deepcopy(self.manifest)
        manifest['companies'][0]['parser_profile']='adapter.json'
        manifest['reports'][0]['reporting_currency']='USD'
        with self.assertRaisesRegex(ValueError,'冲突'): self.create(manifest)
        manifest['reports'][0]['reporting_currency']='CNY'
        project=self.create(manifest); entry=load_project(project)['companies']['SYNTHETIC']
        self.assertEqual(read_json(project/entry['profile']),existing)

    def test_currency_profile_rejects_stale_hash_or_wrong_annual_period(self):
        from financial_workbook.parsing import validated_profile
        project=self.create(); entry=load_project(project)['companies']['SYNTHETIC']
        reports=load_report_set(project/entry['manifest']); source=reports.sources[0]
        valid={'file_name':source.file_name,'file_hash':source.file_hash,'report_year':2020,
               'currency':'CNY','confirmed_by':'SYNTHETIC_ACTOR'}
        for field,value in [('file_hash','f'*64),('report_year',2021)]:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validated_profile({'report_currencies':[{**valid,field:value}]},reports)

    def test_merge_retains_adapter_config_and_refuses_conflicting_currency(self):
        confirmation={'file_name':self.pdf.name,'file_hash':'a'*64,'report_year':2020,
                      'currency':'CNY','confirmed_by':'SYNTHETIC_ACTOR'}
        profile={'metric_aliases':{'Synthetic net sales':'revenue'}}
        merged=merge_report_currencies(profile,[confirmation])
        self.assertEqual(merged['metric_aliases'],profile['metric_aliases'])
        self.assertNotIn('report_currencies',profile)
        self.assertEqual(merge_report_currencies(merged,[{**confirmation,'confirmed_by':'SECOND_ACTOR'}]),merged)
        with self.assertRaisesRegex(ValueError,'冲突'):
            merge_report_currencies(merged,[{**confirmation,'currency':'USD'}])
        with self.assertRaisesRegex(ValueError,'冲突'):
            merge_report_currencies(merged,[{**confirmation,'file_hash':'b'*64}])

    def test_existing_failed_run_gets_new_profile_without_mutating_snapshot(self):
        project=self.create(); state=load_project(project); entry=state['companies']['SYNTHETIC']
        run=project/'runs'/'SYNTHETIC_SET'/'old_attempt'; run.mkdir(parents=True)
        run_state={'schema_version':'finance-agent-run-v1','status':'validation_failed',
            'files':{'review_workbook':'pending.xlsx','sources':'report_set.snapshot.json'}}
        (run/'run.json').write_text(json.dumps(run_state),encoding='utf-8')
        snapshot={'original':True,'currency_was_not_confirmed':True}
        (run/'parser_profile.snapshot.json').write_text(json.dumps(snapshot),encoding='utf-8')
        before={file.name:file.read_bytes() for file in run.iterdir()}
        entry.update(status='validation_failed',run_dir=str(run.relative_to(project)))
        (project/'project.json').write_text(json.dumps(state),encoding='utf-8')
        result=confirm_report_currency(project,'SYNTHETIC',2020,'CNY','SYNTHETIC_ACTOR')
        after=load_project(project)['companies']['SYNTHETIC']
        self.assertIsNone(after['run_dir']); self.assertEqual(after['status'],'uploaded')
        self.assertEqual({file.name:file.read_bytes() for file in run.iterdir()},before)
        self.assertTrue(Path(result['profile']).is_file()); self.assertTrue(Path(result['confirmation']).is_file())
        audit=read_json(Path(result['confirmation']))
        self.assertEqual(audit['previous_run_dir'],str(run.relative_to(project)))
        self.assertFalse(audit['financial_review'])

    def test_completed_or_running_project_is_not_modified(self):
        project=self.create(); state=load_project(project)
        state['companies']['SYNTHETIC']['status']='completed'
        (project/'project.json').write_text(json.dumps(state),encoding='utf-8')
        before=(project/'project.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'已完成'): confirm_report_currency(project,'SYNTHETIC',2020,'CNY','ACTOR')
        self.assertEqual(before,(project/'project.json').read_bytes())
        state['companies']['SYNTHETIC']['status']='uploaded'
        (project/'project.json').write_text(json.dumps(state),encoding='utf-8')
        with patch('financial_workbook.web_tasks.job_status',return_value={'status':'running'}):
            with self.assertRaisesRegex(ValueError,'仍在运行'): confirm_report_currency(project,'SYNTHETIC',2020,'CNY','ACTOR')

    def test_unknown_year_blank_actor_and_currency_change_are_rejected(self):
        project=self.create()
        with self.assertRaises(ValueError): confirm_report_currency(project,'SYNTHETIC',2019,'CNY','ACTOR')
        with self.assertRaises(ValueError): confirm_report_currency(project,'SYNTHETIC',2020,'CNY',' ')
        confirm_report_currency(project,'SYNTHETIC',2020,'CNY','ACTOR')
        state_before=(project/'project.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'冲突'): confirm_report_currency(project,'SYNTHETIC',2020,'USD','ACTOR')
        self.assertEqual(state_before,(project/'project.json').read_bytes())


if __name__=='__main__': unittest.main()
