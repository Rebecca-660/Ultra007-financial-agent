"""Local real-PDF regression oracle for the uploaded Luxshare reports.

This invokes the application locator/parser, never a model API. Known source
pages and amounts below are fixture expectations, not production extraction
rules. It does not supply missing currency evidence or financial assumptions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import re
import unicodedata

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from financial_workbook.extract import extract, locate
from financial_workbook.models import Dataset
from rag_step1.report import load_report_set


# Verified against original PDF pages, including statements that finish above
# another entity's statement on the same page. Values are original base units.
EXPECTATIONS = {
    2021: {
        'BS': {'pages': [109, 110, 111, 112], 'last_row_bottom': 392,
               'metrics': {'assets': '120572098167.88', 'liabilities': '74789454618.31',
                           'equity': '45782643549.57'}},
        'IS': {'pages': [115, 116, 117], 'last_row_bottom': 501,
               'metrics': {'revenue': '153946097790.40', 'net_income': '7820610306.19',
                           'parent_net_income': '7070520386.57'}},
        'CF': {'pages': [119, 120, 121], 'last_row_bottom': 513,
               'metrics': {'cash_opening': '10464804451.34', 'cash_change': '-1543267723.26',
                           'cash_closing': '8921536728.08', 'capex': '12567222230.86'}},
    },
    2022: {
        'BS': {'pages': [105, 106, 107, 108], 'last_row_bottom': 200,
               'metrics': {'assets': '148384319074.71', 'liabilities': '89600449377.52',
                           'equity': '58783869697.19'}},
        'IS': {'pages': [110, 111, 112], 'last_row_bottom': 177,
               'metrics': {'revenue': '214028394291.44', 'net_income': '10490676778.96',
                           'parent_net_income': '9163104849.54'}},
        'CF': {'pages': [113, 114], 'last_row_bottom': 770,
               'metrics': {'cash_opening': '8921536728.08', 'cash_change': '8390881701.43',
                           'cash_closing': '17312418429.51', 'capex': '13584140261.73'}},
    },
    2023: {
        'BS': {'pages': [116, 117, 118, 119], 'last_row_bottom': 309,
               'metrics': {'assets': '161992099595.65', 'liabilities': '91707234769.43',
                           'equity': '70284864826.22'}},
        'IS': {'pages': [121, 122, 123], 'last_row_bottom': 288,
               'metrics': {'revenue': '231905459829.83', 'net_income': '12243213143.13',
                           'parent_net_income': '10952656702.16'}},
        'CF': {'pages': [124, 125, 126], 'last_row_bottom': 174,
               'metrics': {'cash_opening': '17312418429.51', 'cash_change': '12371733891.14',
                           'cash_closing': '29684152320.65', 'capex': '11387449010.98'}},
    },
}


# Source-fixture geometry was checked in rendered originals. This oracle uses
# drawings and original text only: no application identify/parse functions.
START_GRID = {(2021, 'BS'): (109, 384), (2021, 'IS'): (115, 119),
              (2021, 'CF'): (119, 528), (2022, 'BS'): (105, 663),
              (2022, 'IS'): (110, 256), (2022, 'CF'): (113, 533),
              (2023, 'BS'): (117, 71), (2023, 'IS'): (121, 360),
              (2023, 'CF'): (124, 653)}
METRIC_PATTERNS = {
    'assets': r'^资产总计$', 'liabilities': r'^负债合计$',
    'equity': r'^所有者权益合计$', 'revenue': r'^其中[:：]营业收入$',
    'net_income': r'^[一二三四五六七八九十]+、净利润',
    'parent_net_income': r'^1\.归属于母公司股东的净利润$',
    'cash_opening': r'^加[:：]期初现金及现金等价物余额$',
    'cash_change': r'^[一二三四五六七八九十]+、现金及现金等价物净增加额$',
    'cash_closing': r'^[一二三四五六七八九十]+、期末现金及现金等价物余额$',
    'capex': r'^购建固定资产[、,]?无形资产和其他长期资产支付的现金$',
}


def source_oracle(report_set) -> dict:
    sources = {s.report_year: s for s in report_set.sources}
    result = {}
    for year, records in EXPECTATIONS.items():
        source = sources[year]
        with pymupdf.open(source.pdf_path) as document:
            for kind, expected in records.items():
                numeric_start, lower_guard = START_GRID[(year, kind)]
                left = 204.8 if year == 2021 else 217.1
                middle = 369.8 if year == 2021 else 377.85
                right = 535.3 if year == 2021 else 538.8
                if year == 2021 and kind == 'IS':
                    left, middle = 210.5, 371.0
                metrics = {}
                all_rows = []
                for number in expected['pages']:
                    if number < numeric_start:
                        continue
                    page = document[number - 1]
                    top = lower_guard if number == numeric_start else 71
                    bottom = expected['last_row_bottom'] if number == expected['pages'][-1] else 790
                    lines = []
                    for drawing in page.get_drawings():
                        for item in drawing['items']:
                            if item[0] == 'l':
                                a, b = item[1:]
                                if abs(a.y-b.y) < .6:
                                    y, lo, hi = a.y, min(a.x, b.x), max(a.x, b.x)
                                else:
                                    continue
                            elif item[0] == 're':
                                rect = item[1]
                                if rect.height > 1.5:
                                    continue
                                y, lo, hi = rect.y0, rect.x0, rect.x1
                            else:
                                continue
                            if top <= y <= bottom and lo <= left+2 and hi >= middle-2:
                                lines.append(y)
                    horizontal = []
                    for y in sorted(lines):
                        if not horizontal or y-horizontal[-1] > .8:
                            horizontal.append(y)
                    words = page.get_text('words')
                    for y0, y1 in zip(horizontal, horizontal[1:]):
                        group = [w for w in words if y0 < (w[1]+w[3])/2 < y1]
                        label_words = [w for w in group if (w[0]+w[2])/2 < left]
                        raw_label = ''.join(w[4] for w in sorted(label_words, key=lambda w: (round(w[1], 0), w[0])))
                        label = unicodedata.normalize('NFKC', re.sub(r'\s+', '', raw_label))
                        if not label or label.lower() in ('项目', 'item'):
                            continue
                        cells = []
                        for a, b in [(left, middle), (middle, right)]:
                            selected = [w for w in group if a < (w[0]+w[2])/2 < b]
                            raw = ''.join(w[4] for w in sorted(selected, key=lambda w: w[0]))
                            normalized = unicodedata.normalize('NFKC', raw).replace(',', '').replace('−', '-')
                            value = str(Decimal(normalized)) if normalized and normalized not in ('-', '—', '–') else None
                            bbox = [min(w[0] for w in selected), min(w[1] for w in selected),
                                    max(w[2] for w in selected), max(w[3] for w in selected)] if selected else None
                            cells.append({'raw': raw, 'value': value, 'bbox': bbox})
                        source_row = {'pdf_page': number, 'raw_label': raw_label,
                                      'row_bbox': [56, y0, right, y1], 'cells': cells}
                        all_rows.append(source_row)
                        for metric, pattern in METRIC_PATTERNS.items():
                            if not re.search(pattern, label):
                                continue
                            if (kind, metric) not in ({('BS', x) for x in ('assets', 'liabilities', 'equity')} |
                                                     {('IS', x) for x in ('revenue', 'net_income', 'parent_net_income')} |
                                                     {('CF', x) for x in ('cash_opening', 'cash_change', 'cash_closing', 'capex')}):
                                continue
                            if metric in metrics:
                                raise ValueError(f'Independent source oracle found duplicate {year}/{kind}/{metric}')
                            metrics[metric] = source_row
                result[f'{year}_{kind}'] = {'file_name': source.file_name, 'file_hash': source.file_hash,
                                           'metrics': metrics, 'rows': all_rows}
    return result


def validate_source_oracle(oracle: dict) -> list[dict]:
    checks = []
    for year, records in EXPECTATIONS.items():
        for kind, expected in records.items():
            metrics = oracle[f'{year}_{kind}']['metrics']
            for metric, amount in expected['metrics'].items():
                source = metrics.get(metric, {})
                actual = source.get('cells', [{}])[0].get('value')
                checks.append({'check': f'{year}_{kind}_{metric}_verified_source',
                               'pass': actual is not None and Decimal(actual) == Decimal(amount),
                               'actual': actual, 'expected': amount})
            equation = ('assets', 'liabilities', 'equity') if kind == 'BS' else (
                       ('cash_closing', 'cash_opening', 'cash_change') if kind == 'CF' else None)
            if equation and all(key in metrics for key in equation):
                for column in (0, 1):
                    amounts = [metrics[key]['cells'][column]['value'] for key in equation]
                    diff = Decimal(amounts[0])-Decimal(amounts[1])-Decimal(amounts[2]) if all(v is not None for v in amounts) else None
                    checks.append({'check': f'{year}_{kind}_equation_column_{column}',
                                   'pass': diff is not None and abs(diff) <= Decimal('.05'),
                                   'difference': str(diff) if diff is not None else None})
    return checks


def validate(dataset: Dataset, oracle: dict) -> dict:
    checks = validate_source_oracle(oracle)
    statements = {(item.report_year, item.kind): item for item in dataset.statements}
    expected_keys = {(year, kind) for year, records in EXPECTATIONS.items() for kind in records}
    checks.append({'check': 'nine_statement_coverage', 'pass': set(statements) == expected_keys})
    details = []
    full_row_coverage = []
    for year, records in EXPECTATIONS.items():
        for kind, expected in records.items():
            statement = statements.get((year, kind))
            if statement is None:
                checks.append({'check': f'{year}_{kind}_present', 'pass': False})
                continue
            # A title-only page may be retained as provenance or omitted from
            # row-page coverage. The 2023 BS first numeric page is 117.
            acceptable = [expected['pages']]
            if (year, kind) == (2023, 'BS'):
                acceptable.append([117, 118, 119])
            checks.append({'check': f'{year}_{kind}_pages',
                           'pass': statement.pdf_pages in acceptable,
                           'actual': statement.pdf_pages, 'expected': acceptable})
            last_page = expected['pages'][-1]
            tail = [r for r in statement.rows if r.pdf_page == last_page]
            checks.append({'check': f'{year}_{kind}_no_parent_table',
                           'pass': bool(tail) and all(r.bbox[3] < expected['last_row_bottom'] for r in tail)})
            current = [i for i, column in enumerate(statement.columns) if column.role == 'current']
            checks.append({'check': f'{year}_{kind}_one_current_column', 'pass': len(current) == 1})
            source_metrics = oracle[f'{year}_{kind}']['metrics']
            for metric, source in source_metrics.items():
                amount = source['cells'][0]['value']
                rows = [r for r in statement.rows if r.canonical_metric == metric]
                actual = rows[0].values[current[0]] if len(rows) == 1 and len(current) == 1 else None
                checks.append({'check': f'{year}_{kind}_{metric}',
                               'pass': actual == (Decimal(amount) if amount is not None else None) and len(rows) == 1,
                               'actual': str(actual) if actual is not None else None, 'expected': amount})
            required = set(expected['metrics']) | ({'capex'} if kind == 'CF' else set())
            checks.append({'check': f'{year}_{kind}_source_oracle_coverage',
                           'pass': required.issubset(source_metrics),
                           'missing': sorted(required-set(source_metrics))})
            original_rows = oracle[f'{year}_{kind}']['rows']
            normal = lambda value: unicodedata.normalize('NFKC', re.sub(r'\s+', '', value))
            mismatches = []
            for index in range(max(len(original_rows), len(statement.rows))):
                original = original_rows[index] if index < len(original_rows) else None
                candidate = statement.rows[index] if index < len(statement.rows) else None
                matching = (original is not None and candidate is not None and
                            original['pdf_page'] == candidate.pdf_page and
                            normal(original['raw_label']) == normal(candidate.raw_label) and
                            [normal(cell['raw']) for cell in original['cells']] ==
                            [normal(raw) for raw in candidate.raw_values] and
                            [cell['value'] for cell in original['cells']] ==
                            [str(value) if value is not None else None for value in candidate.values])
                if not matching:
                    mismatches.append({'row_index': index,
                                       'source': original,
                                       'candidate': candidate.model_dump(mode='json') if candidate else None})
            original_empty = sum(not any(cell['raw'] for cell in row['cells']) for row in original_rows)
            candidate_empty = sum(not any(row.raw_values) for row in statement.rows)
            coverage = {'year': year, 'kind': kind, 'status': 'passed' if not mismatches else 'failed',
                        'source_rows': len(original_rows), 'candidate_rows': len(statement.rows),
                        'source_rows_with_amount': len(original_rows)-original_empty,
                        'candidate_rows_with_amount': len(statement.rows)-candidate_empty,
                        'source_empty_value_rows': original_empty,
                        'candidate_empty_value_rows': candidate_empty,
                        'compared_cells': sum(len(row['cells']) for row in original_rows),
                        'mismatches': mismatches}
            full_row_coverage.append(coverage)
            checks.append({'check': f'{year}_{kind}_full_row_coverage', 'pass': not mismatches,
                           'source_rows': len(original_rows), 'candidate_rows': len(statement.rows)})
            details.append({'year': year, 'kind': kind, 'pages': statement.pdf_pages,
                            'rows': len(statement.rows), 'currency': statement.currency,
                            'scale': str(statement.scale), 'checks': statement.checks})
    return {'status': 'passed' if all(c['pass'] for c in checks) else 'failed',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'data_kind': 'REAL_UPLOADED_PDFS', 'api_called': False,
            'note': 'Layout and source-cell regression only; missing reporting currency remains unresolved, never inferred from company identity.',
            'checks': checks, 'statements': details, 'source_oracle': oracle,
            'full_row_coverage': full_row_coverage}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path,
                        default=ROOT/'outputs/research_projects/research_2303fdea52b44e2e')
    parser.add_argument('--dataset', type=Path, help='Validate an existing candidates.json instead of extracting again.')
    parser.add_argument('--oracle-only', action='store_true', help='Read source cells without invoking the application parser.')
    parser.add_argument('--output', type=Path, default=ROOT/'tmp/luxshare_layout_validation.json')
    args = parser.parse_args()
    try:
        project = json.loads((args.project/'project.json').read_text(encoding='utf-8-sig'))
        entry = next(e for e in project['companies'].values() if e['metadata']['name'] == '立讯精密')
        report_set = load_report_set(args.project/entry['manifest'])
        oracle = source_oracle(report_set)
        if args.oracle_only:
            source_checks = validate_source_oracle(oracle)
            result = {'status': 'source_oracle_saved' if all(c['pass'] for c in source_checks) else 'failed',
                      'api_called': False, 'source_oracle': oracle, 'checks': source_checks}
        elif args.dataset:
            dataset = Dataset.model_validate_json(args.dataset.read_text(encoding='utf-8-sig'))
        else:
            profile = json.loads((args.project/entry['profile']).read_text(encoding='utf-8-sig')) if entry.get('profile') else {}
            dataset = extract(report_set, locate(report_set, profile), profile)
        if not args.oracle_only:
            result = validate(dataset, oracle)
            result['dataset_fingerprint'] = dataset.fingerprint
            result['report_set_id'] = dataset.report_set_id
            result['candidate_dataset'] = str(args.dataset.resolve()) if args.dataset else None
    except Exception as exc:
        result = {'status': 'blocked', 'api_called': False,
                  'error_type': type(exc).__name__, 'message': str(exc)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'output': str(args.output),
                      'checks': len(result.get('checks', [])),
                      'failed': [c['check'] for c in result.get('checks', []) if not c['pass']],
                      'message': result.get('message')}, ensure_ascii=False))
    return 0 if result['status'] in ('passed', 'source_oracle_saved') else 1


if __name__ == '__main__':
    raise SystemExit(main())
