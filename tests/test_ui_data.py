"""View-model and Streamlit tests use only synthetic approvals and saved files."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_financial_workbook import synthetic_dataset,approve_synthetic
from financial_workbook.analysis import analyze
from financial_workbook.cli import export_payload,export_workbook
from financial_workbook.ui_data import (
    CATEGORIES,ResultError,chart_rows,discover_runs,display_value,inside,load_run,
    metric_rows,number,run_signature,source_rows,
)

ROOT=Path(__file__).resolve().parents[1]


def saved_fixture(root,name='sample',company='SYNTHETIC_TEST_ONLY'):
    folder=root/'synthetic'/name; attempt=folder/'finalize_fixture'
    attempt.mkdir(parents=True)
    dataset=synthetic_dataset()
    dataset.company_id=company
    for table in dataset.statements: table.company_id=company
    review=approve_synthetic(dataset)
    analysis=analyze(dataset,review)
    (folder/'candidates.json').write_text(dataset.model_dump_json(),encoding='utf-8')
    (attempt/'review.json').write_text(review.model_dump_json(),encoding='utf-8')
    (attempt/'analysis.json').write_text(json.dumps(analysis),encoding='utf-8')
    export_workbook(export_payload(dataset,review,True),attempt/'formal.xlsx')
    state={'schema_version':'finance-agent-run-v1','status':'completed','company_id':company,
        'report_set_id':dataset.report_set_id,'dataset_fingerprint':dataset.fingerprint,
        'updated_at':'2026-10-27T08:00:00+00:00','last_attempt':'finalize_fixture',
        'formal_workbook':'finalize_fixture/formal.xlsx','approved_statements':6,
        'files':{'candidates':'candidates.json','sources':'snapshot.json','review_workbook':'review.xlsx'}}
    (folder/'run.json').write_text(json.dumps(state),encoding='utf-8')
    return folder


class UIDataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.folder=saved_fixture(self.root)

    def tearDown(self): self.temp.cleanup()

    def test_only_complete_runs_are_discovered(self):
        pending=self.root/'synthetic'/'pending'; pending.mkdir()
        (pending/'run.json').write_text('{"status":"needs_human_review"}',encoding='utf-8')
        records,invalid=discover_runs(self.root)
        self.assertEqual(len(records),1); self.assertEqual(invalid,0)

    def test_stale_analysis_and_review_are_not_displayed(self):
        path=self.folder/'finalize_fixture'/'analysis.json'
        data=json.loads(path.read_text()); data['dataset_fingerprint']='old'
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ResultError,'版本'): load_run(self.folder)

    def test_outside_workbook_is_rejected(self):
        path=self.folder/'run.json'; state=json.loads(path.read_text())
        state['formal_workbook']='../../outside.xlsx'; path.write_text(json.dumps(state))
        with self.assertRaises(ResultError): load_run(self.folder)
        with self.assertRaises(ResultError): inside(self.folder,'../../.env')

    def test_source_values_and_units_are_preserved(self):
        bundle=load_run(self.folder)
        source=next(r for r in source_rows(bundle,2020) if r['输入']=='营业收入')
        self.assertEqual(source['标准化金额'],'120.0')
        self.assertEqual(source['PDF物理页'],1)
        self.assertEqual(source['币种'],'CNY')

    def test_filters_and_raw_percentages(self):
        bundle=load_run(self.folder)
        rows=metric_rows(bundle,[2020],['偿债与流动性'])
        self.assertEqual(len(rows),4)
        self.assertEqual({r['年度'] for r in rows},{2020})
        point=chart_rows(bundle,[2020],['资产负债率'],True)[0]
        self.assertEqual(point['数值'],.6)
        self.assertEqual(display_value('0.6','percent'),'60.0%')

    def test_missing_is_not_zero_and_zero_is_valid(self):
        bundle=load_run(self.folder)
        row=next(r for r in bundle['analysis']['results'] if r['name']=='简化自由现金流' and r['year']==2020)
        row.update(value=None,reason='Synthetic missing capex')
        self.assertIsNone(chart_rows(bundle,[2020],['简化自由现金流'])[0]['数值'])
        row['value']='0'
        self.assertEqual(chart_rows(bundle,[2020],['简化自由现金流'])[0]['数值'],0)
        for value in ('NaN','Infinity','bad'):
            with self.assertRaises(ResultError): number(value)

    def test_result_signature_changes_with_saved_result(self):
        before=run_signature(self.folder)
        file=self.folder/'finalize_fixture'/'analysis.json'
        file.write_text(file.read_text()+' ')
        self.assertNotEqual(before,run_signature(self.folder))


@unittest.skipUnless(importlib.util.find_spec('streamlit'),'Install requirements-ui.txt for UI tests')
class StreamlitViewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.folder=saved_fixture(self.root)
        self.env=patch.dict(os.environ,{'AIF_UI_RUNS_DIR':str(self.root),'AIF_UI_PROJECTS_DIR':str(self.root/'projects')})
        self.env.start()

    def tearDown(self):
        self.env.stop(); self.temp.cleanup()

    def app(self):
        from streamlit.testing.v1 import AppTest
        return AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=30)

    def test_initial_page_and_filters_never_call_agents(self):
        import streamlit as st
        with patch('financial_workbook.service.FinancialAnalysisAgent.prepare',side_effect=AssertionError('Unexpected Agent invocation')) as prepare,\
             patch('financial_workbook.service.FinancialAnalysisAgent.finalize',side_effect=AssertionError('Unexpected Agent invocation')) as finalize,\
             patch('streamlit.altair_chart',wraps=st.altair_chart) as charts:
            app=self.app().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.metric),4)
            self.assertEqual(charts.call_count,5)
            self.assertEqual(app.metric[2].value,'20.0%')
            app.selectbox(key='focus_year').set_value(2019).run()
            self.assertFalse(app.exception)
            app.multiselect(key='visible_years').set_value([2019]).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.focus_year,2019)
            prepare.assert_not_called(); finalize.assert_not_called()

    def test_empty_filters_and_empty_directory_are_explained(self):
        app=self.app().run()
        app.multiselect(key='visible_years').set_value([]).run()
        self.assertFalse(app.exception)
        self.assertTrue(any('至少选择一个年度' in item.value for item in app.info))
        empty=self.root/'empty'; empty.mkdir()
        with patch.dict(os.environ,{'AIF_UI_RUNS_DIR':str(empty)}):
            empty_app=self.app().run()
            self.assertFalse(empty_app.exception)
            self.assertTrue(any('还没有' in item.value for item in empty_app.info))

    def test_switching_run_resets_year_and_preserves_company_scope(self):
        other=saved_fixture(self.root,'second','SECOND_SYNTHETIC_COMPANY')
        app=self.app().run()
        app.selectbox(key='selected_run').set_value(str(other.resolve())).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state.active_run,str(other.resolve()))
        self.assertTrue(any('SECOND_SYNTHETIC_COMPANY' in s.value for s in app.subheader))

    def test_download_bytes_match_the_selected_saved_workbook(self):
        import streamlit_app
        bundle=load_run(self.folder)
        self.assertEqual(streamlit_app.workbook_bytes(bundle['workbook'],run_signature(self.folder)),
                         Path(bundle['workbook']).read_bytes())
        app=self.app().run()
        self.assertFalse(app.exception)
        button=app.get('download_button')[0]
        self.assertTrue(button.label.startswith('下载') and 'Excel' in button.label)


if __name__=='__main__': unittest.main()
