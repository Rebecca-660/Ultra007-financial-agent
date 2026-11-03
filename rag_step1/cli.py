"""Stage 1 CLI: uploaded reports -> page index -> snippets -> two real agents."""
from __future__ import annotations
import argparse
import asyncio
import importlib.metadata
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from .config import REPORTS_DIR, REVIEW_DIR, DEEPSEEK_MODEL, EMBEDDING_MODEL, create_llm
from .report import load_report_set, inspect_reports, sha256_file

def _emit(payload: dict, output: Path | None = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    if output and "warning_pages" in payload:
        short = {k: v for k, v in payload.items() if k not in ("warning_pages", "storage_hashes")}
        short["warning_page_count"] = len(payload["warning_pages"])
        print(json.dumps(short, ensure_ascii=False, indent=2))
    else:
        print(text)

async def doctor(online: bool) -> dict:
    from .config import deepseek_api_key
    versions = {name: importlib.metadata.version(name) for name in
                ("llama-index-core", "llama-index-llms-deepseek", "llama-index-embeddings-huggingface", "PyMuPDF")}
    result = {"python": sys.version.split()[0], "executable": sys.executable,
              "packages": versions, "embedding_model": EMBEDDING_MODEL,
              "llm_model": DEEPSEEK_MODEL, "online_requested": online,
              "online_tool_call": "not_tested"}
    try:
        deepseek_api_key()
        result["api_key_configured"] = True
    except RuntimeError:
        result["api_key_configured"] = False
        return result
    llm = create_llm()
    result["function_calling_declared"] = llm.metadata.is_function_calling_model
    if online:
        from llama_index.core.tools import FunctionTool
        def aif_probe(value: str) -> str:
            """Return value to verify tool-call argument transport."""
            return value
        tool = FunctionTool.from_defaults(fn=aif_probe)
        try:
            response = await llm.achat_with_tools([tool], user_msg="Call aif_probe with value='tool-support-ok'.",
                                                 tool_choice="aif_probe", allow_parallel_tool_calls=False)
            calls = llm.get_tool_calls_from_response(response, error_on_no_tool_call=False)
            valid = any(c.tool_name == "aif_probe" and c.tool_kwargs == {"value": "tool-support-ok"} for c in calls)
            result["online_tool_call"] = "passed" if valid else "failed_no_valid_tool_call"
        except Exception as exc:
            result.update(online_tool_call="failed", error_type=type(exc).__name__)
    return result

def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Single-company annual-report RAG, Prompt 1")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("sources", "inspect", "index", "retrieve", "ask", "evaluate"):
        p = sub.add_parser(command)
        p.add_argument("--report-set", type=Path, default=REPORTS_DIR / "report_set.json")
        p.add_argument("--output", type=Path)
        if command in ("index", "retrieve", "ask", "evaluate"):
            p.add_argument("--index-dir", type=Path, default=None)
            p.add_argument("--offline-embedding", action="store_true", help="Diagnostic lexical model only; not multilingual validation")
        if command == "index":
            p.add_argument("--force", action="store_true")
        if command in ("retrieve", "ask"):
            p.add_argument("question")
            p.add_argument("--year", type=int, action="append")
            p.add_argument("--top-k", type=int, default=5)
        if command == "evaluate":
            p.add_argument("--questions", type=Path, required=True, help="JSON list with question/report_year/expected_pdf_pages")
            p.add_argument("--top-k", type=int, default=5)
    p = sub.add_parser("doctor")
    p.add_argument("--online", action="store_true", help="Perform one actual provider tool-call probe")
    p.add_argument("--output", type=Path)
    return parser

def main(argv=None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            result = asyncio.run(doctor(args.online))
            _emit(result, args.output)
            return 0 if not args.online or result["online_tool_call"] == "passed" else 2
        report_set = load_report_set(args.report_set)
        if args.command == "sources":
            result = report_set.manifest()
        elif args.command == "inspect":
            result = inspect_reports(list(report_set.sources))
            result.update(company_id=report_set.company_id, report_set_id=report_set.report_set_id)
        else:
            from .indexer import build_index, load_index
            if args.command == "index":
                result = build_index(report_set, args.index_dir, force=args.force, offline=args.offline_embedding)
            else:
                from .retrieval import EvidenceRetriever
                index = load_index(report_set, args.index_dir, offline=args.offline_embedding)
                retriever = EvidenceRetriever(report_set, index, top_k=args.top_k)
                if args.command == "retrieve":
                    hits = retriever.retrieve(args.question, report_years=args.year)
                    result = {"question": args.question, "report_set_id": report_set.report_set_id,
                              "status": "retrieved_snippets" if hits else "no_evidence", "evidence": hits,
                              "offline_embedding": args.offline_embedding}
                elif args.command == "ask":
                    from .qa import ask_question
                    result = asyncio.run(ask_question(retriever, args.question, report_years=args.year))
                else:
                    questions = json.loads(args.questions.read_text(encoding="utf-8-sig"))
                    rows = []
                    for q in questions:
                        wanted = q.get("report_year")
                        hits = retriever.retrieve(q["question"], report_years=[wanted] if wanted else None)
                        pages = {h["pdf_page"] for h in hits if (h["report_year"] == wanted or wanted is None)
                                 and (not q.get("expected_file_name") or h["file_name"] == q["expected_file_name"])}
                        expected = set(q["expected_pdf_pages"])
                        rows.append({**q, "retrieved_pages": sorted(p for p in pages if p is not None),
                                     "page_hit": expected.issubset(pages),
                                     "evidence_ids": [h["evidence_id"] for h in hits],
                                     "answer_truthfulness": "not_evaluated_retrieval_only"})
                    result = {"report_set_id": report_set.report_set_id, "offline_embedding": args.offline_embedding,
                              "questions_sha256": sha256_file(args.questions),
                              "retrieval_method": "dense_bm25_with_separately_cited_adjacent_context",
                              "created_at_utc": datetime.now(timezone.utc).isoformat(), "top_k": args.top_k,
                              "hits": sum(r["page_hit"] for r in rows), "trials": len(rows), "results": rows}
        _emit(result, args.output)
        return 2 if result.get("status") in ("invalid_agent_output", "agent_error") else 0
    except Exception as exc:
        # Avoid logging provider exceptions containing request headers or secrets.
        if isinstance(exc, (FileNotFoundError, ValueError, RuntimeError, PermissionError)):
            message = str(exc) if exc.__class__.__module__.startswith(("builtins", "rag_step1")) else type(exc).__name__
        else:
            message = type(exc).__name__
        print(f"错误：{message}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
