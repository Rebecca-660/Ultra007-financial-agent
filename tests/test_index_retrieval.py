"""Persistent index and provenance tests using an explicitly lexical test model."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import fitz

from rag_step1 import config, report
from rag_step1.indexer import build_index, configure_embedding, embedding_profile, expected_manifest, load_index
from rag_step1.report import ReportSource, make_report_set
from rag_step1.retrieval import EvidenceRetriever
from rag_step1.lexical import PageBM25, expanded_query


class NoDenseCandidates:
    def retrieve(self, question):
        return []


def split_report_fixture(directory: Path, padding: int, risk_list: bool = False):
    year = 2031
    if risk_list:
        anchor = "Main risks to future development. (1) Supplier concentration risk. Continued on the next page."
        continuation = "(2) Commodity price fluctuations. (3) Overseas competition. (4) Exchange rate fluctuations."
    else:
        anchor = "Summary accounting data and financial indicators. Comparative cashflow table. Unit: SEK. Columns 2031 and 2030."
        continuation = "Net cash flows from operating activities. 2031: 555 SEK. Comparative column 2030: 444 SEK."
    path = directory / "boreal_report.pdf"
    with fitz.open() as pdf:
        for body in ["Unrelated appendix with legal information."] * padding + [anchor, continuation, "Unrelated subsequent business discussion."]:
            page = pdf.new_page()
            page.insert_textbox(fitz.Rect(40, 40, 555, 720), body, fontsize=10)
            page.insert_text((40, 810), f"Page {len(pdf) + 50}", fontsize=9)
        pdf.save(path)
    other = directory / "boreal_other_report.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), "Other reporting year: operating cashflow 999 and exchange rate risk.")
        pdf.save(other)
    report_set = make_report_set("unrelated-boreal", [ReportSource(path, year, padding+3), ReportSource(other, year+2, 1)])
    return report_set, year, padding + 1


def fixture_report_set(directory: Path, company: str = "sample-alpha"):
    sources = []
    for year, value in ((2024, 111), (2025, 222)):
        path = directory / f"alpha_{year}.pdf"
        with fitz.open() as pdf:
            first = pdf.new_page(width=595, height=1400)
            body = (f"ALPHA{year}PAGEONE Revenue {year}: {value} yuan. " +
                    "This audited annual report contains source evidence for financial review. " * 60)
            first.insert_textbox(fitz.Rect(40, 40, 555, 1250), body, fontsize=9)
            first.insert_text((40, 1360), "Page 10", fontsize=9)
            second = pdf.new_page()
            second.insert_text((40, 40), f"ALPHA{year}PAGETWO Depreciation and cash flow {year}: 44 yuan.")
            second.insert_text((40, 810), "Page 11", fontsize=9)
            pdf.save(path)
        sources.append(ReportSource(path, year, 2))
    text = directory / "supplement_2023.txt"
    text.write_text("TEXTFIRST Interest and noncash expenses 2023: 333 yuan.\f"
                    "TEXTSECOND Amortization and tangible assets 2023: 444 yuan.", encoding="utf-8")
    sources.append(ReportSource(text, 2023, 0))
    return make_report_set(company, sources)


class IndexRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name)
        cls.report_set = fixture_report_set(cls.directory)
        cls.index_dir = cls.directory / "alpha_index"
        cls.manifest = build_index(cls.report_set, cls.index_dir, offline=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def retriever(self, report_set=None, index_dir=None, top_k=5):
        report_set = report_set or self.report_set
        index = load_index(report_set, index_dir or self.index_dir, offline=True)
        return EvidenceRetriever(report_set, index, top_k=top_k)

    def test_persist_reload_sources_and_registry(self):
        cached = build_index(self.report_set, self.index_dir, offline=True)
        self.assertEqual(cached["status"], "already_built")
        self.assertEqual(cached["fingerprint"], self.manifest["fingerprint"])
        retriever = self.retriever()
        evidence = retriever.retrieve("Revenue 2025 222", report_years=[2025])
        self.assertTrue(evidence)
        for item in evidence:
            self.assertEqual(item["report_year"], 2025)
            self.assertEqual(item["company_id"], "sample-alpha")
            self.assertEqual(item["report_set_id"], self.report_set.report_set_id)
            self.assertEqual(item["file_name"], "alpha_2025.pdf")
            self.assertEqual(item["file_hash"], self.report_set.sources[2].file_hash)
            self.assertTrue(retriever.validate_evidence(item["evidence_id"]))
            self.assertEqual(item, retriever.registry[item["evidence_id"]])

    def test_page_boundaries_and_printed_pages(self):
        index = load_index(self.report_set, self.index_dir, offline=True)
        first_page_chunks = 0
        for node in index.docstore.docs.values():
            if node.metadata["file_name"].endswith(".pdf"):
                page = node.metadata["pdf_page"]
                self.assertIn(page, (1, 2))
                self.assertEqual(node.metadata["printed_page"], "10" if page == 1 else "11")
                if page == 1:
                    first_page_chunks += 1
                    self.assertNotIn("PAGETWO", node.text)
                else:
                    self.assertNotIn("PAGEONE", node.text)
        self.assertGreater(first_page_chunks, 2, "long pages must be chunked within their own page")

    def test_filter_and_unavailable_report_year(self):
        retriever = self.retriever()
        self.assertTrue(retriever.retrieve("Depreciation 2024", report_years=[2024]))
        self.assertEqual(retriever.retrieve("Revenue", report_years=[2099]), [])
        self.assertEqual(retriever.retrieve("Revenue", report_years=[]), [])

    def test_txt_sections_never_invent_page_numbers(self):
        retriever = self.retriever(top_k=10)
        evidence = retriever.retrieve("TEXTFIRST TEXTSECOND 2023", report_years=[2023])
        self.assertEqual(len(evidence), 2)
        for item in evidence:
            self.assertIsNone(item["pdf_page"])
            self.assertIsNone(item["printed_page"])
            self.assertIn("txt_page_unverifiable", item["parsing_warnings"])
            self.assertTrue(retriever.validate_evidence(item["evidence_id"]))

    def test_raw_page_context_preserves_headers_outside_retrieved_chunk(self):
        retriever = self.retriever()
        evidence = retriever.retrieve("audited annual report source evidence financial review", report_years=[2024])
        page_one = next(item for item in evidence if item["pdf_page"] == 1)
        self.assertIn("Revenue 2024: 111 yuan.", page_one["page_text"])
        self.assertNotIn("Revenue 2024: 111 yuan.", page_one["text"])
        self.assertIn(2024, page_one["possible_value_years"])
        self.assertTrue(retriever.validate_evidence(page_one["evidence_id"]))
        retriever.registry[page_one["evidence_id"]]["page_text"] += " Forged table header."
        self.assertFalse(retriever.validate_evidence(page_one["evidence_id"]))

    def test_unknown_id_and_mutated_return_value_cannot_forge_registry(self):
        retriever = self.retriever()
        evidence = retriever.retrieve("Revenue 2024", report_years=[2024])[0]
        evidence_id = evidence["evidence_id"]
        self.assertFalse(retriever.validate_evidence("ev_invented"))
        evidence["text"] = "Invented revenue 999999."
        self.assertNotEqual(evidence["text"], retriever.registry[evidence_id]["text"])
        self.assertTrue(retriever.validate_evidence(evidence_id))
        retriever.registry[evidence_id]["text"] = "Invented revenue 999999."
        self.assertFalse(retriever.validate_evidence(evidence_id))

    def test_changed_source_rejects_load_and_registered_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report_set = fixture_report_set(base)
            index_dir = base / "index"
            build_index(report_set, index_dir, offline=True)
            retriever = self.retriever(report_set, index_dir)
            item = retriever.retrieve("Interest 2023", report_years=[2023])[0]
            source = next(source for source in report_set.sources if source.file_name.endswith(".txt"))
            source.pdf_path.write_text("Changed uploaded document: amount 999 yuan.", encoding="utf-8")
            self.assertFalse(retriever.validate_evidence(item["evidence_id"]))
            with self.assertRaisesRegex(RuntimeError, "source changed"):
                load_index(report_set, index_dir, offline=True)
            fresh = make_report_set(report_set.company_id,
                                    [ReportSource(s.pdf_path, s.report_year, s.page_count) for s in report_set.sources])
            self.assertNotEqual(fresh.report_set_id, report_set.report_set_id)
            with self.assertRaisesRegex(RuntimeError, "another company or report set"):
                load_index(fresh, index_dir, offline=True)

    def test_company_isolation(self):
        beta = make_report_set("sample-beta", list(self.report_set.sources))
        with self.assertRaisesRegex(RuntimeError, "another company or report set"):
            load_index(beta, self.index_dir, offline=True)
        retriever = EvidenceRetriever(beta, load_index(self.report_set, self.index_dir, offline=True))
        with self.assertRaisesRegex(RuntimeError, "another company or report set"):
            retriever.retrieve("Revenue")

    def test_configuration_stale_and_generation_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report_set = fixture_report_set(base)
            index_dir = base / "index"
            first = build_index(report_set, index_dir, offline=True)
            with patch.object(config, "CHUNK_SIZE", 96):
                with self.assertRaisesRegex(RuntimeError, "stale"):
                    load_index(report_set, index_dir, offline=True)
                second = build_index(report_set, index_dir, offline=True)
                self.assertNotEqual(first["fingerprint"], second["fingerprint"])
                self.assertTrue(Path(first["generation_dir"]).is_dir())
                self.assertTrue(Path(second["generation_dir"]).is_dir())
                load_index(report_set, index_dir, offline=True)

    def test_parser_change_rebuilds_and_reuses_only_exact_text_embeddings(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report_set = fixture_report_set(base)
            index_dir = base / "index"
            first = build_index(report_set, index_dir, offline=True)
            embedding = configure_embedding(offline=True)
            with patch.object(report, "PARSER_VERSION", report.PARSER_VERSION + "-changed"):
                with self.assertRaisesRegex(RuntimeError, "stale"):
                    load_index(report_set, index_dir, offline=True)
                # Any newly computed text vector would fail this test. Metadata
                # updates must use saved vectors for identical raw text only.
                with patch.object(type(embedding), "_get_text_embedding", side_effect=AssertionError("unexpected inference")):
                    second = build_index(report_set, index_dir, offline=True)
                self.assertNotEqual(first["fingerprint"], second["fingerprint"])
                self.assertEqual(second["new_embeddings"], 0)
                self.assertEqual(second["reused_embeddings"], second["indexed_chunks"])
                self.assertTrue(Path(first["generation_dir"]).is_dir())
                self.retriever(report_set, index_dir).retrieve("Revenue 2024", report_years=[2024])

    def test_verified_printed_page_map_changes_index_fingerprint(self):
        source = self.report_set.sources[1]
        modified = replace(source, verified_printed_pages=((1, "999"),))
        sources = tuple(modified if s is source else s for s in self.report_set.sources)
        modified_set = replace(self.report_set, sources=sources)
        original = expected_manifest(self.report_set, offline=True)
        changed = expected_manifest(modified_set, offline=True)
        self.assertNotEqual(original["fingerprint"], changed["fingerprint"])
        with self.assertRaisesRegex(RuntimeError, "stale"):
            load_index(modified_set, self.index_dir, offline=True)

    def test_embedding_cache_does_not_normalize_changed_input_text(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report_set = fixture_report_set(base)
            index_dir = base / "index"
            first = build_index(report_set, index_dir, offline=True)
            original_extract = report.extract_source
            def alternate_extraction(source):
                return [replace(page, text=page.text.replace("333 yuan", "333  yuan"))
                        for page in original_extract(source)]
            with patch.object(report, "PARSER_VERSION", report.PARSER_VERSION + "-whitespace"), \
                 patch("rag_step1.indexer.extract_source", side_effect=alternate_extraction):
                rebuilt = build_index(report_set, index_dir, offline=True)
            self.assertEqual(rebuilt["new_embeddings"], 1)
            self.assertEqual(rebuilt["reused_embeddings"], first["indexed_chunks"] - 1)

    def test_embedding_cache_rejects_changed_model_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report_set = fixture_report_set(base)
            index_dir = base / "index"
            build_index(report_set, index_dir, offline=True)
            changed_profile = {**embedding_profile(offline=True), "model_hash": "1" * 64}
            with patch("rag_step1.indexer.embedding_profile", return_value=changed_profile):
                rebuilt = build_index(report_set, index_dir, offline=True)
            self.assertEqual(rebuilt["reused_embeddings"], 0)
            self.assertEqual(rebuilt["new_embeddings"], rebuilt["indexed_chunks"])

    def test_embedding_cache_rejects_corrupt_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report_set = fixture_report_set(base)
            index_dir = base / "index"
            built = build_index(report_set, index_dir, offline=True)
            (Path(built["generation_dir"]) / "default__vector_store.json").write_text("{}", encoding="utf-8")
            rebuilt = build_index(report_set, index_dir, force=True, offline=True)
            self.assertEqual(rebuilt["reused_embeddings"], 0)
            self.assertEqual(rebuilt["new_embeddings"], rebuilt["indexed_chunks"])

    def test_dependency_versions_participate_in_index_fingerprint(self):
        original = expected_manifest(self.report_set, offline=True)
        actual_version = __import__("importlib.metadata", fromlist=["version"]).version
        def updated_version(name):
            return actual_version(name) + "-changed" if name == "PyMuPDF" else actual_version(name)
        with patch("rag_step1.indexer.importlib.metadata.version", side_effect=updated_version):
            changed = expected_manifest(self.report_set, offline=True)
            self.assertNotEqual(original["fingerprint"], changed["fingerprint"])
            with self.assertRaisesRegex(RuntimeError, "stale"):
                load_index(self.report_set, self.index_dir, offline=True)

    def test_corrupted_storage_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report_set = fixture_report_set(base)
            index_dir = base / "index"
            manifest = build_index(report_set, index_dir, offline=True)
            (Path(manifest["generation_dir"]) / "docstore.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "corrupted"):
                load_index(report_set, index_dir, offline=True)

    def test_foreign_directory_not_overwritten(self):
        foreign = self.directory / "foreign"
        foreign.mkdir(exist_ok=True)
        sentinel = foreign / "user_file.txt"
        sentinel.write_text("preserve user data", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "ownership marker"):
            build_index(self.report_set, foreign, force=True, offline=True)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve user data")

    def test_custom_query_engine_returns_snippets_and_source_nodes(self):
        retriever = self.retriever()
        response = retriever.query_engine.query("Revenue 2025 222")
        evidence = json.loads(str(response))["evidence"]
        self.assertTrue(evidence)
        self.assertEqual(len(response.source_nodes), len(evidence))
        self.assertEqual(response.metadata["answer_mode"], "retrieved_snippets_only")

    def test_offline_profile_is_explicitly_not_multilingual_validation(self):
        profile = embedding_profile(offline=True)
        self.assertEqual(profile["kind"], "offline_lexical_test_only")
        self.assertFalse(profile["multilingual_validation"])


class HybridRetrievalTests(unittest.TestCase):
    def test_split_tables_recovered_with_lexical_only_anchor_after_relocation(self):
        for padding in (0, 4):
            with self.subTest(padding=padding), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                report_set, year, anchor_page = split_report_fixture(base, padding)
                index_dir = base / "index"
                build_index(report_set, index_dir, offline=True)
                index = load_index(report_set, index_dir, offline=True)
                retriever = EvidenceRetriever(report_set, index, top_k=3)
                with patch.object(type(index), "as_retriever", return_value=NoDenseCandidates()):
                    evidence = retriever.retrieve("Summary accounting data and financial indicators comparative cashflow table", report_years=[year])
                anchor = next(item for item in evidence if item["retrieval_origin"] == "hybrid_ranked")
                self.assertEqual(anchor["pdf_page"], anchor_page)
                self.assertIsNone(anchor["score"], "lexical candidates must not invent dense similarity")
                self.assertGreater(anchor["lexical_score"], 0)
                continuation = next(item for item in evidence if item["pdf_page"] == anchor_page + 1)
                self.assertIn("Comparative column 2030: 444 SEK.", continuation["page_text"])
                self.assertEqual(continuation["context_anchor_node_id"], anchor["node_id"])
                self.assertEqual(continuation["retrieval_origin"], "adjacent_page_context")
                self.assertIsNone(continuation["score"])
                self.assertIsNone(continuation["lexical_score"])
                self.assertIsNone(continuation["fusion_score"])
                for item in evidence:
                    self.assertEqual(item["report_year"], year)
                    self.assertEqual(item["file_name"], "boreal_report.pdf")
                    self.assertTrue(retriever.validate_evidence(item["evidence_id"]))

    def test_numbered_list_continuation_has_its_own_citation_and_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report_set, year, anchor_page = split_report_fixture(base, padding=2, risk_list=True)
            index_dir = base / "index"
            build_index(report_set, index_dir, offline=True)
            index = load_index(report_set, index_dir, offline=True)
            retriever = EvidenceRetriever(report_set, index, top_k=3)
            with patch.object(type(index), "as_retriever", return_value=NoDenseCandidates()):
                evidence = retriever.retrieve("All main risks to future development", report_years=[year])
            continuation = next(item for item in evidence if item["pdf_page"] == anchor_page + 1)
            anchor = next(item for item in evidence if item["pdf_page"] == anchor_page)
            self.assertNotEqual(continuation["evidence_id"], anchor["evidence_id"])
            self.assertNotEqual(continuation["printed_page"], anchor["printed_page"])
            self.assertIn("(4) Exchange rate fluctuations.", continuation["page_text"])
            one = EvidenceRetriever(report_set, index, top_k=1)
            with patch.object(type(index), "as_retriever", return_value=NoDenseCandidates()):
                limited = one.retrieve("All main risks to future development", report_years=[year])
            self.assertEqual(len(limited), 1)
            self.assertEqual(limited[0]["retrieval_origin"], "hybrid_ranked")

    def test_context_anchor_cannot_be_self_or_a_different_source(self):
        from rag_step1.retrieval import _evidence_id
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report_set, year, _ = split_report_fixture(base, padding=1)
            index_dir = base / "index"
            build_index(report_set, index_dir, offline=True)
            index = load_index(report_set, index_dir, offline=True)
            retriever = EvidenceRetriever(report_set, index, top_k=3)
            with patch.object(type(index), "as_retriever", return_value=NoDenseCandidates()):
                evidence = retriever.retrieve("Summary accounting data financial indicators comparative cashflow table", report_years=[year])
            context = dict(next(item for item in evidence if item["retrieval_origin"] == "adjacent_page_context"))
            other = next(node for node in index.docstore.docs.values() if node.metadata["file_name"] == "boreal_other_report.pdf")
            for invalid_anchor in (context["node_id"], other.node_id):
                context["context_anchor_node_id"] = invalid_anchor
                forged_id = _evidence_id(context)
                context["evidence_id"] = forged_id
                retriever.registry[forged_id] = dict(context)
                self.assertFalse(retriever.validate_evidence(forged_id))

    def test_bilingual_glossary_expands_search_only(self):
        texts = ["Operating revenue in the audited statements.", "Gross profit margin in a different table."]
        ranking = PageBM25(texts).rank("营业收入是多少", {0, 1})
        self.assertEqual(ranking[0][0], 0)
        self.assertIn("operating revenue", expanded_query("营业收入是多少"))
        self.assertEqual(texts[0], "Operating revenue in the audited statements.")


if __name__ == "__main__":
    unittest.main()
