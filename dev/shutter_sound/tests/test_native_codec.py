from pathlib import Path
import math
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_codec import decode, encode_filter0


class NativeCodecHypothesisTests(unittest.TestCase):
    def test_full_supported_pcm_range_has_bounded_quantization_without_prediction(self):
        source = list(range(-32512, 32513))
        encoded = encode_filter0(source)
        decoded = decode(encoded)[:len(source)]
        self.assertEqual(len(encoded) % 64, 0)
        self.assertTrue(all(encoded[at] <= 8 for at in range(0, len(encoded), 32)))
        self.assertLessEqual(max(abs(a - b) for a, b in zip(source, decoded)), 128)

    def test_tail_padding_is_silence_and_filter0_ignores_uncertain_filter1_coefficient(self):
        source = [round(3000 * math.sin(i * .2)) for i in range(79)]
        encoded = encode_filter0(source)
        a, b = decode(encoded, predictor=0), decode(encoded, predictor=1)
        self.assertEqual(a, b)
        self.assertEqual(a[len(source):], [0] * (len(a) - len(source)))
        self.assertLessEqual(max(abs(x - y) for x, y in zip(source, a)), 16)

    def test_invalid_blocks_and_clipping_inputs_are_not_silently_encoded(self):
        for raw in (b'', bytes(31), bytes([0x29]) + bytes(31)):
            with self.assertRaises(ValueError): decode(raw)
        for source in ([], [32767], [-32768]):
            with self.assertRaises(ValueError): encode_filter0(source)


if __name__ == '__main__':
    unittest.main()
