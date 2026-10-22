import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import boot_trial
import trial


class BootTrialOrderingTests(unittest.TestCase):
    def scenario(self, check):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            native, audio, job = (folder / name for name in ('native', 'audio', 'job'))
            identity = {'model': 'ILCE-7CM2', 'serial_sha256': 'synthetic'}
            payload = bytes(64)
            for path, value in ((native, {'identity': identity}),
                                (audio, {'identity': identity, 'wire_format': 0, 'owner_audio_correct': True})):
                path.mkdir()
                (path / 'job.private.json').write_text(json.dumps(value))
            (audio / 'payload.private.bin').write_bytes(payload)
            state = {'files': {'/usr/lib/appFw.so': b'original-unrelated',
                               '/cp/cpapp-b.bin': b'unchanged CP'}, 'events': [], 'fault': None}

            class Camera:
                core = None
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self, path, missing=False):
                    if state['fault'] == 'file_readback' and path == boot_trial.PATHS[1]: return b'corrupt'
                    if state['fault'] == 'restore_readback' and state.get('restoring') and path == '/usr/lib/appFw.so': return b'wrong'
                    return state['files'].get(path) if missing else state['files'][path]
                def snapshot(self, memory): return b'unchanged settings'
                def records(self, raw): return raw

            def factory(expected):
                self.assertEqual(expected, identity)
                state['events'].append('connect')
                return Camera()

            def prepare(ap, cp, value, output, zig):
                root = Path(output); root.mkdir()
                (root / 'audio').write_bytes(value)
                (root / 'csv').write_bytes(b'private CSV')
                return {'appFw.so': b'modified' + ap[8:], 'cpapp-b.bin': cp}, {
                    'windows': [{'offset': 0, 'before_hex': b'original'.hex(), 'after_hex': b'modified'.hex()}],
                    'program': {'path': 'forward', 'windows': 1, 'sizes': [len(ap), len(cp)]},
                    'files': 'fileworker', 'probe': 'probe', 'wbi': 'wbi',
                    'audio': str(root / 'audio'), 'csv': str(root / 'csv')}

            def files(camera, root, job_state, worker, mode):
                state['events'].append(('files', mode))
                if mode == 1:
                    for path, name in zip(boot_trial.PATHS, ('audio', 'csv')):
                        state['files'][path] = Path(job_state['components'][name]).read_bytes()
                elif mode == 2:
                    for path in boot_trial.PATHS: del state['files'][path]
                return {'native_success': True}

            def program(camera, root, job_state, blob, kind, mode=0, plan=None):
                state['events'].append((kind, mode, str(blob)))
                if kind == 'program' and mode == 1:
                    restoring = str(blob) == 'reverse'
                    prefix = b'original' if restoring else b'modified'
                    state['files']['/usr/lib/appFw.so'] = prefix + state['files']['/usr/lib/appFw.so'][8:]
                    state['restoring'] = restoring
                    if state['fault'] == 'lost_ap_ack': raise TimeoutError('lost AP commit result')
                return {}

            def reverse_worker(ap, cp, edits, output, zig):
                return {'path': 'reverse', 'windows': 1, 'sizes': [len(ap), len(cp)]}

            def install():
                return boot_trial.install(job, folder / 'backup2', native, audio, payload, 100, camera_factory=factory)

            with patch.object(boot_trial, 'prepare', prepare), patch.object(boot_trial, 'invoke_files', files), \
                 patch.object(boot_trial, 'probe', return_value={'image_mode': '0'}), \
                 patch.object(boot_trial, 'program_worker', reverse_worker), \
                 patch.object(trial, 'run_native', program), patch('looktool.devicesettings.compare'):
                check(job, state, install, factory, audio)

    def test_bad_file_readback_stops_before_any_AP_commit(self):
        def check(job, state, install, factory, audio):
            state['fault'] = 'file_readback'
            with self.assertRaisesRegex(ValueError, 'AP hook was not invoked'): install()
            self.assertFalse(any(isinstance(e, tuple) and e[:2] == ('program', 1) for e in state['events']))
            self.assertEqual(state['files']['/usr/lib/appFw.so'], b'original-unrelated')
        self.scenario(check)

    def test_lost_AP_ack_keeps_resources_and_does_not_replay(self):
        def check(job, state, install, factory, audio):
            state['fault'] = 'lost_ap_ack'
            with self.assertRaises(TimeoutError): install()
            self.assertEqual(json.loads((job / 'job.private.json').read_text())['phase'], 'needs_review')
            self.assertTrue(all(path in state['files'] for path in boot_trial.PATHS))
            events = list(state['events'])
            with self.assertRaises(FileExistsError): install()
            self.assertEqual(state['events'], events)
            self.assertNotIn(('files', 2), events)
        self.scenario(check)

    def test_restore_readback_failure_keeps_audio_files(self):
        def check(job, state, install, factory, audio):
            install()
            state['fault'] = 'restore_readback'
            with self.assertRaisesRegex(ValueError, 'audio files must remain'): boot_trial.restore(job, camera_factory=factory)
            self.assertTrue(all(path in state['files'] for path in boot_trial.PATHS))
            self.assertNotIn(('files', 2), state['events'])
        self.scenario(check)

    def test_full_ordering_and_restore_preserve_later_unrelated_edits(self):
        def check(job, state, install, factory, audio):
            install()
            state['files']['/usr/lib/appFw.so'] = state['files']['/usr/lib/appFw.so'][:-1] + b'Z'
            boot_trial.restore(job, camera_factory=factory)
            self.assertEqual(state['files']['/usr/lib/appFw.so'], b'original-unrelateZ')
            self.assertEqual(state['files']['/cp/cpapp-b.bin'], b'unchanged CP')
            self.assertLess(state['events'].index(('files', 1)), state['events'].index(('program', 1, 'forward')))
            self.assertLess(state['events'].index(('program', 1, 'reverse')), state['events'].index(('files', 2)))
        self.scenario(check)

    def test_invalid_encoded_audio_never_opens_a_camera(self):
        def check(job, state, install, factory, audio):
            (audio/'payload.private.bin').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError,'another body or payload'): install()
            self.assertFalse(state['events'])
            self.assertFalse(job.exists())
        self.scenario(check)


if __name__ == '__main__':
    unittest.main()
