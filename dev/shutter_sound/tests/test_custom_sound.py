from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from custom_sound import native_candidate, pcm_candidate, reconstruct, registration


def resources(root, *, alias=False, overlap=False):
    root.mkdir()
    (root / 'SysSound.bin').write_bytes(b'A' * 64 + b'B' * 64 + b'C' * 64)
    (root / 'Ka.bin').write_bytes(b'B' * 64)
    rows = ['/usr/share/avsystemsound/',
            'BEEP_ID_KA,0x1,PIN,Ka.bin,0x40,0x40,AA_RT,6,1,0,0,0']
    if alias:
        (root / 'Alias.bin').write_bytes(b'B' * 64)
        rows += ['BEEP_ID_SHA,0x2,PIN,Alias.bin,0x40,0x40,AA_RT,6,2,0,0,0']
    if overlap:
        (root / 'Overlap.bin').write_bytes(b'B' * 32 + b'C' * 32)
        rows += ['BEEP_ID_SHA,0x2,PIN,Overlap.bin,0x40,0x60,AA_RT,6,2,0,0,0']
    (root / 'beeplist.txt').write_text('\n'.join(rows) + '\n')


class CustomSoundTests(unittest.TestCase):
    def test_same_size_change_preserves_other_bank_bytes_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'sounds'
            resources(root)
            files, inverse, report = native_candidate(root, 'BEEP_ID_KA', b'D' * 64)
            self.assertEqual(files['SysSound.bin'], b'A' * 64 + b'D' * 64 + b'C' * 64)
            self.assertEqual(files['Ka.bin'], b'D' * 64)
            original = reconstruct(files, inverse)
            self.assertEqual(original['SysSound.bin'], (root / 'SysSound.bin').read_bytes())
            self.assertEqual(original['Ka.bin'], (root / 'Ka.bin').read_bytes())
            self.assertFalse(report['playback_verified'])
            self.assertFalse(report['registry_changed'])

    def test_shared_span_updates_and_restores_each_resource_alias(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'sounds'
            resources(root, alias=True)
            files, inverse, report = native_candidate(root, 'BEEP_ID_KA', b'D' * 64)
            self.assertEqual(files['Alias.bin'], b'D' * 64)
            self.assertEqual(set(report['affected_labels']), {'BEEP_ID_KA', 'BEEP_ID_SHA'})
            self.assertEqual(reconstruct(files, inverse)['Alias.bin'], b'B' * 64)

    def test_partial_overlap_and_resizing_do_not_emit_a_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'sounds'
            resources(root, overlap=True)
            with self.assertRaisesRegex(ValueError, 'Overlapping partial'):
                native_candidate(root, 'BEEP_ID_KA', b'D' * 64)
            with self.assertRaisesRegex(ValueError, 'exact existing allocation'):
                native_candidate(root, 'BEEP_ID_KA', b'D' * 128)

    def test_inverse_preserves_later_unselected_changes_without_hash_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'sounds'
            resources(root)
            files, inverse, _ = native_candidate(root, 'BEEP_ID_KA', b'D' * 64)
            changed = bytearray(files['SysSound.bin'])
            changed[0] = ord('Z')
            files['SysSound.bin'] = bytes(changed)
            self.assertEqual(reconstruct(files, inverse)['SysSound.bin'][0], ord('Z'))
            changed[64] = ord('X')
            files['SysSound.bin'] = bytes(changed)
            with self.assertRaisesRegex(ValueError, 'Selected sound bytes changed'):
                reconstruct(files, inverse)

    def test_wav_candidates_keep_rate_and_samples_and_explicitly_lack_playback_proof(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'own.wav'
            samples = struct.pack('<7h', 0, 1000, -1000, 32767, -32768, 50, -50)
            with wave.open(str(path), 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(samples)
            data, request, report = pcm_candidate(path, 2)
            self.assertEqual(data[:len(samples)], samples)
            self.assertEqual(data[len(samples):], bytes(64 - len(samples)))
            self.assertEqual(request[23], 1)
            self.assertEqual(struct.unpack_from('<I', request, 16)[0], 64)
            self.assertEqual(report['source_wav_rate_hz'], 24000)
            self.assertFalse(report['native_rate_and_pcm_layout_verified'])
            self.assertTrue(report['address_is_synthetic'])

    def test_do_not_silently_interpret_stereo_as_mono(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'stereo.wav'
            with wave.open(str(path), 'wb') as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(48000)
                w.writeframes(bytes(64))
            with self.assertRaisesRegex(ValueError, 'mono PCM16'):
                pcm_candidate(path, 2)

    def test_unregister_does_not_leave_an_active_buffer_or_format(self):
        request = registration(2, 0x10000000, 128, enabled=False, audio_format=1)
        self.assertEqual(struct.unpack_from('<4H', request), (0x200d, 0x329, 40, 0x8001))
        self.assertEqual(request[20], 2)
        self.assertEqual(request[8:20] + request[21:], bytes(31))


if __name__ == '__main__':
    unittest.main()
