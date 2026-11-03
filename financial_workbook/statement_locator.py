"""Period-aware statement discovery with explicit table boundaries.

Only original PDF text and coordinates participate in selection.  A caption
mention in audit prose, a parent-only statement, and an opening adjustment
table cannot become a current-year consolidated main statement.  Multiple
independent, eligible statements remain an error rather than a guessed choice.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import statistics
import pymupdf


@dataclass(frozen=True)
class CaptionHit:
    kind: str
    scope: str
    y0: float
    y1: float
    text: str


_TITLES = {
    'BS': r'(?:balance\s+sheets?|statements?\s+of\s+financial\s+position)',
    'IS': r'(?:income\s+statements?|statements?\s+of\s+(?:operations|earnings|profit(?:\s+or\s+loss)?|(?:comprehensive\s+)?income))',
    'CF': r'(?:cash\s+flows?\s+statements?|statements?\s+of\s+cash\s+flows?)',
}
_CHINESE = {'BS':'资产负债表','IS':'利润表','CF':'现金流量表'}
_NUMBER = re.compile(r'^\(?[+−–-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?$')
_END = {
    'BS':r'负债(?:和|及)所有者权益(?:总计|合计)|负债(?:和|及)股东权益(?:总计|合计)|total\s+liabilities\s+and\s+(?:(?:stock|share)holders.?\s+)?(?:owners.?\s+)?equity',
    'IS':r'稀释每股收益|diluted\s+(?:earnings|income|profit|net\s+income).*per\s+share|diluted\s+(?:earnings|income|profit)\s+per\s+(?:common\s+)?share',
    'CF':r'期末现金及现金等价物余额|cash\s+and\s+cash\s+equivalents\s+(?:at\s+)?(?:the\s+)?end\s+of\s+(?:the\s+)?(?:year|period)|ending\s+balance\s+of\s+cash\s+and\s+cash\s+equivalents',
}


def _lines(page):
    result=[]
    # Caption scanning needs text geometry only; retaining image binaries in
    # hundreds of page dictionaries is needlessly expensive.
    flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    for block in page.get_text('dict',flags=flags)['blocks']:
        for line in block.get('lines',[]):
            text=''.join(span['text'] for span in line.get('spans',[])).strip()
            if text:
                result.append((float(line['bbox'][1]),float(line['bbox'][3]),text))
    return sorted(result,key=lambda x:(x[0],x[1]))


def _title_kind(text):
    clean=re.sub(r'^\s*(?:\d+[、.．)]|[一二三四五六七八九十]+[、.．])\s*','',text).strip()
    compact=re.sub(r'\s+','',clean)
    for kind,name in _CHINESE.items():
        if re.fullmatch(r'(合并|母公司)'+name+r'(?:[（(](?:续|续表)[）)])?',compact):
            return kind,'consolidated' if compact.startswith('合并') else 'parent'
    clean=re.sub(r'\s*\(?continued\)?\s*$','',clean,flags=re.I).strip()
    for kind,pattern in _TITLES.items():
        if re.fullmatch(r'consolidated\s+'+pattern,clean,re.I):
            return kind,'consolidated'
        if re.fullmatch(r'(?:parent\s+company|company(?:-only)?|separate|individual)\s+'+pattern,clean,re.I):
            return kind,'parent'
    return None


def caption_hits(page) -> list[CaptionHit]:
    """Recognize complete standalone title lines, anywhere on a page."""
    lines=_lines(page); result=[]; used=set()
    for index,(y0,y1,text) in enumerate(lines):
        if index in used: continue
        match=_title_kind(text)
        # English reports sometimes wrap "Consolidated Statements of" and
        # "Cash Flows" onto separate adjacent lines.
        if match is None and index+1<len(lines):
            next_y0,next_y1,next_text=lines[index+1]
            if next_y0-y1<12:
                match=_title_kind(text+' '+next_text)
                if match:
                    text+=' '+next_text; y1=next_y1; used.add(index+1)
        if match:
            result.append(CaptionHit(match[0],match[1],y0,y1,text))
    return result


def _body_top(page) -> float:
    """Exclude a recognizable running header/page number, not statement rows."""
    top=0.0
    for y0,y1,text in _lines(page):
        if y0>page.rect.height*.10: break
        if re.search(r'年度报告|annual\s+report',text,re.I) or re.fullmatch(r'(?:Page\s+)?\d+',text,re.I):
            top=max(top,y1+0.5)
    return top


def statement_body_bounds(page, kind: str, *, continued: bool=False) -> tuple[float,float]:
    """Return y limits for one selected statement on this physical page.

    A continuation without its own title inherits the table at the top of the
    page and stops at the first next title.  A repeated title at the very top
    is the continued header.  Starting pages may begin after audit prose or a
    previous statement, so their own caption is found over the whole page.
    """
    hits=caption_hits(page)
    own=[hit for hit in hits if hit.kind==kind and hit.scope=='consolidated']
    start=None
    if not continued:
        if own: start=own[0]
    elif own and own[0].y0<=max(100.0,page.rect.height*.12):
        start=own[0]
    top=start.y1 if start else _body_top(page)
    following=[hit.y0 for hit in hits if hit.y0>top+0.01]
    bottom=min(following) if following else float(page.rect.height)
    return top,bottom


def _text_region(page, top, bottom):
    return '\n'.join(text for y0,y1,text in _lines(page) if y0>=top-.2 and y1<=bottom+.2)


def _header_text(page, hit):
    later=[x.y0 for x in caption_hits(page) if x.y0>hit.y1]
    bottom=min(later+[hit.y1+180,float(page.rect.height)])
    rows=[]
    for y0,y1,text in _lines(page):
        if y0<hit.y1-.2 or y1>bottom: continue
        # Stop before body rows so years mentioned in an explanatory label do
        # not prove the period. Keep headings such as "Current assets" out.
        if re.search(r'^(?:流动资产|非流动资产|一[、．.]?\s*营业|一[、．.]?\s*经营活动)|^(?:total\s+assets|current\s+assets|(?:operating\s+)?revenue|net\s+sales|cash\s+flows?\s+from)',text,re.I):
            break
        rows.append(text)
    return '\n'.join(rows)


def _eligible_period(page, hit, year, following=None):
    header=_header_text(page,hit)
    # A real title and unit disclosure can finish a page while the actual
    # column header starts on the next one. Extend only this immediate,
    # otherwise uncaptioned successor, not arbitrary later pages.
    if following is not None and hit.y0>page.rect.height*.70 and not caption_hits(following):
        proxy=CaptionHit(hit.kind,hit.scope,_body_top(following),_body_top(following),'')
        header+='\n'+_header_text(following,proxy)
    years=re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)',header)
    if str(year) not in years or len(years)<2:
        return False
    if re.search(r'半年度|季度|(?:three|six|nine)\s+months',header,re.I):
        return False
    if hit.kind=='BS':
        dates=[]
        for match in re.finditer(r'(?<!\d)'+str(year)+r'\s*(?:年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日|[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2}))(?!\d)',header):
            groups=match.groups(); dates.append((int(groups[0] or groups[2]),int(groups[1] or groups[3])))
        english_opening=re.search(r'January\s+1\s*,?\s*'+str(year),header,re.I)
        if dates and all(value==(1,1) for value in dates): return False
        if english_opening and not re.search(r'(?:December\s+31|June\s+30|September\s+30|March\s+31)\s*,?\s*'+str(year),header,re.I): return False
        if re.search(r'调整数|首次执行|opening\s+adjustment|transition\s+adjustment',header,re.I) and not any(date!=(1,1) for date in dates):
            return False
    return True


def _amounts(page, top, bottom):
    return [(float(word[2]),float(word[1]),word[4]) for word in page.get_text('words')
            if word[1]>=top-.2 and word[3]<=bottom+.2 and word[0]>=page.rect.width*.30
            and _NUMBER.fullmatch(word[4])]


def _signature(amounts):
    monetary=[amount for amount in amounts if '.' in amount[2] or ',' in amount[2]]
    if monetary: amounts=monetary
    else: amounts=[amount for amount in amounts if not re.fullmatch(r'(?:19|20)\d{2}',amount[2])]
    groups=[]
    for edge,_,raw in sorted(amounts):
        if groups and abs(statistics.mean(groups[-1])-edge)<5:
            groups[-1].append(edge)
        else: groups.append([edge])
    # Numeric dates occur in headers but repeated amount-column right edges
    # survive across pages. Keep even a single-value column for sparse tables.
    return [statistics.mean(group) for group in groups]


def _table_numbers(page, top, bottom):
    return [amount for amount in _amounts(page,top,bottom)
            if not re.fullmatch(r'(?:19|20)\d{2}',amount[2])
            and not (amount[2]==str(page.number+1) and amount[1]>page.rect.height*.85)]


def _continuation(page, kind, signature):
    top,bottom=statement_body_bounds(page,kind,continued=True)
    amounts=_amounts(page,top,bottom)
    if len(amounts)<2: return False
    if not signature: return len(_signature(amounts))>=2
    matches=sum(any(abs(edge-other)<9 for other in signature) for edge,_,_ in amounts)
    return matches>=2 and matches>=len(amounts)*.60


def _looks_like_table(page, top, bottom):
    """Detect a possible following table without trusting its column mapping.

    A geometry change must not silently end an otherwise unclosed statement.
    Repeated amount-column edges and aligned amount pairs distinguish a table
    from isolated amounts mentioned in explanatory prose.
    """
    amounts=_table_numbers(page,top,bottom)
    monetary=[amount for amount in amounts if '.' in amount[2] or ',' in amount[2]]
    if monetary: amounts=monetary
    groups=[]
    for amount in sorted(amounts,key=lambda x:x[0]):
        if groups and abs(statistics.mean(item[0] for item in groups[-1])-amount[0])<5:
            groups[-1].append(amount)
        else: groups.append([amount])
    repeated=[group for group in groups if len(group)>=2]
    if len(repeated)<2: return False
    aligned_rows=set()
    for index,first in enumerate(repeated):
        for second in repeated[index+1:]:
            for _,y,_ in first:
                if any(abs(y-other_y)<3 for _,other_y,_ in second):
                    aligned_rows.add(round(y/3))
    return len(aligned_rows)>=2


def _pages_for_candidate(document, index, hit):
    result=[]; signature=[]
    for page_index in range(index,min(len(document),index+30)):
        page=document[page_index]
        top,bottom=statement_body_bounds(page,hit.kind,continued=page_index!=index)
        if page_index!=index and not _continuation(page,hit.kind,signature):
            if _looks_like_table(page,top,bottom):
                raise ValueError(f'PDF物理页 {page_index+1}: 合并 {hit.kind} 尚未确认结束，但下一页存在无法对齐的金额栏位置；系统无法可靠识别续表，不能省略续页。')
            break
        result.append(page_index+1)
        amounts=_amounts(page,top,bottom)
        if not signature:
            candidate_signature=_signature(amounts)
            if len(candidate_signature)>=2: signature=candidate_signature
        text=_text_region(page,top,bottom)
        if bottom<page.rect.height-1 or re.search(_END[hit.kind],text,re.I): break
        # Signatures may repeat on every physical table page. They are not a
        # reliable statement terminator; the next page still has to pass the
        # original amount-column continuation check.
    return result


def statement_catalog(document):
    """Scan each source page once for all three statement kinds."""
    result={kind:[] for kind in _TITLES}
    for index,page in enumerate(document):
        for hit in caption_hits(page):
            if hit.scope=='consolidated': result[hit.kind].append((index,hit))
    return result


def find_statement_pages(document, year: int, kind: str, file_name: str, *, catalog=None) -> list[int]:
    groups=[]
    catalog=statement_catalog(document) if catalog is None else catalog
    for index,hit in catalog[kind]:
        page=document[index]
        following=document[index+1] if index+1<len(document) else None
        if not _eligible_period(page,hit,year,following): continue
        same=[other for other in caption_hits(page) if other.kind==kind and other.scope=='consolidated']
        if len(same)>1 and any(_eligible_period(page,other,year,following) for other in same if other!=hit):
            raise ValueError(f'{file_name}: {year} 年合并 {kind} 在 PDF物理页 {index+1} 有多组有效候选，系统无法可靠区分同页表格区域。')
        if same and hit!=same[0]:
            raise ValueError(f'{file_name}: {year} 年合并 {kind} 有效主表位于 PDF物理页 {index+1} 的另一同名表之后，需要适配明确表格区域。')
        top,bottom=statement_body_bounds(page,kind)
        table_numbers=_table_numbers(page,top,bottom)
        if len(table_numbers)<2 and following is not None and hit.y0>page.rect.height*.70 and not caption_hits(following):
            table_numbers=_table_numbers(following,*statement_body_bounds(following,kind,continued=True))
        if len(table_numbers)<2: continue
        if any(index+1 in pages for pages in groups): continue
        try:
            groups.append(_pages_for_candidate(document,index,hit))
        except ValueError as exc:
            raise ValueError(f'{file_name}: {exc}') from None
    if not groups:
        raise ValueError(f'{file_name}: 未找到具有 {year} 年度有效期间列的完整合并 {kind} 主表；请检查报告年度、文本层和表头。')
    if len(groups)>1:
        locations='；'.join(','.join(map(str,pages)) for pages in groups)
        raise ValueError(f'{file_name}: {year} 年合并 {kind} 主表仍有多组有效候选（PDF物理页 {locations}），系统无法可靠区分。')
    return groups[0]
