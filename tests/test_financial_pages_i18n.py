"""Financial display locales preserve canonical selections and source values."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from financial_workbook.analysis import INPUTS,RECIPES
from financial_workbook.models import digest
from financial_workbook.ui_data import load_run
from financial_workbook.web_financial_i18n import COPY,text,metric_name,table_rows,unit_label
from financial_workbook.web_pages import display_scale
from test_ui_data import saved_fixture

ROOT=Path(__file__).resolve().parents[1]
CJK=re.compile(r'[\u3400-\u9fff]')


class FinancialTranslationTests(unittest.TestCase):
    def test_every_registered_metric_and_definition_has_a_translation(self):
        for lang in ('EN','RU'):
            for label,_ in INPUTS.values():
                self.assertIn(label,COPY)
                self.assertFalse(CJK.search(text(label,lang)))
            for name,expression,kind,positive,definition in RECIPES:
                self.assertIn(name,COPY)
                self.assertIn(definition,COPY)
                self.assertFalse(CJK.search(metric_name(name,lang)))
                self.assertFalse(CJK.search(text(definition,lang)))

    def test_missing_reasons_and_dynamic_validation_notes_are_localized(self):
        messages=[
            '上年营业收入：原表缺少该指标、映射或期间列不唯一；营业成本：原单元格空白、单位缺失或期初/比较年度不匹配',
            '分母或同比基数非正：归母股东权益、期初归母权益',
            '2 处跨报告比较差异保留；系统按各年原报本年数分析，不自动覆盖重述。',
            '2023_IS 指标映射不唯一：net_income；该指标不自动补值。',
        ]
        for lang in ('EN','RU'):
            for message in messages:
                translated=text(message,lang)
                self.assertFalse(CJK.search(translated),translated)
                self.assertNotIn('Additional source-specific',translated)
                self.assertNotIn('Дополнительные сведения',translated)

    def test_source_text_is_preserved_while_headers_and_explanations_translate(self):
        original=[{'输入':'营业收入','原始项目':'一、营业收入','报告':'立讯精密2023年报.pdf',
                   '原列头':'2023年度','原披露单位':'单位：元','标准化金额':'123.45','币种':'CNY',
                   '说明':'原表缺少该指标、映射或期间列不唯一'}]
        before=deepcopy(original)
        result=table_rows(original,lang='EN',source=True)[0]
        self.assertEqual(result['Input'],'Revenue')
        self.assertEqual(result['Source item (original)'],'一、营业收入')
        self.assertEqual(result['Source report'],'立讯精密2023年报.pdf')
        self.assertEqual(result['Normalized amount'],'123.45')
        self.assertFalse(CJK.search(result['Explanation']))
        self.assertEqual(original,before)

    def test_display_unit_language_does_not_change_magnitude(self):
        self.assertEqual(display_scale(['170447000000'],'CNY'),(1e8,'亿 CNY'))
        self.assertEqual(display_scale(['170447000000'],'CNY','EN'),(1e8,'100m CNY'))
        self.assertEqual(display_scale(['170447000000'],'CNY','RU'),(1e8,'100 млн CNY'))
        self.assertFalse(CJK.search(unit_label(1e6,'CNY','EN')))


@unittest.skipUnless(importlib.util.find_spec('streamlit'),'Install requirements-ui.txt')
class FinancialLocalePagesTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'tmp').mkdir(exist_ok=True)
        self.temporary=tempfile.TemporaryDirectory(prefix='financial-locale-',dir=ROOT/'tmp')
        self.root=Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.run=saved_fixture(self.root/'runs')

    def app(self,body):
        from streamlit.testing.v1 import AppTest
        script="""import streamlit as st
from pathlib import Path
from financial_workbook.ui_data import load_run as _load_run
from financial_workbook.web_pages import render_overview,render_comparison,render_summary
def load_run(path):
    bundle=_load_run(path)
    bundle['state']['run_dir']=str(path)
    return bundle
