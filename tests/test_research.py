"""Synthetic financial research tests; never approve or value user company data."""
from __future__ import annotations
import asyncio
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import pymupdf
from pydantic import ValidationError

from financial_workbook.analysis import analyze
from financial_workbook.comparison import compare_companies
from financial_workbook.extract import extract
from financial_workbook.human_review import review_template
from financial_workbook.models import digest
from financial_workbook.models import Dataset
from financial_workbook.research import ResearchWorkflow
from financial_workbook.research_cli import interactive, collect_assumptions
from financial_workbook.research_io import load_project,read_json,project_lock
from financial_workbook.research_models import DiscountRate,ResearchManifest,ValuationRequest
from financial_workbook.valuation import calculate_wacc,value_company
from rag_step1.report import load_report_set
from test_agents import ScriptedToolLLM,FakeRetriever
from test_finance_application import prepare_script,finalize_script
from test_financial_workbook import synthetic_dataset,approve_synthetic

D=Decimal


def metadata(cid='SYNTHETIC_TEST_ONLY',**kwargs):
    return {'company_id':cid,'name':cid,'industry':'Synthetic manufacturing',
            'business_type':'non_financial','accounting_standard':'SYNTHETIC_GAAP',
            'fiscal_year_end':'12-31','comparability_confirmed':True,**kwargs}


def synthetic_bundle(cid='SYNTHETIC_TEST_ONLY'):
    dataset=synthetic_dataset(); dataset.company_id=cid
    for statement in dataset.statements: statement.company_id=cid
    review=approve_synthetic(dataset); analysis=analyze(dataset,review)
    return {'state':{'company_id':cid,'dataset_fingerprint':dataset.fingerprint},
            'dataset':dataset.model_dump(mode='json'),'review':review.model_dump(mode='json'),
            'analysis':analysis,'currency':'CNY'}


def assumptions(bundle):
    return {'schema_version':'finance-fcff-assumptions-v1','company_id':bundle['state']['company_id'],
        'dataset_fingerprint':bundle['state']['dataset_fingerprint'],'analysis_fingerprint':digest(bundle['analysis']),
        'currency':'CNY','unit':'currency_base_unit','base_year':2020,'valuation_date':'2020-12-31',
        'initial_operating_nwc':'12','initial_operating_nwc_evidence':'Synthetic operating working capital fixture',
        'scenarios':[{'name':'Base','discount_rate':{'mode':'direct','wacc':'.1','rationale':'SYNTHETIC'},
            'forecasts':[{'year':2021,'revenue_growth':'.1','ebit_margin':'.2','cash_tax_rate':'.25',
                'depreciation_to_revenue':'.03','capex_to_revenue':'.05','operating_nwc_to_revenue':'.1','rationale':'SYNTHETIC'}],
            'terminal':{'growth':'.02','ebit_margin':'.2','cash_tax_rate':'.25',
                        'return_on_invested_capital':'.1','rationale':'SYNTHETIC'},
            'sensitivity_wacc':['.01','.1','.12'],'sensitivity_growth':['.02','.03']}],
        'bridge':{'as_of':'2020-12-31','excess_cash':'10','non_operating_assets':'0','interest_bearing_debt':'20',
                  'minority_interest':'0','preferred_equity':'0','other_claims':'0','diluted_shares':'10',
                  'market_price':'15','rationale':'SYNTHETIC'},
        'confirmed':True,'confirmed_by':'synthetic-tester','rationale':'Synthetic test assumptions only'}


def make_pdf(path,company,year,mult=1):
    """Three genuine parseable PDF pages carrying entirely synthetic amounts."""
    facts={
        'Consolidated Balance Sheets':[
            ('Total assets',200),('Total liabilities',120),('Total equity',80),
            ('Equity attributable to owners of the parent',70),('Total current assets',90),
            ('Total current liabilities',50),('Inventories',30),('Trade receivables',20)],
        'Consolidated Statements of Operations':[
            ('Revenue',100),('Cost of sales',60),('Income from operations',20),('Net income',16),
            ('Net profits attributable to shareholders of the parent',12)],
        'Consolidated Statements of Cash Flows':[
            ('Net cash flows from operating activities',22),('Net cash flows from investing activities',-10),
            ('Net cash flows from financing activities',-5),('Capital expenditure',5)]}
    doc=pymupdf.open()
    for title,rows in facts.items():
        page=doc.new_page(width=600,height=850)
        page.insert_text((40,40),title,fontsize=12)
        page.insert_text((40,65),f'SYNTHETIC ONLY {company}',fontsize=9)
        page.insert_text((40,85),'Unit: CNY',fontsize=10)
        for x,y in [(320,year),(430,year-1),(540,year-2)]: page.insert_text((x,110),str(y),fontsize=10)
        for i,(label,value) in enumerate(rows):
            y=145+i*28; page.insert_text((40,y),label,fontsize=7)
            for right,factor in zip([365,475,585],[D(1),D('.9'),D('.8')]):
                amount=D(value)*D(str(mult))*factor
                page.insert_textbox(pymupdf.Rect(right-65,y-12,right,y+8),f'{amount:.2f}',fontsize=10,align=2)
        page.insert_text((40,700),'Legal Representative:',fontsize=10)
    doc.save(path); doc.close()


