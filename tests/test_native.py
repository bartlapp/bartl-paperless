import importlib.util
import os
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import uuid
from contextlib import ExitStack
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location(
    'bartl_native', Path(__file__).parents[1] / 'runtime' / 'native.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class FileObservationTests(unittest.TestCase):
    def test_empty_and_nested_owned_files_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(list(native.files_under(root)), [])
            nested = root / 'documents' / 'originals'
            nested.mkdir(parents=True)
            original = nested / 'record.pdf'
            original.write_bytes(b'retained original')
            self.assertEqual(list(native.files_under(root)), [original])

    @unittest.skipIf(os.geteuid() == 0, 'root bypasses directory DAC permissions')
    def test_unreadable_owned_directory_is_not_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'unreadable'
            root.mkdir()
            (root / 'record.pdf').write_bytes(b'must not initialize over this')
            root.chmod(0)
            try:
                with self.assertRaises(PermissionError):
                    list(native.files_under(root))
            finally:
                root.chmod(0o700)

    def test_changed_export_bytes_refuse_reconstruction(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'BARTL_INSTALLATION': 'test-installation', 'BARTL_INSTANCE': 'records',
        }):
            root = Path(directory)
            (root / 'export').mkdir()
            (root / 'export' / 'manifest.json').write_text('[]')
            original = root / 'export' / 'record.pdf'
            original.write_bytes(b'original capture')
            native.save(root / 'bartl-manifest.json', {
                'format': 1, 'identity': native.identity(), 'version': '3.3.1',
                'files': native.inventory(root),
            })
            native.verify_capture(root)
            original.write_bytes(b'corrupted bytes')
            with self.assertRaises(RuntimeError):
                native.verify_capture(root)


class AdmissionTests(unittest.TestCase):
    def test_replacement_waits_for_retiring_pod(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            execution = root / 'execution'
            pods = {'items': [
                {'metadata': {'uid': 'current'}},
                {'metadata': {'uid': 'retiring', 'deletionTimestamp': '2026-11-04T00:00:00Z'}},
            ]}
            stack.enter_context(patch.object(native, 'STATE', root))
            stack.enter_context(patch.object(native, 'Path', side_effect=lambda p:
                execution if p == '/run/bartl-execution' else Path(p)))
            stack.enter_context(patch.dict(os.environ, {
                'BARTL_NAMESPACE': 'test', 'BARTL_UID': 'application',
                'BARTL_POD_UID': 'current',
            }))
            stack.enter_context(patch.object(native, 'authority'))
            stack.enter_context(patch.object(native, 'api', return_value=pods))
            stack.enter_context(patch.object(native, 'observe', return_value={
                'state': 'Existing', 'version': '3.3.1',
            }))
            stack.enter_context(patch.object(native, 'version', return_value='3.3.1'))
            with self.assertRaises(BlockingIOError):
                native.gate()
            self.assertFalse(execution.exists(), 'replacement received ordinary-service admission')
            pods['items'].pop()
            native.gate()
            self.assertEqual(str(uuid.UUID(execution.read_text())), execution.read_text())


class CaptureCompletionTests(unittest.TestCase):
    def test_resumption_outcome_controls_durable_startup_admission(self):
        for outcome in ('failed', 'interrupted', 'resumed'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                state, staging, home = root / 'state', root / 'staging', root / 'home'
                state.mkdir()
                current = {'operation': 'capture', 'execution': 'execution',
                           'state': 'Capturing', 'resumed': False}
                native.save(state / 'capture.json', current)
                native.save(state / 'transition.json', current)
                stack.enter_context(patch.object(native, 'STATE', state))
                stack.enter_context(patch.object(native, 'STAGING', staging))
                stack.enter_context(patch.object(native, 'HOME', home))
                stack.enter_context(patch.dict(os.environ, {
                    'BARTL_INSTALLATION': 'installation', 'BARTL_INSTANCE': 'records',
                }))
                stack.enter_context(patch.object(native, 'authority'))
                stack.enter_context(patch.object(native, 'version', return_value='3.3.1'))
                stack.enter_context(patch.object(native, 'settled', return_value=True))
                stack.enter_context(patch.object(native, 'native_processes', return_value={}))
                stack.enter_context(patch.object(native, 'broker_empty', return_value=True))
                db = MagicMock()
                db.__enter__.return_value.execute.return_value.fetchone.return_value = (False,)
                stack.enter_context(patch.object(native, 'database', return_value=db))
                stack.enter_context(patch.dict(sys.modules, {
                    'django.db': SimpleNamespace(connections=MagicMock()),
                }))
                def export(*args):
                    (Path(args[1]) / 'manifest.json').write_text('[]')
                stack.enter_context(patch.object(native, 'manage', side_effect=export))
                def services(up, names):
                    if up and outcome == 'failed':
                        raise RuntimeError('native service resumption failed')
                    if up and outcome == 'interrupted':
                        raise SystemExit('container exited during resumption')
                stack.enter_context(patch.object(native, 's6', side_effect=services))
                if outcome == 'interrupted':
                    with self.assertRaises(SystemExit):
                        native.capture('capture', 'execution', 1)
                else:
                    native.capture('capture', 'execution', 1)
                self.assertEqual((state / 'transition.json').exists(), outcome != 'resumed')
                if outcome != 'resumed':
                    with self.assertRaises(RuntimeError):
                        native.observe()
                else:
                    self.assertTrue(native.load(state / 'capture.json')['resumed'])


if __name__ == '__main__':
    unittest.main()
