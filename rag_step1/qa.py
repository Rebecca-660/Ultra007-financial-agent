"""Compatibility import and asynchronous, evidence-grounded Agent entry point."""
import re

def beyond_corpus_actuals(question: str, covered_years: list[int]) -> bool:
    years = [int(y) for y in re.findall(r"(?<!\d)(20\d{2})(?!\d)", question)]
    return bool(years and covered_years and max(years) > max(covered_years) and
                re.search(r"audited|actual|realized|reported|经审计|实际|已实现|完成的", question, re.I))

async def ask_question(retriever, question: str, *, report_years=None, llm=None) -> dict:
    from .agents import build_agents
    return await build_agents(retriever, llm).run(question, report_years=report_years)
