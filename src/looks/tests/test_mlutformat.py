"""User-LUT active dimensions, range and parity bank associations."""
import itertools
import unittest
import numpy as np
from looktool import mlutformat


class MlutFormatTests(unittest.TestCase):
    def test_identity_absolute_cube_round_trips_at_thirteen_fractional_bits(self):
        axis = np.linspace(0, 1, 17)
        grid = np.array(list(itertools.product(axis, repeat=3)))[:, ::-1].reshape(17, 17, 17, 3)
        payload = mlutformat.pack_absolute_cube(grid)
        self.assertEqual(len(payload), 48000)
        np.testing.assert_allclose(mlutformat.unpack_active_cube(payload), grid, atol=1 / 8192)

    def test_one_vertex_targets_one_channel_one_bank(self):
        values = np.zeros((17, 17, 17, 3))
        values[3, 4, 5, 1] = .5
        payload = np.frombuffer(mlutformat.pack_absolute_cube(values), dtype='<u2').reshape(3, 8, 10, 10, 10)
        self.assertEqual(int(payload[1, 5, 2, 2, 1]), 4096)  # parity R1/G0/B1
        self.assertEqual(int(np.count_nonzero(payload)), 1)

    def test_thirty_three_input_is_decimated_on_this_integer_path(self):
        small = np.random.default_rng(2).uniform(0, 1, (17, 17, 17, 3))
        large = np.zeros((33, 33, 33, 3))
        large[::2, ::2, ::2] = small
        self.assertEqual(mlutformat.pack_absolute_cube(small), mlutformat.pack_absolute_cube(large))

    def test_absolute_values_do_not_have_signed_seven_bit_delta_range(self):
        values = np.zeros((17, 17, 17, 3))
        values[0, 0, 0] = [-1, 1, 9]
        actual = mlutformat.unpack_active_cube(mlutformat.pack_absolute_cube(values))
        np.testing.assert_allclose(actual[0, 0, 0], [0, 1, 65535 / 8192])


if __name__ == '__main__':
    unittest.main()
