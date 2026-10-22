"""Desktop recovery tests; no USB device is opened."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from desktopapp import recovery
from looktool import checkpoint

BODY = {'model': 'ILCE-7CM2', 'serial_sha256': 'this-body'}
OTHER = {'model': 'ILCE-7CM2', 'serial_sha256': 'other-body'}


def archive(path, identity=BODY, year=2026):
    from zipfile import ZipInfo
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = dict(schema=checkpoint.SCHEMA, model='ILCE-7CM2', version='2.01',
                    identity=identity, files=sorted(checkpoint.inventory()),
                    provenance={'type': 'fl23-prepare-before-changes'}, limitations=[])
    with ZipFile(path, 'w') as stream:
        stream.writestr(ZipInfo('manifest.json', (year, 1, 1, 0, 0, 0)), json.dumps(manifest))
        for name in checkpoint.inventory():
            stream.writestr(name, b'fixture')
    return path


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'A7C2_DESKTOP_DATA': str(self.root / 'app')})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_discover_metadata_only_preserves_capture_time_after_copy(self):
        old = archive(self.root / 'backups/old/checkpoint.private.zip', year=2024)
        new = archive(self.root / 'backups/new/checkpoint.private.zip')
        os.utime(old, None)
        recovery.register(old)
        with patch.object(checkpoint, 'read', side_effect=AssertionError('No full program scan')):
            rows = recovery.discover([self.root / 'backups'])
        self.assertEqual([row['path'] for row in rows], [str(old.resolve()), str(new.resolve())])
        self.assertEqual(len(recovery.discover([self.root / 'backups', old])), 2)

    def test_selects_oldest_of_connected_body_only(self):
        wrong = archive(self.root / 'wrong/checkpoint.private.zip', OTHER, 2022)
        old = archive(self.root / 'old/checkpoint.private.zip', BODY, 2024)
        new = archive(self.root / 'new/checkpoint.private.zip', BODY, 2026)
        rows = [recovery.describe(path) for path in (wrong, new, old)]
        self.assertEqual(recovery.select(rows, BODY)['path'], str(old.resolve()))
        with self.assertRaisesRegex(ValueError, 'connected body'):
            recovery.select([rows[0]], BODY)

    def test_incomplete_backup_is_skipped_with_diagnostic(self):
        path = self.root / 'bad/checkpoint.private.zip'
        path.parent.mkdir()
        with ZipFile(path, 'w') as stream:
            stream.writestr('manifest.json', json.dumps({'schema': checkpoint.SCHEMA, 'version': '2.01'}))
        with patch('builtins.print') as log:
            self.assertEqual(recovery.discover([self.root]), [])
        self.assertTrue(log.called)

    def test_auto_restore_one_session_and_existing_rollback_backend(self):
        original = archive(self.root / 'backup2/checkpoint.private.zip')
        recovery.register(original)
        events = []
        camera = type('Camera', (), {'identity': BODY})()

        @contextmanager
        def connect():
            events.append('open')
            try:
                yield camera
            finally:
                events.append('close')

        class Rollback:
            def __init__(self, root, factory):
                self.root, self.factory = root, factory
            def run(self, path, battery, version):
                with self.factory(BODY) as shared:
                    assert shared is camera
                    assert Path(path) == original
                    events.append(('restore', battery, version))
                return {'phase': 'RESTORED_AWAITING_RELOAD'}

        job = self.root / 'job'
        job.mkdir()
        result = recovery.restore_auto(dict(firmware='2.01', battery=100, workspace=str(self.root / 'restore')),
                                       job, factory=connect, rollback_type=Rollback)
        self.assertEqual(events, ['open', ('restore', 100, '2.01'), 'close'])
        self.assertEqual(result['phase'], 'RESTORED_AWAITING_RELOAD')
        self.assertEqual(json.loads((job / 'recovery-selection.private.json').read_text())['path'], str(original))

    def test_no_backup_or_wrong_body_never_restores(self):
        with patch('looktool.checkpointjob.CheckpointCamera') as camera:
            with self.assertRaisesRegex(ValueError, 'No complete initial backup'):
                recovery.restore_auto(dict(firmware='2.01', battery=100, workspace='unused'), self.root)
            camera.assert_not_called()
        recovery.register(archive(self.root / 'other/checkpoint.private.zip', OTHER))
        camera = type('Camera', (), {'identity': BODY})()
        @contextmanager
        def connect():
            yield camera
        with patch('looktool.checkpointjob.Rollback') as rollback:
            with self.assertRaisesRegex(ValueError, 'connected body'):
                recovery.restore_auto(dict(firmware='2.01', battery=100, workspace='unused'), self.root, factory=connect)
            rollback.assert_not_called()


if __name__ == '__main__':
    unittest.main()
