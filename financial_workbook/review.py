"""Explicit human workbook import, immutable source cells, correction audit."""
from decimal import Decimal
from pathlib import Path
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from .models import Correction, Dataset, Decision, Review, digest
from .analysis import effective_statements
from rag_step1.report import ReportSet, sha256_file
from .workbook_schema import table_layout, column_name

NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def read_xlsx(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        if any(x.file_size>50_000_000 for x in archive.infolist()):
            raise ValueError("Workbook member too large")
        strings=[]
        if 'xl/sharedStrings.xml' in archive.namelist():
            root=ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings=[''.join(node.itertext()) for node in root]
        root=ET.fromstring(archive.read('xl/workbook.xml'))
        rels=ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets={node.attrib['Id']:node.attrib['Target'] for node in rels}
        sheets={}
        for sheet in root.find('m:sheets',NS):
            target=targets[sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            member=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
            if not member.startswith('xl/') or '..' in member.split('/'):
                raise ValueError("Invalid workbook relationship")
            cells={}
            for cell in ET.fromstring(archive.read(member)).findall('.//m:sheetData/m:row/m:c',NS):
                addr=cell.attrib['r']
                if cell.find('m:f',NS) is not None:
                    cells[addr]={'formula':True}
                    continue
                value=cell.find('m:v',NS)
                typ=cell.attrib.get('t')
                if typ=='s': val=strings[int(value.text)] if value is not None else ''
                elif typ=='inlineStr': val=''.join(cell.find('m:is',NS).itertext())
                elif value is None or value.text is None: val=None
                elif typ in ('str','e'): val=value.text
                else: val=Decimal(value.text)
                cells[addr]=val
            sheets[sheet.attrib['name']]=cells
        return sheets


def assert_sources(dataset: Dataset, report_set: ReportSet):
    if dataset.report_set_id != report_set.report_set_id or dataset.company_id != report_set.company_id:
        raise ValueError("Candidate source set does not match current uploads")
    current={s.file_name:s for s in report_set.sources}
    from .parsing import validated_profile
    validated_profile(dataset.extraction_profile,report_set)
    from .extract import locate
    expected_pages={(item.report_year,item.kind,item.file_name):item.pdf_pages
                    for item in locate(report_set,dataset.extraction_profile)}
    for statement in dataset.statements:
        source=current.get(statement.file_name)
        if not source or source.report_year!=statement.report_year or source.file_hash!=statement.file_hash or sha256_file(source.pdf_path)!=statement.file_hash:
            raise ValueError("报告已变化；必须重新提取和人工审核。")
        if expected_pages.get((statement.report_year,statement.kind,statement.file_name))!=statement.pdf_pages:
            raise ValueError('候选页范围不再匹配原报告的主表与续页，请重新提取。')
        # Bind candidate numbers and metadata to actual PDF cells, not merely to
        # a caller-supplied file hash. Re-reading a candidate JSON is not proof.
        import pymupdf
        from .parsing import parse_statement
        from .models import Locator
        with pymupdf.open(source.pdf_path) as document:
            if not statement.pdf_pages or any(n<1 or n>len(document) for n in statement.pdf_pages):
                raise ValueError('候选页码越出当前原报告。')
            locator=Locator(report_year=statement.report_year,kind=statement.kind,file_name=statement.file_name,
                file_hash=statement.file_hash,pdf_pages=statement.pdf_pages)
            cols,rows,unit,currency,scale=parse_statement(document,locator,source,dataset.extraction_profile)
            if cols!=statement.columns or currency!=statement.currency or scale!=statement.scale or unit!=statement.raw_unit:
                raise ValueError("候选列头、单位或币种不再匹配原页。")
        if rows!=statement.rows:
            raise ValueError("候选行、数值或证据已改动；请重新提取，不要修改原始 JSON。")
        if sha256_file(source.pdf_path)!=statement.file_hash:
            raise ValueError('源报告在核验过程中发生变化，请重新开始。')


def import_review(path: Path, dataset: Dataset, report_set: ReportSet) -> Review:
    assert_sources(dataset,report_set)
    sheets=read_xlsx(path)
    if sheets.get('方法与口径',{}).get('B3')!=dataset.fingerprint:
        raise ValueError("工作簿版本与候选不符，不能复用旧批准。")
    decisions=[]
    reviews=sheets.get('审核',{})
    for index,statement in enumerate(dataset.statements,9):
        layout=table_layout(statement)
        if reviews.get(f'G{index}')!=statement.statement_id or reviews.get(f'H{index}')!=digest(statement):
            raise ValueError("审核表来源身份已改变")
        decision=str(reviews.get(f'C{index}') or '').strip()
        if decision not in ('pending','approved','rejected',''):
            raise ValueError("审核决定仅允许 pending / approved / rejected")
        cells=sheets.get(f'{statement.report_year}_{statement.kind}',{})
        if any(cells.get(f'{column_name(letter)}8')!=column.raw_header for letter,column in zip(layout.originals,statement.columns)):
            raise ValueError('原始比较栏标题已改变，请使用原候选副本。')
        corrections=[]
        for row_index,row in enumerate(statement.rows,9):
            if cells.get(f'{column_name(layout.identity)}{row_index}')!=row.row_id:
                raise ValueError("报表行已变动或排序；请使用未改动行序的候选副本。")
            if (cells.get(f'A{row_index}')!=row.raw_label or
                (cells.get(f'B{row_index}') or '')!=row.note or
                cells.get(f'{column_name(layout.page)}{row_index}')!=row.pdf_page or
                (cells.get(f'{column_name(layout.metric)}{row_index}') or '')!=(row.canonical_metric or '')):
                raise ValueError('原始项目、附注、页码或标准指标已改变；请重新提取。')
            for col,letter_index in enumerate(layout.originals):
                letter=column_name(letter_index)
                value=cells.get(f'{letter}{row_index}')
                original=row.values[col]
                if original is None:
                    matches=value in (None,'')
                else:
                    matches=isinstance(value,Decimal) and abs(value-original)<=max(Decimal('.0005'),abs(original)*Decimal('1e-15'))
                if not matches:
                    raise ValueError("原始值不能直接修改；请在对应的黄色修正栏填值并在修正理由栏写原因。")
                override=cells.get(f'{column_name(layout.overrides[col])}{row_index}')
                if override not in (None,''):
                    if decision!='approved':
                        raise ValueError("含修正的表必须由用户明确批准或清除修正。")
                    corrected=None if override=='MISSING' else Decimal(str(override))
                    reason=str(cells.get(f'{column_name(layout.reason)}{row_index}') or '').strip()
                    if not reason:
                        raise ValueError("每行修正必须填写修正理由。")
                    corrections.append(Correction(row_id=row.row_id,column_id=statement.columns[col].column_id,
                        original=original,corrected=corrected,reason=reason))
        if decision in ('approved','rejected'):
            reviewer=str(reviews.get(f'D{index}') or '').strip()
            if not reviewer:
                raise ValueError("请填写人工审核人；程序和 Agent 不会代签。")
            resolution=str(reviews.get(f'E{index}') or '').strip()
            decisions.append(Decision(statement_id=statement.statement_id,statement_digest=digest(statement),
                decision=decision,reviewer=reviewer,note=str(reviews.get(f'F{index}') or ''),
                conflict_resolution=resolution,corrections=corrections))
    review=Review(dataset_fingerprint=dataset.fingerprint,report_set_id=dataset.report_set_id,decisions=decisions)
    effective_statements(dataset,review)
    return review
