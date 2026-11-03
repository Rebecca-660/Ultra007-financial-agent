"""User-uploaded single-company report sets, physical pages and parse warnings."""
from __future__ import annotations
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
import pymupdf as fitz
from .config import REPORTS_DIR, REVIEW_DIR

PARSER_VERSION = "pdf-physical-pages-verified-footer-v2"

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

@dataclass(frozen=True)
class PageRecord:
    pdf_page: int | None
    text: str
    printed_page: str | None = None
    parsing_warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class ReportSource:
    pdf_path: Path  # Legacy attribute name; accepts PDF or TXT.
    report_year: int
    page_count: int
    verified_printed_pages: tuple[tuple[int, str], ...] = ()

    @property
    def file_name(self) -> str:
        return self.pdf_path.name

    @cached_property
    def file_hash(self) -> str:
        return sha256_file(self.pdf_path)

@dataclass(frozen=True)
class ReportSet:
    company_id: str
    report_set_id: str
    sources: tuple[ReportSource, ...]

    def manifest(self) -> dict:
        return {"company_id": self.company_id, "report_set_id": self.report_set_id,
                "sources": [{"file_name": s.file_name, "file_hash": s.file_hash,
                             "report_year": s.report_year, "kind": s.pdf_path.suffix.lower(),
                             "verified_printed_pages": dict(s.verified_printed_pages)}
                            for s in self.sources]}

def detect_report_year(path: Path) -> int:
    """Discovery hint only; the user confirms years in report_set.json."""
    match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", Path(path).name)
    if match:
        return int(match.group(1))
    if Path(path).suffix.lower() == ".pdf":
        with fitz.open(path) as pdf:
            text = pdf[0].get_text() if len(pdf) else ""
    else:
        text = Path(path).read_text(encoding="utf-8-sig")[:4000]
    match = re.search(r"((?:19|20)\d{2})\s+Annual Report", text, re.I)
    if not match:
        raise ValueError(f"无法识别 {Path(path).name} 的报告年度，请在上传清单中指定。")
    return int(match.group(1))

def _source(path: Path, year: int, verified_printed_pages: dict | None = None) -> ReportSource:
    if not path.is_file():
        raise FileNotFoundError(f"报告不存在：{path}")
    if isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2200:
        raise ValueError("report_year 必须是合理的整数年度。")
    if path.suffix.lower() == ".pdf":
        with fitz.open(path) as pdf:
            count = len(pdf)
            if pdf.is_encrypted or not count:
                raise ValueError(f"空白或加密 PDF 不支持：{path.name}")
    elif path.suffix.lower() == ".txt":
        count = 0
    else:
        raise ValueError("第一阶段只接受文本型 PDF 或 UTF-8 TXT。")
    mappings = tuple(sorted((int(k), str(v)) for k, v in (verified_printed_pages or {}).items()))
    if any(page < 1 or page > count or not re.fullmatch(r"\d{1,4}", printed) for page, printed in mappings):
        raise ValueError("已核对印刷页码映射必须对应真实 PDF 页和明确数字页脚。")
    return ReportSource(path.resolve(), year, count, mappings)

def discover_reports(reports_dir: Path = REPORTS_DIR) -> list[ReportSource]:
    paths = sorted(p for p in Path(reports_dir).iterdir() if p.suffix.lower() in (".pdf", ".txt"))
    if not paths:
        raise FileNotFoundError(f"没有用户报告：{reports_dir}")
    return [_source(p, detect_report_year(p)) for p in paths]

def make_report_set(company_id: str, sources: list[ReportSource]) -> ReportSet:
    if not isinstance(company_id, str) or not company_id.strip() or not sources:
        raise ValueError("必须确认一个 company_id 以及至少一份报告。")
    names = [s.file_name for s in sources]
    if len(names) != len(set(names)):
        raise ValueError("报告文件名必须唯一，避免出处混淆。")
    if len({s.file_hash for s in sources}) != len(sources):
        raise ValueError("同一源文件不能重复上传或赋予不同报告年度。")
    sources = sorted(sources, key=lambda s: (s.report_year, s.file_name))
    payload = {"company_id": company_id.strip(),
               "sources": [(s.file_name, s.file_hash, s.report_year) for s in sources]}
    identity = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
    return ReportSet(company_id.strip(), identity, tuple(sources))

