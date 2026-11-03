"""Source-bound machine validation. It never signs a human review."""
from decimal import Decimal

from .models import Dataset, SystemValidation, digest


def assert_validation(dataset: Dataset, validation: SystemValidation):
    if (validation.dataset_fingerprint!=dataset.fingerprint or validation.company_id!=dataset.company_id
        or validation.report_set_id!=dataset.report_set_id
        or validation.statement_digests!={s.statement_id:digest(s) for s in dataset.statements}):
        raise ValueError('系统校验与当前候选版本不一致，请重新校验来源。')
    check_dataset(dataset)


def check_dataset(dataset: Dataset) -> tuple[list[dict],list[str]]:
    years={s.report_year for s in dataset.statements}
    if {(s.report_year,s.kind) for s in dataset.statements}!={(y,k) for y in years for k in ('IS','BS','CF')}:
        raise ValueError('系统校验失败：每年必须具有完整合并三表。')
    currencies={s.currency for s in dataset.statements}
    if len(currencies)!=1 or None in currencies:
        raise ValueError('系统校验失败：主表币种缺失或不一致。')
    checks=[]; warnings=['系统校验仅检查可验证的来源和规则，未经人工财务复核。']
    for s in dataset.statements:
        if not s.scale or s.scale<=0 or not s.raw_unit.strip():
            raise ValueError('系统校验失败：金额单位缺失或无效。')
        indexed={}
        for row in s.rows:
            if row.canonical_metric:
                if row.canonical_metric in indexed:
                    # Ambiguous mappings remain missing in the calculation rather than guesses.
                    warnings.append(f'{s.report_year}_{s.kind} 指标映射不唯一：{row.canonical_metric}；该指标不自动补值。')
                indexed.setdefault(row.canonical_metric,[]).append(row)
        equations=([('assets',['liabilities','equity'])] if s.kind=='BS' else
                   [('cash_closing',['cash_opening','cash_change'])] if s.kind=='CF' else [])
        for total,parts in equations:
            for col in range(len(s.columns)):
                available=all(len(indexed.get(k,[]))==1 and indexed[k][0].values[col] is not None for k in [total,*parts])
                if not available:
                    checks.append({'statement_id':s.statement_id,'name':total,'column':col,'status':'unavailable'})
                    continue
                difference=indexed[total][0].values[col]-sum(indexed[k][0].values[col] for k in parts)
                if abs(difference)>Decimal('.05'):
                    raise ValueError(f'系统校验失败：{s.report_year}_{s.kind} 基础勾稽不成立。')
                checks.append({'statement_id':s.statement_id,'name':total,'column':col,'status':'pass','difference':str(difference)})
        if any(c.get('status')=='fail' for c in s.checks):
            raise ValueError(f'系统校验失败：{s.report_year}_{s.kind} 已记录勾稽失败。')
        checks.append({'statement_id':s.statement_id,'name':'identity_units_columns','status':'pass'})
    if dataset.conflicts:
        warnings.append(f'{len(dataset.conflicts)} 处跨报告比较差异保留；系统按各年原报本年数分析，不自动覆盖重述。')
    return checks,list(dict.fromkeys(warnings))


def validate_sources(dataset: Dataset, report_set) -> SystemValidation:
    from .review import assert_sources
    assert_sources(dataset,report_set)
    expected={(s.report_year,k) for s in report_set.sources for k in ('IS','BS','CF')}
    if {(s.report_year,s.kind) for s in dataset.statements}!=expected:
        raise ValueError('系统校验失败：上传年报与候选三表覆盖不一致。')
    checks,warnings=check_dataset(dataset)
    return SystemValidation(dataset_fingerprint=dataset.fingerprint,company_id=dataset.company_id,
        report_set_id=dataset.report_set_id,statement_digests={s.statement_id:digest(s) for s in dataset.statements},
        checks=[{'name':'original_pdf_reparse','status':'pass'},*checks],warnings=warnings)
