"""Durable local jobs for web clients, without a Streamlit dependency.

Polling only reads files. A separate Python process owns its event loop and
records real workflow progress; refreshing a page never starts a job. This is
a local single-user job runner, not a production multi-tenant queue.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid

from .models import digest, now
from .research_io import load_project, read_json, selected_companies
from .service import _inside, _write_json

ROOT=Path(__file__).resolve().parents[1]
ACTIVE={'queued','running'}
TERMINAL={'completed','failed','interrupted'}
JOB_SCHEMA='finance-web-job-v1'
STARTUP_GRACE_SECONDS=30


class JobBusy(ValueError):
    """Another local process holds a job-management lock."""


def _jobs_root(project_dir: Path) -> Path:
    project=Path(project_dir).resolve()
    if not project.is_dir(): raise ValueError('研究项目不存在。')
    return _inside(project,'.web_jobs')


def _job_folder(project_dir: Path, job_id: str) -> Path:
    if not isinstance(job_id,str) or re.fullmatch(r'[0-9a-f]{32}',job_id) is None:
        raise ValueError('任务标识无效。')
    return _inside(_jobs_root(project_dir),job_id)


@contextmanager
def _file_lock(path: Path):
    """An OS-owned lock releases on process death; no stale-lock unlink race."""
    path.parent.mkdir(parents=True,exist_ok=True)
    stream=path.open('a+b')
    try:
        if stream.tell()==0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except (OSError,BlockingIOError):
            raise JobBusy('研究任务正在提交，请稍后刷新。') from None
        try: yield
        finally:
            stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
    finally: stream.close()


def _process_info(pid: int) -> tuple[bool|None,str|None]:
    """Check a PID without PowerShell, process listing or a blocking probe.

    Creation identity protects against PID reuse. None means access was denied
    or identity could not be established, so a new paid job is not authorized.
    """
    if type(pid) is not int or pid<=0: return False,None
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype=wintypes.BOOL
        kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
        kernel.GetProcessTimes.restype=wintypes.BOOL
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            error=ctypes.get_last_error()
            return (False,None) if error in (87,1168) else (None,None)
        try:
            code=wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)): return None,None
            if code.value!=259: return False,None  # STILL_ACTIVE
            times=[wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle,*[ctypes.byref(x) for x in times]): return True,None
            created=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
            return True,str(created)
        finally: kernel.CloseHandle(handle)
    try:
        os.kill(pid,0)
    except ProcessLookupError: return False,None
    except PermissionError: return None,None
    try:
        # Linux: fields after the final ')' start at field 3; starttime is 22.
        data=Path(f'/proc/{pid}/stat').read_text(encoding='utf-8')
        return True,data.rsplit(')',1)[1].split()[19]
    except (OSError,IndexError): return True,None


def _alive(receipt: dict) -> bool|None:
    live,identity=_process_info(receipt.get('pid'))
    if live is False: return False
    original=receipt.get('creation_identity')
    if original and identity and original!=identity: return False
    return live


def _age_seconds(stamp: str) -> float:
    try:
        value=datetime.fromisoformat(stamp)
        return (datetime.now(timezone.utc)-value).total_seconds()
    except (ValueError,TypeError): return STARTUP_GRACE_SECONDS+1


def _scope(state: dict, selected: list[str]) -> str:
    return digest({'project_id':state['project_id'],'companies':{
        cid:{'metadata':state['companies'][cid]['metadata'],
             'manifest':state['companies'][cid]['manifest'],
             'report_set_id':state['companies'][cid]['report_set_id']} for cid in selected}})


def job_status(project_dir: Path) -> dict|None:
    """Read latest persisted progress; never launch work or change state files."""
    root=_jobs_root(project_dir)
    if not (root/'latest_job.json').is_file(): return None
    latest=read_json(root/'latest_job.json')
    folder=_job_folder(project_dir,latest.get('job_id'))
    state=read_json(folder/'state.json')
    if state.get('schema_version')!=JOB_SCHEMA or state.get('job_id')!=latest.get('job_id'):
        raise ValueError('后台任务记录无效。')
    view={**state,'job_dir':str(folder)}
    if state['status'] in ACTIVE:
        receipt_path=folder/'process.json'
        if receipt_path.is_file():
            receipt=read_json(receipt_path); live=_alive(receipt)
            view['process_alive']=live
            if live is False:
                view.update(status='interrupted',error_type='WorkerExited',
                    message='后台进程已退出，任务未保存完成。可以检查现有结果后重新启动。',restart_safe=True)
        elif _age_seconds(state.get('created_at'))>STARTUP_GRACE_SECONDS:
            view.update(status='interrupted',error_type='WorkerNotStarted',
                message='后台启动状态无法确认，请先检查后台进程，避免重复运行。',
                process_alive=None,restart_safe=False)
    return view


def _spawn(project: Path, job_id: str):
    kwargs={'cwd':str(ROOT),'stdin':subprocess.DEVNULL,'stdout':subprocess.DEVNULL,
            'stderr':subprocess.DEVNULL,'shell':False,'close_fds':True}
    if os.name=='nt': kwargs['creationflags']=subprocess.CREATE_NO_WINDOW
    return subprocess.Popen([sys.executable,'-m','financial_workbook.web_tasks','--worker',str(project),job_id],**kwargs)


def start_job(project_dir: Path, action: str='analyze', companies: list[str]|None=None,
              *, restart: bool=False) -> dict:
    """Start on explicit user action; deduplicate active or identical completed jobs.

    Only use restart=True for an explicit re-run after a terminal result. A
    previous failed/interrupted attempt can be retried by an explicit call.
    """
    project=Path(project_dir).resolve(); state=load_project(project)
    if action not in ('analyze','compare'): raise ValueError('不支持的后台任务类型。')
    selected=selected_companies(state,companies)
    if action=='compare' and len(selected)<2: raise ValueError('公司比较至少选择两家公司。')
    root=_jobs_root(project); root.mkdir(parents=True,exist_ok=True)
    try:
        with _file_lock(root/'launch.lock'):
            current=job_status(project)
            scope=_scope(state,selected)
            if current and current['status'] in ACTIVE:
                return {**current,'reused':True}
            if current and current['status']=='interrupted' and current.get('restart_safe') is False:
                raise ValueError('尚无法证明原后台进程已经退出，请检查后台进程后恢复；不重复启动付费分析。')
            if (current and current['status']=='completed' and not restart
                and current.get('scope_fingerprint')==scope and current.get('action')==action
                and current.get('companies')==selected):
                return {**current,'reused':True}
            job_id=uuid.uuid4().hex; folder=_job_folder(project,job_id); folder.mkdir()
            request={'schema_version':JOB_SCHEMA,'job_id':job_id,'project_dir':str(project),
                'action':action,'companies':selected,'scope_fingerprint':scope,'created_at':now()}
            record={**request,'status':'queued','updated_at':now(),'progress':[],
                    'message':'任务已提交，正在启动后台分析。','result':None}
            _write_json(folder/'request.json',request)
            _write_json(folder/'state.json',record)
            _write_json(root/'latest_job.json',{'job_id':job_id},replace=True)
            try:
                process=_spawn(project,job_id)
            except Exception as exc:
                record.update(status='failed',updated_at=now(),error_type=type(exc).__name__,
                    message='后台进程未能启动，请检查 Python 环境与文件权限。')
                _write_json(folder/'state.json',record,replace=True)
            else:
                try:
                    live,identity=_process_info(process.pid)
                    _write_json(folder/'process.json',{'pid':process.pid,'creation_identity':identity,'recorded_at':now()},replace=True)
                except (OSError,ValueError):
                    # A spawned worker registers itself before any paid work.
                    # Never label a possibly live worker failed and permit a duplicate.
                    pass
            return {**job_status(project),'reused':False}
    except JobBusy:
        current=job_status(project)
        if current and current['status'] in ACTIVE: return {**current,'reused':True}
        raise


def _safe_message(exc: Exception) -> str:
    """Do not persist provider exceptions, request headers, keys or tracebacks."""
    from pydantic import ValidationError
    from .errors import ReportSourceError
    if isinstance(exc,ValidationError): return '输入资料不完整或格式不正确，请核对公司、年度和文件配置。'
    module=type(exc).__module__
    if isinstance(exc,ReportSourceError) or (isinstance(exc,ValueError) and module.startswith(('builtins','financial_workbook','rag_step1'))):
        value=str(exc).strip()
        if value and not re.search(r'(?i)bearer|authorization|api[_ -]?key|sk-[a-z0-9]|password|secret',value):
            return value[:700]
    return '任务未完成，请检查报告格式和模型服务配置。错误类型：'+type(exc).__name__


def _safe_progress(message) -> str:
    value=str(message)
    if re.search(r'(?i)bearer|authorization|api[_ -]?key|sk-[a-z0-9]|password|secret',value):
        return '正在处理当前分析步骤。'
    return value[:1000]


def _run_worker(project_dir: Path, job_id: str, *, workflow_factory=None) -> int:
    """Private injection point lets tests execute the real lifecycle without APIs."""
    project=Path(project_dir).resolve(); folder=_job_folder(project,job_id)
    try:
        with _file_lock(folder/'worker.lock'):
            record=read_json(folder/'state.json')
            if record['status'] in TERMINAL: return 0
            request=read_json(folder/'request.json')
            if (request.get('schema_version')!=JOB_SCHEMA or request.get('job_id')!=job_id
                or Path(request.get('project_dir','')).resolve()!=project):
                raise ValueError('后台任务请求身份不一致。')
            project_state=load_project(project)
            selected=selected_companies(project_state,request.get('companies'))
            if _scope(project_state,selected)!=request.get('scope_fingerprint'):
                raise ValueError('公司或来源清单已变化，请重新提交分析。')
            if request['action'] not in ('analyze','compare'):
                raise ValueError('后台任务类型无效。')
            live,identity=_process_info(os.getpid())
            _write_json(folder/'process.json',{'pid':os.getpid(),'creation_identity':identity,'recorded_at':now()},replace=True)
            write_lock=threading.Lock()
            record.update(status='running',started_at=now(),updated_at=now(),message='后台分析已开始。')
            _write_json(folder/'state.json',record,replace=True)
            def progress(message):
                with write_lock:
                    text=_safe_progress(message)
                    record['progress']=(record['progress']+[{'at':now(),'message':text}])[-200:]
                    record.update(message=text,updated_at=now())
                    _write_json(folder/'state.json',record,replace=True)
            if workflow_factory is None:
                from .research import ResearchWorkflow
                workflow_factory=ResearchWorkflow
            workflow=workflow_factory(progress=progress)
            if request['action']=='analyze':
                result=asyncio.run(workflow.analyze_automatically(project,selected))
            else:
                progress('正在核对所选公司的可比年度并生成比较结果。')
                result=workflow.history(project,selected)
            with write_lock:
                record.update(status='completed',completed_at=now(),updated_at=now(),result=result,
                    message='分析已完成，可以查看图表和下载结果。')
                _write_json(folder/'state.json',record,replace=True)
            return 0
    except JobBusy: return 3
    except Exception as exc:
        try:
            record=read_json(folder/'state.json')
            record.update(status='failed',completed_at=now(),updated_at=now(),error_type=type(exc).__name__,
                          message=_safe_message(exc),result=None)
            _write_json(folder/'state.json',record,replace=True)
        except (OSError,ValueError): pass
        return 2


def main(argv=None):
    parser=argparse.ArgumentParser(description='Local financial analysis background worker')
    parser.add_argument('--worker',type=Path,required=True)
    parser.add_argument('job_id')
    args=parser.parse_args(argv)
    return _run_worker(args.worker,args.job_id)


if __name__=='__main__': raise SystemExit(main())
