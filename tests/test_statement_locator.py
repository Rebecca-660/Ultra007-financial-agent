"""Synthetic source geometry covers general statement-selection decisions."""
import unittest
import pymupdf

from financial_workbook.statement_locator import (
    caption_hits,find_statement_pages,statement_body_bounds,
)


def caption(page,title='Consolidated Balance Sheets',y=55):
    page.insert_text((40,y),title,fontsize=12)


def table(page,rows,*,year=2021,header_y=100,opening=False):
    page.insert_text((40,header_y-20),'Unit: USD',fontsize=10)
    page.insert_text((40,header_y),'Item',fontsize=10)
    headers=['2020-12-31','2021-01-01'] if opening else [f'{year}-12-31',f'{year-1}-12-31']
    for x,value in zip([320,460],headers): page.insert_text((x,header_y),value,fontsize=10)
    body(page,rows,y=header_y+35)


def body(page,rows,*,y=80,offset=0):
    for i,(label,a,b) in enumerate(rows):
        baseline=y+i*30
        page.insert_text((40,baseline),label,fontsize=9)
        for edge,value in [(410+offset,a),(550+offset,b)]:
            page.insert_textbox(pymupdf.Rect(edge-65,baseline-12,edge,baseline+7),value,fontsize=10,align=2)


