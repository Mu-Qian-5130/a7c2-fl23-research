from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inspect_native import beeplist, inventory


ROW = 'BEEP_ID_KA,0x0001,PIN,Ka.bin,0x4,0x0,AA_RT,6,1,0,0,0\n'


class InventoryTests(unittest.TestCase):
    def test_native_path_and_named_pin_preserved(self):
        base, rows = beeplist('/* comment */\n/usr/share/avsystemsound/\n' + ROW)
        self.assertEqual(base, '/usr/share/avsystemsound/')
        self.assertEqual(rows[0]['kind'], 1)
        self.assertEqual(rows[0]['beep_id'], 1)

    def test_do_not_silently_rewrite_original_ambiguous_continuous_text(self):
        text = ROW.replace(',0,0,0\n', ',1,4.00E+00,720\n')
        _, rows = beeplist('/usr/share/avsystemsound/\n' + text)
        self.assertEqual(rows[0]['length_text'], '4.00E+00')
        self.assertEqual(rows[0]['first_length_text'], '720')

    def test_duplicate_ids_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            beeplist('/sounds/\n' + ROW + ROW)

    def test_native_reserved_alias_does_not_hide_a_real_resource(self):
        reserve = ROW.replace('BEEP_ID_KA', 'BEEP_ID_RESERVE_1').replace('Ka.bin,0x4,0x0', 'None,N/A,N/A')
        _, rows = beeplist('/sounds/\n' + reserve + ROW)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['file'], 'Ka.bin')

    def test_native_kind_numbers_are_hexadecimal(self):
        _, rows = beeplist('/sounds/\n' + ROW.replace(',6,1,0,', ',6,10,0,'))
        self.assertEqual(rows[0]['kind'], 16)

    def test_empty_and_truncated_registries_rejected(self):
        for text in ['', '/sounds/\n', '/sounds/\nBEEP_ID_KA,1,PIN']:
            with self.assertRaises(ValueError):
                beeplist(text)

    def test_original_resource_bytes_match_packed_image_without_hash_admission(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'beeplist.txt').write_text('/sounds/\n' + ROW)
            (root / 'Ka.bin').write_bytes(b'1234')
            (root / 'SysSound.bin').write_bytes(b'1234')
            result = inventory(root)
            self.assertTrue(result['resource_bytes_checked'])
            self.assertFalse(result['audible_playback_tested'])
            (root / 'SysSound.bin').write_bytes(b'4321')
            with self.assertRaisesRegex(ValueError, 'packing'):
                inventory(root)

    def test_resource_names_never_escape_input_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'beeplist.txt').write_text('/sounds/\n' + ROW.replace('Ka.bin', '../Ka.bin'))
            (root / 'SysSound.bin').write_bytes(b'1234')
            with self.assertRaisesRegex(ValueError, 'single filename'):
                inventory(root)


if __name__ == '__main__':
    unittest.main()
