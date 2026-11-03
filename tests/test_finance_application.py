"""Application regressions, intended for the user's local test run.

All financial facts/reviews are synthetic fixtures. No live API is called.
Scripted provider responses still execute actual FunctionAgent workflows.
"""
import asyncio
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

import pymupdf

from test_agents import ScriptedToolLLM,FakeRetriever
from test_financial_workbook import synthetic_dataset,approve_synthetic
from financial_workbook.agents import WorkbookAgents
from financial_workbook.analysis import analyze
from financial_workbook.cli import export_payload
from financial_workbook.excel_export import export_xlsx
from financial_workbook.extract import extract,_column_metadata
from financial_workbook.models import Dataset,Locator,Review,digest
from financial_workbook.parsing import validated_profile,unit_metadata
from financial_workbook.review import assert_sources,import_review,read_xlsx
from financial_workbook.service import FinanceConfig,FinancialAnalysisAgent
from financial_workbook.workbook_schema import table_layout,column_name
from rag_step1.report import load_report_set

HAS_XLSXWRITER=importlib.util.find_spec('xlsxwriter') is not None


def tool(name): return {'tool':name,'kwargs':{}}
def handoff(status,ids): return json.dumps({'status':status,'ids':ids})


def prepare_script(dataset):
    ids=[s.statement_id for s in dataset.statements]
    located=[f'{s.report_year}_{s.kind}' for s in dataset.statements]
    return [tool('delegate_evidence'),tool('retrieve_statement_pages'),handoff('located',located),
            tool('delegate_extraction'),tool('extract_complete_statements'),handoff('extracted',ids),
            handoff('needs_human_review',ids)]


def finalize_script(dataset,review):
    ids=[s.statement_id for s in dataset.statements]
    result_ids=[dataset.fingerprint,digest(analyze(dataset,review))]
    return [tool('delegate_validation'),tool('validate_approved_sources'),handoff('validated',ids),
            tool('delegate_analysis'),tool('calculate_historical_metrics'),handoff('analyzed',result_ids),
            tool('export_analysis_excel'),handoff('exported',result_ids)]


def locators(dataset):
    return [Locator(report_year=s.report_year,kind=s.kind,file_name=s.file_name,file_hash=s.file_hash,pdf_pages=s.pdf_pages)
            for s in dataset.statements]


class GeneralFinancialRulesTests(unittest.TestCase):
    def test_separate_currency_disclosure_is_preserved(self):
        page=SimpleNamespace(get_text=lambda:'合并资产负债表\n单位：万元\n币种：人民币\n')
        raw,currency,scale=unit_metadata(page)
        self.assertIn('币种：人民币',raw)
        self.assertEqual(currency,'CNY')
        self.assertEqual(scale,Decimal('10000'))

    def test_multiple_years_and_nonleading_current_column(self):
        dataset=synthetic_dataset()
        for statement in dataset.statements:
            year=statement.report_year
            statement.columns=_column_metadata([str(year-2),str(year-1),str(year)],year,statement.kind)
            for row in statement.rows:
                current,prior=row.values
                row.values=[prior*Decimal('.8'),prior,current]
                row.raw_values=[str(v) for v in row.values]
        result=analyze(dataset,approve_synthetic(dataset))
        metric=next(r for r in result['results'] if r['year']==2020 and r['name']=='营业收入同比')
        self.assertEqual(Decimal(metric['value']),Decimal('.2'))
        self.assertEqual(result['inputs']['2020']['revenue']['source']['column'],2)
        layout=table_layout(dataset.statements[0])
        self.assertEqual(layout.originals,(2,3,4))
        self.assertEqual(column_name(layout.reason),'L')

    def test_negative_expenses_require_explicit_convention(self):
        dataset=synthetic_dataset()
        for statement in dataset.statements:
            for row in statement.rows:
                if row.canonical_metric in ('cost_of_sales','capex'):
                    row.values=[-v for v in row.values]
                    row.raw_values=[str(v) for v in row.values]
        result=analyze(dataset,approve_synthetic(dataset))
        self.assertIsNone(next(r for r in result['results'] if r['year']==2020 and r['name']=='毛利率')['value'])
        dataset.extraction_profile={'outflow_signs':{'cost_of_sales':'negative','capex':'negative'}}
        result=analyze(dataset,approve_synthetic(dataset))
        self.assertEqual(Decimal(next(r for r in result['results'] if r['year']==2020 and r['name']=='毛利率')['value']),Decimal('.4'))
        self.assertEqual(Decimal(next(r for r in result['results'] if r['year']==2020 and r['name']=='简化自由现金流')['value']),Decimal('20.4'))

    def test_parser_profile_cannot_supply_financial_values_or_stale_pages(self):
        with self.assertRaises(ValueError): validated_profile({'numbers':{'revenue':123}})
        source=SimpleNamespace(file_name='synthetic.pdf',file_hash='0'*64,page_count=5,report_year=2020)
        report_set=SimpleNamespace(sources=[source])
        with self.assertRaises(ValueError):
            validated_profile({'statements':[{'file_name':'synthetic.pdf','file_hash':'a'*64,'report_year':2020,'kind':'IS','pdf_pages':[1]}]},report_set)

    def test_empty_dataset_is_never_approved(self):
        with self.assertRaises(ValueError): Dataset(company_id='synthetic',report_set_id='synthetic',statements=[])

    def test_borderless_three_year_statements_of_another_company(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); document=pymupdf.open()
            audit=document.new_page(width=600,height=800)
            audit.insert_textbox(pymupdf.Rect(40,40,560,200),
                "At December 31, 2017, inventory in the company's consolidated balance sheet "
                "was audited. This Item compares the report with December 31, 2016. "
                "These dates and the statement mention are audit prose, not a financial table.",fontsize=10)
            facts={
                'Consolidated Balance Sheets':[('Total assets',[200,180,160]),('Total liabilities',[120,100,90]),('Total equity',[80,80,70])],
                'Consolidated Statements of Operations':[('Revenue',[100,90,80]),('Cost of sales',[60,55,50]),('Net income',[16,14,12])],
                'Consolidated Statements of Cash Flows':[('Net cash flows from operating activities',[22,20,18]),('Net cash flows from investing activities',[-10,-9,-8]),('Net cash flows from financing activities',[-5,-4,-3])],
            }
            for title,rows in facts.items():
                page=document.new_page(width=600,height=800)
                page.insert_text((40,45),title,fontsize=12)
                page.insert_text((40,80),'Unit: USD',fontsize=10)
                for x,year in [(320,2017),(430,2016),(540,2015)]: page.insert_text((x,110),str(year),fontsize=10)
                for index,(label,values) in enumerate(rows):
                    y=145+index*30
                    page.insert_text((40,y),label,fontsize=8)
                    for right,amount in zip([365,475,585],values):
                        page.insert_textbox(pymupdf.Rect(right-65,y-12,right,y+8),f'{amount:.2f}',fontsize=10,align=2)
                page.insert_text((40,270),'Legal Representative:',fontsize=10)
            document.save(folder/'reports.pdf'); document.close()
            (folder/'manifest.json').write_text(json.dumps({'company_id':'synthetic-borderless-company','single_company_confirmed':True,
                'reports':[{'file_name':'reports.pdf','report_year':2017}]}),encoding='utf-8')
            report_set=load_report_set(folder/'manifest.json')
            dataset=extract(report_set)
            self.assertEqual(len(dataset.statements),3)
            self.assertTrue(all(len(s.columns)==3 for s in dataset.statements))
            self.assertEqual(dataset.statements[0].rows[0].values,[Decimal(200),Decimal(180),Decimal(160)])
            assert_sources(dataset,report_set)


