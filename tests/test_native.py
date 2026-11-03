import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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


if __name__ == '__main__':
    unittest.main()