class ValuationTests(unittest.TestCase):
    def setUp(self): self.bundle=synthetic_bundle(); self.raw=assumptions(self.bundle)

    def value(self,raw=None,meta=None):
        return value_company(self.bundle,meta or metadata(),ValuationRequest.model_validate(raw or self.raw))

    def test_hand_calculated_fcff_terminal_and_equity(self):
        result=self.value()['scenarios'][0]; row=result['forecast'][0]; value=result['valuation']
        self.assertEqual(D(row['revenue']),D(132))
        self.assertEqual(D(row['fcff']),D('15.96'))
        self.assertEqual(D(value['terminal_fcff']),D('16.1568'))
        self.assertEqual(D(value['terminal_value']),D('201.96'))
        expected=(D('15.96')+D('201.96'))/D('1.1')-D(10)
        self.assertAlmostEqual(float(value['equity_value']),float(expected),places=10)
        self.assertAlmostEqual(float(value['per_share_value']),float(expected/10),places=10)

    def test_wacc_components_independent_example(self):
        rate=DiscountRate(mode='components',risk_free_rate='.03',beta='1.2',equity_risk_premium='.05',
            country_risk_premium='0',pretax_cost_of_debt='.04',debt_tax_rate='.25',
            market_equity='800',market_debt='200',rationale='SYNTHETIC')
        result=calculate_wacc(rate)
        self.assertEqual(D(result['cost_of_equity']),D('.09'))
        self.assertEqual(D(result['wacc']),D('.078'))

    def test_missing_mixed_and_percentage_wacc_are_rejected(self):
        for raw in ({'mode':'direct','wacc':8,'rationale':'SYNTHETIC'},
                    {'mode':'components','risk_free_rate':'.03','rationale':'SYNTHETIC'},
                    {'mode':'direct','wacc':'.1','beta':1,'rationale':'SYNTHETIC'}):
            with self.assertRaises(ValidationError): DiscountRate.model_validate(raw)

    def test_invalid_sensitivity_cells_are_not_infinity(self):
        rows=self.value()['scenarios'][0]['sensitivity']
        self.assertTrue(all(r['per_share_value'] is None for r in rows if r['wacc']=='.01' or D(r['wacc'])==D('.01')))
        valid=[r for r in rows if D(r['growth'])==D('.02') and r['per_share_value'] is not None]
        self.assertGreater(D(valid[0]['per_share_value']),D(valid[1]['per_share_value']))

    def test_terminal_spread_and_reinvestment_guards(self):
        for field,value in [('growth','.1'),('return_on_invested_capital','.01')]:
            raw=deepcopy(self.raw); raw['scenarios'][0]['terminal'][field]=value
            with self.assertRaises((ValueError,ValidationError)): self.value(raw)

    def test_rejects_financials_currency_stale_identity_and_midyear(self):
        with self.assertRaisesRegex(ValueError,'金融'): self.value(meta=metadata(business_type='financial'))
        for key,value in [('currency','USD'),('analysis_fingerprint','old'),('dataset_fingerprint','old'),('valuation_date','2021-06-30')]:
            raw=deepcopy(self.raw); raw[key]=value
            if key=='valuation_date': raw['bridge']['as_of']=value
            with self.assertRaises(ValueError): self.value(raw)

    def test_no_automatic_tax_credit_for_losses(self):
        self.raw['scenarios'][0]['forecasts'][0]['ebit_margin']='-.1'
        self.assertEqual(D(self.value()['scenarios'][0]['forecast'][0]['cash_tax']),0)

    def test_negative_equity_is_not_a_negative_stock_price(self):
        self.raw['bridge']['interest_bearing_debt']='10000'
        value=self.value()['scenarios'][0]['valuation']
        self.assertLess(D(value['equity_value']),0); self.assertIsNone(value['per_share_value'])

    def test_all_scenarios_are_independently_computed(self):
        for name,growth in [('Bear','-.1'),('Bull','.2')]:
            scenario=deepcopy(self.raw['scenarios'][0]); scenario['name']=name
            scenario['forecasts'][0]['revenue_growth']=growth; self.raw['scenarios'].append(scenario)
        results={r['name']:r for r in self.value()['scenarios']}
        self.assertLess(D(results['Bear']['valuation']['equity_value']),D(results['Base']['valuation']['equity_value']))
        self.assertGreater(D(results['Bull']['valuation']['equity_value']),D(results['Base']['valuation']['equity_value']))

    def test_missing_judgment_values_and_nonfinite_are_rejected(self):
        for value in (None,'NaN','Infinity'):
            raw=deepcopy(self.raw); raw['initial_operating_nwc']=value
            with self.assertRaises(ValidationError): ValuationRequest.model_validate(raw)
        for confirmation in (False,1,'true'):
            raw=deepcopy(self.raw); raw['confirmed']=confirmation
            with self.assertRaises(ValidationError): ValuationRequest.model_validate(raw)


