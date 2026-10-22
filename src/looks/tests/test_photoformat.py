"""Native record constraints and preservation, using synthetic records only."""
import struct
import unittest
from looktool import photoformat as photo


def curve():
    record = bytearray(576)
    record[0x204:0x210] = bytes((0, 0, 1, 2, 3, 4, 5, 4, 3, 4, 4, 3))
    values = tuple(x * 2 for x in photo.gamma_coordinates(record))
    struct.pack_into('<129I', record, 0, *values)
    struct.pack_into('<I', record, 0x220, values[-1])
    record[0x228:] = bytes(range(24))
    return bytes(record)


class PhotoFormatTests(unittest.TestCase):
    def test_gamma_edit_retains_nonuniform_sampling_and_metadata(self):
        original = curve()
        values = tuple(v + j * 2 for j, v in enumerate(photo.gamma_values(original)))
        changed = photo.replace_gamma_values(original, values)
        self.assertEqual(photo.gamma_coordinates(changed), photo.gamma_coordinates(original))
        self.assertEqual(photo.gamma_values(changed), values)
        self.assertEqual(changed[0x204:0x220], original[0x204:0x220])
        self.assertEqual(changed[0x224:], original[0x224:])
        self.assertEqual(struct.unpack_from('<I', changed, 0x220)[0], values[-1])
        self.assertNotEqual(photo.gamma_coordinates(original)[64], 65535 // 2)

    def test_gamma_rejects_nonmonotone_and_wrong_endpoint_semantics(self):
        original = curve()
        values = list(photo.gamma_values(original))
        values[1] = values[2] + 1
        with self.assertRaisesRegex(ValueError, 'monotone'):
            photo.replace_gamma_values(original, values)
        modified = bytearray(original)
        struct.pack_into('<I', modified, 0x220, 0)
        with self.assertRaisesRegex(ValueError, 'endpoint'):
            photo.replace_gamma_values(modified, photo.gamma_values(original))

    def test_matrix_keeps_current_context_row_sums_and_other_selectors(self):
        coefficients = (134, -131, -118, -14, -125, 41)
        sums = (1000, 1100, 1200)
        matrix = photo.expand_matrix(coefficients, sums)
        self.assertEqual(struct.unpack('<6h', photo.encode_matrix(matrix, sums)), coefficients)
        bank = photo.PhotoBank(curve(), curve(), bytes(576), bytes(64))
        changed = bank.replace_matrix(1, 9, matrix, sums)
        self.assertEqual(changed.matrix(1, 9, sums), matrix)
        self.assertEqual(changed.matrices[:300], bank.matrices[:300])
        self.assertEqual(changed.matrices[312:], bank.matrices[312:])
        with self.assertRaisesRegex(ValueError, 'row sums'):
            photo.encode_matrix((1001, 0, 0, 0, 1100, 0, 0, 0, 1200), sums)

    def test_chroma_planes_preserve_tail_and_native_signed_wrapping(self):
        record = struct.pack('<24h', *([32760] * 8 + [20] * 8 + [-30] * 8)) + b'tail-preserved!!'
        self.assertEqual(len(record), 64)
        planes = photo.expand_chroma(record)
        self.assertEqual(planes[8], -32756)
        self.assertEqual(photo.encode_chroma(planes, record), record)
        adjusted = photo.expand_chroma(record, (10,) * 8)
        self.assertEqual(adjusted[:8], (-32766,) * 8)

    def test_secondary_chroma_uses_shared_domain_values_without_overwriting_them(self):
        unit = bytearray(8192)
        struct.pack_into('<16h', unit, 0xf00, *range(16))
        record = struct.pack('<24h', *([1] * 8 + [20] * 16)) + bytes(16)
        result = photo.secondary_chroma(record, unit, 1, (-3,) * 8)
        self.assertEqual(result, (-2,) * 8 + tuple(range(8, 16)))
        self.assertEqual(struct.unpack_from('<16h', unit, 0xf00), tuple(range(16)))

    def test_six_independent_bundles_roundtrip_without_a_firmware_image(self):
        banks = [photo.PhotoBank(curve(), curve(), bytes([j]) * 576,
                                bytes([j]) * 64) for j in range(6)]
        blob = b''.join(bank.pack() for bank in banks)
        self.assertEqual(len(blob), 10752)
        restored = [photo.PhotoBank.unpack(blob[j * photo.BANK_BYTES:(j + 1) * photo.BANK_BYTES])
                    for j in range(6)]
        self.assertEqual(restored, banks)

    def test_extract_uses_distinct_explicit_curve_matrix_and_chroma_bindings(self):
        cp = bytearray(4096)
        cp[0x100:0x340] = curve();cp[0x400:0x640] = curve()
        struct.pack_into('<I', cp, 0, 0x1100)
        struct.pack_into('<I', cp, 28 + 24, 0x1400)
        chroma, matrices = bytearray(8192), bytearray(28672)
        chroma[0x1200 + 7] = 4;matrices[0x196 + 7] = 3
        chroma[0x1250 + 4 * 64:0x1250 + 5 * 64] = bytes([1]) * 64
        matrices[0x1e0 + 3 * 768:0x1e0 + 3 * 768 + 576] = bytes([2]) * 576
        bank, report = photo.extract_bank(cp, chroma, matrices, gamma_table_va=0x1000,
            regular_row=0, still_row=1, color_parameter=7, link_base=0x1000)
        self.assertEqual(bank.regular_curve, curve())
        self.assertEqual(bank.still_curve, curve())
        self.assertEqual(bank.chroma, bytes([1]) * 64)
        self.assertEqual(bank.matrices, bytes([2]) * 576)
        self.assertEqual((report['matrix_slot'], report['chroma_slot']), (3, 4))

    def test_stage_probes_do_not_change_other_stages_or_native_metadata(self):
        bank = photo.PhotoBank(curve(), curve(), bytes(576), bytes(64))
        gamma = bank.perturb(curve_toe=.125)
        self.assertNotEqual(gamma.regular_curve, bank.regular_curve)
        self.assertEqual(gamma.matrices, bank.matrices)
        self.assertEqual(gamma.chroma, bank.chroma)
        self.assertEqual(gamma.regular_curve[0x204:], bank.regular_curve[0x204:])
        matrix = bank.perturb(matrix_delta=(0, 16, 0, 0, 0, 0))
        self.assertEqual(matrix.regular_curve, bank.regular_curve)
        self.assertEqual(matrix.chroma, bank.chroma)
        for plane in range(3):
            for selector in range(16):
                values = matrix.matrix(plane, selector, (1024, 1100, 1200))
                self.assertEqual(values, (1040, 0, -16, 0, 1100, 0, 0, 0, 1200))
        chroma = bank.perturb(chroma_delta=(16,) + (0,) * 7)
        self.assertEqual(chroma.regular_curve, bank.regular_curve)
        self.assertEqual(chroma.matrices, bank.matrices)
        self.assertEqual(chroma.chroma[16:], bank.chroma[16:])
        self.assertEqual(photo.expand_chroma(chroma.chroma)[::8], (16, 16, 16))

    def test_full_photo_delta_roundtrip_preserves_every_native_coefficient(self):
        bank = photo.PhotoBank(curve(), curve(), bytes(576), bytes(64))
        values = list(photo.gamma_values(bank.regular_curve))
        values[64] += 1
        matrices = struct.pack('<288h', *range(-144, 144))
        planes = tuple(range(-12, 12))
        changed = photo.PhotoBank(photo.replace_gamma_values(bank.regular_curve, values),
            bank.still_curve, matrices, photo.encode_chroma(planes, bank.chroma))
        delta = photo.difference(bank, changed)
        self.assertEqual(photo.apply_delta(bank, delta), changed)
        self.assertEqual(len(delta['matrix_coefficient_delta'][0]), 16)
        self.assertEqual(delta['curves']['regular']['ordinate_delta'][64], 1)
        self.assertNotIn('metadata', delta)

    def test_portable_delta_reuses_destination_body_metadata(self):
        bank = photo.PhotoBank(curve(), curve(), bytes(576), bytes(64))
        target = bank.perturb(curve_toe=.1, matrix_delta=(16,) * 6, chroma_delta=(4,) * 8)
        delta = photo.difference(bank, target)
        other_curve = bytearray(bank.still_curve);other_curve[0x238:0x23c] = b'BODY'
        other = photo.PhotoBank(bank.regular_curve, bytes(other_curve), bank.matrices, bank.chroma)
        rebuilt = photo.apply_delta(other, delta)
        self.assertEqual(rebuilt.still_curve[0x238:0x23c], b'BODY')
        self.assertEqual(photo.gamma_values(rebuilt.still_curve), photo.gamma_values(target.still_curve))


if __name__ == '__main__':
    unittest.main()
