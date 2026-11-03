"""Durable task lifecycle tests; synthetic work only, no model or API calls."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from financial_workbook import web_tasks as jobs
from financial_workbook.models import now


def make_project(root: Path):
    root.mkdir(parents=True)
    metadata={'company_id':'SYNTHETIC','name':'Synthetic only','industry':'Fixture',
              'business_type':'non_financial','accounting_standard':'FIXTURE',
              'fiscal_year_end':'12-31','comparability_confirmed':True}
    state={'schema_version':'finance-research-project-v1','project_id':'test-project',
           'companies':{'SYNTHETIC':{'metadata':metadata,'manifest':'sources/manifest.json',
               'profile':None,'report_set_id':'synthetic-set','run_dir':None,'status':'uploaded'}},
           'created_at':now(),'updated_at':now(),'history_exports':[]}
    (root/'project.json').write_text(json.dumps(state),encoding='utf-8')
    return root


class Workflow:
    def __init__(self,progress): self.progress=progress
    async def analyze_automatically(self,project,companies):
        self.progress('核验当前报告来源。')
        self.progress('生成历史分析。')
        return {'status':'completed','companies':companies}


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.project=make_project(Path(self.temporary.name)/'project')
        self.fake_process=type('SyntheticProcess',(),{'pid':os.getpid()})()

    def tearDown(self): self.temporary.cleanup()

    def start(self):
        with patch.object(jobs,'_spawn',return_value=self.fake_process):
            return jobs.start_job(self.project)

    def test_start_is_explicit_poll_is_read_only_and_active_is_deduplicated(self):
        self.assertIsNone(jobs.job_status(self.project))
        with patch.object(jobs,'_spawn',return_value=self.fake_process) as spawn:
            first=jobs.start_job(self.project)
            second=jobs.start_job(self.project)
            self.assertEqual(first['job_id'],second['job_id'])
            self.assertTrue(second['reused']); self.assertEqual(spawn.call_count,1)
        folder=Path(first['job_dir']); before=(folder/'state.json').read_bytes()
        with patch.object(jobs,'_spawn',side_effect=AssertionError('poll spawned work')):
            self.assertEqual(jobs.job_status(self.project)['status'],'queued')
        self.assertEqual(before,(folder/'state.json').read_bytes())

    def test_worker_uses_own_event_loop_and_persists_real_progress(self):
        record=self.start()
        self.assertEqual(jobs._run_worker(self.project,record['job_id'],workflow_factory=Workflow),0)
        result=jobs.job_status(self.project)
        self.assertEqual(result['status'],'completed')
        self.assertEqual([p['message'] for p in result['progress']],['核验当前报告来源。','生成历史分析。'])
        self.assertEqual(result['result']['companies'],['SYNTHETIC'])
        with patch.object(jobs,'_spawn',side_effect=AssertionError('completed duplicate spawned work')):
            self.assertTrue(jobs.start_job(self.project)['reused'])
        self.assertEqual(jobs._run_worker(self.project,record['job_id'],workflow_factory=lambda **_:self.fail('reran terminal worker')),0)

    def test_provider_error_and_progress_do_not_leak_credentials(self):
        class Failure(Workflow):
            async def analyze_automatically(self,project,companies):
                self.progress('Authorization: Bearer sk-SYNTHETIC-SECRET')
                raise RuntimeError('HTTP Authorization Bearer sk-SYNTHETIC-SECRET')
        record=self.start()
        self.assertEqual(jobs._run_worker(self.project,record['job_id'],workflow_factory=Failure),2)
        result=jobs.job_status(self.project)
        self.assertEqual(result['status'],'failed')
        saved=(Path(record['job_dir'])/'state.json').read_text(encoding='utf-8')
        self.assertNotIn('SYNTHETIC-SECRET',saved); self.assertNotIn('Authorization',saved)
        self.assertEqual(result['error_type'],'RuntimeError')

    def test_user_source_error_has_useful_reason(self):
        class Failure(Workflow):
            async def analyze_automatically(self,project,companies):
                raise ValueError('无法可靠识别金额列；请配置原页坐标。')
        record=self.start(); jobs._run_worker(self.project,record['job_id'],workflow_factory=Failure)
        self.assertIn('金额列',jobs.job_status(self.project)['message'])

    def test_typed_source_error_reaches_web_but_untyped_runtime_error_does_not(self):
        from financial_workbook.errors import ReportSourceError
        detail='报表准备失败：sample.pdf PDF第109、157页存在同名主表，请核对期间列。'
        self.assertEqual(jobs._safe_message(ReportSourceError(detail)),detail)
        self.assertNotIn('原始服务内容',jobs._safe_message(RuntimeError('原始服务内容')))
        self.assertNotIn('SYNTHETIC-SECRET',jobs._safe_message(ReportSourceError('Bearer sk-SYNTHETIC-SECRET')))

    def test_dead_worker_is_interrupted_without_mutating_state(self):
        record=self.start(); path=Path(record['job_dir'])/'state.json'; before=path.read_bytes()
        with patch.object(jobs,'_process_info',return_value=(False,None)):
            self.assertEqual(jobs.job_status(self.project)['status'],'interrupted')
        self.assertEqual(before,path.read_bytes())

    def test_pid_reuse_does_not_count_as_alive(self):
        with patch.object(jobs,'_process_info',return_value=(True,'new-process')):
            self.assertFalse(jobs._alive({'pid':123,'creation_identity':'old-process'}))

    def test_no_pid_old_queued_record_does_not_authorize_duplicate(self):
        record=self.start(); folder=Path(record['job_dir'])
        (folder/'process.json').unlink()
        state=json.loads((folder/'state.json').read_text(encoding='utf-8'))
        state['created_at']='2000-01-01T00:00:00+00:00'
        (folder/'state.json').write_text(json.dumps(state),encoding='utf-8')
        self.assertEqual(jobs.job_status(self.project)['status'],'interrupted')
        with patch.object(jobs,'_spawn',side_effect=AssertionError('unknown live process duplicated')):
            with self.assertRaisesRegex(ValueError,'无法证明'): jobs.start_job(self.project)

    def test_launch_failure_is_saved(self):
        with patch.object(jobs,'_spawn',side_effect=OSError('synthetic launch error')):
            result=jobs.start_job(self.project)
        self.assertEqual(result['status'],'failed'); self.assertEqual(result['error_type'],'OSError')

    def test_scope_changes_do_not_reach_workflow(self):
        record=self.start(); path=self.project/'project.json'
        state=json.loads(path.read_text(encoding='utf-8')); state['companies']['SYNTHETIC']['report_set_id']='changed'
        path.write_text(json.dumps(state),encoding='utf-8')
        called=[]
        self.assertEqual(jobs._run_worker(self.project,record['job_id'],workflow_factory=lambda **_:called.append(True)),2)
        self.assertFalse(called); self.assertIn('已变化',jobs.job_status(self.project)['message'])

    def test_duplicate_worker_lock_and_invalid_paths_are_blocked(self):
        record=self.start()
        with jobs._file_lock(Path(record['job_dir'])/'worker.lock'):
            self.assertEqual(jobs._run_worker(self.project,record['job_id'],workflow_factory=Workflow),3)
        with self.assertRaises(ValueError): jobs._job_folder(self.project,'../../outside')
        with self.assertRaises(ValueError): jobs.start_job(self.project,'bad-action')
        with self.assertRaises(ValueError): jobs.start_job(self.project,companies=['UNKNOWN'])
        with self.assertRaises(ValueError): jobs.start_job(self.project,'compare')

    def test_real_child_process_completion_and_recovery(self):
        processes=[]
        code=textwrap.dedent('''
            import asyncio,time,sys
            from pathlib import Path
            from financial_workbook.web_tasks import _run_worker
            class SyntheticWorkflow:
                def __init__(self,progress): self.progress=progress
                async def analyze_automatically(self,project,companies):
                    self.progress('Synthetic phase')
                    await asyncio.sleep(.15)
                    return {'status':'completed','synthetic':True}
            raise SystemExit(_run_worker(Path(sys.argv[1]),sys.argv[2],workflow_factory=SyntheticWorkflow))
        ''')
        def spawn(project,job_id):
            kwargs={'cwd':str(jobs.ROOT),'stdout':subprocess.DEVNULL,'stderr':subprocess.DEVNULL}
            if os.name=='nt': kwargs['creationflags']=subprocess.CREATE_NO_WINDOW
            process=subprocess.Popen([sys.executable,'-c',code,str(project),job_id],**kwargs)
            processes.append(process); return process
        with patch.object(jobs,'_spawn',side_effect=spawn):
            record=jobs.start_job(self.project)
            duplicate=jobs.start_job(self.project)
        self.assertEqual(record['job_id'],duplicate['job_id'])
        self.assertEqual(len(processes),1)
        self.assertEqual(processes[0].wait(timeout=20),0)
        result=jobs.job_status(self.project)
        self.assertEqual(result['status'],'completed'); self.assertTrue(result['result']['synthetic'])
        self.assertEqual(result['progress'][0]['message'],'Synthetic phase')


if __name__=='__main__': unittest.main()
