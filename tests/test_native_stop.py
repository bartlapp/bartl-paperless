import importlib.util
import json
import os
from pathlib import Path
import tempfile
from contextlib import ExitStack
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'bartl_native_stop', Path(__file__).parents[1] / 'runtime' / 'native.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class StoppedPublicationTests(unittest.TestCase):
    def test_stopped_publication_checks_bound_authority_through_completion(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            stack.enter_context(patch.object(native, 'STAGING', root))
            stack.enter_context(patch.object(native, 'Path', side_effect=lambda p:
                root if p == '/tmp' else Path(p)))
            stack.enter_context(patch.dict(os.environ, {
                'BARTL_NAMESPACE': 'target', 'BARTL_NAME': 'paperless',
                'BARTL_UID': 'owner', 'BARTL_POD_NAME': 'publish-job',
                'BARTL_POD_UID': 'job-pod', 'BARTL_OPERATION': 'publish',
                'BARTL_INSTALLATION': 'installation', 'BARTL_INSTANCE': 'records',
            }))
            app = {'metadata': {'uid': 'owner'}, 'spec': {
                'running': False, 'replicas': 1, 'claims': {}, 'identity': native.identity()},
                'status': {'backup': {'captureOperation': 'capture', 'capturedAt': 'point-time',
                                      'phase': 'Publishing', 'publication': {'id': 'publish'}}}}
            def api(path):
                if '/paperlessapplications/' in path:
                    return app
                return {'metadata': {'uid': 'job-pod'}}
            stack.enter_context(patch.object(native, 'api', side_effect=api))
            stack.enter_context(patch.object(native, 'verify_capture', return_value={'capturedAt': 'point-time'}))
            stack.enter_context(patch.object(native, 'repository_id', return_value='a' * 64))
            stack.enter_context(patch.object(native, 'tags', return_value=[]))
            stack.enter_context(patch.object(native, 'selected_restore'))
            stack.enter_context(patch.object(native, 'result', side_effect=lambda value: value))
            labels = []
            def restic(*args):
                if args[0] == 'backup':
                    label = args[args.index('--tag') + 1]
                    labels.append(label)
                    return json.dumps({'message_type': 'summary',
                                       'snapshot_id': ('b' if label == 'candidate' else 'c') * 64})
                return json.dumps({'tree': 'd' * 64})
            stack.enter_context(patch.object(native, 'restic', side_effect=restic))
            result = native.publish('capture')
            self.assertEqual(result['state'], 'Published')
            self.assertEqual(result['snapshotID'], 'c' * 64)
            self.assertEqual(labels, ['candidate', 'complete'])
            self.assertFalse(app['spec']['running'])


class IntactSourceStartupTests(unittest.TestCase):
    def test_ordinary_start_finishes_only_its_intact_capture_bookkeeping(self):
        for marker_state in ('Capturing', 'Preparing'):
            with self.subTest(marker_state=marker_state), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                stack.enter_context(patch.object(native, 'STATE', root))
                stack.enter_context(patch.dict(os.environ, {
                    'BARTL_UID': 'owner', 'BARTL_NAMESPACE': 'ns', 'BARTL_POD_UID': 'pod',
                    'BARTL_INSTALLATION': 'installation', 'BARTL_INSTANCE': 'records',
                }))
                native.save(root / 'binding.json', {'applicationUID': 'owner', 'identity': native.identity()})
                native.save(root / 'transition.json', {'state': marker_state, 'operation': 'capture', 'execution': 'execution'})
                native.save(root / 'capture.json', {'state': 'Failed', 'sourceIntact': True,
                                                    'operation': 'capture', 'execution': 'execution'})
                stack.enter_context(patch.object(native, 'authority'))
                stack.enter_context(patch.object(native, 'api', return_value={'items': [{'metadata': {'uid': 'pod'}}]}))
                stack.enter_context(patch.object(native, 'version', return_value='3.3.1'))
                stack.enter_context(patch.object(native, 'Path', side_effect=lambda p:
                    root / 'execution' if p == '/run/bartl-execution' else Path(p)))
                def observe():
                    if (root / 'transition.json').exists():
                        raise RuntimeError('Unresolved native transition')
                    return {'state': 'Existing', 'version': '3.3.1'}
                stack.enter_context(patch.object(native, 'observe', side_effect=observe))
                if marker_state == 'Capturing':
                    native.gate()
                    self.assertTrue((root / 'execution').exists())
                else:
                    with self.assertRaisesRegex(RuntimeError, 'Unresolved native transition'):
                        native.gate()
                    self.assertFalse((root / 'execution').exists())


if __name__ == '__main__':
    unittest.main()
