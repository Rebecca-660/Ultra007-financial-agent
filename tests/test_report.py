"""Offline ingestion checks: physical pages, upload identity, and unsupported data."""
import json
import tempfile
import unittest
from pathlib import Path
import fitz
from rag_step1.qa import beyond_corpus_actuals
from rag_step1.report import (ReportSource, detect_report_year, extract_pages,
                             extract_source, inspect_reports, load_report_set, make_report_set)

def pdf_fixture(path, text="2020 Annual Report. Revenue 2019: 100.00 RMB.", footer=None, blank=False):
    with fitz.open() as pdf:
        page = pdf.new_page()
        if not blank:
            page.insert_text((72, 72), text)
        if footer:
            page.insert_text((72, page.rect.height - 25), footer)
        pdf.save(path)

class ReportTests(unittest.TestCase):
    def test_physical_page_and_footer_are_independent(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.pdf"
            pdf_fixture(path, footer="Page 17 of 88")
            pages, count = extract_pages(path)
            self.assertEqual(count, 1)
            self.assertEqual(pages[0].pdf_page, 1)
            self.assertEqual(pages[0].printed_page, "17")
            self.assertIn("numeric_table_columns_require_review", pages[0].parsing_warnings)

    def test_body_number_is_not_printed_page(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.pdf"
            pdf_fixture(path, "8")
            page = extract_pages(path)[0][0]
            self.assertIsNone(page.printed_page)
            self.assertIn("printed_page_not_verified", page.parsing_warnings)

    def test_bottom_table_number_not_a_verified_printed_page(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "table.pdf"
            pdf_fixture(path, "Bottom financial table cell", footer="123")
            page = extract_pages(path)[0][0]
            self.assertIsNone(page.printed_page)
            self.assertIn("numeric_footer_requires_visual_verification", page.parsing_warnings)
            verified = extract_source(ReportSource(path, 2020, 1, ((1, "123"),)))[0]
            self.assertEqual(verified.printed_page, "123")

    def test_blank_scan_stays_missing(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "scan.pdf"
            pdf_fixture(path, blank=True)
            result = inspect_reports([ReportSource(path, 2020, 1)], Path(d) / "review")
            self.assertEqual(result["reports"][0]["status"], "unsupported_no_text")
            self.assertEqual(result["reports"][0]["empty_pages"], [1])

    def test_image_only_pdf_is_not_treated_as_text_report(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "image_scan.pdf"
            with fitz.open() as source:
                page = source.new_page()
                page.insert_text((72, 72), "Scanned annual report: Revenue 2020 = 100 RMB")
                raster = page.get_pixmap().tobytes("png")
            with fitz.open() as scan:
                page = scan.new_page()
                page.insert_image(page.rect, stream=raster)
                scan.save(path)
            with fitz.open(path) as scan:
                self.assertTrue(scan[0].get_images())
            result = inspect_reports([ReportSource(path, 2020, 1)], Path(d) / "review")
            self.assertEqual(result["reports"][0]["text_page_count"], 0)
            self.assertEqual(result["reports"][0]["status"], "unsupported_no_text")

    def test_txt_form_feed_does_not_invent_physical_pages(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.txt"
            path.write_text("Revenue: 100\fProfit: 10", encoding="utf-8")
            pages = extract_source(ReportSource(path, 2020, 0))
            self.assertEqual(len(pages), 2)
            self.assertTrue(all(p.pdf_page is None and p.printed_page is None for p in pages))
            self.assertTrue(all("txt_page_unverifiable" in p.parsing_warnings for p in pages))

    def test_report_set_changes_with_company_file_and_declared_year(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.txt"
            path.write_text("revenue 100", encoding="utf-8")
            first = make_report_set("company-a", [ReportSource(path, 2020, 0)])
            other = make_report_set("company-b", [ReportSource(path, 2020, 0)])
            year = make_report_set("company-a", [ReportSource(path, 2021, 0)])
            path.write_text("revenue 200", encoding="utf-8")
            changed = make_report_set("company-a", [ReportSource(path, 2020, 0)])
            self.assertEqual(len({first.report_set_id, other.report_set_id, year.report_set_id, changed.report_set_id}), 4)

    def test_manifest_rejects_mixed_company_and_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.txt"
            path.write_text("report", encoding="utf-8")
            manifest = Path(d) / "report_set.json"
            payload = {"company_id": "a", "reports": [{"file_name": path.name, "report_year": 2020, "company_id": "b"}]}
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "single_company_confirmed"):
                load_report_set(manifest)
            payload["single_company_confirmed"] = True
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "另一家"):
                load_report_set(manifest)

    def test_report_year_separate_from_comparative_text_year(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "annual_2020.pdf"
            pdf_fixture(path)
            manifest = Path(d) / "report_set.json"
            manifest.write_text(json.dumps({"company_id": "a", "single_company_confirmed": True,
                                           "reports": [{"file_name": path.name, "report_year": 2020}]}), encoding="utf-8")
            report = load_report_set(manifest).sources[0]
            self.assertEqual(report.report_year, 2020)
            self.assertIn("2019", extract_source(report)[0].text)
            self.assertEqual(detect_report_year(path), 2020)

    def test_future_actual_refusal(self):
        self.assertTrue(beyond_corpus_actuals("2021 audited actual revenue", [2020]))
        self.assertFalse(beyond_corpus_actuals("2021 plan", [2020]))

if __name__ == "__main__":
    unittest.main()