def load_report_set(manifest_path: Path = REPORTS_DIR / "report_set.json") -> ReportSet:
    manifest_path = Path(manifest_path).resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    company = data.get("company_id")
    if data.get("single_company_confirmed") is not True:
        raise ValueError("请先核对所有上传文件属于同一家公司，并设 single_company_confirmed=true。")
    sources = []
    for entry in data.get("reports", []):
        if entry.get("company_id", company) != company:
            raise ValueError("一次报告集合不能混入另一家公司。")
        if entry.get("verified_printed_pages") and not entry.get("file_hash"):
            raise ValueError("人工核对的印刷页码映射必须绑定 file_hash。")
        source = _source(manifest_path.parent / entry["file_name"], entry["report_year"], entry.get("verified_printed_pages"))
        if entry.get("file_hash") and entry["file_hash"] != source.file_hash:
            raise ValueError(f"文件与已确认哈希不符：{source.file_name}；请重新核对上传清单。")
        sources.append(source)
    return make_report_set(company, sources)

def _warnings(text: str) -> list[str]:
    warnings = []
    if not text:
        warnings.append("no_text_scanned_or_blank_page")
    elif len(text) < 30:
        warnings.append("short_text")
    if "\ufffd" in text:
        warnings.append("replacement_character")
    return warnings

def extract_pages(path: Path, verified_printed_pages: dict[int, str] | None = None) -> tuple[list[PageRecord], int]:
    """Never infer printed pages by subtracting an offset."""
    pages = []
    with fitz.open(path) as pdf:
        if pdf.is_encrypted or not len(pdf):
            raise ValueError("空白或加密 PDF 不支持。")
        for i, page in enumerate(pdf):
            text = page.get_text("text", sort=True).strip()
            footer_numbers, explicit_footer_numbers = set(), set()
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    line_text = "".join(s["text"] for s in line["spans"]).strip()
                    footer = re.fullmatch(r"(?:Page\s+)?(\d{1,4})(?:\s+of\s+\d{1,4})?", line_text, re.I)
                    if line["bbox"][1] >= page.rect.height * .90 and footer:
                        footer_numbers.add(footer.group(1))
                        if re.match(r"Page\s", line_text, re.I):
                            explicit_footer_numbers.add(footer.group(1))
            printed = next(iter(explicit_footer_numbers)) if len(explicit_footer_numbers) == 1 else None
            mapped = (verified_printed_pages or {}).get(i + 1)
            if mapped is not None:
                if mapped not in footer_numbers:
                    raise ValueError(f"已核对页码 {mapped} 未出现在 PDF 第 {i + 1} 页的原文页脚中。")
                printed = mapped
            warnings = _warnings(text)
            if printed is None:
                warnings.append("printed_page_not_verified")
                if footer_numbers:
                    warnings.append("numeric_footer_requires_visual_verification")
            if re.search(r"\d[\d,]*\.\d{2}", text):
                warnings.append("numeric_table_columns_require_review")
            pages.append(PageRecord(i + 1, text, printed, tuple(warnings)))
    return pages, len(pages)

def extract_source(source: ReportSource) -> list[PageRecord]:
    if source.pdf_path.suffix.lower() == ".pdf":
        return extract_pages(source.pdf_path, dict(source.verified_printed_pages))[0]
    text = source.pdf_path.read_text(encoding="utf-8-sig")
    return [PageRecord(None, part.strip(), None,
                       tuple(_warnings(part.strip()) + ["txt_page_unverifiable"]))
            for part in text.split("\f")]

def inspect_reports(sources: list[ReportSource], review_dir: Path = REVIEW_DIR) -> dict:
    review_dir = Path(review_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    entries, warnings = [], []
    for source in sources:
        pages = extract_source(source)
        for page in pages:
            warnings.extend({"file_name": source.file_name, "report_year": source.report_year,
                             "pdf_page": page.pdf_page, "warning": warning}
                            for warning in page.parsing_warnings)
        entries.append({"file_name": source.file_name, "report_year": source.report_year,
                        "file_hash": source.file_hash, "pdf_page_count": source.page_count,
                        "text_page_count": sum(bool(p.text) for p in pages),
                        "empty_pages": [p.pdf_page for p in pages if not p.text],
                        "status": "parsed_needs_source_review" if any(p.text for p in pages) else "unsupported_no_text"})
    with (review_dir / "parse_warnings.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["file_name", "report_year", "pdf_page", "warning"])
        writer.writeheader()
        writer.writerows(warnings)
    result = {"reports": entries, "warnings_count": len(warnings),
              "checked_at_utc": datetime.now(timezone.utc).isoformat()}
    (review_dir / "inspection.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
