"""Extract the complete visible main statements from PDF word coordinates.

Numbers are copied from source cells. The LLM never supplies a number, year,
currency, approval, or source identity to this parser. Unsupported layouts fail
explicitly rather than falling back to an LLM reconstruction.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import statistics
import pymupdf

from rag_step1.report import ReportSet, sha256_file
from .models import Column, Dataset, Locator, Statement, StatementRow, digest

CAPTIONS = {
    "BS": r"consolidated\s+(?:balance\s+sheets?|statements?\s+of\s+financial\s+position)|合并资产负债表",
    "IS": r"consolidated\s+(?:income\s+statements?|statements?\s+of\s+(?:operations|earnings|profit|(?:comprehensive\s+)?income))|合并利润表",
    "CF": r"consolidated\s+(?:cash\s+flows?\s+statements?|statements?\s+of\s+cash\s+flows?)|合并现金流量表",
}
NUMBER = re.compile(r"^\(?[+−–-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?$")


def parse_number(raw: str) -> Decimal | None:
    clean = raw.strip().replace(" ", "").replace("−", "-").replace("–", "-")
    if clean in ("", "-", "—", "–"):
        return None
    if not NUMBER.fullmatch(clean):
        raise ValueError(f"Unrecognized source cell: {raw!r}")
    if clean.startswith('(')!=clean.endswith(')'):
        raise ValueError('Unbalanced source number parentheses')
    if clean.startswith("("):
        if clean[1] in '+-':
            raise ValueError('Ambiguous source number sign')
        clean = "-" + clean[1:-1]
    value = Decimal(clean.replace(",", ""))
    if not value.is_finite():
        raise ValueError("Non-finite source cell")
    return value


def key(label: str) -> str:
    text = re.sub(r"\([^)]*\)|（[^）]*）", "", label.lower())
    text = re.sub(r'^[一二三四五六七八九十百]+[、.．]\s*', '', text)
    text = re.sub(r"^[a-z\s]{0,5}[ivx]+[.]\s*|^[ivx]+[、]\s*|^\d+[.、]\s*", "", text)
    text = re.sub(r"^(including|less|add)\s*:\s*", "", text)
    text = re.sub(r'^(?:其中|加|减)\s*[:：]\s*', '', text)
    return re.sub(r"[^a-z\u4e00-\u9fff]", "", text)


ALIASES = {
    "revenue": ["operating revenue", "revenue", "revenues", "net revenue", "net revenues", "net sales", "sales revenue", "营业收入"],
    "total_revenue": ["total operating revenue", "营业总收入"],
    "cost_of_sales": ["operating costs", "cost of sales", "cost of goods sold", "cost of revenue", "cost of revenues", "营业成本"],
    "operating_profit": ["operating profits", "operating profit", "income from operations", "营业利润"],
    "net_income": ["net profits", "net profit", "net income", "profit for the year", "profit for the period", "profit after tax", "净利润"],
    "parent_net_income": ["net profits attributable to shareholders of the parent company", "net profits attributable to shareholders of the parent", "net profit attributable to shareholders of the parent company", "归属于母公司股东的净利润", "归属于母公司所有者的净利润"],
    "assets": ["total assets", "资产总计"],
    "liabilities": ["total liabilities", "负债合计"],
    "equity": ["total equity", "total shareholders' equity", "total stockholders' equity", "total owners' equity", "所有者权益合计", "股东权益合计"],
    "parent_equity": ["total equity attributable to shareholders of the parent company", "equity attributable to owners of the parent", "归属于母公司所有者权益合计"],
    "current_assets": ["total current assets", "流动资产合计"],
    "current_liabilities": ["total current liabilities", "流动负债合计"],
    "inventory": ["inventory", "inventories", "存货"],
    "receivables": ["accounts receivable", "accounts receivable net", "trade receivables", "应收账款"],
    "cfo": ["net cash flows from operating activities", "net cash flow from operating activities", "net cash provided by operating activities", "经营活动产生的现金流量净额"],
    "cfi": ["net cash flows from investment activities", "net cash flows from investing activities", "net cash flow from investing activities", "投资活动产生的现金流量净额"],
    "cff": ["net cash flows from financing activities", "net cash flow from financing activities", "筹资活动产生的现金流量净额"],
    "capex": ["cash paid for purchase and construction of fixed assets intangible assets and other long-term assets", "cash paid for the purchase and construction of fixed assets intangible assets and other long-term assets", "购建固定资产无形资产和其他长期资产支付的现金"],
    "cash_change": ["net increase in cash and cash equivalents", "现金及现金等价物净增加额"],
    "cash_opening": ["beginning balance of cash and cash equivalents", "期初现金及现金等价物余额"],
    "cash_closing": ["ending balance of cash and cash equivalents", "期末现金及现金等价物余额"],
    "fx_cash": ["impact of foreign exchange rate changes on cash and cash equivalents", "effect of exchange rate changes on cash and cash equivalents", "汇率变动对现金及现金等价物的影响"],
}
LOOKUP = {key(alias): metric for metric, aliases in ALIASES.items() for alias in aliases}


def identify(label: str) -> str | None:
    return LOOKUP.get(key(label))


def locate(report_set: ReportSet, profile: dict | None = None) -> list[Locator]:
    from .parsing import validated_profile
    from .statement_locator import find_statement_pages,statement_catalog
    parsed = validated_profile(profile, report_set)
    result = []
    for source in report_set.sources:
        if source.pdf_path.suffix.lower() != ".pdf":
            raise ValueError("完整三表需要有真实页码和坐标的文本 PDF；TXT 不支持本轮表格输出。")
        if sha256_file(source.pdf_path) != source.file_hash:
            raise ValueError("Source changed after report-set confirmation")
        with pymupdf.open(source.pdf_path) as document:
            catalog=statement_catalog(document)
            for kind in CAPTIONS:
                selected = [s for s in parsed.statements if s.file_name == source.file_name and s.kind == kind]
                if selected:
                    pages = selected[0].pdf_pages
                else:
                    pages=find_statement_pages(document,source.report_year,kind,source.file_name,catalog=catalog)
                result.append(Locator(report_year=source.report_year, kind=kind,
                    file_name=source.file_name, file_hash=source.file_hash, pdf_pages=pages))
    return result


def _cluster(values, tolerance=1.6):
    groups = []
    for value in sorted(values):
        if groups and abs(statistics.mean(groups[-1]) - value) <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [statistics.mean(group) for group in groups]


def _column_metadata(headers: list[str], year: int, kind: str) -> list[Column]:
    columns = []
    for i, header in enumerate(headers):
        years = re.findall(r"(?:19|20)\d{2}", header)
        if len(set(years)) != 1:
            raise ValueError(f"Unverifiable column year: {header!r}")
        source_year = int(years[0])
        opening = bool(re.search(r"January\s+1\b|[/.-]0?1[/.-]0?1\b|年\s*1\s*月\s*1\s*日", header, re.I))
        role = "opening" if opening else "current" if source_year == year else "prior"
        if source_year > year or (source_year == year and role not in ('current','opening')):
            raise ValueError("Column does not match a verified annual/opening period")
        as_of = None
        numeric_date=re.search(r'((?:19|20)\d{2})[/.-](\d{1,2})[/.-](\d{1,2})',header)
        chinese_date=re.search(r'((?:19|20)\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日',header)
        english_date=re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})',header,re.I)
        if numeric_date or chinese_date:
            from datetime import date
            as_of=date(*(int(x) for x in (numeric_date or chinese_date).groups())).isoformat()
        elif english_date:
            from datetime import date
            months=['january','february','march','april','may','june','july','august','september','october','november','december']
            as_of=date(source_year,months.index(english_date.group(1).lower())+1,int(english_date.group(2))).isoformat()
        elif opening:
            as_of=f'{source_year}-01-01'
        # A year-only income/cash-flow heading does not prove a December 31 end.
        columns.append(Column(column_id=f"col{i}", raw_header=header,
            value_year=source_year, role=role, as_of=as_of))
    if len([c for c in columns if c.role == 'current']) != 1:
        raise ValueError('必须存在且仅存在一个已核实的本年主列。')
    return columns


def _legacy_page(page, year: int, kind: str, file_hash: str):
    words = page.get_text("words")
    items = [w for w in words if w[4].lower() in ("item", "项目")]
    if len(items) != 1:
        raise ValueError("Cannot identify a unique Item header")
    header = items[0]
    notes = [w for w in words if w[4].lower() in ("note", "附注") and abs(w[1] - header[1]) < 4]
    if len(notes) != 1:
        raise ValueError("This layout needs a unique Note column")
    note = notes[0]
    drawing = page.get_drawings()
    xs = _cluster([(d["rect"].x0 + d["rect"].x1) / 2 for d in drawing
        if d["rect"].width < 2 and d["rect"].height > 4])
    left_note = max(x for x in xs if x < note[0])
    left_value = min(x for x in xs if x > note[2])
    other = [x for x in xs if x > left_value + 10 and x < page.rect.width - 15]
    if len(other) < 1:
        raise ValueError("Cannot verify both numeric column boundaries")
    divider, right = other[0], page.rect.width - 10
    # Page frame is wider than a table in some reports. Use the actual value
    # header and word content; the frame is only an inclusive right boundary.
    header_words = [w for w in words if abs(w[1] - header[1]) < 3 and w[0] > left_value]
    raw_headers = [" ".join(w[4] for w in sorted(header_words, key=lambda w: w[0])
                            if lo < (w[0]+w[2])/2 < hi)
                   for lo, hi in [(left_value, divider), (divider, right + 1)]]
    columns = _column_metadata(raw_headers, year, kind)
    from .parsing import signature_positions
    signatures = signature_positions(page,header[3])
    bottom = min(signatures) if signatures else page.rect.height * .94
    body = [w for w in words if w[1] > header[3] - 1 and w[3] < bottom + .2]
    unit_lines = [line.strip() for line in page.get_text().splitlines() if re.search(r"Unit\s*:|单位", line, re.I)]
    unit = " ".join(unit_lines)
    currency = "CNY" if re.search(r"CNY|RMB|yuan|人民币", unit, re.I) else ("USD" if "USD" in unit or "$" in unit else None)
    scale = (Decimal("1000000") if re.search(r"million|百万", unit, re.I) else
             Decimal("10000") if "万元" in unit else
             Decimal("1000") if re.search(r"thousand|千元", unit, re.I) else
             Decimal("1") if currency else None)
    # Real per-row border segments give exact row bands, including wrapped text.
    ys = _cluster([v for d in drawing if d["rect"].width < 2 and
        abs(d["rect"].x0-left_value) < 2 and d["rect"].height < 100
        for v in (d["rect"].y0, d["rect"].y1) if header[3] - 3 < v < bottom + 2], .9)
    groups = defaultdict(list)
    if len(ys) > 18:
        import bisect
        for word in body:
            groups[bisect.bisect_right(ys, (word[1]+word[3])/2)].append(word)
    else:
        # Borderless row interiors: align numeric baselines with visible label
        # lines; a two-line caption can straddle its vertically centred amount.
        numeric = [w for w in body if w[0] >= left_value - 1 and NUMBER.fullmatch(w[4])]
        anchors = _cluster([(w[1]+w[3])/2 for w in numeric], 1.5)
        label_lines = defaultdict(list)
        for word in body:
            if word[0] < left_note - 1:
                label_lines[(word[5], word[6])].append(word)
        pitches = sorted({round((w[1]+w[3])/2, 1) for w in body if w[0] < left_note - 1})
        gaps = [b-a for a,b in zip(pitches,pitches[1:]) if 4 < b-a < 30]
        limit = min(10, (statistics.median(gaps) if gaps else 12)*.72)
        line_anchor = {}
        for line_id, line in label_lines.items():
            mid = statistics.mean((w[1]+w[3])/2 for w in line)
            near = min(anchors, key=lambda a: abs(a-mid)) if anchors else mid
            anchor = near if abs(near-mid) <= limit else mid
            line_anchor[line_id] = anchor
            groups[anchor].extend(line)
        for word in body:
            if word[0] < left_note - 1:
                continue
            mid = (word[1]+word[3])/2
            if not groups:
                raise ValueError("No statement labels")
            anchor = min(groups, key=lambda a: abs(a-mid))
            if abs(anchor-mid) > limit:
                raise ValueError("Numeric/note cell has no matching source row")
            groups[anchor].append(word)
    rows = []
    for _, group in sorted(groups.items()):
        def joined(lo, hi):
            selected = [w for w in group if lo <= (w[0]+w[2])/2 < hi]
            return " ".join(w[4] for w in sorted(selected, key=lambda w:(round(w[1], 0), w[0])))
        label = joined(0, left_note)
        if not label:
            raise ValueError("Source numeric row without a visible label")
        raw = [joined(left_value, divider), joined(divider, right+1)]
        values = [parse_number(x) for x in raw]
        bbox = [min(w[0] for w in group), min(w[1] for w in group),
                max(w[2] for w in group), max(w[3] for w in group)]
        row_id = digest([file_hash, page.number+1, kind, label, raw, bbox])[:24]
        rows.append(StatementRow(row_id=row_id, raw_label=label,
            note=joined(left_note,left_value), values=values, raw_values=raw,
            pdf_page=page.number+1, bbox=bbox, canonical_metric=identify(label)))
    return columns, rows, unit, currency, scale


def _page(page, year: int, kind: str, file_hash: str, profile=None, file_name=''):
    from .parsing import parse_page
    return parse_page(page,year,kind,file_hash,profile,file_name)


def extract(report_set: ReportSet, locators: list[Locator] | None = None, profile: dict | None = None) -> Dataset:
    from .parsing import validated_profile,parse_statement
    parsed = validated_profile(profile,report_set)
    profile = parsed.model_dump(mode='json') if profile else {}
    locators = locators if locators is not None else locate(report_set,profile)
    statements = []
    for locator in locators:
        sources = [s for s in report_set.sources if s.file_name == locator.file_name and s.file_hash == locator.file_hash]
        if len(sources) != 1 or sources[0].report_year != locator.report_year:
            raise ValueError("Locator is outside confirmed source scope")
        source = sources[0]
        if sha256_file(source.pdf_path) != locator.file_hash:
            raise ValueError("Source changed during extraction")
        with pymupdf.open(source.pdf_path) as document:
            columns,all_rows,unit,currency,scale=parse_statement(document,locator,source,profile)
        statement = Statement(statement_id=digest([report_set.report_set_id, locator.model_dump()])[:24],
            company_id=report_set.company_id, report_set_id=report_set.report_set_id,
            report_year=source.report_year, kind=locator.kind, file_name=source.file_name,
            file_hash=source.file_hash, pdf_pages=locator.pdf_pages,
            currency=currency, raw_unit=unit, scale=scale, columns=columns, rows=all_rows,
            warnings=["全部数值待人工核对；自动提取与勾稽检查不构成批准。"])
        statements.append(statement)
    if len({(s.report_year,s.kind) for s in statements}) != len(statements):
        raise ValueError("同年度同类报表有多份来源，需人工选择，不能静默覆盖。")
    dataset = Dataset(company_id=report_set.company_id, report_set_id=report_set.report_set_id,extraction_profile=profile,
        statements=statements, limitations=["只验证当前上传的文本 PDF；其他布局和扫描件未验证。",
        "源表空白保留为未披露，不能视为零。", "各年本年主列用于分析；比较栏差异必须人工明确接受。"])
    add_checks(dataset)
    return dataset


def add_checks(dataset: Dataset):
    current = {}
    for statement in dataset.statements:
        values = defaultdict(list)
        for row in statement.rows:
            if row.canonical_metric:
                values[row.canonical_metric].append(row)
        for metric, rows in values.items():
            if len(rows) > 1:
                statement.warnings.append(f"标准指标映射不唯一：{metric}")
            else:
                current[(statement.report_year,statement.kind,metric)] = (statement, rows[0])
        equations = ([('balance', 'assets', ['liabilities','equity'])] if statement.kind == 'BS' else
                     [('cash_bridge','cash_closing',['cash_opening','cash_change'])] if statement.kind == 'CF' else [])
        for name, total, parts in equations:
            for col in range(len(statement.columns)):
                if all(len(values.get(k,[])) == 1 and values[k][0].values[col] is not None for k in [total,*parts]):
                    difference = values[total][0].values[col] - sum(values[p][0].values[col] for p in parts)
                    statement.checks.append({"name":name,"column":col,"difference":str(difference),
                        "status":"pass" if abs(difference)<=Decimal('.05') else "fail"})
                else:
                    statement.checks.append({"name":name,"column":col,"status":"unavailable"})
    for statement in dataset.statements:
        for row in statement.rows:
            if not row.canonical_metric:
                continue
            for index,col in enumerate(statement.columns):
                if col.role == 'current':
                    continue
                year = col.value_year - 1 if col.role == 'opening' else col.value_year
                prior = current.get((year,statement.kind,row.canonical_metric))
                prior_col = next((i for i,c in enumerate(prior[0].columns) if c.role=='current'),None) if prior else None
                if prior and prior_col is not None and statement.currency == prior[0].currency and statement.scale and prior[0].scale and row.values[index] is not None and prior[1].values[prior_col] is not None:
                    a,b = row.values[index]*statement.scale, prior[1].values[prior_col]*prior[0].scale
                    if a != b:
                        dataset.conflicts.append({"metric":row.canonical_metric,"value_year":year,
                            "current_statement_id":prior[0].statement_id,"comparison_statement_id":statement.statement_id,
                            "current":str(b),"comparative":str(a),
                            "note":"比较栏/期初与上年原报主列不同；保留原始来源，人工选择 as_reported 后才按各年原报分析。"})
