"""Explicit confirmation recording tests; all approvals here are synthetic."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_financial_workbook import synthetic_dataset
from scripts import record_user_confirmation as recorder


class UserConfirmationTests(unittest.TestCase):
    def setup_run(self,folder):
        dataset=synthetic_dataset()
        (folder/'candidates.json').write_text(dataset.model_dump_json(),encoding='utf-8')
        state={'schema_version':'finance-agent-run-v1','status':'needs_human_review',
               'dataset_fingerprint':dataset.fingerprint,
               'files':{'candidates':'candidates.json','sources':'sources.json','review_workbook':'pending.xlsx'}}
        (folder/'run.json').write_text(json.dumps(state),encoding='utf-8')
        confirmation={'dataset_fingerprint':dataset.fingerprint,'statement_count':len(dataset.statements),
            'decision':'approved','conflict_resolution':'as_reported','reviewer':'Synthetic reviewer',
            'statement':'Synthetic explicit approval of all fixture tables.','source':'Synthetic test fixture'}
        return dataset,confirmation

    def call_recorder(self,folder,confirmation):
        path=folder/'confirmation.json'
        path.write_text(json.dumps(confirmation),encoding='utf-8')
        with patch.object(sys,'argv',['record_user_confirmation','--run-dir',str(folder),'--confirmation',str(path)]):
            recorder.main()

    def test_stale_confirmation_is_rejected_before_source_access(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); _,confirmation=self.setup_run(folder)
            confirmation['dataset_fingerprint']='old-version'
            with patch.object(recorder,'load_report_set') as load:
                with self.assertRaisesRegex(ValueError,'version and scope'):
                    self.call_recorder(folder,confirmation)
                load.assert_not_called()
            self.assertFalse(list(folder.glob('human_confirmation_*')))

    def test_wrong_scope_and_empty_human_statement_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); _,confirmation=self.setup_run(folder)
            confirmation['statement_count']=0
            with self.assertRaises(ValueError): self.call_recorder(folder,confirmation)
            confirmation['statement_count']=6; confirmation['statement']=' '
            with self.assertRaisesRegex(ValueError,'actual human statement'):
                self.call_recorder(folder,confirmation)
            self.assertFalse(list(folder.glob('human_confirmation_*')))

    def test_explicit_fixture_approval_is_preserved_and_round_trips(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); dataset,confirmation=self.setup_run(folder)
            original=(folder/'candidates.json').read_bytes()
            output=io.StringIO()
            with patch.object(recorder,'load_report_set'),patch.object(recorder,'assert_sources'),\
                 patch('financial_workbook.review.assert_sources'),redirect_stdout(output):
                self.call_recorder(folder,confirmation)
            result=json.loads(output.getvalue())
            self.assertEqual(result['approved_statements'],6)
            saved=json.loads(Path(result['confirmation_record']).read_text(encoding='utf-8'))
            self.assertEqual(saved['statement'],confirmation['statement'])
            self.assertEqual(saved['dataset_fingerprint'],dataset.fingerprint)
            self.assertEqual(len(saved['statement_ids']),6)
            self.assertTrue(Path(result['review_workbook']).is_file())
            self.assertEqual((folder/'candidates.json').read_bytes(),original)


if __name__=='__main__': unittest.main()
