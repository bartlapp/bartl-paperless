import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from contextlib import ExitStack
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('native_state', Path(__file__).parents[1] / 'runtime/native.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def complete_capture(root, version='3.3.1'):
    for name in native.OWNED_DIRECTORIES:
        (root / 'files' / name).mkdir(parents=True)
    (root / 'database.dump').write_bytes(b'PGDMP complete native database')
    (root / 'files/media/original.pdf').write_bytes(b'original')
    (root / 'files/data/classifier.pickle').write_bytes(b'classifier')
    native.save(root / 'bartl-manifest.json', {
        'format': 2, 'identity': native.identity(), 'version': version,
        'operation': 'capture', 'execution': 'execution', 'capturedAt': 'capture-time',
        'files': native.inventory(root),
    })


class CompleteNativeStateTests(unittest.TestCase):
    def test_incomplete_export_format_and_unsupported_source_version_are_refused(self):
        for format_number, version in ((1, '3.3.0'), (1, '3.3.1'), (2, '3.2.0')):
            with self.subTest(format=format_number, version=version), tempfile.TemporaryDirectory() as directory, \
                    patch.object(native, 'identity', return_value={}):
                root = Path(directory)
                complete_capture(root, version)
                manifest = native.load(root / 'bartl-manifest.json')
                manifest['format'] = format_number
                native.save(root / 'bartl-manifest.json', manifest)
                with self.assertRaises(RuntimeError):
                    native.verify_capture(root)

    def test_missing_owned_directory_or_database_is_not_complete(self):
        for missing in ('database.dump', 'files/consume'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory, \
                    patch.object(native, 'identity', return_value={}):
                root = Path(directory)
                complete_capture(root)
                path = root / missing
                path.rmdir() if path.is_dir() else path.unlink()
                manifest = native.load(root / 'bartl-manifest.json')
                manifest['files'] = native.inventory(root)
                native.save(root / 'bartl-manifest.json', manifest)
                with self.assertRaises(RuntimeError):
                    native.verify_capture(root)

    def test_restore_preserves_owned_files_and_requires_empty_database(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                capture, home = root / 'capture', root / 'home'
                stack.enter_context(patch.object(native, 'identity', return_value={}))
                stack.enter_context(patch.object(native, 'HOME', home))
                complete_capture(capture)
                db = MagicMock()
                db.__enter__.return_value.execute.return_value.fetchone.return_value = (existing,)
                stack.enter_context(patch.object(native, 'database', return_value=db))
                postgres = stack.enter_context(patch.object(native, 'postgres'))
                if existing:
                    with self.assertRaisesRegex(RuntimeError, 'empty owned database'):
                        native.restore_state(capture)
                    postgres.assert_not_called()
                else:
                    native.restore_state(capture)
                    self.assertEqual((home / 'media/original.pdf').read_bytes(), b'original')
                    self.assertEqual((home / 'data/classifier.pickle').read_bytes(), b'classifier')

    def test_unresolved_native_tasks_or_scratch_refuse_capture(self):
        for pending, scratch, missing_original in ((True, False, False), (False, True, False),
                                                   (False, False, True), (False, False, False)):
            with self.subTest(pending=pending, scratch=scratch, missing_original=missing_original), \
                    tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if scratch:
                    (root / 'interrupted-upload.pdf').write_bytes(b'uncommitted')
                tasks = MagicMock()
                tasks.objects.filter.return_value.exists.return_value = pending
                messages = SimpleNamespace(has_error=missing_original, log_messages=MagicMock())
                with patch.dict(sys.modules, {
                    'django': SimpleNamespace(setup=MagicMock()),
                    'django.conf': SimpleNamespace(settings=SimpleNamespace(SCRATCH_DIR=root)),
                    'documents.models': SimpleNamespace(PaperlessTask=tasks),
                    'documents.sanity_checker': SimpleNamespace(check_sanity=lambda: messages),
                }):
                    if pending or scratch or missing_original:
                        with self.assertRaises(RuntimeError):
                            native.assert_settled_state()
                    else:
                        native.assert_settled_state()


class WithdrawalCancellationTests(unittest.TestCase):
    def test_completed_cancellation_survives_interruption_without_starting_services(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            state, staging = root / 'state', root / 'staging'
            stack.enter_context(patch.object(native, 'STATE', state))
            stack.enter_context(patch.object(native, 'STAGING', staging))
            stack.enter_context(patch.object(native, 'identity', return_value={}))
            stack.enter_context(patch.object(native, 'version', return_value='3.3.1'))
            stack.enter_context(patch.dict(os.environ, {
                'BARTL_OPERATION': 'cancel', 'BARTL_PREPARE_MODE': 'capture', 'BARTL_UID': 'owner',
            }))
            stack.enter_context(patch.object(native, 'result', side_effect=lambda value: value))
            stack.enter_context(patch.object(native, 'authority', return_value={'status': {
                'operation': {'id': 'cancel', 'kind': 'cancel-withdrawal', 'mode': 'capture'},
                'backup': {'captureOperation': 'capture', 'execution': 'execution', 'withdrawn': True},
            }}))
            services = stack.enter_context(patch.object(native, 's6'))
            capture = staging / 'captures/capture'
            complete_capture(capture)
            receipt = {'state': 'Captured', 'operation': 'capture', 'execution': 'execution',
                       'withdrawAfterCapture': True, 'withdrawn': True, 'resumed': False,
                       'capturedAt': 'capture-time', 'path': str(capture)}
            native.save(state / 'capture.json', receipt)
            native.save(state / 'transition.json', receipt)
            save = native.save
            def interrupted_save(path, value):
                if Path(path) == state / 'capture.json':
                    raise OSError('interrupted after durable cancellation receipt')
                save(path, value)
            with patch.object(native, 'save', side_effect=interrupted_save):
                with self.assertRaises(OSError):
                    native.cancel_withdrawal()
            self.assertTrue((state / 'transition.json').exists())
            self.assertEqual(native.cancel_withdrawal()['state'], 'WithdrawalCancelled')
            self.assertEqual(native.cancel_withdrawal()['captureOperation'], 'capture')
            self.assertFalse((state / 'transition.json').exists())
            self.assertEqual(native.load(state / 'capture.json')['state'], 'Cancelled')
            services.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, 'not publishable'):
                native.publish('capture')
            with self.assertRaisesRegex(RuntimeError, 'admission changed'):
                native.capture('capture', 'execution', 1)

    def test_incomplete_withdrawal_is_not_cancellation_repair(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            state = Path(directory)
            stack.enter_context(patch.object(native, 'STATE', state))
            stack.enter_context(patch.dict(os.environ, {
                'BARTL_OPERATION': 'cancel', 'BARTL_PREPARE_MODE': 'capture',
            }))
            stack.enter_context(patch.object(native, 'authority', return_value={'status': {
                'operation': {'id': 'cancel', 'kind': 'cancel-withdrawal', 'mode': 'capture'},
                'backup': {'captureOperation': 'capture', 'execution': 'execution', 'withdrawn': True},
            }}))
            native.save(state / 'capture.json', {'state': 'Failed', 'operation': 'capture'})
            native.save(state / 'transition.json', {'state': 'Capturing', 'operation': 'capture'})
            with self.assertRaisesRegex(RuntimeError, 'completed bound withdrawal'):
                native.cancel_withdrawal()
            self.assertEqual(native.load(state / 'transition.json')['state'], 'Capturing')
            self.assertFalse((state / 'cancellations/capture.json').exists())


    def test_new_capture_after_cancellation_does_not_reuse_cancelled_completion(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            stack.enter_context(patch.object(native, 'STATE', root))
            stack.enter_context(patch.object(native, 'STAGING', root))
            stack.enter_context(patch.object(native, 'observe'))
            stack.enter_context(patch.object(native, 'result', side_effect=lambda value: value))
            stack.enter_context(patch.object(native, 'authority', return_value={'status': {
                'backup': {'captureOperation': 'fresh', 'execution': 'new-execution'},
            }}))
            child = stack.enter_context(patch.object(native.subprocess, 'Popen'))
            native.save(root / 'capture.json', {'operation': 'cancelled', 'state': 'Cancelled'})
            current = native.begin_capture('fresh', 'new-execution', 1)
            self.assertEqual(current['state'], 'Capturing')
            self.assertEqual(current['operation'], 'fresh')
            self.assertEqual(native.load(root / 'transition.json')['execution'], 'new-execution')
            child.assert_called_once()

    def test_stop_rejects_cancellation_without_changing_native_state(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(native, 'STATE', Path(directory)):
            native.save(Path(directory) / 'transition.json', {'state': 'Captured', 'withdrawn': True})
            with patch.object(native, 'authority', side_effect=RuntimeError('Running authority withdrawn')):
                with self.assertRaisesRegex(RuntimeError, 'authority withdrawn'):
                    native.cancel_withdrawal()
            self.assertTrue(native.load(Path(directory) / 'transition.json')['withdrawn'])
            self.assertFalse((Path(directory) / 'cancellations').exists())


if __name__ == '__main__':
    unittest.main()
