"""Build a clean, relocatable handoff without modifying the live workspace.

Use --include-env only for a private handoff authorized to retain credentials.
No credential values are logged. Source/analysis fingerprints stay unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
from hashlib import sha256
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
MODEL='paraphrase-multilingual-MiniLM-L12-v2'
PROJECTS=('research_2303fdea52b44e2e','research_a6e593fc8f6b4268')
LEGACY=Path('outputs/agent_runs/a61c4c2f411135c2acec33bf/20261020T121540Z_79c1b5ca')
IGNORE={'.cache','__pycache__','.web_jobs','.venv','node_modules','.git','tmp'}


def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def copy_tree(source,target):
    if source.is_symlink(): raise ValueError('Symlink is not allowed in the handoff: '+source.name)
    target.mkdir(parents=True,exist_ok=True)
    for item in source.iterdir():
        if item.name in IGNORE or item.name.endswith(('.pyc','.pyo','.lock')): continue
        destination=target/item.name
        if item.is_dir(): copy_tree(item,destination)
        elif item.is_file():
            if item.is_symlink(): raise ValueError('External-linked files must not enter the handoff')
            shutil.copy2(item,destination)


def copy_run(source,target,source_map):
    state=read(source/'run.json')
    if state.get('status')!='completed': raise ValueError('Only completed runs may be bundled')
    target.mkdir(parents=True,exist_ok=True)
    for item in source.iterdir():
        if item.is_file() and not item.name.startswith('.') and not item.name.endswith(('.lock','.tmp','.log')):
            shutil.copy2(item,target/item.name)
    copy_tree(source/state['last_attempt'],target/state['last_attempt'])
    snapshot_file=target/state['files']['sources']
    snapshot=read(snapshot_file)
    for entry in snapshot['reports']:
        original=Path(entry['file_name'])
        original=(original if original.is_absolute() else source/original).resolve()
        replacement=source_map.get(original)
        if replacement is None or not replacement.is_file():
            raise ValueError('A required PDF has not been copied into the handoff')
        entry['file_name']=Path(os.path.relpath(replacement,target)).as_posix()
    write(snapshot_file,snapshot)
    # These fields locate files; immutable candidates/analysis/proofs are not rewritten.
    state['run_dir']='.'
    if state.get('review_workbook'): state['review_workbook']=state['files']['review_workbook'].replace('\\','/')
    for key in ('formal_workbook','last_attempt'):
        if isinstance(state.get(key),str): state[key]=state[key].replace('\\','/')
    state['files']={key:value.replace('\\','/') for key,value in state['files'].items()}
    write(target/'run.json',state)


def copy_project(source,target):
    state=read(source/'project.json')
    if any(entry.get('status')!='completed' for entry in state['companies'].values()):
        raise ValueError('The selected research project has unfinished companies')
    target.mkdir(parents=True,exist_ok=True)
    source_map={}
    copy_tree(source/'sources',target/'sources')
    for original in (source/'sources').rglob('*.pdf'):
        source_map[original.resolve()]=target/original.relative_to(source)
    for entry in state['companies'].values():
        run=Path(entry['run_dir'])
        copy_run(source/run,target/run,source_map)
        if entry.get('profile'):
            profile=Path(entry['profile'])
            destination=target/profile; destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source/profile,destination)
            confirmation=source/profile.parent/'confirmation.json'
            if confirmation.is_file(): shutil.copy2(confirmation,destination.parent/confirmation.name)
        for key in ('manifest','profile','run_dir'):
            if isinstance(entry.get(key),str): entry[key]=entry[key].replace('\\','/')
        entry.pop('review_submission',None)
    # New operators make their own continuation choice and enter their own
    # assumptions. No personal draft or old process receipt is copied.
    state['history_exports']=[]
    write(target/'project.json',state)
    if (source/'input_manifest.json').is_file(): shutil.copy2(source/'input_manifest.json',target/'input_manifest.json')


def constraints(target):
    packages=['PyMuPDF','python-dotenv','llama-index-core','llama-index-llms-deepseek',
        'llama-index-embeddings-huggingface','sentence-transformers','pydantic','XlsxWriter',
        'streamlit','altair','pandas','torch','transformers','huggingface-hub','numpy','scipy',
        'scikit-learn','tokenizers','safetensors']
    (target/'constraints-portable.txt').write_text(
        '# Key runtime versions verified in the source environment.\n'+
        '\n'.join(name+'=='+metadata.version(name) for name in packages)+'\n',encoding='utf-8')
    (target/'requirements-portable.txt').write_text(
        '-r requirements.txt\n-r requirements-ui.txt\n-c constraints-portable.txt\n',encoding='utf-8')


def file_inventory(target):
    result=[]
    for item in sorted(target.rglob('*')):
        relative=item.relative_to(target)
        if (item.is_file() and item.name!='PACKAGE_MANIFEST.json' and
            not any(part in IGNORE for part in relative.parts) and not item.name.endswith(('.pyc','.pyo','.lock'))):
            h=sha256()
            with item.open('rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''): h.update(block)
            result.append({'path':item.relative_to(target).as_posix(),'bytes':item.stat().st_size,'sha256':h.hexdigest()})
    return result


def stage(target,include_env=False):
    if target.exists(): raise ValueError('Choose a new staging directory; existing folders are never overwritten')
    target.mkdir(parents=True)
    for name in ('financial_workbook','rag_step1','assets','.streamlit','tests'):
        copy_tree(ROOT/name,target/name)
    for name in ('streamlit_app.py','run_finance.py','requirements.txt','requirements-ui.txt','.env.example','.gitignore'):
        shutil.copy2(ROOT/name,target/name)
    copy_tree(ROOT/'scripts/portable',target/'scripts/portable')
    # Optional developer tools; the application itself needs Python only.
    for name in ('download_embedding.py','validate_luxshare_layouts.py'):
        shutil.copy2(ROOT/'scripts'/name,target/'scripts'/name)
    shutil.copy2(Path(__file__),target/'scripts'/Path(__file__).name)
    (target/'config').mkdir()
    for name in ('finance.example.json','parser_profile.example.json','research.example.json'):
        shutil.copy2(ROOT/'config'/name,target/'config'/name)
    sys.path.insert(0,str(ROOT))
    from financial_workbook.research_models import ResearchManifest,ValuationRequest,HumanReview
    from financial_workbook.parsing import ExtractionProfile
    for name,model in [('research_manifest.schema.json',ResearchManifest),('fcff_assumptions.schema.json',ValuationRequest),
                       ('human_review.schema.json',HumanReview),('parser_profile.schema.json',ExtractionProfile)]:
        write(target/'config'/name,model.model_json_schema())
    for source,name in [('01_install.bat','01_安装依赖.bat'),('02_check.bat','02_检查环境.bat'),('03_start.bat','03_启动程序.bat')]:
        shutil.copy2(ROOT/'scripts/portable'/source,target/name)
    copy_tree(ROOT/'data/models'/MODEL,target/'data/models'/MODEL)
    for name in PROJECTS:
        copy_project(ROOT/'outputs/research_projects'/name,target/'outputs/research_projects'/name)
    source_map={}
    for original in (ROOT/'data/reports').iterdir():
        if original.is_file() and (original.suffix.lower()=='.pdf' or original.name=='report_set.json'):
            destination=target/'data/reports'/original.name; destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(original,destination)
            if original.suffix.lower()=='.pdf': source_map[original.resolve()]=destination
    copy_run(ROOT/LEGACY,target/LEGACY,source_map)
    if include_env:
        settings=(ROOT/'.env').read_text(encoding='utf-8-sig')
        settings=re.sub(r'(?m)^\s*AIF_EMBEDDING_MODEL\s*=.*$',
            'AIF_EMBEDDING_MODEL=sentence-transformers/'+MODEL,settings)
        (target/'.env').write_text(settings,encoding='utf-8')
    else:
        shutil.copy2(ROOT/'.env.example',target/'.env')
    constraints(target)
    docs=target/'docs'; docs.mkdir()
    for name in ('Ultra007_运行说明.md','财务分析公式清单_当前代码版.md'):
        source_doc=ROOT/name if (ROOT/name).is_file() else ROOT/'docs'/name
        shutil.copy2(source_doc,docs/name)
    license_distribution=metadata.distribution('sentence-transformers')
    license_file=next(Path(license_distribution.locate_file(f)) for f in license_distribution.files or [] if f.name.upper()=='LICENSE')
    (target/'licenses').mkdir()
    shutil.copy2(license_file,target/'licenses/APACHE-2.0.txt')
    (target/'THIRD_PARTY_NOTICES.md').write_text(
        '# Included model\n\nModel: sentence-transformers/'+MODEL+'\n\n'+
        'Source: https://huggingface.co/sentence-transformers/'+MODEL+'\n\n'+
        'The model card identifies Apache-2.0. A copy is in licenses/APACHE-2.0.txt.\n'+
        'Model weights and tokenizer files are unchanged. Runtime dependencies keep their own licenses.\n',encoding='utf-8')
    summary={'format':'ultra007-portable-v1','created_at':datetime.now(timezone.utc).isoformat(),
        'python_tested':sys.version.split()[0],'python_supported':'64-bit Python 3.11–3.14',
        'local_embedding_included':True,'embedding_model':MODEL,'credentials_included':include_env,
        'completed_research_projects':list(PROJECTS),'legacy_analysis_included':True,
        'personal_valuation_drafts_included':False,'background_jobs_included':False,
        'rag_index_cache_included':False,'pip_wheels_included':False,
        'files':file_inventory(target)}
    write(target/'PACKAGE_MANIFEST.json',summary)
    return summary


def refresh_manifest(target):
    summary=read(target/'PACKAGE_MANIFEST.json'); summary['files']=file_inventory(target)
    write(target/'PACKAGE_MANIFEST.json',summary)
    return summary


def archive(target,output):
    refresh_manifest(target)
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED,compresslevel=5,allowZip64=True) as package:
        for item in sorted(target.rglob('*')):
            relative=item.relative_to(target)
            if (item.is_file() and not any(part in IGNORE for part in relative.parts)
                and not item.name.endswith(('.pyc','.pyo','.lock'))):
                package.write(item,Path(target.name)/relative)
    checksum=sha256()
    with output.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): checksum.update(block)
    output.with_name(output.name+'.sha256.txt').write_text(checksum.hexdigest()+'  '+output.name+'\n',encoding='utf-8')
    return {'zip':str(output),'bytes':output.stat().st_size,'sha256':checksum.hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',type=Path,required=True)
    parser.add_argument('--include-env',action='store_true')
    parser.add_argument('--archive-only',action='store_true')
    parser.add_argument('--zip',type=Path)
    args=parser.parse_args(); target=args.target.resolve()
    if not target.is_relative_to(ROOT): raise ValueError('The handoff directory must remain inside the project workspace')
    if args.archive_only:
        if not args.zip: parser.error('--archive-only requires --zip')
        print(json.dumps(archive(target,args.zip.resolve()),ensure_ascii=False))
    else:
        summary=stage(target,args.include_env)
        print(json.dumps({'stage':str(target),'files':len(summary['files']),
            'credentials_included':summary['credentials_included'],'model_included':True},ensure_ascii=False))
    return 0


if __name__=='__main__': raise SystemExit(main())
