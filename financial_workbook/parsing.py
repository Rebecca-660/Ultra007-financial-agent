"""Company-independent adapters; ambiguous geometry requires an explicit profile.

Profiles select original PDF regions/labels, never supply financial cell values.
The legacy grid parser remains available alongside a borderless text adapter.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import re
import statistics
from typing import Literal
from pydantic import Field, model_validator

from .models import StrictModel, StatementRow, digest
from .research_models import ReportingCurrency


class StatementSelection(StrictModel):
    file_name: str
    file_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    report_year: int
    kind: Literal['BS', 'IS', 'CF']
    pdf_pages: list[int] = Field(min_length=1)

    @model_validator(mode='after')
    def valid_pages(self):
        if self.pdf_pages != sorted(set(self.pdf_pages)) or min(self.pdf_pages) < 1:
            raise ValueError('页码必须为递增且不重复的 PDF 物理页。')
        return self


class PageLayout(StrictModel):
    file_name: str
    file_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    kind: Literal['BS', 'IS', 'CF']
    pdf_page: int = Field(ge=1)
    header_top: float = Field(ge=0)
    body_top: float = Field(gt=0)
    body_bottom: float = Field(gt=0)
    label_right: float = Field(gt=0)
    value_bands: list[tuple[float, float]] = Field(min_length=2, max_length=8)
    note_band: tuple[float, float] | None = None

    @model_validator(mode='after')
    def valid_regions(self):
        if not self.header_top < self.body_top < self.body_bottom:
            raise ValueError('页眉/表体上下界顺序错误。')
        if any(a >= b for a,b in self.value_bands):
            raise ValueError('金额栏左右界错误。')
        if any(a[1] > b[0] for a,b in zip(self.value_bands,self.value_bands[1:])):
            raise ValueError('金额栏不能重叠。')
        if self.label_right > self.value_bands[0][0]:
            raise ValueError('项目栏不能覆盖金额栏。')
        if self.note_band and not self.label_right <= self.note_band[0] < self.note_band[1] <= self.value_bands[0][0]:
            raise ValueError('附注栏边界错误。')
        return self


class ReportCurrency(StrictModel):
    """User-supplied presentation currency, bound to one uploaded PDF."""
    file_name: str
    file_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    report_year: int
    currency: ReportingCurrency
    confirmed_by: str = Field(min_length=1, pattern=r'.*\S.*')


class ExtractionProfile(StrictModel):
    metric_aliases: dict[str, str] = Field(default_factory=dict)
    outflow_signs: dict[str,Literal['positive','negative']] = Field(default_factory=dict)
    statements: list[StatementSelection] = Field(default_factory=list)
    pages: list[PageLayout] = Field(default_factory=list)
    report_currencies: list[ReportCurrency] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_entries(self):
        from .extract import ALIASES, key
        if any(metric not in ALIASES for metric in self.metric_aliases.values()):
            raise ValueError('别名只能指向已注册的标准财务指标。')
        if any(metric not in ('cost_of_sales','capex') for metric in self.outflow_signs):
            raise ValueError('支出正负口径仅适用于 cost_of_sales 和 capex。')
        if len({key(k) for k in self.metric_aliases}) != len(self.metric_aliases):
            raise ValueError('标准化后重复的项目别名。')
        for entries, attributes in [(self.statements,('file_name','kind')),
                                     (self.pages,('file_name','kind','pdf_page')),
                                     (self.report_currencies,('file_name',))]:
            identities=[tuple(getattr(x,k) for k in attributes) for x in entries]
            if len(set(identities)) != len(identities):
                raise ValueError('重复的报表/页面配置。')
        return self


def validated_profile(profile: dict | None, report_set=None) -> ExtractionProfile:
    parsed=ExtractionProfile.model_validate(profile or {})
    if report_set is not None:
        sources={s.file_name:s for s in report_set.sources}
        for entry in [*parsed.statements,*parsed.pages,*parsed.report_currencies]:
            source=sources.get(entry.file_name)
            if source is None or source.file_hash != entry.file_hash:
                raise ValueError('解析配置的文件身份过期或不属于当前公司报告集合。')
            if isinstance(entry,ReportCurrency):
                if entry.report_year != source.report_year:
                    raise ValueError('列报币种确认的年度与上传清单不符。')
                continue
            pages=entry.pdf_pages if isinstance(entry,StatementSelection) else [entry.pdf_page]
            if max(pages)>source.page_count:
                raise ValueError('解析配置的物理页超过源 PDF。')
            if isinstance(entry,StatementSelection) and entry.report_year != source.report_year:
                raise ValueError('解析配置的报告年度与上传清单不符。')
    return parsed


def unit_metadata(page):
    lines=[line.strip() for line in page.get_text().splitlines() if
           re.search(r'Unit\s*[:：]|单位|^\s*(?:Currency|币种)\s*[:：]|in (?:millions|thousands|billions)|amounts? in|expressed in',line,re.I)]
    raw=' '.join(lines)
    definitions=[('CNY',r'CNY|RMB|yuan|人民币'),('USD',r'USD|US\s*\$|U\.S\. dollars|US dollars'),
                 ('HKD',r'HKD|HK\s*\$|Hong Kong dollars|港元'),('EUR',r'EUR|euros?|欧元'),
                 ('GBP',r'GBP|pounds? sterling|英镑'),('JPY',r'JPY|Japanese yen|日元')]
    currencies=[c for c,pattern in definitions if re.search(pattern,raw,re.I)]
    currency=currencies[0] if len(currencies)==1 else None
    scale=(Decimal('1000000000') if re.search(r'billions?|十亿',raw,re.I) else
           Decimal('100000000') if '亿元' in raw else
           Decimal('1000000') if re.search(r'millions?|百万',raw,re.I) else
           Decimal('10000') if '万元' in raw else
           Decimal('1000') if re.search(r'thousands?|千元',raw,re.I) else
           Decimal('1') if re.search(r'(?:金额)?单位\s*[:：]\s*(?:人民币\s*)?元(?:\b|\s|[；;]|$)',raw) else
           Decimal('1') if currency and re.search(r'Unit\s*[:：]|单位|amounts? in|expressed in',raw,re.I) else None)
    return raw,currency,scale


def _grid_edges(page, top, bottom):
    """Read actual vector borders; never infer source rows from LLM text."""
    vertical=[]; horizontal=[]
    def edge(x0,y0,x1,y1):
        if max(y0,y1)<top-2 or min(y0,y1)>bottom+2: return
        if abs(x0-x1)<1.5 and abs(y1-y0)>5:
            vertical.append(float((x0+x1)/2))
        if abs(y0-y1)<1.5 and abs(x1-x0)>page.rect.width*.16:
            horizontal.append(float((y0+y1)/2))
    for drawing in page.get_drawings():
        for item in drawing.get('items',[]):
            if item[0]=='l':
                edge(item[1].x,item[1].y,item[2].x,item[2].y)
            elif item[0]=='re':
                rect=item[1]
                if drawing.get('type')=='f' and rect.width>2 and rect.height>2:
                    # Filled cell/text backgrounds are not table borders.
                    continue
                for a,b,c,d in [(rect.x0,rect.y0,rect.x1,rect.y0),(rect.x0,rect.y1,rect.x1,rect.y1),
                                (rect.x0,rect.y0,rect.x0,rect.y1),(rect.x1,rect.y0,rect.x1,rect.y1)]:
                    edge(a,b,c,d)
    from .extract import _cluster
    return _cluster(vertical,1.2),_cluster(horizontal,.8)


def signature_positions(page, after=0):
    """Use complete signature labels, not an expense word such as 'Legal'."""
    positions=[]
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines',[]):
            text=''.join(span['text'] for span in line.get('spans',[])).strip()
            if line['bbox'][1]>after and re.match(
                r'^(?:Legal\s+Representative\b|Chief\s+Financial\s+Officer\b|'
                r'法定代表人\s*[:：]|主管会计工作负责人\s*[:：]|会计机构负责人\s*[:：（(])',text,re.I):
                positions.append(line['bbox'][1])
    return positions


def _infer_layout(page, year, kind, file_hash, file_name):
    from .extract import NUMBER, _cluster
    words=page.get_text('words')
    if not words:
        raise ValueError('无文字坐标，扫描件需先进行 OCR。')
    year_words=[w for w in words if re.search(r'(?:19|20)\d{2}',w[4])]
    levels=_cluster([(w[1]+w[3])/2 for w in year_words],3)
    candidates=[]
    for level in levels:
        line=[w for w in year_words if abs((w[1]+w[3])/2-level)<=3]
        if 2<=len(line)<=8 and any(str(year) in w[4] for w in line):
            candidates.append(sorted(line,key=lambda w:w[0]))
    if len(candidates)!=1:
        raise ValueError('无法唯一识别年度列头；请提供 parser_profile 的页面区域配置。')
    header=candidates[0]
    top=max(w[3] for w in header)+1
    signatures=signature_positions(page,top)
    bottom=min(signatures) if signatures else min(getattr(page,'clip_bottom',page.rect.height*.94),page.rect.height*.97)
    anchors=[(w[0]+w[2])/2 for w in header]
    xs,ys=_grid_edges(page,top,bottom)
    # A label column plus any note column are proven by vertical borders.
    # This also works when the initial page has many legitimately empty cells.
    bounds=[]
    if xs:
        before=[x for x in xs if x<anchors[0]]
        after=[x for x in xs if x>anchors[-1]]
        interior=[[x for x in xs if a<x<b] for a,b in zip(anchors,anchors[1:])]
        if before and after and all(interior):
            bounds=[max(before),*[min(group,key=lambda x:abs(x-(a+b)/2))
                     for group,a,b in zip(interior,anchors,anchors[1:])],min(after)]
    if bounds:
        notes=[w for w in words if w[4].lower() in ('note','notes','附注') and
               abs(w[1]-header[0][1])<15 and w[2]<bounds[0]]
        note_band=(max(x for x in xs if x<notes[0][0]),bounds[0]) if len(notes)==1 and any(x<notes[0][0] for x in xs) else None
        return PageLayout(file_name=file_name,file_hash=file_hash,kind=kind,pdf_page=page.number+1,
            header_top=max(0,min(w[1] for w in header)-18),body_top=top,body_bottom=bottom,
            label_right=note_band[0] if note_band else bounds[0],note_band=note_band,
            value_bands=list(zip(bounds,bounds[1:])))
    numbers=[w for w in words if top<=w[1] and w[3]<bottom and
             w[0]>min(anchors)-page.rect.width*.18 and NUMBER.fullmatch(w[4])]
    edges=_cluster([w[2] for w in numbers],2.5)
    ranked=sorted(edges,key=lambda edge:sum(abs(w[2]-edge)<3 for w in numbers),reverse=True)
    rights=sorted(ranked[:len(header)])
    if len(rights)!=len(header) or any(abs(x-y)>page.rect.width*.20 for x,y in zip(anchors,rights)):
        raise ValueError('无法可靠识别金额列；请配置原页坐标，禁止猜测或让模型补数字。')
    grouped=[[w for w in numbers if abs(w[2]-right)<3] for right in rights]
    if any(len(group)<2 for group in grouped):
        raise ValueError('可验证金额列不足。')
    lefts=[min(w[0] for w in group) for group in grouped]
    if any(rights[i]>=lefts[i+1] for i in range(len(rights)-1)):
        raise ValueError('检测到金额列重叠。')
    boundaries=[min(lefts[0],header[0][0])-3,
                *[(rights[i]+lefts[i+1])/2 for i in range(len(rights)-1)],page.rect.width]
    # A header is sometimes centred beyond the right edge of its amounts.
    if any(not boundaries[i] <= anchors[i] < boundaries[i+1] for i in range(len(header))):
        raise ValueError('金额列和年度列头未对齐，请配置明确的页面区域。')
    notes=[w for w in words if w[4].lower() in ('note','notes','附注') and abs(w[1]-header[0][1])<15 and w[2]<boundaries[0]]
    note_band=(notes[0][0]-5,boundaries[0]) if len(notes)==1 else None
    return PageLayout(file_name=file_name,file_hash=file_hash,kind=kind,pdf_page=page.number+1,
        header_top=max(0,min(w[1] for w in header)-22),body_top=top,body_bottom=bottom,
        label_right=note_band[0] if note_band else boundaries[0],note_band=note_band,
        value_bands=list(zip(boundaries,boundaries[1:])))


def parse_page(page, year, kind, file_hash, profile=None, file_name='', *, inherited=None,
               inherited_columns=None, return_context=False):
    from .extract import _legacy_page, _column_metadata, identify, key, parse_number, _cluster
    parsed=validated_profile(profile)
    matches=[p for p in parsed.pages if p.file_name==file_name and p.kind==kind and p.pdf_page==page.number+1]
    used_inherited=False
    if matches:
        spec=matches[0]
        if spec.file_hash!=file_hash:
            raise ValueError('页面配置的源哈希不匹配。')
    else:
        try: result=_legacy_page(page,year,kind,file_hash)
        except (ValueError,StopIteration): result=None
        if result is not None:
            aliases={key(label):metric for label,metric in parsed.metric_aliases.items()}
            for row in result[1]: row.canonical_metric=aliases.get(key(row.raw_label),row.canonical_metric)
            output=(result[0],result[1],*unit_metadata(page))
            if not return_context: return output
            try: spec=_infer_layout(page,year,kind,file_hash,file_name)
            except ValueError: spec=None
            return (*output,spec)
        try: spec=_infer_layout(page,year,kind,file_hash,file_name)
        except ValueError:
            if inherited is None: raise
            # Headerless continuation is allowed only inside a locator-proven
            # adjacent table region. Any visible year columns must validate.
            year_words=[w for w in page.get_text('words') if re.search(r'(?:19|20)\d{2}',w[4])]
            levels=_cluster([(w[1]+w[3])/2 for w in year_words],3)
            if any(sum(abs((w[1]+w[3])/2-level)<=3 for w in year_words)>=2 for level in levels):
                raise ValueError('续页存在无法验证的年度列头，不能沿用上一页。') from None
            words=page.get_text('words')
            top=max(getattr(page,'clip_top',0),0.01)
            signatures=signature_positions(page,top)
            bottom=min([getattr(page,'clip_bottom',page.rect.height*.94),*signatures])
            spec=inherited.model_copy(update={'pdf_page':page.number+1,'header_top':max(0,top-1),
                'body_top':top,'body_bottom':bottom})
            used_inherited=True
            # A changed horizontal table geometry must not silently put values
            # into the old columns. Borderless continuations retain exact bands.
            xs,_=_grid_edges(page,top,bottom)
            boundaries=[a for a,b in spec.value_bands]+[spec.value_bands[-1][1]]
            if xs and any(not any(abs(x-boundary)<3 for x in xs) for boundary in boundaries):
                raise ValueError('无列头续页的金额栏位置发生变化，不能可靠继承。')
    if spec.body_bottom>page.rect.height or spec.value_bands[-1][1]>page.rect.width:
        raise ValueError('配置坐标超出 PDF 页面。')
    words=page.get_text('words')
    def inside(word,lo,hi): return lo<=(word[0]+word[2])/2<hi
    def join(selected):
        return ' '.join(w[4] for w in sorted(selected,key=lambda w:(round(w[1],0),w[0])))
    headers=[join([w for w in words if spec.header_top<=w[1] and w[3]<spec.body_top and inside(w,a,b)])
             for a,b in spec.value_bands]
    columns=inherited_columns if used_inherited else _column_metadata(headers,year,kind)
    body=[w for w in words if w[1]>=spec.body_top and w[3]<=spec.body_bottom]
    numeric=[w for w in body if any(inside(w,a,b) for a,b in spec.value_bands)]
    anchors=_cluster([(w[1]+w[3])/2 for w in numeric],2)
    if not anchors:
        raise ValueError('所选区域没有可提取金额。')
    pitches=[b-a for a,b in zip(anchors,anchors[1:]) if b-a>5]
    limit=min(10,(statistics.median(pitches) if pitches else 12)*.6)
    groups=defaultdict(list)
    _,grid_y=_grid_edges(page,spec.body_top,spec.body_bottom)
    grid_y=[y for y in grid_y if spec.body_top-2<=y<=spec.body_bottom+2]
    if len(grid_y)>=4:
        import bisect
        # Horizontal source borders, including per-cell line segments, preserve
        # multi-line labels and vertically centered values in the same row.
        for word in body:
            middle=(word[1]+word[3])/2
            if grid_y[0]-.5<=middle<=grid_y[-1]+.5:
                groups[bisect.bisect_right(grid_y,middle)].append(word)
    else:
        for word in body:
            middle=(word[1]+word[3])/2
            near=min(anchors,key=lambda y:abs(middle-y))
            anchor=near if abs(middle-near)<=limit else round(middle,1)
            groups[anchor].append(word)
    aliases={key(label):metric for label,metric in parsed.metric_aliases.items()}
    rows=[]
    for _,group in sorted(groups.items()):
        label=join([w for w in group if inside(w,0,spec.label_right)])
        raw=[join([w for w in group if inside(w,a,b)]) for a,b in spec.value_bands]
        if not label:
            if any(raw): raise ValueError('金额行缺少对应原始项目，停止提取。')
            continue
        values=[parse_number(x) for x in raw]
        bbox=[min(w[0] for w in group),min(w[1] for w in group),max(w[2] for w in group),max(w[3] for w in group)]
        rows.append(StatementRow(row_id=digest([file_hash,page.number+1,kind,label,raw,bbox])[:24],
            raw_label=label,note=join([w for w in group if spec.note_band and inside(w,*spec.note_band)]),
            values=values,raw_values=raw,pdf_page=page.number+1,bbox=bbox,
            canonical_metric=aliases.get(key(label),identify(label))))
    if not rows:
        raise ValueError('没有可验证的完整表体行。')
    result=(columns,rows,*unit_metadata(page))
    return (*result,spec) if return_context else result


class _RegionPage:
    """Read-only clipped view retaining original physical PDF coordinates."""
    def __init__(self,page,top,bottom):
        self.page=page; self.rect=page.rect; self.number=page.number
        self.clip_top=top; self.clip_bottom=bottom
    def get_text(self,kind='text',**kwargs):
        import pymupdf
        return self.page.get_text(kind,clip=pymupdf.Rect(0,self.clip_top,self.rect.width,self.clip_bottom),**kwargs)
    def get_drawings(self):
        return [d for d in self.page.get_drawings() if d['rect'].y1>=self.clip_top and d['rect'].y0<=self.clip_bottom]


def _presentation_currency(document):
    """Explicit report presentation declaration; a parent's functional
    currency alone does not establish a group's presentation currency."""
    definitions={'CNY':r'人民币|RMB|CNY','USD':r'美元|USD|U\.S\.\s*dollars',
        'HKD':r'港元|港币|HKD|Hong\s+Kong\s+dollars','EUR':r'欧元|EUR|euros',
        'GBP':r'英镑|GBP|pounds\s+sterling','JPY':r'日元|JPY|Japanese\s+yen'}
    found=[]
    for page in document:
        text=re.sub(r'\s+',' ',page.get_text())
        for currency,pattern in definitions.items():
            match=re.search(r'(?:本|该|合并)?财务报表(?:以|采用)\s*(?:'+pattern+r')\s*(?:列示|列报|呈列)|'
                r'(?:consolidated\s+)?financial\s+statements\s+(?:are\s+)?(?:presented|expressed)\s+in\s+(?:'+pattern+r')',text,re.I)
            if match: found.append((currency,page.number+1,match.group(0)))
    if len({item[0] for item in found})>1:
        raise ValueError('报告包含不同列报币种声明，需明确填写该年合并报表的列报币种。')
    return found[0] if found else None


