"""Return registered, page-traceable report snippets without LLM synthesis."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from .report import ReportSet, extract_source, sha256_file
from .lexical import PageBM25, expanded_query, tokens


def _evidence_id(evidence: dict) -> str:
    identity = {key: evidence[key] for key in
                ("node_id", "text", "page_text", "possible_value_years", "company_id",
                 "report_set_id", "file_name", "file_hash", "report_year", "pdf_page",
                 "printed_page", "parsing_warnings")}
    identity["retrieval_origin"] = evidence.get("retrieval_origin")
    identity["context_anchor_node_id"] = evidence.get("context_anchor_node_id")
    return "ev_" + hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")).encode("utf-8")).hexdigest()


class EvidenceRetriever:
    """One retriever and evidence registry for exactly one company/report set."""

    def __init__(self, report_set: ReportSet, index: Any, top_k: int = 5):
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self.report_set = report_set
        self.index = index
        self.top_k = top_k
        self.registry: dict[str, dict] = {}
        self._sources = {source.file_name: source for source in report_set.sources}
        self._page_cache: dict[tuple[str, str], dict] = {}
        self._catalog_cache: list[dict] | None = None
        self._bm25: PageBM25 | None = None
        self.query_engine = self._query_engine()

    def _query_engine(self):
        from llama_index.core.query_engine import CustomQueryEngine
        from llama_index.core.base.response.schema import Response
        from llama_index.core.schema import NodeWithScore

        class SnippetQueryEngine(CustomQueryEngine):
            evidence_retriever: Any

            def custom_query(self, query_str: str):
                evidence = self.evidence_retriever.retrieve(query_str)
                return Response(response=json.dumps({"evidence": evidence}, ensure_ascii=False),
                                source_nodes=[NodeWithScore(
                                    node=self.evidence_retriever.index.docstore.get_node(item["node_id"]),
                                    score=item["score"]) for item in evidence],
                                metadata={"answer_mode": "retrieved_snippets_only"})

        return SnippetQueryEngine(evidence_retriever=self)

    def retrieve(self, question: str, report_years: list[int] | None = None) -> list[dict]:
        from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterCondition

        if not isinstance(question, str) or not question.strip():
            raise ValueError("A nonempty retrieval question is required.")
        filters = None
        if report_years is not None:
            years = sorted({int(year) for year in report_years})
            if not years:
                return []
            filters = MetadataFilters(filters=[MetadataFilter(key="report_year", value=year)
                                                for year in years], condition=FilterCondition.OR)
        catalog = self._catalog()
        allowed = {i for i, record in enumerate(catalog)
                   if report_years is None or record["source"].report_year in years}
        if not allowed:
            return []
        candidate_limit = max(self.top_k * 8, 20)
        hits = self.index.as_retriever(similarity_top_k=candidate_limit, filters=filters).retrieve(question)
        by_node = {}
        for i, record in enumerate(catalog):
            for node in record["nodes"]:
                by_node.setdefault(node.node_id, []).append(i)
        dense_rank, best_nodes, dense_scores = [], {}, {}
        for hit in hits:
            for i in by_node.get(hit.node.node_id, []):
                if i in allowed and i not in best_nodes:
                    dense_rank.append(i)
                    best_nodes[i] = hit.node
                    dense_scores[i] = float(hit.score) if hit.score is not None else None
        sparse_rank = self._bm25.rank(question, allowed, limit=candidate_limit)
        sparse_scores = dict(sparse_rank)
        fused = {}
        for ranking in (dense_rank, [i for i, _ in sparse_rank]):
            for rank, i in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + 1.0 / (60 + rank + 1)
        ranking = sorted(fused, key=lambda i: (-fused[i], i))
        if not ranking:
            return []
        # Reserve bounded same-file neighbors around the best page. Split tables
        # and numbered lists may put headers and rows on different physical pages.
        # Each neighbor remains an independent citation, explicitly labeled context.
        anchor = ranking[0]
        selected = [(anchor, "hybrid_ranked", None)]
        anchor_record = catalog[anchor]
        if isinstance(anchor_record["page"].pdf_page, int):
            for offset in (1, -1):
                if len(selected) >= self.top_k:
                    break
                neighbor = next((i for i in allowed if catalog[i]["source"].file_name == anchor_record["source"].file_name
                                 and catalog[i]["page"].pdf_page == anchor_record["page"].pdf_page + offset), None)
                if neighbor is not None:
                    selected.append((neighbor, "adjacent_page_context", anchor))
        used = {i for i, _, _ in selected}
        for i in ranking:
            if len(selected) >= self.top_k:
                break
            if i not in used:
                selected.append((i, "hybrid_ranked", None))
                used.add(i)
        query_terms = set(tokens(expanded_query(question)))
        result = []
        for i, origin, context_anchor in selected:
            record = catalog[i]
            page = record["page"]
            node = best_nodes.get(i)
            if node is None:
                node = max(record["nodes"], key=lambda node: len(query_terms & set(tokens(node.get_content()))))
            best_nodes[i] = node
            metadata = node.metadata
            item = {"node_id": node.node_id, "text": node.get_content(), "page_text": page.text,
                    **{key: metadata.get(key) for key in
                       ("company_id", "report_set_id", "file_name", "file_hash", "report_year",
                        "pdf_page", "printed_page", "parsing_warnings")},
                    "possible_value_years": sorted({int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", page.text)}),
                    "score": dense_scores.get(i) if origin == "hybrid_ranked" else None,
                    "lexical_score": sparse_scores.get(i) if origin == "hybrid_ranked" else None,
                    "fusion_score": fused.get(i) if origin == "hybrid_ranked" else None,
                    "retrieval_origin": origin,
                    "context_anchor_node_id": best_nodes[context_anchor].node_id if context_anchor is not None else None}
            item["evidence_id"] = _evidence_id(item)
            self.registry[item["evidence_id"]] = copy.deepcopy(item)
            if not self.validate_evidence(item["evidence_id"]):
                self.registry.pop(item["evidence_id"], None)
                raise RuntimeError("Retrieved evidence cannot be verified against its uploaded source.")
            result.append(copy.deepcopy(item))
        return result

    def evidence(self, question: str, report_years: list[int] | None = None) -> list[dict]:
        return self.retrieve(question, report_years=report_years)

    def _source_pages(self, source, actual_hash: str) -> dict:
        cache_key = (source.file_name, actual_hash)
        if cache_key not in self._page_cache:
            by_page = {}
            for page in extract_source(source):
                by_page.setdefault(page.pdf_page, []).append(page)
            self._page_cache[cache_key] = by_page
        return self._page_cache[cache_key]

    def _catalog(self) -> list[dict]:
        for source in self._sources.values():
            if sha256_file(source.pdf_path) != source.file_hash:
                raise RuntimeError("Retrieved evidence source is missing or changed.")
        if self._catalog_cache is not None:
            return self._catalog_cache
        records, lookup = [], {}
        for source in self._sources.values():
            for pages in self._source_pages(source, source.file_hash).values():
                for page in pages:
                    if page.text.strip():
                        key = (source.file_name, page.pdf_page, hashlib.sha256(page.text.encode("utf-8")).hexdigest())
                        lookup[key] = len(records)
                        records.append({"source": source, "page": page, "nodes": []})
        for node in self.index.docstore.docs.values():
            metadata = node.metadata
            if metadata.get("company_id") != self.report_set.company_id or metadata.get("report_set_id") != self.report_set.report_set_id:
                raise RuntimeError("Retrieved node belongs to another company or report set.")
            source = self._sources.get(metadata.get("file_name"))
            if source is None or metadata.get("file_hash") != source.file_hash or metadata.get("report_year") != source.report_year:
                raise RuntimeError("Indexed node does not match its current uploaded source.")
            pages = self._source_pages(source, source.file_hash).get(metadata.get("pdf_page"), [])
            matches = [page for page in pages if page.printed_page == metadata.get("printed_page")
                       and " ".join(node.get_content().split()) in " ".join(page.text.split())]
            if not matches:
                raise RuntimeError("Retrieved chunk cannot be located on its source page.")
            for page in matches:
                key = (source.file_name, page.pdf_page, hashlib.sha256(page.text.encode("utf-8")).hexdigest())
                records[lookup[key]]["nodes"].append(node)
        self._catalog_cache = [record for record in records if record["nodes"]]
        self._bm25 = PageBM25([record["page"].text for record in self._catalog_cache])
        return self._catalog_cache

    def validate_evidence(self, evidence_id: str) -> bool:
        """Reject invented IDs, changed source files and altered registry records."""
        evidence = self.registry.get(evidence_id)
        if not isinstance(evidence, dict):
            return False
        try:
            if _evidence_id(evidence) != evidence_id:
                return False
            source = self._sources[evidence["file_name"]]
            if evidence["company_id"] != self.report_set.company_id or evidence["report_set_id"] != self.report_set.report_set_id:
                return False
            actual_hash = sha256_file(source.pdf_path)
            if actual_hash != evidence["file_hash"] or source.report_year != evidence["report_year"]:
                return False
            node = self.index.docstore.get_node(evidence["node_id"])
            if node.get_content() != evidence["text"]:
                return False
            for key in ("company_id", "report_set_id", "file_name", "file_hash", "report_year",
                        "pdf_page", "printed_page", "parsing_warnings"):
                if node.metadata.get(key) != evidence.get(key):
                    return False
            origin = evidence.get("retrieval_origin")
            anchor_id = evidence.get("context_anchor_node_id")
            if origin == "adjacent_page_context":
                if not isinstance(anchor_id, str):
                    return False
                anchor = self.index.docstore.get_node(anchor_id)
                for key in ("company_id", "report_set_id", "file_name", "file_hash", "report_year"):
                    if anchor.metadata.get(key) != evidence.get(key):
                        return False
                anchor_page = anchor.metadata.get("pdf_page")
                page = evidence.get("pdf_page")
                if not isinstance(anchor_page, int) or not isinstance(page, int) or abs(anchor_page-page) != 1:
                    return False
                if any(evidence.get(key) is not None for key in ("score", "lexical_score", "fusion_score")):
                    return False
            elif origin != "hybrid_ranked" or anchor_id is not None:
                return False
            pages = self._source_pages(source, actual_hash).get(evidence["pdf_page"], [])
            normalize = lambda value: " ".join(value.split())
            return any(page.printed_page == evidence["printed_page"] and
                       evidence["page_text"] == page.text and
                       evidence["possible_value_years"] == sorted({int(year) for year in
                           re.findall(r"\b(?:19|20)\d{2}\b", page.text)}) and
                       normalize(evidence["text"]) in normalize(page.text) for page in pages)
        except (KeyError, OSError, ValueError, RuntimeError):
            return False