class ComparisonTests(unittest.TestCase):
    def setUp(self): self.items=[(metadata('A'),synthetic_bundle('A')),(metadata('B'),synthetic_bundle('B'))]

    def test_common_year_panel_index_and_sample_count(self):
        value=compare_companies(self.items)
        self.assertEqual(value['years'],[2019,2020]); self.assertEqual(value['company_ids'],['A','B'])
        self.assertEqual(D(value['revenue_index'][1]['revenue_index']),D(120))
        self.assertTrue(all(r['count']==2 for r in value['sample_statistics']))

    def test_different_currency_standard_and_fiscal_year_block_comparison(self):
        for key,value in [('currency','USD'),('accounting_standard','OTHER_GAAP'),('fiscal_year_end','06-30')]:
            items=deepcopy(self.items)
            if key=='currency': items[1][1][key]=value
            else: items[1][0][key]=value
            with self.assertRaises(ValueError): compare_companies(items)

    def test_no_matched_year_and_duplicate_selection_are_rejected(self):
        with self.assertRaises(ValueError): compare_companies(self.items,[2018])
        with self.assertRaises(ValueError): compare_companies([self.items[0],self.items[0]])

    def test_cross_industry_not_presented_as_industry_average(self):
        self.items[1][0]['industry']='OTHER'
        value=compare_companies(self.items)
        self.assertEqual(value['sample_statistics'],[])
        self.assertEqual(value['comparison_type'],'selected_cross_industry_companies')

    def test_missing_not_zero_and_effective_sample_count(self):
        bundle=self.items[1][1]; dataset=Dataset.model_validate(bundle['dataset'])
        row=next(r for s in dataset.statements if s.report_year==2020 and s.kind=='IS' for r in s.rows if r.canonical_metric=='net_income')
        row.values[0]=None; row.raw_values[0]=''
        review=approve_synthetic(dataset)
        bundle.update(dataset=dataset.model_dump(mode='json'),review=review.model_dump(mode='json'),analysis=analyze(dataset,review))
        bundle['state']['dataset_fingerprint']=dataset.fingerprint
        value=compare_companies(self.items)
        stat=next(r for r in value['sample_statistics'] if r['year']==2020 and r['metric']=='净利率')
        self.assertEqual(stat['count'],1)


class ParameterInterviewTests(unittest.TestCase):
    def interview(self,mode='1',confirm='CONFIRM'):
        template=assumptions(synthetic_bundle())
        first=['12','SYNTHETIC evidence','10','0','20','0','0','0','10','15','SYNTHETIC bridge','Base','1',mode]
        rate=['.1'] if mode=='1' else ['.03','1.2','.05','0','.04','.25','800','200']
        answers=iter(first+rate+['SYNTHETIC rate','.1','.2','.25','.03','.05','.1','SYNTHETIC forecast',
                     '.02','.2','.25','.1','SYNTHETIC terminal','.1,.12','.02,.03','SYNTHETIC overall',confirm])
        with patch('builtins.print'):
            result=collect_assumptions(template,'synthetic-tester',lambda _:next(answers))
        self.assertEqual(list(answers),[])
        return result

    def test_direct_rate_interview_requires_confirmation(self):
        result=self.interview()
        self.assertTrue(result['confirmed']); self.assertEqual(result['scenarios'][0]['discount_rate']['mode'],'direct')
        ValuationRequest.model_validate(result)

    def test_component_rate_interview(self):
        result=self.interview(mode='2')
        rate=ValuationRequest.model_validate(result).scenarios[0].discount_rate
        self.assertEqual(D(calculate_wacc(rate)['wacc']),D('.078'))

    def test_interview_without_final_confirmation_is_draft(self):
        self.assertFalse(self.interview(confirm='NO')['confirmed'])


class ResearchWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        for cid,year,mult in [('A',2019,1),('A',2020,1.2),('B',2020,1.5)]:
            make_pdf(self.root/f'{cid}_{year}.pdf',cid,year,mult)
        (self.root/'profile.json').write_text(json.dumps({'metric_aliases':{'Capital expenditure':'capex'}}))
        manifest={'confirmed_by':'synthetic-tester','companies':[metadata('A',parser_profile='profile.json'),metadata('B',parser_profile='profile.json')],
            'reports':[{'company_id':cid,'report_year':year,'file_name':f'{cid}_{year}.pdf'} for cid,year in [('A',2019),('A',2020),('B',2020)]]}
        self.manifest=manifest
        path=self.root/'manifest.json'; path.write_text(json.dumps(manifest))
        self.workflow=ResearchWorkflow(); created=self.workflow.create(path,self.root/'projects')
        self.folder=Path(created['project_dir'])

    def tearDown(self): self.temp.cleanup()

    async def prepare_company(self,cid):
        state=load_project(self.folder); entry=state['companies'][cid]
        source=load_report_set(self.folder/entry['manifest'])
        profile=read_json(self.folder/entry['profile']); dataset=extract(source,profile=profile)
        self.workflow.llm_factory=lambda:ScriptedToolLLM(prepare_script(dataset))
        with patch('financial_workbook.service.FinancialAnalysisAgent._retriever',return_value=FakeRetriever()),\
             patch('financial_workbook.agents.extract',return_value=dataset):
            result=await self.workflow.prepare(self.folder,[cid])
        run=self.folder/result['companies'][cid]['run_dir']
        return dataset,run

    async def finish_company(self,cid):
        dataset,run=await self.prepare_company(cid)
        raw=review_template(dataset); raw.update(confirmed_by='synthetic-tester',source_checked=True,statement='Synthetic PDF checked')
        for row in raw['review']['decisions']:
            row.update(decision='approved',reviewer='synthetic-tester',conflict_resolution='as_reported')
        reviewfile=self.root/f'review_{cid}.json'; reviewfile.write_text(json.dumps(raw))
        submitted=self.workflow.submit_review(self.folder,cid,reviewfile)
        from financial_workbook.research_models import HumanReview
        review=HumanReview.model_validate(raw).review
        self.workflow.llm_factory=lambda:ScriptedToolLLM(finalize_script(dataset,review))
        result=await self.workflow.finalize(self.folder,cid)
        return dataset,run,result

    async def test_single_pdf_and_multiyear_real_parser_agent_review_export(self):
        for cid,count in [('A',6),('B',3)]:
            dataset,run,result=await self.finish_company(cid)
            self.assertEqual(len(dataset.statements),count)
            self.assertEqual(result['history']['status'],'completed')
            self.assertEqual(result['investment_offer']['status'],'awaiting_user_choice')
            with zipfile.ZipFile(result['history']['formal_workbook_path']) as archive:
                self.assertEqual(len([n for n in archive.namelist() if n.startswith('xl/charts/chart') and n.endswith('.xml')]),5)
        self.assertEqual(self.workflow.history(self.folder,['A'])['mode'],'longitudinal')
        self.assertEqual(self.workflow.history(self.folder,['B'])['mode'],'single_report')
        compared=self.workflow.history(self.folder,['B','A'])
        self.assertEqual(read_json(Path(compared['comparison']))['years'],[2020])
        self.assertEqual(compared['selected_companies'],['B','A'])
        with zipfile.ZipFile(compared['workbook']) as archive: self.assertIsNone(archive.testzip())

    async def test_review_required_stale_review_rejected_and_prepare_idempotent(self):
        dataset,run=await self.prepare_company('B')
        with self.assertRaises(ValueError): self.workflow.history(self.folder,['B'])
        self.workflow.llm_factory=lambda:self.fail('prepare repeated an API task')
        await self.workflow.prepare(self.folder,['B'])
        raw=review_template(dataset); raw['source_checked']=True; raw['confirmed_by']='synthetic-tester'; raw['statement']='SYNTHETIC'
        raw['review']['dataset_fingerprint']='stale'
        reviewfile=self.root/'badreview.json'; reviewfile.write_text(json.dumps(raw))
        with self.assertRaises(ValueError): self.workflow.submit_review(self.folder,'B',reviewfile)

    async def test_stop_choice_never_reads_parameters_or_runs_valuation(self):
        await self.finish_company('B')
        self.workflow.decide(self.folder,'B',proceed=False,decided_by='synthetic-tester')
        with patch('financial_workbook.valuation.value_company',side_effect=AssertionError('must stop')):
            with self.assertRaisesRegex(ValueError,'停止'):
                self.workflow.value(self.folder,'B',self.root/'NONEXISTENT.json')
        with self.assertRaises(ValueError): self.workflow.decide(self.folder,'B',proceed=True,decided_by='synthetic-tester')

    async def test_continue_then_confirmed_parameters_export_and_reload(self):
        dataset,run,result=await self.finish_company('B')
        bundle=self.workflow._bundle(self.folder,load_project(self.folder),'B')[1]
        raw=assumptions(bundle); path=self.root/'assumptions.json'; path.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError,'未选择'): self.workflow.value(self.folder,'B',path)
        chosen=self.workflow.decide(self.folder,'B',proceed=True,decided_by='synthetic-tester')
        template=read_json(Path(chosen['assumptions_template']))
        self.assertIsNone(template['scenarios'][0]['discount_rate']['wacc']); self.assertFalse(template['confirmed'])
        value=self.workflow.value(self.folder,'B',path)
        saved=read_json(Path(value['output_dir'])/'valuation.json')
        self.assertEqual(saved['assumptions_fingerprint'],digest(ValuationRequest.model_validate(raw)))
        with zipfile.ZipFile(value['workbook']) as archive:
            self.assertIsNone(archive.testzip()); self.assertTrue(any('charts/chart' in n for n in archive.namelist()))
        self.assertEqual(ResearchWorkflow().status(self.folder)['companies']['B']['status'],'completed')

    async def test_interactive_no_is_terminal(self):
        await self.finish_company('B'); answers=iter(['','no'])
        with patch.object(self.workflow,'value',side_effect=AssertionError('must stop')),patch('builtins.print'):
            value=interactive(self.workflow,self.folder,['B'],'synthetic-tester',input_fn=lambda _:next(answers))
        self.assertEqual(value['decisions'][0]['status'],'declined')

    def test_duplicate_ownership_invalid_metadata_and_scanned_upload(self):
        for mutate in ('duplicate_year','duplicate_pdf','metadata','scan'):
            raw=deepcopy(self.manifest)
            if mutate=='duplicate_year': raw['reports'].append(deepcopy(raw['reports'][0]))
            if mutate=='duplicate_pdf': raw['reports'][-1]['file_name']=raw['reports'][0]['file_name']
            if mutate=='metadata': raw['companies'][0]['comparability_confirmed']=False
            if mutate=='scan':
                doc=pymupdf.open(); doc.new_page(); doc.save(self.root/'blank.pdf'); doc.close()
                raw['reports'][0]['file_name']='blank.pdf'
            path=self.root/'invalid.json'; path.write_text(json.dumps(raw))
            with self.assertRaises(ValueError): self.workflow.create(path,self.root/'invalid_projects')

    def test_future_uploader_bytes_are_isolated_and_traversal_names_safe(self):
        raw=deepcopy(self.manifest); raw['companies']=raw['companies'][:1]
        raw['companies'][0].pop('parser_profile'); raw['reports']=raw['reports'][:1]
        content=(self.root/'A_2019.pdf').read_bytes(); raw['reports'][0]['file_name']='../../A_2019.pdf'
        result=self.workflow.create_from_uploads(raw,{'../../A_2019.pdf':content},self.root/'bytes_projects')
        self.assertEqual(result['companies'],['A'])
        self.assertFalse((self.root/'bytes_projects'/'A_2019.pdf').exists())

    def test_project_lock_blocks_duplicate_task(self):
        with project_lock(self.folder):
            with self.assertRaises(ValueError):
                with project_lock(self.folder): pass

    async def test_unchecked_review_never_calls_model(self):
        dataset,run=await self.prepare_company('B')
        raw=review_template(dataset); raw['source_checked']=False
        path=self.root/'unchecked.json'; path.write_text(json.dumps(raw))
        self.workflow.llm_factory=lambda:self.fail('Unchecked human review called API')
        with self.assertRaises(ValueError): await self.workflow.finalize(self.folder,'B',path)

    async def test_source_change_invalidates_historical_reuse(self):
        dataset,run,result=await self.finish_company('B')
        state=load_project(self.folder); manifest_path=self.folder/state['companies']['B']['manifest']
        source=manifest_path.parent/read_json(manifest_path)['reports'][0]['file_name']
        source.write_bytes(source.read_bytes()+b'\nSYNTHETIC CHANGE')
        with self.assertRaises(ValueError): self.workflow.history(self.folder,['B'])


if __name__=='__main__': unittest.main()
