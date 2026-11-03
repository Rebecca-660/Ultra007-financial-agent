"""Explicit report-currency metadata; never infer currencies from company names.

Confirmations bind one uploaded PDF hash and annual-report identity. Changing
metadata makes a new parser-profile version and keeps every previous run and
PDF immutable. This is not a financial-data review or currency conversion.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from .models import now
from .research_models import ReportingCurrency


def merge_report_currencies(profile: dict | None, confirmations: list[dict]) -> dict:
    """Merge matching explicit metadata, rejecting contradictory attestations."""
    from .parsing import ExtractionProfile,ReportCurrency
    result=deepcopy(profile or {})
    parsed=ExtractionProfile.model_validate(result)
    records=[entry.model_dump(mode='json') for entry in parsed.report_currencies]
    by_identity={(entry['file_name'],entry['file_hash'],entry['report_year']):entry for entry in records}
    for raw in confirmations:
        entry=ReportCurrency.model_validate(raw).model_dump(mode='json')
        identity=(entry['file_name'],entry['file_hash'],entry['report_year'])
        previous=by_identity.get(identity)
        if previous:
            if previous['currency']!=entry['currency']:
                raise ValueError(f"{entry['file_name']}：已确认的列报币种与本次输入冲突，不可静默覆盖。")
            continue
        # Same filename with another hash or annual period is stale, not a new
        # independent attestation inside this immutable company's report set.
        if any(old['file_name']==entry['file_name'] for old in records):
            raise ValueError('币种确认的文件哈希或报告年度与已有记录冲突。')
        records.append(entry); by_identity[identity]=entry
    result['report_currencies']=records
    ExtractionProfile.model_validate(result)
    return result


def confirm_report_currency(project: Path, cid: str, year: int, currency: str, confirmed_by: str) -> dict:
    """Record explicit metadata for an unfinished project without editing runs.

    A new extraction will use the new profile. Existing candidates are detached
    from the active company entry, while their original run folders, snapshots
    and any prior confirmation records remain on disk unchanged.
    """
    from .parsing import validated_profile
    from .research_io import load_project,project_lock,read_json,process_alive
    from .service import FinancialAnalysisAgent,_inside,_write_json
    from .web_tasks import job_status,ACTIVE
    from rag_step1.report import load_report_set

    selected_currency=TypeAdapter(ReportingCurrency).validate_python(currency)
    if type(year) is not int: raise ValueError('报告年度需填写整数。')
    if not isinstance(confirmed_by,str) or not confirmed_by.strip():
        raise ValueError('请填写确认列报币种的使用者。')
    folder=Path(project).resolve()
    with project_lock(folder):
        state=load_project(folder)
        if cid not in state['companies']: raise ValueError('币种确认对应的公司不存在。')
        job=job_status(folder)
        if job and (job['status'] in ACTIVE or (job['status']=='interrupted' and job.get('restart_safe') is False)):
            raise ValueError('后台任务仍在运行或状态不明，请结束后再确认报告币种。')
        entry=state['companies'][cid]
        previous_run=entry.get('run_dir')
        if previous_run:
            run=FinancialAnalysisAgent.status(_inside(folder,previous_run))
            status=run['status']
            if status=='completed': raise ValueError('已完成分析不可原地修改列报币种；请建立新的研究项目。')
            if status in ('preparing','validating','finalizing'):
                owner=run.get('process_id')
                if type(owner) is not int or process_alive(owner) is not False:
                    raise ValueError('原分析仍在运行或状态不明，不能修改报告币种。')
        elif entry.get('status')=='completed':
            raise ValueError('已完成分析不可原地修改列报币种；请建立新的研究项目。')
        reports=load_report_set(_inside(folder,entry['manifest']))
        matches=[source for source in reports.sources if source.report_year==year]
        if len(matches)!=1: raise ValueError('需匹配且仅匹配一份该年度主报告，才能确认列报币种。')
        source=matches[0]
        confirmation={'file_name':source.file_name,'file_hash':source.file_hash,'report_year':year,
                      'currency':selected_currency,'confirmed_by':confirmed_by.strip()}
        previous_profile=entry.get('profile')
        profile=read_json(_inside(folder,previous_profile)) if previous_profile else {}
        merged=merge_report_currencies(profile,[confirmation])
        validated_profile(merged,reports)
        token=uuid4().hex[:16]
        version_folder=_inside(folder,f'currency_confirmations/{token}')
        version_folder.mkdir(parents=True,exist_ok=False)
        profile_file=version_folder/'parser_profile.json'
        audit_file=version_folder/'confirmation.json'
        _write_json(profile_file,merged)
        audit={'schema_version':'finance-report-currency-confirmation-v1','created_at':now(),
            'company_id':cid,'method':'explicit_user_confirmation','reports':[confirmation],
            'previous_profile':previous_profile,'new_profile':str(profile_file.relative_to(folder)),
            'previous_run_dir':previous_run,'financial_review':False,
            'action':'new_extraction_required_existing_runs_unchanged'}
        _write_json(audit_file,audit)
        entry.update(profile=str(profile_file.relative_to(folder)),run_dir=None,status='uploaded')
        state['updated_at']=now()
        _write_json(folder/'project.json',state,replace=True)
        return {'status':'confirmed','company_id':cid,'report_year':year,'currency':selected_currency,
            'profile':str(profile_file),'confirmation':str(audit_file),
            'previous_run_dir':previous_run,'new_extraction_required':True}
