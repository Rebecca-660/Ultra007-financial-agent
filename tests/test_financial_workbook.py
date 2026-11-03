import json
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

import pymupdf
from financial_workbook.models import Column, Dataset, Statement, StatementRow, Review, Decision, Correction, digest
from financial_workbook.extract import parse_number, identify, locate, extract
from financial_workbook.analysis import analyze, effective_statements
from financial_workbook.cli import export_payload
from financial_workbook.review import assert_sources, import_review
from unittest.mock import patch
from rag_step1.report import load_report_set


def synthetic_dataset():
    """Fully synthetic test facts; never approve user annual-report data."""
    statements=[]
    for year,mult in [(2019,Decimal('1')),(2020,Decimal('1.2'))]:
        facts={'IS':{'revenue':100,'cost_of_sales':60,'operating_profit':20,'net_income':16,'parent_net_income':12},
               'BS':{'assets':200,'liabilities':120,'equity':80,'parent_equity':70,'current_assets':90,
                     'current_liabilities':50,'inventory':30,'receivables':20},
               'CF':{'cfo':22,'cfi':-10,'cff':-5,'capex':5}}
        for kind,metrics in facts.items():
            sid=f'synthetic-{year}-{kind}'
            rows=[StatementRow(row_id=f'{sid}-{k}',raw_label=k,values=[Decimal(v)*mult,Decimal(v)*Decimal('.9')*mult],
                raw_values=[str(Decimal(v)*mult),str(Decimal(v)*Decimal('.9')*mult)],pdf_page=1,bbox=[0,0,100,20],canonical_metric=k)
                  for k,v in metrics.items()]
            statements.append(Statement(statement_id=sid,company_id='SYNTHETIC_TEST_ONLY',report_set_id='synthetic',
                report_year=year,kind=kind,file_name=f'synthetic_{year}.pdf',file_hash='0'*64,pdf_pages=[1],
                currency='CNY',raw_unit='Unit: CNY',scale=Decimal(1),
                columns=[Column(column_id='col0',raw_header=str(year),value_year=year,role='current',as_of=f'{year}-12-31'),
                         Column(column_id='col1',raw_header=str(year-1),value_year=year-1,role='prior',as_of=f'{year-1}-12-31')],rows=rows))
    return Dataset(company_id='SYNTHETIC_TEST_ONLY',report_set_id='synthetic',statements=statements)


def approve_synthetic(dataset):
    return Review(dataset_fingerprint=dataset.fingerprint,report_set_id=dataset.report_set_id,
        decisions=[Decision(statement_id=s.statement_id,statement_digest=digest(s),decision='approved',reviewer='synthetic-test-fixture') for s in dataset.statements])