class StatementLocatorTests(unittest.TestCase):
    def setUp(self): self.document=pymupdf.open()
    def tearDown(self): self.document.close()
    def page(self): return self.document.new_page(width=600,height=800)

    def main(self,*,year=2021):
        page=self.page(); caption(page)
        table(page,[('Total assets','200.00','180.00'),('Total liabilities and equity','200.00','180.00')],year=year)
        return page

    def test_opening_adjustment_is_not_a_second_year_end_statement(self):
        self.main()
        page=self.page(); caption(page)
        table(page,[('Total assets','180.00','181.00')],opening=True)
        self.assertEqual(find_statement_pages(self.document,2021,'BS','source.pdf'),[1])

    def test_continuation_inherits_columns_and_stops_before_parent_statement(self):
        page=self.page(); caption(page)
        table(page,[('Total assets','200.00','180.00')])
        page=self.page()
        body(page,[('Total liabilities','120.00','100.00'),('Total equity','80.00','80.00'),('Total liabilities and equity','200.00','180.00')])
        caption(page,'Parent Company Balance Sheet',y=400)
        table(page,[('Total assets','20.00','18.00')],header_y=450)
        self.assertEqual(find_statement_pages(self.document,2021,'BS','source.pdf'),[1,2])
        top,bottom=statement_body_bounds(self.document[1],'BS',continued=True)
        self.assertLess(top,80)
        self.assertGreater(bottom,130)
        self.assertLess(bottom,400)

    def test_title_after_long_audit_prose_is_found(self):
        page=self.page()
        for i in range(20): page.insert_text((40,40+i*14),'Auditor responsibility disclosure; this is explanatory prose.',fontsize=10)
        caption(page,y=400)
        table(page,[('Total assets','200.00','180.00'),('Total liabilities and equity','200.00','180.00')],header_y=450)
        self.assertEqual(find_statement_pages(self.document,2021,'BS','source.pdf'),[1])

    def test_title_and_unit_can_precede_column_header_on_next_page(self):
        page=self.page(); caption(page,y=690)
        page.insert_text((40,730),'Unit: USD',fontsize=10)
        page=self.page()
        table(page,[('Total assets','200.00','180.00'),('Total liabilities and equity','200.00','180.00')],header_y=100)
        self.assertEqual(find_statement_pages(self.document,2021,'BS','source.pdf'),[1,2])

    def test_two_independent_current_year_main_tables_are_ambiguous(self):
        self.main(); self.main()
        with self.assertRaisesRegex(ValueError,'多组有效候选.*1.*2'):
            find_statement_pages(self.document,2021,'BS','source.pdf')

    def test_two_current_year_main_tables_on_one_page_are_not_collapsed(self):
        page=self.main()
        caption(page,y=420)
        table(page,[('Total assets','201.00','181.00'),('Total liabilities and equity','201.00','181.00')],header_y=470)
        with self.assertRaisesRegex(ValueError,'多组有效候选'):
            find_statement_pages(self.document,2021,'BS','source.pdf')

    def test_current_main_after_same_page_adjustment_is_not_misparsed(self):
        page=self.page(); caption(page)
        table(page,[('Total assets','180.00','181.00')],opening=True)
        caption(page,y=420)
        table(page,[('Total assets','200.00','180.00'),('Total liabilities and equity','200.00','180.00')],header_y=470)
        with self.assertRaisesRegex(ValueError,'另一同名表之后'):
            find_statement_pages(self.document,2021,'BS','source.pdf')

    def test_wrong_report_year_does_not_select_another_period(self):
        self.main(year=2020)
        with self.assertRaisesRegex(ValueError,'2021.*有效期间列'):
            find_statement_pages(self.document,2021,'BS','source.pdf')

    def test_parent_only_table_and_audit_prose_are_not_main_tables(self):
        page=self.page(); caption(page,'Parent Company Balance Sheet')
        table(page,[('Total assets','200.00','180.00')])
        page=self.page()
        page.insert_textbox(pymupdf.Rect(40,40,550,200),
            'The consolidated balance sheets at December 31, 2021 and December 31, 2020 '
            'have been audited. This reference describes an audit opinion, not a table.',fontsize=10)
        with self.assertRaisesRegex(ValueError,'未找到'):
            find_statement_pages(self.document,2021,'BS','source.pdf')

    def test_caption_and_years_without_financial_cells_are_not_enough(self):
        page=self.page(); caption(page)
        page.insert_text((40,100),'As of December 31, 2021 and December 31, 2020',fontsize=10)
        page.insert_text((40,140),'No original statement cells occur in this audit excerpt.',fontsize=10)
        with self.assertRaisesRegex(ValueError,'未找到'):
            find_statement_pages(self.document,2021,'BS','source.pdf')

    def test_wrapped_english_caption_and_repeated_continuation_heading(self):
        page=self.page()
        caption(page,'Consolidated Statements of',y=50)
        page.insert_text((40,65),'Cash Flows',fontsize=12)
        table(page,[('Cash from operating activities','50.00','40.00')])
        page=self.page(); caption(page,'Consolidated Statements of Cash Flows (continued)')
        table(page,[('Ending balance of cash and cash equivalents','20.00','18.00')])
        self.assertEqual(caption_hits(self.document[0])[0].kind,'CF')
        self.assertEqual(find_statement_pages(self.document,2021,'CF','source.pdf'),[1,2])

    def test_repeating_page_signatures_do_not_truncate_the_statement(self):
        page=self.page(); caption(page)
        table(page,[('Total assets','200.00','180.00')])
        page.insert_text((40,700),'Legal Representative: Synthetic Name',fontsize=10)
        page=self.page(); caption(page,'Consolidated Balance Sheets (continued)')
        table(page,[('Total liabilities and equity','200.00','180.00')])
        self.assertEqual(find_statement_pages(self.document,2021,'BS','source.pdf'),[1,2])

    def test_unclosed_statement_cannot_silently_skip_shifted_amount_columns(self):
        page=self.page(); caption(page)
        table(page,[('Total current assets','90.00','80.00'),('Inventory','20.00','18.00')])
        page=self.page()
        body(page,[('Total assets','120.00','100.00'),('Total liabilities','70.00','60.00'),('Total equity','50.00','40.00')],offset=25)
        with self.assertRaisesRegex(ValueError,'物理页 2.*金额栏位置.*续表'):
            find_statement_pages(self.document,2021,'BS','source.pdf')

    def test_proven_statement_end_does_not_claim_another_numeric_table(self):
        self.main()
        page=self.page()
        body(page,[('Another disclosed item','120.00','100.00'),('Another detail','70.00','60.00')],offset=25)
        self.assertEqual(find_statement_pages(self.document,2021,'BS','source.pdf'),[1])


if __name__=='__main__': unittest.main()
