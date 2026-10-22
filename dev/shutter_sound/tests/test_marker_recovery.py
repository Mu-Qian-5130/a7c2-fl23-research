import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from buffer_trial import initial_marker, retire_recovered_marker


class MarkerRecoveryTests(unittest.TestCase):
    def scenario(self, check, token=None, recovered=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); old = root / 'old'; old.mkdir(); new = root / 'new'; new.mkdir()
            identity = {'model': 'ILCE-7CM2', 'serial_sha256': 'synthetic'}
            previous = {'identity': identity, 'owner_cold_recovery_confirmed': recovered,
                        'result': {'temporary_pcm_registered': True, 'payload_length': 3776,
                                   'original_entry_hex': bytes(48).hex()}}
            if token is not None: previous['lease_token_hex'] = token.hex()
            (old / 'job.private.json').write_text(json.dumps(previous))
            data = {'marker': initial_marker(previous), 'removed': []}
            class Camera:
                def read(self, path, missing=False):
                    self_path = '/tmp/jiritsu/shutter.custom.lease'
                    if path != self_path: raise AssertionError(path)
                    return data['marker']
                def temp_remove(self, name):
                    if name != 'shutter.custom.lease': raise AssertionError(name)
                    data['removed'].append(name); data['marker'] = None
            camera = Camera(); camera.identity = identity
            check(camera, new, old, data)

    def test_legacy_marker_removed_only_after_same_body_owner_recovery(self):
        def check(camera, new, old, data):
            before = data['marker']
            self.assertEqual(len(before), 208)
            self.assertEqual(struct.unpack_from('<I', before, 132)[0], 3776)
            result = retire_recovered_marker(camera, new, old)
            self.assertEqual((new / 'retired-marker.before.private.bin').read_bytes(), before)
            self.assertIsNone(data['marker'])
            self.assertFalse(result['camera_memory_or_firmware_changed'])
        self.scenario(check)

    def test_persistent_marker_without_owner_recovery_is_preserved(self):
        def check(camera, new, old, data):
            with self.assertRaisesRegex(ValueError, 'owner-confirmed'): retire_recovered_marker(camera, new, old)
            self.assertFalse(data['removed'])
        self.scenario(check, recovered=False)

    def test_other_attempt_token_is_preserved(self):
        def check(camera, new, old, data):
            data['marker'] = data['marker'][:-16] + b'B' * 16
            with self.assertRaisesRegex(ValueError, 'unknown attempt'): retire_recovered_marker(camera, new, old)
            self.assertFalse(data['removed'])
        self.scenario(check, token=b'A' * 16)

    def test_matching_attempt_token_can_be_retired(self):
        def check(camera, new, old, data):
            self.assertEqual(len(data['marker']), 224)
            retire_recovered_marker(camera, new, old)
            self.assertEqual(data['removed'], ['shutter.custom.lease'])
        self.scenario(check, token=b'A' * 16)

    def test_marker_may_already_be_absent_after_cold_recovery(self):
        def check(camera, new, old, data):
            data['marker'] = None
            self.assertTrue(retire_recovered_marker(camera, new, old)['previous_marker_absent'])
            self.assertFalse(data['removed'])
        self.scenario(check)


if __name__ == '__main__': unittest.main()
