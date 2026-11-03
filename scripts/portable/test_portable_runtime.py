"""Portable-helper checks without installing packages, starting apps or APIs."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import portable_runtime as runtime


class PortableRuntimeTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[2] / 'tmp'
        parent.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='Ultra 007 & 测试 ', dir=parent)
        self.root = Path(self.temporary.name)
        for filename in ('streamlit_app.py', 'requirements.txt', 'requirements-ui.txt'):
            (self.root / filename).write_text('# synthetic fixture\n', encoding='utf-8')
        self.addCleanup(self.temporary.cleanup)

    def model(self):
        folder = self.root / 'data/models' / runtime.DEFAULT_MODEL_NAME
        (folder / '1_Pooling').mkdir(parents=True)
        for filename in ('config.json', 'tokenizer_config.json', 'tokenizer.json'):
            (folder / filename).write_text('{}', encoding='utf-8')
        (folder / 'model.safetensors').write_bytes(b'SYNTHETIC FILE PRESENCE FIXTURE')
        (folder / '1_Pooling/config.json').write_text('{}', encoding='utf-8')
        (folder / 'modules.json').write_text(json.dumps([{'path': ''}, {'path': '1_Pooling'}]), encoding='utf-8')
        return folder

    def test_root_and_model_relocate_with_spaces_ampersand_and_chinese(self):
        self.assertEqual(runtime.project_root(self.root), self.root.resolve())
        folder = self.model()
        self.assertEqual(runtime.local_model_folder(self.root, {'AIF_EMBEDDING_MODEL': runtime.DEFAULT_MODEL_ID}), folder)
        self.assertEqual(runtime.local_model_folder(self.root, {'AIF_EMBEDDING_MODEL':
            r'C:\OLD_COMPUTER\models\paraphrase-multilingual-MiniLM-L12-v2'}), folder)
        self.assertTrue(runtime.model_files_present(folder))

    def test_declared_model_modules_cannot_escape_the_bundled_folder(self):
        folder = self.model()
        (folder / 'modules.json').write_text(json.dumps([{'path': '../../outside'}]), encoding='utf-8')
        self.assertFalse(runtime.model_files_present(folder))
        (folder / 'model.safetensors').unlink()
        self.assertFalse(runtime.model_files_present(folder))

    def test_doctor_reports_key_boolean_only_and_does_not_need_a_network_call(self):
        self.model()
        secret = 'SYNTHETIC-KEY-MUST-NOT-APPEAR'
        (self.root / '.env').write_text('DEEPSEEK_API_KEY=' + secret + '\n', encoding='utf-8')
        with patch.dict(runtime.os.environ, {}, clear=True), \
             patch.object(runtime.metadata, 'version', return_value='fixture'), \
             patch.object(runtime.importlib.util, 'find_spec', return_value=object()), \
             patch.object(runtime.importlib, 'import_module', return_value=object()):
            result = runtime.inspect(self.root, check_port=False)
        self.assertTrue(result['api_key_configured'])
        self.assertTrue(result['local_embedding_files_present'])
        self.assertFalse(result['api_called'])
        self.assertNotIn(secret, json.dumps(result))
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture): runtime.show_check(result)
        self.assertNotIn(secret, capture.getvalue())
        self.assertIn('value hidden', capture.getvalue())

    def test_install_routes_only_to_project_venv_and_both_requirements_constraints(self):
        interpreter = self.root / '.venv' / ('Scripts/python.exe' if runtime.os.name == 'nt' else 'bin/python')
        interpreter.parent.mkdir(parents=True); interpreter.write_bytes(b'fixture')
        (self.root / 'constraints-portable.txt').write_text('example==1\n', encoding='utf-8')
        (self.root / 'scripts/portable').mkdir(parents=True)
        (self.root / 'scripts/portable/constraints-direct.txt').write_text('example==1\n', encoding='utf-8')
        (self.root / '.env.example').write_text('DEEPSEEK_API_KEY=\n', encoding='utf-8')
        with patch.object(runtime, 'supported_python', return_value=True), \
             patch.object(runtime.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as called, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runtime.install(self.root), 0)
        self.assertTrue((self.root / '.env').is_file())
        arguments = called.call_args_list[-1].args[0]
        self.assertEqual(arguments[0], str(interpreter))
        self.assertIn(str(self.root / 'requirements.txt'), arguments)
        self.assertIn(str(self.root / 'requirements-ui.txt'), arguments)
        self.assertIn(str(self.root / 'constraints-portable.txt'), arguments)

    def test_missing_venv_or_unsupported_runtime_never_starts_an_app(self):
        with patch.object(runtime.subprocess, 'run') as called, \
             patch.object(runtime, 'supported_python', return_value=True), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runtime.start(self.root, 8501), 2)
            called.assert_not_called()
        with patch.object(runtime.subprocess, 'run') as called, \
             patch.object(runtime, 'supported_python', return_value=False), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runtime.install(self.root), 2)
            called.assert_not_called()

    def test_start_uses_loopback_and_current_bundled_model_without_downloads(self):
        model = self.model()
        interpreter = self.root / '.venv' / ('Scripts/python.exe' if runtime.os.name == 'nt' else 'bin/python')
        interpreter.parent.mkdir(parents=True); interpreter.write_bytes(b'fixture')
        with patch.object(runtime.sys, 'executable', str(interpreter)), \
             patch.object(runtime, 'supported_python', return_value=True), \
             patch.object(runtime, 'port_available', return_value=True), \
             patch.object(runtime.importlib.util, 'find_spec', return_value=object()), \
             patch.object(runtime.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as called, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runtime.start(self.root, 8501), 0)
        args = called.call_args.args[0]
        self.assertIn('127.0.0.1', args)
        self.assertEqual(called.call_args.kwargs['env']['AIF_EMBEDDING_MODEL'], str(model))
        self.assertEqual(called.call_args.kwargs['env']['HF_HUB_OFFLINE'], '1')
        self.assertEqual(called.call_args.kwargs['env']['TRANSFORMERS_OFFLINE'], '1')


if __name__ == '__main__': unittest.main()
