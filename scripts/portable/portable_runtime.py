"""Portable Windows setup, environment check and launch helpers.

This helper uses only the Python standard library until dependencies have been
installed. It never submits reports or calls the model API. Configuration values
and exception payloads containing credentials are never printed.
"""
from __future__ import annotations

import argparse
import importlib
from importlib import metadata
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile

DEFAULT_MODEL_NAME = 'paraphrase-multilingual-MiniLM-L12-v2'
DEFAULT_MODEL_ID = 'sentence-transformers/' + DEFAULT_MODEL_NAME
SUPPORTED = {(3, minor) for minor in range(11, 15)}
REQUIRED_PACKAGES = {
    'streamlit': 'streamlit', 'altair': 'altair', 'pandas': 'pandas',
    'pydantic': 'pydantic', 'PyMuPDF': 'pymupdf', 'python-dotenv': 'dotenv',
    'XlsxWriter': 'xlsxwriter', 'llama-index-core': 'llama_index.core',
    'llama-index-llms-deepseek': 'llama_index.llms.deepseek',
    'llama-index-embeddings-huggingface': 'llama_index.embeddings.huggingface',
    'sentence-transformers': 'sentence_transformers',
}
UI_IMPORTS = {'streamlit', 'altair', 'pandas', 'pydantic', 'pymupdf', 'dotenv', 'xlsxwriter'}


def project_root(explicit: Path | None = None) -> Path:
    root = explicit.resolve() if explicit else Path(__file__).resolve().parents[2]
    if not (root / 'streamlit_app.py').is_file():
        raise ValueError('Project entry streamlit_app.py is missing. Extract the complete ZIP first.')
    if not (root / 'requirements.txt').is_file() or not (root / 'requirements-ui.txt').is_file():
        raise ValueError('Project requirements files are missing. Extract the complete ZIP first.')
    return root


def supported_python() -> bool:
    return sys.version_info[:2] in SUPPORTED and struct.calcsize('P') == 8


def installed_supported_python() -> Path | None:
    """Choose only an existing interpreter listed by the Windows launcher.

    Listing does not install another Python version. Probe the actual candidate
    executable before using it; a default Python 3.15 must not create this venv.
    """
    launcher = shutil.which('py')
    if not launcher:
        return None
    try:
        listed = subprocess.run([launcher, '-0p'], capture_output=True, text=True,
                                errors='replace', timeout=10, stdin=subprocess.DEVNULL)
        candidates = []
        for line in listed.stdout.splitlines():
            found = re.search(r'([A-Za-z]:\\.+?python\.exe)\s*$', line, re.I)
            if not found or not Path(found.group(1)).is_file():
                continue
            interpreter = Path(found.group(1))
            probe = subprocess.run([str(interpreter), '-c',
                'import json,struct,sys; print(json.dumps([sys.version_info[0],sys.version_info[1],struct.calcsize("P")]))'],
                capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
            version = json.loads(probe.stdout.strip())
            if probe.returncode == 0 and tuple(version[:2]) in SUPPORTED and version[2] == 8:
                candidates.append((version[1], interpreter))
        return max(candidates, key=lambda value:value[0])[1] if candidates else None
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return None


def _settings(root: Path) -> dict[str, str]:
    """Read settings internally; callers only expose a boolean for the key."""
    result = {}
    path = root / '.env'
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            name, value = line.split('=', 1)
            name = name.removeprefix('export ').strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            else:
                value = value.split(' #', 1)[0].rstrip()
            result[name] = value
    return result


def local_model_folder(root: Path, settings: dict[str, str]) -> Path:
    configured = os.environ.get('AIF_EMBEDDING_MODEL') or settings.get('AIF_EMBEDDING_MODEL') or DEFAULT_MODEL_ID
    candidate = Path(configured)
    if candidate.is_absolute() and candidate.is_dir():
        return candidate.resolve()
    relative = root / candidate
    if relative.is_dir():
        return relative.resolve()
    # A sender's Windows path is not portable; the model's final directory
    # name is. It is safe to relocate only to the included matching model.
    name = PureWindowsPath(configured.replace('/', '\\')).name
    return root / 'data' / 'models' / name


def model_files_present(folder: Path) -> bool:
    try:
        required = ['config.json', 'modules.json', 'tokenizer_config.json']
        if any(not (folder / name).is_file() for name in required):
            return False
        if not any((folder / name).is_file() and (folder / name).stat().st_size > 0
                   for name in ('model.safetensors', 'pytorch_model.bin')):
            return False
        if not any((folder / name).is_file() for name in ('tokenizer.json', 'sentencepiece.bpe.model', 'vocab.txt')):
            return False
        modules = json.loads((folder / 'modules.json').read_text(encoding='utf-8'))
        if not isinstance(modules, list) or not all(isinstance(module, dict) for module in modules):
            return False
        for module in modules:
            directory = (folder / module.get('path', '')).resolve()
            if not directory.is_relative_to(folder.resolve()) or not directory.is_dir():
                return False
            if module.get('path') and not (directory / 'config.json').is_file():
                return False
        return bool(modules)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
        try:
            stream.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def _writable(root: Path) -> bool:
    try:
        output = root / 'outputs'
        output.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix='.ultra007_write_test_', dir=output, delete=True) as stream:
            stream.write(b'check'); stream.flush()
        return True
    except OSError:
        return False


