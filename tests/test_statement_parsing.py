"""Independent synthetic PDF regressions for adaptive statement parsing.

Numbers and source layouts are intentionally simple and hand-verifiable. No
real-company files, model API, or network connection is needed by these tests.
"""
from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest

import pymupdf

from financial_workbook.extract import extract, identify, locate
from financial_workbook.parsing import validated_profile
from financial_workbook.review import assert_sources
from rag_step1.report import ReportSource, make_report_set


ROOT = Path(__file__).resolve().parents[1]


def text(page, point, value, size=10):
    page.insert_text(point, value, fontsize=size,
                     fontname='china-s' if any(ord(c) > 127 for c in value) else 'helv')


def table(page, top, rows, *, header=False, previous_year=2023, offset=0):
    """Draw a real three-column table, including a two-line source label."""
    xs = [40+offset, 260+offset, 420+offset, 580+offset]
    current_y = top
    borders = [top]
    if header:
        text(page, (xs[0]+5, current_y+18), 'Item')
        text(page, (xs[1]+15, current_y+18), '2024-12-31')
        text(page, (xs[2]+15, current_y+18), f'{previous_year}-12-31')
        current_y += 30
        borders.append(current_y)
    for label, current, prior in rows:
        label_lines = label.split('\n')
        height = 42 if len(label_lines) > 1 else 30
        for index, line in enumerate(label_lines):
            text(page, (xs[0]+5, current_y+16+index*14), line, 9)
        for right, amount in zip(xs[2:], (current, prior)):
            raw = f'{amount:.2f}'
            width = pymupdf.get_text_length(raw, fontsize=10)
            text(page, (right-6-width, current_y+height/2+4), raw)
        current_y += height
        borders.append(current_y)
    for x in xs:
        page.draw_line((x, top), (x, current_y), width=.5)
    for y in borders:
        page.draw_line((xs[0], y), (xs[-1], y), width=.5)
    return current_y


def fixture(path: Path, *, title_only=False, currency_line='Unit: CNY',
            declaration=None, parent=True, continuation_year=None,
            continuation_offset=0, body_currency_line=None,
            balance_title='Consolidated Balance Sheets', include_legal_fee=False):
    document = pymupdf.open()
    first = document.new_page(width=640, height=850)
    if title_only:
        text(first, (40, 740), balance_title, 12)
        text(first, (40, 775), currency_line)
        first = document.new_page(width=640, height=850)
        if body_currency_line:
            text(first, (40, 50), body_currency_line)
        table_top = 80
    else:
        text(first, (40, 45), balance_title, 12)
        text(first, (40, 75), currency_line)
        table_top = 105
    table(first, table_top, [('Total current assets', D(90), D(80)),
                             ('Inventory', D(20), D(18))], header=True)
    continuation = document.new_page(width=640, height=850)
    text(continuation, (40, 30), 'SYNTHETIC Annual Report 2024', 8)
    bottom = table(continuation, 70,
                   [('Lease liabilities\npayable after one year', D('7.25'), D('6.50')),
                    ('Total assets', D(120), D(100)),
                    ('Total liabilities', D(70), D(60)),
                    ('Total equity', D(50), D(40))],
                   header=continuation_year is not None,
                   previous_year=continuation_year or 2023,
                   offset=continuation_offset)
    if parent:
        text(continuation, (40, bottom+45), 'Parent company Balance Sheets', 12)
        text(continuation, (40, bottom+70), 'Unit: USD')
        table(continuation, bottom+90,
              [('Total assets', D(999), D(888)),
               ('Total liabilities', D(600), D(500)),
               ('Total equity', D(399), D(388))], header=True)
    income_rows = [('Operating revenue', D(150), D(130))]
    if include_legal_fee:
        income_rows.append(('Legal and professional fees', D(5), D(4)))
    income_rows.append(('Net income', D(15), D(13)))
    for title, rows in [
        ('Consolidated Income Statements', income_rows),
        ('Consolidated Cash Flow Statements', [('Beginning balance of cash and cash equivalents', D(10), D(8)),
                                               ('Net increase in cash and cash equivalents', D(3), D(2)),
                                               ('Ending balance of cash and cash equivalents', D(13), D(10))]),
    ]:
        page = document.new_page(width=640, height=850)
        text(page, (40, 45), title, 12)
        text(page, (40, 75), currency_line)
        # Long source labels remain entirely within the label column.
        short_rows = [(label.replace(' and cash equivalents', '\nand cash equivalents'), a, b)
                      for label, a, b in rows]
        table(page, 105, short_rows, header=True)
    if declaration:
        page = document.new_page(width=640, height=850)
        text(page, (40, 80), declaration, 10)
    document.save(path)
    count = len(document)
    document.close()
    source = ReportSource(path.resolve(), 2024, count)
    return make_report_set('SYNTHETIC_LAYOUT_TEST', [source])