@unittest.skipUnless(HAS_XLSXWRITER,'Install requirements.txt before testing portable Excel output')
class PortableWorkbookTests(unittest.TestCase):
    def test_pending_workbook_cannot_approve_itself(self):
        dataset=synthetic_dataset()
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'pending.xlsx'
            export_xlsx(export_payload(dataset,None,False),output)
            with patch('financial_workbook.review.assert_sources'):
                review=import_review(output,dataset,None)
            self.assertEqual(review.decisions,[])
            with zipfile.ZipFile(output) as archive:
                self.assertFalse(any('/charts/' in n for n in archive.namelist()))

    def test_formal_workbook_has_five_native_charts_and_cached_math(self):
        dataset=synthetic_dataset(); review=approve_synthetic(dataset)
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'formal.xlsx'
            export_xlsx(export_payload(dataset,review,True),output)
            sheets=read_xlsx(output)
            self.assertEqual(len(sheets),10)
            with zipfile.ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                charts=[n for n in archive.namelist() if '/charts/' in n and n.endswith('.xml')]
                self.assertEqual(len(charts),5)
                ns={'c':'http://schemas.openxmlformats.org/drawingml/2006/chart','m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                for name in charts:
                    formulas=ET.fromstring(archive.read(name)).findall('.//c:f',ns)
                    self.assertTrue(formulas)
                    self.assertTrue(all('分析计算' in n.text for n in formulas))
                root=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
                growth=root.find('.//m:c[@r="C16"]/m:v',ns)
                self.assertEqual(Decimal(growth.text),Decimal('.2'))
            with self.assertRaises(ValueError): export_xlsx(export_payload(dataset,review,True),output)

    def test_three_column_review_layout_roundtrip(self):
        dataset=synthetic_dataset()
        for s in dataset.statements:
            s.columns=_column_metadata([str(s.report_year),str(s.report_year-1),str(s.report_year-2)],s.report_year,s.kind)
            for r in s.rows:
                r.values.append(r.values[-1]*Decimal('.8')); r.raw_values.append(str(r.values[-1]))
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'three_columns.xlsx'
            export_xlsx(export_payload(dataset,None,False),output)
            with patch('financial_workbook.review.assert_sources'):
                self.assertEqual(import_review(output,dataset,None).decisions,[])


class RealAgentWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_really_delegates_to_both_specialists(self):
        dataset=synthetic_dataset()
        pipeline=WorkbookAgents(SimpleNamespace(),FakeRetriever(),ScriptedToolLLM(prepare_script(dataset)))
        with patch('financial_workbook.agents.locate',return_value=locators(dataset)),patch('financial_workbook.agents.extract',return_value=dataset):
            actual,trace=await pipeline.run()
        self.assertEqual(actual.fingerprint,dataset.fingerprint)
        self.assertEqual({e['agent'] for e in trace['trace'] if e['event']=='agent_completed'},
                         {'FinancialOrchestratorAgent','ReportEvidenceAgent','HistoricalMetricsAgent'})

    async def test_finalize_really_validates_calculates_and_exports(self):
        dataset=synthetic_dataset(); review=approve_synthetic(dataset); exported=[]
        def exporter(result): exported.append(result); return Path('synthetic.xlsx')
        pipeline=WorkbookAgents(SimpleNamespace(),None,ScriptedToolLLM(finalize_script(dataset,review)))
        with patch('financial_workbook.review.assert_sources'):
            result=await pipeline.finalize(dataset,review,exporter)
        self.assertEqual(result['status'],'completed'); self.assertEqual(len(exported),1)
        tools={e['tool'] for e in result['trace'] if e['event']=='ToolCall'}
        self.assertTrue({'validate_approved_sources','calculate_historical_metrics','export_analysis_excel'}<=tools)

    async def test_fake_completion_cannot_skip_tools(self):
        dataset=synthetic_dataset(); review=approve_synthetic(dataset)
        fake=handoff('exported',[dataset.fingerprint,digest(analyze(dataset,review))])
        pipeline=WorkbookAgents(SimpleNamespace(),None,ScriptedToolLLM([fake]))
        with self.assertRaises(RuntimeError): await pipeline.finalize(dataset,review,lambda result:self.fail('Skipped tools but exported'))

    @unittest.skipUnless(HAS_XLSXWRITER,'Install requirements.txt before testing the application lifecycle')
    async def test_application_persists_then_resumes_same_dataset(self):
        dataset=synthetic_dataset(); review=approve_synthetic(dataset)
        llm=ScriptedToolLLM(prepare_script(dataset)+finalize_script(dataset,review))
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            sources=[SimpleNamespace(report_year=year,pdf_path=folder/f'synthetic_{year}.pdf',file_name=f'synthetic_{year}.pdf',
                        file_hash='0'*64,verified_printed_pages=(),page_count=1) for year in (2019,2020)]
            report_set=SimpleNamespace(company_id=dataset.company_id,report_set_id=dataset.report_set_id,sources=sources)
            app=FinancialAnalysisAgent(FinanceConfig(output_dir=folder/'runs'),llm_factory=lambda:llm)
            with patch.object(app,'_load_sources',return_value=report_set),patch.object(app,'_retriever',return_value=FakeRetriever()),\
                 patch.object(app,'_preflight',return_value={'status':'passed','synthetic_fixture':True}),\
                 patch('financial_workbook.agents.locate',return_value=locators(dataset)),patch('financial_workbook.agents.extract',return_value=dataset),\
                 patch('financial_workbook.review.assert_sources'):
                prepared=await app.prepare()
            run_dir=Path(prepared['run_dir'])
            self.assertEqual(prepared['status'],'needs_human_review')
            self.assertTrue(Path(prepared['review_workbook']).exists())
            with patch('rag_step1.report.load_report_set',return_value=report_set),\
                 patch('financial_workbook.review.import_review',return_value=review),patch('financial_workbook.review.assert_sources'):
                completed=await app.finalize(run_dir,Path(prepared['review_workbook']))
            self.assertEqual(completed['status'],'completed')
            self.assertEqual(completed['dataset_fingerprint'],prepared['dataset_fingerprint'])
            self.assertTrue((run_dir/completed['formal_workbook']).exists())
            self.assertFalse((run_dir/'.finalize.lock').exists())
            with self.assertRaises(ValueError): await app.finalize(run_dir,Path(prepared['review_workbook']))

    async def test_application_blocks_incomplete_review_before_model_call(self):
        dataset=synthetic_dataset()
        empty_review=Review(dataset_fingerprint=dataset.fingerprint,report_set_id=dataset.report_set_id,decisions=[])
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            (folder/'candidates.json').write_text(dataset.model_dump_json(),encoding='utf-8')
            state={'schema_version':'finance-agent-run-v1','status':'needs_human_review','dataset_fingerprint':dataset.fingerprint,
                   'files':{'sources':'sources.json','candidates':'candidates.json','review_workbook':'pending.xlsx'}}
            (folder/'run.json').write_text(json.dumps(state),encoding='utf-8')
            app=FinancialAnalysisAgent(llm_factory=lambda:self.fail('Incomplete review must not call a model'))
            with patch('rag_step1.report.load_report_set',return_value=SimpleNamespace(report_set_id=dataset.report_set_id)),\
                 patch('financial_workbook.review.import_review',return_value=empty_review):
                with self.assertRaisesRegex(ValueError,'0/6'):
                    await app.finalize(folder,folder/'pending.xlsx')
            self.assertFalse((folder/'.finalize.lock').exists())


if __name__=='__main__': unittest.main()
