"""Local report readiness checks must fail before embeddings or paid model calls."""
from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from financial_workbook.errors import ReportSourceError
from financial_workbook.service import FinanceConfig,FinancialAnalysisAgent
from rag_step1.report import load_report_set
from test_research import make_pdf


class ReportPreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_locator_failure_is_saved_before_model_or_index_is_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            source=SimpleNamespace(report_year=2021,pdf_path=root/'sample.pdf',file_name='sample.pdf',
                file_hash='0'*64,verified_printed_pages=(),page_count=200)
            reports=SimpleNamespace(company_id='SYNTHETIC',report_set_id='SYNTHETIC_SET',sources=[source])
            app=FinancialAnalysisAgent(FinanceConfig(output_dir=root/'runs'),
                llm_factory=lambda:self.fail('Preflight failure invoked a model'))
            reason='sample.pdf: 2021 BS 主表存在歧义，候选 PDF 物理页 109、157。'
            with patch.object(app,'_load_sources',return_value=reports),\
                 patch.object(app,'_retriever',side_effect=AssertionError('Preflight failure built RAG')) as retriever,\
                 patch('financial_workbook.extract.locate',side_effect=ValueError(reason)):
                with self.assertRaisesRegex(ReportSourceError,'109、157'):
                    await app.prepare()
            retriever.assert_not_called()
            run=next((root/'runs'/'SYNTHETIC_SET').iterdir())
            state=json.loads((run/'run.json').read_text(encoding='utf-8'))
            check=json.loads((run/'preflight.json').read_text(encoding='utf-8'))
            trace=json.loads((run/'prepare.trace.json').read_text(encoding='utf-8'))
            self.assertEqual(state['status'],'prepare_failed')
            self.assertEqual(state['failure_stage'],'preflight')
            self.assertEqual(check['status'],'failed')
            self.assertIn('109、157',check['detail'])
            self.assertEqual(trace['trace'][0]['event'],'source_error')
            self.assertFalse((run/'candidates.json').exists())

    def test_unextractable_geometry_is_not_deferred_until_after_indexing(self):
        app=FinancialAnalysisAgent()
        with patch('financial_workbook.extract.locate',return_value=['SYNTHETIC_LOCATOR']),\
             patch('financial_workbook.extract.extract',side_effect=ValueError('sample.pdf PDF第110页金额列无法可靠识别')):
            with self.assertRaisesRegex(ReportSourceError,'110页金额列'):
                app._preflight(SimpleNamespace(),{})

    def test_real_pdf_preflight_preserves_sources_without_creating_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); pdf=root/'synthetic2020.pdf'
            make_pdf(pdf,'SYNTHETIC',2020,1.2)
            original=pdf.read_bytes()
            manifest=root/'reports.json'
            manifest.write_text(json.dumps({'company_id':'SYNTHETIC','single_company_confirmed':True,
                'reports':[{'file_name':pdf.name,'report_year':2020}]}),encoding='utf-8')
            reports=load_report_set(manifest)
            summary=FinancialAnalysisAgent()._preflight(reports,{})
            self.assertEqual(summary['status'],'passed')
            self.assertFalse(summary['human_approval'])
            self.assertEqual({s['kind'] for s in summary['statements']},{'BS','IS','CF'})
            self.assertTrue(all(s['rows']>0 and s['pdf_pages'] for s in summary['statements']))
            self.assertEqual(pdf.read_bytes(),original)
            self.assertFalse(list(root.glob('*review*')))


if __name__=='__main__': unittest.main()
