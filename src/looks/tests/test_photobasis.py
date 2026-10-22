"""Native integer basis compiles to exactly the declared portable fields."""
import unittest
from looktool import photoformat, photobasis
from test_photoformat import curve


class PhotoBasisTests(unittest.TestCase):
    def setUp(self):
        self.baseline = photoformat.PhotoBank(curve(), curve(), bytes(576), bytes(64))

    def test_identity_preserves_every_native_record_byte(self):
        blob, delta = photobasis.pack(self.baseline)
        self.assertEqual(len(blob), 108)
        self.assertEqual(blob, bytes(108))
        self.assertEqual(photoformat.apply_delta(self.baseline, delta), self.baseline)

    def test_negative_tone_and_independent_planes_compile_exactly(self):
        matrices = [[16 + p, -12, 4, 0, -16, 8] for p in range(3)]
        chroma = [[(p + 1) * (j - 4) for j in range(8)] for p in range(3)]
        blob, delta = photobasis.pack(self.baseline, (-64, 128, -32), matrices, chroma)
        self.assertEqual(photobasis.compile_delta(self.baseline, delta), blob)
        result = photoformat.apply_delta(self.baseline, delta)
        for plane in range(3):
            self.assertEqual(result.matrix(plane, 0, (1024,) * 3),
                             result.matrix(plane, 15, (1024,) * 3))
        self.assertNotEqual(result.matrix(0, 0, (1024,) * 3), result.matrix(2, 0, (1024,) * 3))

    def test_unrepresentable_curve_or_matrix_is_not_silently_approximated(self):
        _, delta = photobasis.pack(self.baseline)
        delta['matrix_coefficient_delta'][1][7][0] += 1
        with self.assertRaisesRegex(ValueError, 'differ'):
            photobasis.compile_delta(self.baseline, delta)

    def test_probe_controls_must_stay_in_the_integer_native_basis(self):
        with self.assertRaisesRegex(ValueError, 'Q10'):
            photobasis.pack(self.baseline, (1025, 0, 0))
        with self.assertRaisesRegex(ValueError, 'integer'):
            photobasis.pack(self.baseline, chroma=[[.5] * 8 for _ in range(3)])
