"""Path relocation preserves immutable financial data and source identity."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from financial_workbook.ui_data import load_run
from test_ui_data import saved_fixture

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from build_portable_bundle import copy_run


class PortableBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.source=saved_fixture(self.root/'sender')

    def test_saved_run_uses_current_folder_without_editing_archive(self):
        path=self.source/'run.json'
        state=json.loads(path.read_text(encoding='utf-8')); state['run_dir']='C:/OLD-COMPUTER/project/run'
        path.write_text(json.dumps(state),encoding='utf-8')
        target=self.root/'Receiver & 新电脑'/'run'
        shutil.copytree(self.source,target)
        original=(target/'run.json').read_bytes()
        bundle=load_run(target)
        self.assertEqual(bundle['state']['run_dir'],str(target.resolve()))
        self.assertEqual((target/'run.json').read_bytes(),original)
        self.assertTrue(Path(bundle['workbook']).is_relative_to(target.resolve()))

    def test_source_snapshot_relocation_keeps_signed_financial_files_identical(self):
        original_pdf=self.root/'sender'/'sources'/'synthetic.pdf'
        original_pdf.parent.mkdir(parents=True); original_pdf.write_bytes(b'SYNTHETIC COPY TEST ONLY')
        snapshot={'company_id':'SYNTHETIC','single_company_confirmed':True,
                  'reports':[{'file_name':str(original_pdf),'file_hash':'f'*64,'report_year':2020}]}
        (self.source/'snapshot.json').write_text(json.dumps(snapshot),encoding='utf-8')
        target_root=self.root/'Receiver & 新电脑'
        target_pdf=target_root/'sources'/'synthetic.pdf'; target_pdf.parent.mkdir(parents=True)
        shutil.copy2(original_pdf,target_pdf)
        target=target_root/'runs'/'completed'
        copy_run(self.source,target,{original_pdf.resolve():target_pdf})
        result=json.loads((target/'snapshot.json').read_text(encoding='utf-8'))
        entry=result['reports'][0]
        self.assertFalse(Path(entry['file_name']).is_absolute())
        self.assertEqual((target/entry['file_name']).resolve(),target_pdf.resolve())
        self.assertEqual(entry['file_hash'],'f'*64)
        for relative in ('candidates.json','finalize_fixture/analysis.json','finalize_fixture/review.json'):
            self.assertEqual((self.source/relative).read_bytes(),(target/relative).read_bytes())
        self.assertEqual(json.loads((self.source/'snapshot.json').read_text(encoding='utf-8')),snapshot)

    def test_unmapped_original_pdf_is_rejected_instead_of_reusing_sender_path(self):
        (self.source/'snapshot.json').write_text(json.dumps({'reports':[{'file_name':'C:/SENDER/report.pdf'}]}),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'required PDF'):
            copy_run(self.source,self.root/'receiver'/'run',{})


if __name__=='__main__': unittest.main()