def parse_statement(document, locator, source, profile=None):
    """Parse source-proven consecutive pages, carrying only headings/units.

    Every amount is still read at its own PDF coordinates. Header-only title
    pages, missing repeated column headings and a next statement on the same
    page are handled without letting a model manufacture financial values.
    """
    from .statement_locator import statement_body_bounds,caption_hits
    from .extract import NUMBER
    parsed=validated_profile(profile)
    rows=[]; columns=None; layout=None; first_unit=None
    def merge_unit(current,new,page_number):
        if not new[0]: return current
        if current is None: return new
        old_raw,old_currency,old_scale=current
        raw,currency,scale=new
        if old_currency and currency and old_currency!=currency:
            raise ValueError(f'{source.file_name}, PDF {page_number}: 续表币种发生变化。')
        if old_scale and scale and old_scale!=scale:
            raise ValueError(f'{source.file_name}, PDF {page_number}: 续表金额单位发生变化。')
        if (old_currency is None and currency is not None) or (old_scale is None and scale is not None):
            old_raw+=f'；PDF {page_number}: {raw}'
        return old_raw,old_currency or currency,old_scale or scale
    numbers=locator.pdf_pages
    if not numbers or any(n<1 or n>len(document) for n in numbers):
        raise ValueError('报表页码超出当前原报告。')
    if numbers!=sorted(set(numbers)):
        raise ValueError('报表页码须按原报告顺序递增且不重复。')
    if not any(hit.kind==locator.kind and hit.scope=='consolidated' for hit in caption_hits(document[numbers[0]-1])):
        raise ValueError('主表首个原页没有所声明的合并表标题。')
    for index,number in enumerate(numbers):
        page=document[number-1]
        top,bottom=statement_body_bounds(page,locator.kind,continued=index>0)
        view=_RegionPage(page,top,bottom)
        unit=unit_metadata(view)
        first_unit=merge_unit(first_unit,unit,number)
        try:
            cols,part,raw,currency,scale,spec=parse_page(view,source.report_year,locator.kind,
                source.file_hash,profile,source.file_name,inherited=layout,inherited_columns=columns,return_context=True)
        except (ValueError,StopIteration) as exc:
            words=view.get_text('words')
            _,ys=_grid_edges(view,top,bottom)
            monetary=[w for w in words if NUMBER.fullmatch(w[4]) and re.search(r'[.,]',w[4])]
            item=re.search(r'(?m)^\s*(?:项目|Item)\s*$',view.get_text(),re.I)
            # A caption plus date/unit can end a page without any table cells.
            # Never skip a body page just because its layout is unsupported.
            if index==0 and len(numbers)>1 and not monetary and not item and len(ys)<3:
                continue
            raise ValueError(f'{source.file_name}, PDF {number}, {locator.kind}: {exc}') from exc
        if columns is not None and cols!=columns:
            raise ValueError(f'{source.file_name}, PDF {number}: 续表年度列发生变化。')
        columns=cols; layout=spec or layout
        first_unit=merge_unit(first_unit,(raw,currency,scale),number)
        rows.extend(part)
    if not rows or columns is None:
        raise ValueError(f'{source.file_name}: {locator.kind} 未找到完整表体。')
    raw,currency,scale=first_unit or ('',None,None)
    confirmations=[c for c in parsed.report_currencies if c.file_name==source.file_name]
    confirmation=confirmations[0] if confirmations else None
    if confirmation and (confirmation.file_hash!=source.file_hash or confirmation.report_year!=source.report_year):
        raise ValueError('列报币种确认已过期或不属于当前原报告。')
    if not currency:
        declaration=_presentation_currency(document)
        if declaration:
            currency,page_number,evidence=declaration
            raw+=f'；列报币种依据 PDF {page_number}: {evidence}'
        if confirmation:
            if currency and currency!=confirmation.currency:
                raise ValueError('填写的列报币种与原报告明确声明不一致。')
            currency=confirmation.currency
            raw+=f'；用户确认列报币种 {currency}（{confirmation.confirmed_by}）'
    elif confirmation and confirmation.currency!=currency:
        raise ValueError('填写的列报币种与主表币种不一致。')
    if scale is None and re.search(r'(?:金额)?单位\s*[:：]\s*(?:人民币\s*)?元(?:\b|\s|[；;]|$)',raw):
        scale=Decimal(1)
    return columns,rows,raw,currency,scale