st.selectbox('Language',['中文','EN','RU'],key='language')
"""+body
        return AppTest.from_string(script,default_timeout=45)

    def assert_controls_translated(self,app):
        values=[]
        for kind in ('title','subheader','caption','info','warning','error','expander','button'):
            for element in app.get(kind):
                value=getattr(element,'value',None) or getattr(element,'label','')
                if isinstance(value,str): values.append(value)
        self.assertFalse(any(CJK.search(value) for value in values),[v for v in values if CJK.search(v)])

    def test_overview_localizes_charts_tables_and_empty_year_message(self):
        import streamlit as st
        body=f"bundle=load_run(Path({str(self.run)!r}))\nrender_overview(bundle,Path({str(self.root)!r}),'SYNTHETIC_TEST_ONLY')"
        captured=[]
        actual_chart=st.altair_chart
        def chart(chart,*args,**kwargs):
            captured.append(chart.to_dict())
            return actual_chart(chart,*args,**kwargs)
        with patch('financial_workbook.web_pages.st.altair_chart',side_effect=chart):
            app=self.app(body).run()
            for lang in ('EN','RU'):
                captured.clear()
                app.selectbox(key='language').set_value(lang).run()
                self.assertFalse(app.exception)
                self.assert_controls_translated(app)
                self.assertEqual(len(captured),5)
                self.assertFalse(CJK.search(json.dumps(captured,ensure_ascii=False)))
                # Metric/definition tables, unlike source-original tables, are
                # translated without modifying the underlying saved analysis.
                for index in (0,1):
                    frame=app.dataframe[index].value
                    self.assertFalse(CJK.search(frame.to_json(force_ascii=False)))
                app.multiselect(key='visible_years').set_value([]).run()
                self.assertFalse(app.exception)
                self.assertTrue(any(text('请在侧栏至少选择一个年度。',lang)==item.value for item in app.info))
                self.assert_controls_translated(app)
                app.multiselect(key='visible_years').set_value([2019,2020]).run()

    def test_category_selection_survives_translation_switches(self):
        body=f"render_overview(load_run(Path({str(self.run)!r})))"
        app=self.app(body).run()
        app.multiselect(key='categories_中文').set_value(['盈利']).run()
        original_metrics=app.metric[0].value
        for lang in ('EN','RU','中文'):
            app.selectbox(key='language').set_value(lang).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.categories,['盈利'])
            self.assertEqual(app.multiselect(key='categories_'+lang).value,['盈利'])
            self.assertEqual(app.metric[0].value,original_metrics)

    def test_single_company_comparison_message_is_localized(self):
        state={'companies':{'SYNTHETIC':{'status':'completed'}}}
        app=self.app(f"render_comparison(Path({str(self.root)!r}),{state!r})").run()
        for lang in ('EN','RU'):
            app.selectbox(key='language').set_value(lang).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.info[0].value,text('请先完成至少两家公司的年报分析。',lang))

    def test_legacy_summary_has_localized_downloads_and_no_model_calls(self):
        body=f"render_summary(load_run(Path({str(self.run)!r})),None,None)"
        with patch('financial_workbook.service.FinancialAnalysisAgent._llm',side_effect=AssertionError('Browsing called model')):
            app=self.app(body).run()
            for lang in ('EN','RU'):
                app.selectbox(key='language').set_value(lang).run()
                self.assertFalse(app.exception)
                self.assert_controls_translated(app)
                self.assertEqual(len(app.get('download_button')),2)
                self.assertFalse(any(CJK.search(x.label) for x in app.get('download_button')))

    def test_saved_comparison_localizes_all_charts_and_sample_tables(self):
        import streamlit as st
        state={'companies':{cid:{'status':'completed','metadata':{'name':cid},'years':[2019,2020],
                                   'run_dir':'runs/'+cid} for cid in ('A','B')}}
        rows=[]
        for cid in ('A','B'):
            for year in (2019,2020):
                for metric,value,kind in [('revenue','1000000000','amount'),('net_income','100000000','amount'),
                                          ('净利率','.1','percent'),('资产负债率','.6','percent')]:
                    rows.append({'company_id':cid,'year':year,'metric':metric,'value':value,'format':kind,'reason':''})
        result={'currency':'CNY','rows':rows,
                'revenue_index':[{'company_id':cid,'year':year,'base_year':2019,'revenue_index':'100','reason':''}
                                 for cid in ('A','B') for year in (2019,2020)],
                'sample_statistics':[{'year':2020,'metric':'资产负债率','count':2,'selected_count':2,'median':'.6',
                                      'label':'用户选择公司样本中位数，不代表全行业'}]}
        comparison=self.root/'comparison.json'
        comparison.write_text(json.dumps(result),encoding='utf-8')
        signature=digest([['A','B'],[2019,2020],['runs/A','runs/B']])
        record={'signature':signature,'result':{'comparison':str(comparison),'workbook':str(self.run/'finalize_fixture/formal.xlsx')}}
        body=f"st.session_state.setdefault({'comparison_result_'+digest(str(self.root))[:10]!r},{record!r})\nrender_comparison(Path({str(self.root)!r}),{state!r})"
        captured=[]; actual_chart=st.altair_chart
        def chart(chart,*args,**kwargs):
            captured.append(chart.to_dict())
            return actual_chart(chart,*args,**kwargs)
        with patch('financial_workbook.web_pages.st.altair_chart',side_effect=chart),\
             patch('financial_workbook.web_pages.ResearchWorkflow.history',side_effect=AssertionError('Browsing recomputed peers')):
            app=self.app(body).run()
            for lang in ('EN','RU'):
                captured.clear()
                app.selectbox(key='language').set_value(lang).run()
                self.assertFalse(app.exception)
                self.assert_controls_translated(app)
                self.assertEqual(len(captured),4)
                self.assertFalse(CJK.search(json.dumps(captured,ensure_ascii=False)))
                for frame in app.dataframe:
                    self.assertFalse(CJK.search(frame.value.to_json(force_ascii=False)))
                company_widget=next(x for x in app.multiselect if x.key.startswith('compare_companies_'))
                self.assertEqual(company_widget.value,['A','B'])
                self.assertFalse(app.button(key='compare_submit').disabled)

    def test_pending_summary_translates_valuation_status(self):
        body=f"render_summary(load_run(Path({str(self.run)!r})),Path({str(self.root)!r}),'SYNTHETIC_TEST_ONLY')"
        with patch('financial_workbook.web_pages.ResearchWorkflow.offer',return_value={'status':'awaiting_user_choice'}),\
             patch('financial_workbook.web_pages.ResearchWorkflow.list_valuations',return_value=[]),\
             patch('financial_workbook.web_pages.state_comparisons',return_value=[]):
            app=self.app(body).run()
            for lang in ('EN','RU'):
                app.selectbox(key='language').set_value(lang).run()
                self.assertFalse(app.exception)
                self.assert_controls_translated(app)
                self.assertTrue(any(text('awaiting_user_choice',lang) in item.value for item in app.markdown))


if __name__=='__main__': unittest.main()