class FinancialWorkbookTests(unittest.TestCase):
    def test_source_numbers(self):
        for raw,expected in [('(1,234.50)',Decimal('-1234.5')),('−12.00',Decimal('-12')),('0',Decimal(0)),('',None),('—',None)]:
            self.assertEqual(parse_number(raw),expected)
        for raw in ['NaN','infinity','1,200 USD','=1+2','12%','1,23','(123','123)','(-123)']:
            with self.assertRaises(ValueError): parse_number(raw)

    def test_no_review_no_calculation(self):
        d=synthetic_dataset(); a=analyze(d)
        self.assertEqual(a['approved_statements'],0)
        self.assertTrue(all(r['value'] is None for r in a['results']))
        with self.assertRaises(ValueError): export_payload(d,None,True)

    def test_independent_financial_examples(self):
        d=synthetic_dataset(); a=analyze(d,approve_synthetic(d))
        result={(r['year'],r['name']):r for r in a['results']}
        self.assertEqual(Decimal(result[2020,'营业收入同比']['value']),Decimal('.2'))
        self.assertEqual(Decimal(result[2020,'资产负债率']['value']),Decimal('.6'))
        self.assertEqual(Decimal(result[2020,'毛利率']['value']),Decimal('.4'))
        self.assertEqual(Decimal(result[2020,'简化自由现金流']['value']),Decimal('20.4'))
        self.assertAlmostEqual(float(result[2020,'ROA']['value']),19.2/228)
        self.assertAlmostEqual(float(a['cagr']['value']),.2)

    def test_zero_denominator_is_unavailable(self):
        d=synthetic_dataset()
        next(r for s in d.statements if s.report_year==2020 and s.kind=='BS' for r in s.rows if r.canonical_metric=='current_liabilities').values[0]=Decimal(0)
        a=analyze(d,approve_synthetic(d))
        self.assertIsNone(next(r for r in a['results'] if r['year']==2020 and r['name']=='流动比率')['value'])

    def test_loss_base_not_misleading_positive_growth(self):
        d=synthetic_dataset()
        next(r for s in d.statements if s.report_year==2019 and s.kind=='IS' for r in s.rows if r.canonical_metric=='net_income').values[0]=Decimal(-10)
        a=analyze(d,approve_synthetic(d)); r=next(r for r in a['results'] if r['year']==2020 and r['name']=='合并净利润同比')
        self.assertIsNone(r['value']); self.assertIn('非正',r['reason'])

    def test_cross_currency_blocks_ratio(self):
        d=synthetic_dataset(); next(s for s in d.statements if s.report_year==2020 and s.kind=='CF').currency='USD'
        a=analyze(d,approve_synthetic(d)); r=next(r for r in a['results'] if r['year']==2020 and r['name']=='经营现金流/净利润')
        self.assertIsNone(r['value']); self.assertIn('币种',r['reason'])

    def test_stale_approval_rejected(self):
        d=synthetic_dataset(); review=approve_synthetic(d)
        d.statements[0].rows[0].values[0]+=1
        with self.assertRaises(ValueError): analyze(d,review)

    def test_review_does_not_grant_agent_authority(self):
        d=synthetic_dataset(); review=approve_synthetic(d)
        review.decisions[0].reviewer=' '
        with self.assertRaises(ValueError): analyze(d,review)

    def test_duplicate_review_rejected(self):
        d=synthetic_dataset(); review=approve_synthetic(d)
        review.decisions.append(review.decisions[0].model_copy())
        with self.assertRaises(ValueError): analyze(d,review)

    def test_zero_correction_preserves_original(self):
        d=synthetic_dataset(); review=approve_synthetic(d); statement=d.statements[0]; row=statement.rows[0]
        review.decisions[0].corrections=[Correction(row_id=row.row_id,column_id='col0',original=row.values[0],corrected=Decimal(0),reason='synthetic correction test')]
        effective=effective_statements(d,review)
        self.assertEqual(effective[statement.statement_id].rows[0].values[0],0)
        self.assertEqual(row.values[0],100)

    def test_conflict_requires_explicit_choice(self):
        d=synthetic_dataset(); d.conflicts=[{'current_statement_id':d.statements[0].statement_id,'comparison_statement_id':d.statements[3].statement_id}]
        review=approve_synthetic(d)
        with self.assertRaises(ValueError): analyze(d,review)
        review.decisions[0].conflict_resolution='as_reported'; review.decisions[3].conflict_resolution='as_reported'
        self.assertEqual(analyze(d,review)['status'],'approved')

    def test_missing_opening_not_replaced_with_closing(self):
        d=synthetic_dataset()
        next(r for s in d.statements if s.report_year==2020 and s.kind=='BS' for r in s.rows if r.canonical_metric=='assets').values[1]=None
        a=analyze(d,approve_synthetic(d)); r=next(r for r in a['results'] if r['year']==2020 and r['name']=='ROA')
        self.assertIsNone(r['value'])

    def test_nonconsecutive_cagr_unavailable(self):
        d=synthetic_dataset()
        for s in d.statements:
            if s.report_year==2020: s.report_year=2021
        a=analyze(d,approve_synthetic(d)); self.assertIsNone(a['cagr']['value'])

    def test_metric_scope_aliases(self):
        self.assertEqual(identify('I. Total operating revenue'),'total_revenue')
        self.assertEqual(identify('Including: Operating revenue'),'revenue')
        self.assertEqual(identify('II. Total operating costs'),None)
        self.assertEqual(identify('Total liabilities and shareholders\' equity'),None)

    def test_correction_cannot_break_balance(self):
        d=synthetic_dataset(); review=approve_synthetic(d)
        s=d.statements[1]; row=s.rows[0]
        review.decisions[1].corrections=[Correction(row_id=row.row_id,column_id='col0',original=row.values[0],corrected=Decimal(201),reason='synthetic bad correction')]
        with self.assertRaises(ValueError): analyze(d,review)

    def test_workbook_human_review_and_protected_source_fields(self):
        d=synthetic_dataset()
        sheets={'方法与口径':{'B3':d.fingerprint},'审核':{}}
        for index,s in enumerate(d.statements,9):
            sheets['审核'].update({f'G{index}':s.statement_id,f'H{index}':digest(s),f'C{index}':'approved',f'D{index}':'synthetic-human'})
            cells={'C8':s.columns[0].raw_header,'D8':s.columns[1].raw_header}
            for ri,row in enumerate(s.rows,9):
                cells.update({f'A{ri}':row.raw_label,f'B{ri}':row.note,f'C{ri}':row.values[0],f'D{ri}':row.values[1],
                    f'E{ri}':row.pdf_page,f'F{ri}':row.canonical_metric,f'G{ri}':row.row_id})
            sheets[f'{s.report_year}_{s.kind}']=cells
        with patch('financial_workbook.review.read_xlsx',return_value=sheets),patch('financial_workbook.review.assert_sources'):
            review=import_review(Path('synthetic.xlsx'),d,None)
            self.assertEqual(len(review.decisions),6)
            sheets['2019_IS']['A9']='forged label'
            with self.assertRaises(ValueError): import_review(Path('synthetic.xlsx'),d,None)

    def test_different_company_geometry_and_source_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); pdf=pymupdf.open()
            titles=['Consolidated Balance Sheet','Consolidated Income Statement','Consolidated Cash Flow Statement']
            for title in titles:
                p=pdf.new_page(width=600,height=800)
                p.insert_text((45,50),title,fontsize=13)
                p.insert_text((430,80),'Unit: USD',fontsize=10)
                for x in [40,280,350,460,565]: p.draw_line((x,100),(x,230))
                for x,t in [(100,'Item'),(300,'Note'),(390,'2017'),(500,'2016')]: p.insert_text((x,115),t,fontsize=10)
                for y,label,a,b in [(140,'Total assets','200.00','180.00'),(165,'Total liabilities','120.00','100.00'),(190,'Total equity','80.00','80.00')]:
                    p.insert_text((50,y),label,fontsize=10); p.insert_text((390,y),a,fontsize=10); p.insert_text((500,y),b,fontsize=10)
                p.insert_text((45,250),'Legal Representative:',fontsize=10)
            pdf.save(folder/'independent.pdf');pdf.close()
            (folder/'reports.json').write_text(json.dumps({'company_id':'independent-company','single_company_confirmed':True,
                'reports':[{'file_name':'independent.pdf','report_year':2017}]}),encoding='utf-8')
            source=load_report_set(folder/'reports.json'); d=extract(source)
            self.assertEqual(len(d.statements),3); self.assertEqual(d.company_id,'independent-company')
            assert_sources(d,source)
            d.statements[0].rows[0].values[0]=Decimal(999)
            with self.assertRaises(ValueError): assert_sources(d,source)


if __name__=='__main__': unittest.main()