def inspect(root: Path, *, port: int = 8501, deep: bool = False,
            check_port: bool = True) -> dict:
    packages = []
    for distribution, module in REQUIRED_PACKAGES.items():
        try:
            installed = metadata.version(distribution)
            available = importlib.util.find_spec(module) is not None
            imported = None
            if available and (module in UI_IMPORTS or deep):
                importlib.import_module(module)
                imported = True
            packages.append({'package': distribution, 'version': installed,
                             'available': available, 'import_checked': imported is True})
        except Exception:
            # Do not print arbitrary import exception payloads or environment.
            packages.append({'package': distribution, 'available': False, 'import_checked': False})
    settings = _settings(root)
    api_configured = bool((os.environ.get('DEEPSEEK_API_KEY') or settings.get('DEEPSEEK_API_KEY') or '').strip())
    model_folder = local_model_folder(root, settings)
    writable = _writable(root)
    free_port = port_available(port) if check_port else None
    basic_ready = supported_python() and writable and all(item['available'] for item in packages)
    return {
        'python': '.'.join(map(str, sys.version_info[:3])), 'python_supported': supported_python(),
        '64_bit': struct.calcsize('P') == 8, 'packages': packages, 'project_writable': writable,
        'using_project_venv': Path(sys.prefix).resolve() == (root / '.venv').resolve(),
        'env_file_present': (root / '.env').is_file(), 'api_key_configured': api_configured,
        'local_embedding_files_present': model_files_present(model_folder),
        'port': port, 'port_available': free_port, 'package_import_mode': 'all' if deep else 'UI imports and backend module discovery',
        'dependencies_ready': basic_ready,
        'new_report_analysis_configured': basic_ready and api_configured and model_files_present(model_folder),
        'api_called': False,
    }


def show_check(result: dict) -> None:
    print('Ultra 007 environment check (no API request)', flush=True)
    print(f"[{'OK' if result['python_supported'] else 'FAIL'}] Python {result['python']} 64-bit", flush=True)
    print(f"[{'OK' if result['using_project_venv'] else 'WARN'}] Running in the project .venv", flush=True)
    for package in result['packages']:
        state = 'OK' if package['available'] else 'FAIL'
        detail = ' / import checked' if package.get('import_checked') else ' / module discovered'
        print(f"[{state}] {package['package']} {package.get('version', '')}{detail}", flush=True)
    print(f"[{'OK' if result['project_writable'] else 'FAIL'}] Project output folder is writable", flush=True)
    print(f"[{'OK' if result['env_file_present'] else 'WARN'}] .env file present", flush=True)
    print(f"[{'OK' if result['api_key_configured'] else 'WARN'}] API key is configured (value hidden)", flush=True)
    print(f"[{'OK' if result['local_embedding_files_present'] else 'WARN'}] Local embedding model files present", flush=True)
    if result['port_available'] is not None:
        print(f"[{'OK' if result['port_available'] else 'WARN'}] Port {result['port']} is available", flush=True)
    if not result['api_key_configured'] or not result['local_embedding_files_present']:
        print('Saved-result browsing and valuation can work without a new API call.', flush=True)
        print('New report analysis needs an API key and the complete local embedding model.', flush=True)
    if result['port_available'] is False:
        print('An app may already be running. Close its terminal with Ctrl+C, or use another --port.', flush=True)