def currency_profile(report_set, currency='CNY', **overrides):
    source = report_set.sources[0]
    confirmation = {'file_name': source.file_name, 'file_hash': source.file_hash,
                    'report_year': source.report_year, 'currency': currency,
                    'confirmed_by': 'SYNTHETIC_METADATA_CONFIRMATION'}
    confirmation.update(overrides)
    return {'report_currencies': [confirmation]}


class AdaptiveStatementParsingTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'tmp').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='statement-tests-', dir=ROOT/'tmp')
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)/'synthetic2024.pdf'

    def parsed(self, **options):
        report_set = fixture(self.path, **options)
        return report_set, extract(report_set)

    def test_headerless_continuation_preserves_wrapped_label_and_values(self):
        report_set, dataset = self.parsed()
        balance = next(s for s in dataset.statements if s.kind == 'BS')
        self.assertEqual(balance.pdf_pages, [1, 2])
        self.assertEqual(len(balance.rows), 6)
        wrapped = next(r for r in balance.rows if r.raw_label.startswith('Lease liabilities'))
        self.assertIn('payable after one year', wrapped.raw_label)
        self.assertEqual(wrapped.values, [D('7.25'), D('6.50')])
        self.assertEqual(wrapped.pdf_page, 2)
        self.assertEqual(next(r for r in balance.rows if r.canonical_metric == 'assets').values,
                         [D(120), D(100)])
        self.assertTrue(all(check['status'] == 'pass' for check in balance.checks))
        assert_sources(dataset, report_set)

    def test_title_only_page_inherits_unit_into_next_page_table(self):
        report_set, dataset = self.parsed(title_only=True)
        balance = next(s for s in dataset.statements if s.kind == 'BS')
        self.assertEqual(balance.pdf_pages, [1, 2, 3])
        self.assertEqual({r.pdf_page for r in balance.rows}, {2, 3})
        self.assertEqual(balance.currency, 'CNY')
        self.assertEqual(balance.scale, D(1))
        self.assertEqual(len(balance.rows), 6)
        assert_sources(dataset, report_set)

    def test_title_unit_and_body_currency_complete_one_verified_unit(self):
        _, dataset = self.parsed(title_only=True, currency_line='单位：元',
                                  body_currency_line='币种：人民币')
        balance = next(s for s in dataset.statements if s.kind == 'BS')
        self.assertEqual(balance.currency, 'CNY')
        self.assertEqual(balance.scale, D(1))

    def test_title_base_units_and_body_ten_thousand_units_conflict(self):
        report_set = fixture(self.path, title_only=True, currency_line='单位：元',
                             body_currency_line='单位：万元')
        with self.assertRaisesRegex(ValueError, '单位'):
            extract(report_set)

    def test_currency_only_title_does_not_force_body_millions_to_base_units(self):
        _, dataset = self.parsed(title_only=True, currency_line='Currency: CNY',
                                  body_currency_line='Unit: CNY millions')
        balance = next(s for s in dataset.statements if s.kind == 'BS')
        self.assertEqual(balance.currency, 'CNY')
        self.assertEqual(balance.scale, D(1000000))

    def test_parent_table_on_same_page_never_enters_consolidated_rows(self):
        _, dataset = self.parsed()
        balance = next(s for s in dataset.statements if s.kind == 'BS')
        self.assertFalse(any(D(999) in r.values or D(888) in r.values for r in balance.rows))
        self.assertEqual(balance.currency, 'CNY')
        self.assertLess(max(r.bbox[3] for r in balance.rows if r.pdf_page == 2), 230)

    def test_changed_continuation_year_columns_are_rejected(self):
        report_set = fixture(self.path, continuation_year=2022)
        with self.assertRaisesRegex(ValueError, '续表年度列|年度列头'):
            extract(report_set)

    def test_shifted_headerless_grid_columns_are_rejected(self):
        report_set = fixture(self.path, continuation_offset=25)
        with self.assertRaisesRegex(ValueError, '金额栏位置|续表|续页'):
            extract(report_set)

    def test_chinese_numbering_and_fullwidth_annotations_map_semantically(self):
        examples = {
            '一、营业总收入': 'total_revenue',
            '其中：营业收入': 'revenue',
            '其中：营业成本': 'cost_of_sales',
            '三、营业利润（亏损以“－”号填列）': 'operating_profit',
            '五、净利润（净亏损以“－”号填列）': 'net_income',
            '1.归属于母公司所有者的净利润': 'parent_net_income',
            '五、现金及现金等价物净增加额': 'cash_change',
            '加：期初现金及现金等价物余额': 'cash_opening',
            '六、期末现金及现金等价物余额': 'cash_closing',
        }
        for original, expected in examples.items():
            with self.subTest(original=original):
                self.assertEqual(identify(original), expected)
        self.assertNotEqual(identify('归属于母公司所有者的净利润'), identify('净利润'))
        self.assertIsNone(identify('持续经营净利润（净亏损以“－”号填列）'))

    def test_legal_expense_row_is_not_a_signature_terminator(self):
        report_set, dataset = self.parsed(include_legal_fee=True)
        income = next(s for s in dataset.statements if s.kind == 'IS')
        self.assertEqual(len(income.rows), 3)
        legal = next(r for r in income.rows if r.raw_label == 'Legal and professional fees')
        self.assertEqual(legal.values, [D(5), D(4)])
        profit = next(r for r in income.rows if r.canonical_metric == 'net_income')
        self.assertEqual(profit.values, [D(15), D(13)])
        assert_sources(dataset, report_set)

    def test_spaced_chinese_title_locates_and_reparses_consistently(self):
        report_set, dataset = self.parsed(balance_title='合 并 资 产 负 债 表')
        balance = next(s for s in dataset.statements if s.kind == 'BS')
        self.assertEqual(balance.pdf_pages, [1, 2])
        self.assertEqual(next(r for r in balance.rows if r.canonical_metric == 'assets').values,
                         [D(120), D(100)])
        assert_sources(dataset, report_set)

    def test_explicit_report_presentation_currency_supplies_yuan_unit(self):
        report_set, dataset = self.parsed(currency_line='单位：元',
                                           declaration='本财务报表以人民币列示。')
        self.assertTrue(all(s.currency == 'CNY' and s.scale == D(1) for s in dataset.statements))
        self.assertTrue(all('列报币种依据 PDF' in s.raw_unit for s in dataset.statements))
        assert_sources(dataset, report_set)

    def test_functional_currency_does_not_imply_group_presentation_currency(self):
        _, dataset = self.parsed(currency_line='单位：元',
                                  declaration='本公司采用人民币为记账本位币。')
        self.assertTrue(all(s.currency is None for s in dataset.statements))
        self.assertTrue(all(s.scale == D(1) for s in dataset.statements))

    def test_currency_confirmation_is_bound_to_original_pdf_and_year(self):
        report_set = fixture(self.path, currency_line='单位：元')
        profile = currency_profile(report_set)
        dataset = extract(report_set, profile=profile)
        self.assertTrue(all(s.currency == 'CNY' for s in dataset.statements))
        self.assertTrue(all('用户确认列报币种' in s.raw_unit for s in dataset.statements))
        assert_sources(dataset, report_set)
        for overrides in [{'file_hash': '0'*64}, {'report_year': 2023}, {'file_name': 'another.pdf'}]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                validated_profile(currency_profile(report_set, **overrides), report_set)

    def test_confirmation_cannot_override_explicit_reporting_currency(self):
        report_set = fixture(self.path, currency_line='单位：元',
                             declaration='The financial statements are presented in USD.')
        with self.assertRaisesRegex(ValueError, '原报告明确声明不一致'):
            extract(report_set, profile=currency_profile(report_set, 'CNY'))

    def test_confirmation_cannot_override_statement_unit_currency(self):
        report_set = fixture(self.path)
        with self.assertRaisesRegex(ValueError, '主表币种不一致'):
            extract(report_set, profile=currency_profile(report_set, 'USD'))

    def test_candidate_number_tampering_fails_original_cell_reparse(self):
        report_set, dataset = self.parsed()
        altered = dataset.model_copy(deep=True)
        altered.statements[0].rows[0].values[0] += D(1)
        with self.assertRaisesRegex(ValueError, '候选行、数值或证据已改动'):
            assert_sources(altered, report_set)

    def test_candidate_page_tampering_fails_original_source_reparse(self):
        report_set, dataset = self.parsed()
        for alteration in ('row_page', 'statement_pages'):
            changed = dataset.model_copy(deep=True)
            balance = next(s for s in changed.statements if s.kind == 'BS')
            if alteration == 'row_page':
                next(r for r in balance.rows if r.pdf_page == 2).pdf_page = 1
            else:
                balance.pdf_pages = [1]
            with self.subTest(alteration=alteration), self.assertRaises(ValueError):
                assert_sources(changed, report_set)


if __name__ == '__main__':
    unittest.main()
