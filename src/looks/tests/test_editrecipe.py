import copy
import unittest
from looktool import editrecipe, lookfile, native


def recipe():
    base = dict(matrix_780f_hex=bytes(276).hex(), cc1_direct_raw=[0]*8,
                gamma_7806_y=[i*2000 for i in range(128)])
    fitted = copy.deepcopy(base)
    raw = bytearray(276);raw[25] = 64
    fitted['matrix_780f_hex'] = raw.hex()
    fitted['gamma_7806_y'][12] += 100
    fitted['cc1_direct_raw'][4] = 8
    axis = [i*512 for i in range(127)] + [65535*32]
    return editrecipe.from_fit(fitted, base, axis, 'a'*64)


class EditRecipeTests(unittest.TestCase):
    def test_exact_binary_roundtrip_and_damage_rejection(self):
        value = recipe();raw = editrecipe.pack(value)
        self.assertEqual(editrecipe.unpack(raw), value)
        for altered in (raw[:-1], raw+b'\0', raw[:80]+bytes([raw[80]^1])+raw[81:]):
            with self.assertRaises(ValueError):editrecipe.unpack(altered)

    def test_unmodeled_fields_and_noninteger_values_fail(self):
        for field in ('gamma_7806_y', 'cc1_direct_raw'):
            value = recipe();value['fitted'][field][1] = 2.5
            with self.assertRaises(ValueError):editrecipe.validate(value)
        value = recipe();value['fitted']['matrix_780f_hex'] = 'ff'+value['fitted']['matrix_780f_hex'][2:]
        with self.assertRaisesRegex(ValueError, 'common fields'):editrecipe.validate(value)

    def test_missing_endpoint_and_ambiguous_legacy_file_fail(self):
        value = recipe();value.pop('gamma_endpoint_policy')
        with self.assertRaises(ValueError):editrecipe.validate(value)
        import base64
        document = dict(schema=lookfile.SCHEMA, target=lookfile.TARGET, base='ST', name='Example',
                        table_format=lookfile.FORMAT, table_base64=base64.b64encode(bytes(1215)).decode(),
                        edit_native=recipe())
        with self.assertRaisesRegex(ValueError, 'creative-look/2'):lookfile.validate(document)
        document['schema'] = lookfile.FULL_SCHEMA
        self.assertEqual(lookfile.validate(document), bytes(1215))
        self.assertEqual(lookfile.writer_document(document), bytes(1215))
        with self.assertRaisesRegex(ValueError, 'full C2 native runtime'):lookfile.writer_table(document)


if __name__ == '__main__':unittest.main()
