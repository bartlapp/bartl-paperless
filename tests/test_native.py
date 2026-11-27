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

    def test_predecessor_binding_is_not_owned_state_for_a_new_application(self):
        for owner in (None, 'predecessor'):
            with self.subTest(owner=owner), tempfile.TemporaryDirectory() as directory, \
                    patch.object(native, 'STATE', Path(directory)), patch.dict(os.environ, {
                        'BARTL_INSTALLATION': 'installation', 'BARTL_INSTANCE': 'records',
                        'BARTL_UID': 'replacement',
                    }):
                binding = {'identity': native.identity(), 'version': '3.3.1', 'storageID': 'retired-storage'}
                if owner is not None:
                    binding['applicationUID'] = owner
                native.save(Path(directory) / 'binding.json', binding)
                with patch.object(native, 'database') as database:
                    with self.assertRaises(RuntimeError):
                        native.observe()
                    database.assert_not_called()

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


class AuthorityTests(unittest.TestCase):
    def test_whole_stop_dominates_component_replicas(self):
        for running, replicas in ((False, 1), (False, 0), (True, 0), (True, 1)):
            with self.subTest(running=running, replicas=replicas), patch.dict(os.environ, {
                'BARTL_NAMESPACE': 'target', 'BARTL_NAME': 'paperless',
                'BARTL_UID': 'target-application', 'BARTL_POD_NAME': 'native-job',
                'BARTL_POD_UID': 'target-pod',
                'BARTL_INSTALLATION': 'installation', 'BARTL_INSTANCE': 'records',
            }):
                app = {
                    'metadata': {'uid': 'target-application'},
                    'spec': {'running': running, 'replicas': replicas,
                             'identity': native.identity(), 'claims': {'storage': 'target-storage'}},
                }
                with patch.object(native, 'api', side_effect=[
                    app,
                    {'metadata': {'annotations': {'paperless.bartl.sh/owner': 'target-application'}}},
                    {'metadata': {'uid': 'target-pod'}},
                ]) as api:
                    if running and replicas == 1:
                        self.assertIs(native.authority(), app)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'Running authority withdrawn'):
                            native.authority()

    def test_failed_authority_observation_is_not_confirmed_withdrawal(self):
        with patch.dict(os.environ, {'BARTL_NAMESPACE': 'target', 'BARTL_NAME': 'paperless'}):
            failure = TimeoutError('Kubernetes unavailable')
            with patch.object(native, 'api', side_effect=failure):
                with self.assertRaises(TimeoutError) as raised:
                    native.authority()
            self.assertIs(raised.exception, failure)


class CaptureAdmissionTests(unittest.TestCase):
    def test_stale_capture_cannot_start_under_a_new_operation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(native, 'STATE', Path(directory)):
            with patch.object(native, 'authority', return_value={
                'status': {'backup': {'captureOperation': 'current', 'execution': 'execution'}},
            }):
                with self.assertRaisesRegex(RuntimeError, 'no longer has current admission'):
                    native.begin_capture('stale', 'execution', 1)
            self.assertFalse((Path(directory) / 'capture.json').exists())
            self.assertFalse((Path(directory) / 'transition.json').exists())


class NativeTransitionTests(unittest.TestCase):

    def test_failed_index_transition_cannot_bind_or_admit_target(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            stack.enter_context(patch.object(native, 'STATE', root))
            stack.enter_context(patch.object(native, 'authority'))
            stack.enter_context(patch.object(native, 'observe', return_value={
                'state': 'Existing', 'version': '3.3.0',
            }))
            stack.enter_context(patch.object(native, 'version', return_value='3.3.1'))
            stack.enter_context(patch.dict(os.environ, {'BARTL_OPERATION': 'target-migrate'}))
            stack.enter_context(patch.object(native.subprocess, 'run'))
            def manage(*args):
                if args[0] == 'document_index':
                    raise RuntimeError('native reindex failed')
            stack.enter_context(patch.object(native, 'manage', side_effect=manage))
            bind = stack.enter_context(patch.object(native, 'bind'))
            with self.assertRaisesRegex(RuntimeError, 'native reindex failed'):
                native.prepare(migration=True)
            bind.assert_not_called()
            self.assertEqual(native.load(root / 'transition.json')['version'], '3.3.1')
            # Use the real observer: the failed boundary blocks even database observation.
            stack.close()
            with patch.object(native, 'STATE', root), patch.object(native, 'database') as database:
                with self.assertRaisesRegex(RuntimeError, 'Interrupted native transition'):
                    native.observe()
                database.assert_not_called()


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
        for outcome in ('failed', 'interrupted', 'stopped', 'resumed', 'withdrawn'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                state, staging, home = root / 'state', root / 'staging', root / 'home'
                state.mkdir()
                current = {'operation': 'capture', 'execution': 'execution',
                           'state': 'Capturing', 'resumed': False,
                           'withdrawAfterCapture': outcome == 'withdrawn'}
                native.save(state / 'capture.json', current)
                native.save(state / 'transition.json', current)
                stack.enter_context(patch.object(native, 'STATE', state))
                stack.enter_context(patch.object(native, 'STAGING', staging))
                stack.enter_context(patch.object(native, 'HOME', home))
                stack.enter_context(patch.dict(os.environ, {
                    'BARTL_INSTALLATION': 'installation', 'BARTL_INSTANCE': 'records',
                }))
                authority_calls = 0
                def authority(execution):
                    nonlocal authority_calls
                    authority_calls += 1
                    if outcome == 'stopped' and authority_calls == 3:
                        raise RuntimeError('Running authority withdrawn')
                stack.enter_context(patch.object(native, 'authority', side_effect=authority))
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
                    if up and outcome in ('stopped', 'withdrawn'):
                        self.fail('completed capture restarted a withdrawn application')
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
                if outcome == 'withdrawn':
                    captured = native.load(state / 'capture.json')
                    self.assertTrue(captured['withdrawn'])
                    self.assertFalse(captured['resumed'])
                    self.assertEqual(captured['state'], 'Captured')
                    native.verify_capture(captured['path'])
                    termination = root / 'termination.json'
                    with patch.dict(os.environ, {'BARTL_UID': 'current-application'}), \
                            patch.object(native, 'authority', side_effect=AssertionError('closed gate must not admit writers')), \
                            patch.object(native, 'Path', side_effect=lambda p:
                                termination if p == '/dev/termination-log' else Path(p)):
                        with self.assertRaises(SystemExit) as stopped:
                            native.gate()
                        self.assertEqual(stopped.exception.code, 1)
                    receipt = native.load(termination)
                    self.assertEqual(receipt['state'], 'WritesWithdrawn')
                    self.assertEqual(receipt['applicationUID'], 'current-application')
                    self.assertEqual(receipt['capture']['operation'], captured['operation'])
                    self.assertTrue((state / 'transition.json').exists())


if __name__ == '__main__':
    unittest.main()