def install(root: Path) -> int:
    if not supported_python():
        print('Use 64-bit Python 3.11-3.14. This project was validated on Python 3.14.', flush=True)
        print('Install Python from https://www.python.org/downloads/windows/ and run this step again.', flush=True)
        return 2
    venv = root / '.venv'
    interpreter = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not interpreter.is_file():
        print('Creating a project-only virtual environment...', flush=True)
        result = subprocess.run([sys.executable, '-m', 'venv', str(venv)], cwd=root)
        if result.returncode:
            return result.returncode
    print('Installing dependencies into .venv. Internet access is needed unless a full wheels folder is provided.', flush=True)
    wheels = root / 'wheels'
    offline_wheels = wheels.is_dir() and any(wheels.glob('*.whl'))
    if not offline_wheels:
        result = subprocess.run([str(interpreter), '-m', 'pip', 'install', '--upgrade', 'pip'], cwd=root)
        if result.returncode:
            return result.returncode
    arguments = [str(interpreter), '-m', 'pip', 'install', '-r', str(root / 'requirements.txt'),
                 '-r', str(root / 'requirements-ui.txt')]
    constraints = root / 'scripts/portable/constraints-direct.txt'
    if constraints.is_file():
        arguments.extend(['-c', str(constraints)])
    root_constraints = root / 'constraints-portable.txt'
    if root_constraints.is_file():
        arguments.extend(['-c', str(root_constraints)])
    if offline_wheels:
        arguments.extend(['--no-index', '--find-links', str(wheels)])
    result = subprocess.run(arguments, cwd=root)
    if result.returncode:
        print('Installation did not complete. Check network/disk space, then run Install again.', flush=True)
        return result.returncode
    template = root / '.env.example'
    if not (root / '.env').exists() and template.is_file():
        shutil.copyfile(template, root / '.env')
        print('Created .env from the template. Configure an API key before analysing new reports.', flush=True)
    print('Installation finished. Run the environment-check shortcut, then the start shortcut.', flush=True)
    return 0


def start(root: Path, port: int) -> int:
    if not supported_python():
        print('Use 64-bit Python 3.11-3.14 and install the project environment first.', flush=True)
        return 2
    interpreter = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not interpreter.is_file():
        print('The project .venv is missing. Run 01_install first.', flush=True)
        return 2
    if Path(sys.executable).resolve() != interpreter.resolve():
        return subprocess.run([str(interpreter), str(Path(__file__).resolve()), 'start',
                               '--root', str(root), '--port', str(port)], cwd=root).returncode
    if not port_available(port):
        print(f'Port {port} is already in use. The application may already be open.', flush=True)
        print(f'If it is Ultra 007, browse to http://127.0.0.1:{port}. Otherwise stop it or choose --port 8503.', flush=True)
        return 3
    if importlib.util.find_spec('streamlit') is None:
        print('Streamlit is missing. Run 01_install first.', flush=True)
        return 2
    environment = os.environ.copy()
    folder = local_model_folder(root, _settings(root))
    if model_files_present(folder):
        environment['AIF_EMBEDDING_MODEL'] = str(folder)
        environment['HF_HUB_OFFLINE'] = '1'
        environment['TRANSFORMERS_OFFLINE'] = '1'
    print(f'Opening Ultra 007 at http://127.0.0.1:{port}', flush=True)
    print('Keep this window open. Press Ctrl+C here to stop the app.', flush=True)
    arguments = [sys.executable, '-m', 'streamlit', 'run', str(root / 'streamlit_app.py'),
                 '--server.address', '127.0.0.1', '--server.port', str(port),
                 '--server.headless', 'false', '--browser.gatherUsageStats', 'false']
    try:
        return subprocess.run(arguments, cwd=root, env=environment).returncode
    except KeyboardInterrupt:
        return 130


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'check', 'start'])
    parser.add_argument('--root', type=Path, help='Normally detected from the helper location.')
    parser.add_argument('--port', type=int, default=8501)
    parser.add_argument('--deep', action='store_true', help='Also import the heavier analysis libraries; never calls an API.')
    parser.add_argument('--no-port-check', action='store_true')
    parser.add_argument('--json', '--json-output', dest='json_output', type=Path,
                        help='Write a diagnostics report without credentials.')
    arguments = parser.parse_args(argv)
    if not 1 <= arguments.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    try:
        root = project_root(arguments.root)
        if arguments.action == 'install':
            if not supported_python() and not (root / '.venv').exists():
                alternate = installed_supported_python()
                if alternate:
                    print('Using an already-installed compatible 64-bit Python for this project.', flush=True)
                    return subprocess.run([str(alternate), str(Path(__file__).resolve()), 'install',
                                           '--root', str(root)], cwd=root).returncode
            return install(root)
        if arguments.action == 'start':
            return start(root, arguments.port)
        result = inspect(root, port=arguments.port, deep=arguments.deep, check_port=not arguments.no_port_check)
        show_check(result)
        if arguments.json_output:
            arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
            arguments.json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return 0 if result['dependencies_ready'] else 1
    except (OSError, ValueError):
        print('The project could not be prepared. Extract the complete ZIP into a writable folder and try again.', flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
