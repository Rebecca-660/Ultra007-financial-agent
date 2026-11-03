"""Deterministic page-level BM25 and optional bilingual financial query terms.

The glossary expands search terms only. It contains no report locations, company
identifiers, financial values or answer templates, and never edits source text.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_STOPWORDS = set("a an the and or of in to for from by on at is was were are be been what how "
                 "which when please provide original evidence page pages unit units according "
                 "report annual company companies list all give identified year years".split())
_GLOSSARY = (
    (r"营业收入|营收", "operating revenue"),
    (r"净利润", "net profit"),
    (r"归属于.*股东", "attributable shareholders listed companies"),
    (r"经营活动.*现金流", "net cash flows operating activities"),
    (r"现金流", "cash flow"),
    (r"主要会计数据", "main accounting data"),
    (r"财务指标", "financial indicators"),
    (r"同比增长|同比增", "increase year on year"),
    (r"解释|原因", "explain reason increase"),
    (r"对比|比较", "comparative column"),
    (r"风险", "risk"),
    (r"未来发展", "future development"),
    (r"标题", "headings"),
    (r"折旧", "depreciation"),
    (r"摊销", "amortization"),
    (r"毛利", "gross profit"),
    (r"合并", "consolidated"),
    (r"母公司", "parent company"),
    (r"重述", "restated"),
    (r"资产", "assets"),
    (r"币种", "currency"),
)


def expanded_query(question: str) -> str:
    additions = [terms for pattern, terms in _GLOSSARY if re.search(pattern, question)]
    return question + (" " + " ".join(additions) if additions else "")


def tokens(text: str) -> list[str]:
    result = []
    for token in re.findall(r"[a-z]+|\d{4}|[\u4e00-\u9fff]+", text.lower()):
        if token in _STOPWORDS:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            result.extend(token[i:i+2] for i in range(len(token)-1))
            if len(token) == 1:
                result.append(token)
        else:
            if token.endswith("ies") and len(token) > 4:
                token = token[:-3] + "y"
            elif token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
                token = token[:-1]
            result.append(token)
    return result


class PageBM25:
    """Small local BM25 index over exact source-page text, without dependencies."""

    def __init__(self, texts: list[str]):
        self.frequency = [Counter(tokens(text)) for text in texts]
        self.lengths = [sum(freq.values()) for freq in self.frequency]
        self.average_length = sum(self.lengths) / max(len(self.lengths), 1) or 1.0
        self.document_frequency = Counter(term for freq in self.frequency for term in freq)

    def rank(self, question: str, allowed: set[int], limit: int = 20) -> list[tuple[int, float]]:
        query_terms = set(tokens(expanded_query(question)))
        count = len(self.frequency)
        scored = []
        for item in allowed:
            freq = self.frequency[item]
            length = self.lengths[item]
            score = 0.0
            for term in query_terms:
                occurrence = freq.get(term, 0)
                if not occurrence:
                    continue
                idf = math.log(1.0 + (count - self.document_frequency[term] + .5) /
                               (self.document_frequency[term] + .5))
                score += idf * occurrence * 2.2 / (occurrence + 1.2 * (.25 + .75 * length / self.average_length))
            if score > 0:
                scored.append((item, score))
        return sorted(scored, key=lambda item: (-item[1], item[0]))[:limit]
