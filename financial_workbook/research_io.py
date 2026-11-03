"""File-backed research workspace, upload intake and approved snapshot checks."""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import json
import tempfile
import uuid
import os

from .models import Dataset, Review, SystemValidation, digest, now
from .research_models import ResearchManifest, Company
from .service import _write_json, _inside, FinancialAnalysisAgent


def read_json(path: Path) -> dict:
    result=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(result,dict):
        raise ValueError('JSON 顶层必须是对象。')
    return result


@contextmanager
def project_lock(folder: Path):
    lock=Path(folder)/'.research.lock'
    if lock.exists():
        try:
            content=lock.read_text(encoding='utf-8'); owner=json.loads(content).get('pid')
            if type(owner) is int and owner>0 and process_alive(owner) is False:
                if lock.read_text(encoding='utf-8')==content: lock.unlink()
        except (OSError,ValueError): pass
    try:
        stream=lock.open('x',encoding='utf-8')
    except FileExistsError:
        raise ValueError('研究任务正在运行，不能重复提交。异常退出后先确认进程已结束。') from None
    try:
        with stream: stream.write(json.dumps({'created_at':now(),'pid':os.getpid()}))
        yield
    finally:
        lock.unlink(missing_ok=True)


def process_alive(pid: int) -> bool | None:
    """Unknown/access-denied owners are never reclaimed; avoid Windows os.kill."""
    if os.name=='nt':
        import ctypes
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        api.OpenProcess.restype=ctypes.c_void_p
        handle=api.OpenProcess(0x1000,False,pid)
        if not handle: return False if ctypes.get_last_error()==87 else None
        try:
            code=ctypes.c_ulong()
            api.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
            if not api.GetExitCodeProcess(handle,ctypes.byref(code)): return None
            return code.value==259
        finally:
            api.CloseHandle.argtypes=[ctypes.c_void_p]; api.CloseHandle(handle)
    try: os.kill(pid,0); return True
    except ProcessLookupError: return False
    except PermissionError: return None


def create_project(manifest: ResearchManifest, destination: Path, *, source_dir: Path,
                   uploads: dict[str,bytes] | None=None) -> dict:
    """Accept local files or bytes from a future uploader. Never infer ownership."""
    import pymupdf
    from rag_step1.report import load_report_set
    from .parsing import validated_profile
    destination=Path(destination).resolve(); destination.mkdir(parents=True,exist_ok=True)
    source_dir=Path(source_dir).resolve()
    upload_total=0; all_hashes=set()
    with tempfile.TemporaryDirectory(prefix='intake_',dir=destination) as temporary:
        staging=Path(temporary)
        companies={}
        for company in manifest.companies:
            key=sha256(company.company_id.encode()).hexdigest()[:16]
            company_folder=staging/'sources'/key; company_folder.mkdir(parents=True)
            reports=[]; names=set(); currency_confirmations=[]
            for report in [r for r in manifest.reports if r.company_id==company.company_id]:
                # Web clients may send C:\fakepath\name.pdf; keep only the basename.
                filename=report.file_name.replace('\\','/').split('/')[-1]
                if (not filename or Path(filename).suffix.lower()!='.pdf' or filename in names
                    or any(c in filename for c in ':\x00')):
                    raise ValueError('只接受文件名唯一的 PDF 年报。')
                names.add(filename)
                if uploads is not None:
                    if report.file_name not in uploads: raise ValueError('上传内容缺失。')
                    content=uploads[report.file_name]
                else:
                    path=Path(report.file_name)
                    path=path if path.is_absolute() else source_dir/path
                    if path.stat().st_size>100_000_000: raise ValueError('单份 PDF 不得超过 100 MB。')
                    content=path.read_bytes()
                upload_total+=len(content)
                if not isinstance(content,bytes) or len(content)>100_000_000 or upload_total>500_000_000:
                    raise ValueError('上传内容无效，或单份超过 100 MB、合计超过 500 MB。')
                if not content[:1024].lstrip().startswith(b'%PDF-'):
                    raise ValueError('文件不是有效 PDF。')
                fingerprint=sha256(content).hexdigest()
                if fingerprint in all_hashes:
                    raise ValueError('同一 PDF 不能重复指定给不同年度或公司。')
                all_hashes.add(fingerprint)
                target=company_folder/filename; target.write_bytes(content)
                with pymupdf.open(target) as pdf:
                    if pdf.is_encrypted or not len(pdf): raise ValueError('空白或加密 PDF 不支持。')
                    if not any(pdf[i].get_text().strip() for i in range(len(pdf))):
                        raise ValueError('PDF 没有可提取文本；扫描件需要 OCR，本版尚不支持。')
                reports.append({'file_name':filename,'report_year':report.report_year,'file_hash':fingerprint})
                if report.reporting_currency is not None:
                    currency_confirmations.append({'file_name':filename,'file_hash':fingerprint,
                        'report_year':report.report_year,'currency':report.reporting_currency,
                        'confirmed_by':manifest.confirmed_by})
            report_manifest={'company_id':company.company_id,'single_company_confirmed':True,'reports':reports}
            _write_json(company_folder/'report_set.json',report_manifest)
            report_set=load_report_set(company_folder/'report_set.json')
            profile_path=None; profile={}
            if company.parser_profile:
                profile=read_json(source_dir/company.parser_profile)
            if currency_confirmations:
                from .currency_confirmation import merge_report_currencies
                profile=merge_report_currencies(profile,currency_confirmations)
            if company.parser_profile or currency_confirmations:
                validated_profile(profile,report_set)
                _write_json(company_folder/'parser_profile.json',profile)
                profile_path=f'sources/{key}/parser_profile.json'
                if currency_confirmations:
                    _write_json(company_folder/'currency_confirmation.intake.json',{
                        'schema_version':'finance-report-currency-confirmation-v1','created_at':now(),
                        'company_id':company.company_id,'confirmed_by':manifest.confirmed_by,
                        'method':'explicit_upload_metadata','reports':currency_confirmations,
                        'profile':'parser_profile.json','financial_review':False})
            metadata=company.model_dump(mode='json'); metadata.pop('parser_profile',None)
            companies[company.company_id]={'metadata':metadata,'manifest':f'sources/{key}/report_set.json',
                'profile':profile_path,'report_set_id':report_set.report_set_id,
                'years':sorted(r['report_year'] for r in reports),'run_dir':None,'status':'uploaded'}
        project_id='research_'+uuid.uuid4().hex[:16]
        folder=destination/project_id
        state={'schema_version':'finance-research-project-v1','project_id':project_id,
               'created_at':now(),'updated_at':now(),'confirmed_by':manifest.confirmed_by,
               'companies':companies,'history_exports':[]}
        _write_json(staging/'project.json',state)
        _write_json(staging/'input_manifest.json',manifest.model_dump(mode='json'))
        # Rename within the same parent so a half-written upload never becomes a project.
        staging.rename(folder)
    return {'project_dir':str(folder),'companies':list(companies),'status':'uploaded'}


