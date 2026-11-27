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


if __name__ == '__main__':
    unittest.main()