def load_project(folder: Path) -> dict:
    state=read_json(Path(folder)/'project.json')
    if state.get('schema_version')!='finance-research-project-v1':
        raise ValueError('不是本系统的研究项目。')
    for company in state['companies'].values():
        Company.model_validate(company['metadata'])
        _inside(folder,company['manifest'])
        if company.get('profile'): _inside(folder,company['profile'])
        if company.get('run_dir'): _inside(folder,company['run_dir'])
    return state


def selected_companies(state: dict, selection: list[str] | None) -> list[str]:
    selected=list(state['companies']) if selection is None else selection
    if not selected or len(set(selected))!=len(selected) or any(c not in state['companies'] for c in selected):
        raise ValueError('请选择存在且不重复的公司标识。')
    return selected


def approved_bundle(folder: Path, *, verify_sources=True) -> dict:
    """Do not trust edited cached analysis or a merely named completed directory."""
    from .ui_data import load_run
    from .analysis import analyze
    from .review import assert_sources
    from rag_step1.report import load_report_set
    bundle=load_run(folder)
    dataset=Dataset.model_validate(bundle['dataset'])
    review=(SystemValidation.model_validate(bundle['validation']) if bundle.get('validation') else Review.model_validate(bundle['review']))
    if digest(analyze(dataset,review))!=digest(bundle['analysis']):
        raise ValueError('保存的分析与已审核输入重新计算不一致。')
    if verify_sources:
        sources=load_report_set(_inside(folder,bundle['state']['files']['sources']))
        assert_sources(dataset,sources)
    return bundle


def assert_approved_snapshot(bundle: dict):
    from .analysis import analyze
    dataset=Dataset.model_validate(bundle['dataset'])
    review=(SystemValidation.model_validate(bundle['validation']) if bundle.get('validation') else Review.model_validate(bundle['review']))
    result=analyze(dataset,review)
    if (result['status'] not in ('approved','validated') or dataset.fingerprint!=bundle['state']['dataset_fingerprint']
        or digest(result)!=digest(bundle['analysis'])):
        raise ValueError('只有与完整人工审核一致的历史分析才能用于比较或估值。')
