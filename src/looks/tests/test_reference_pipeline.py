"""Color references must not fold a spatial lens profile into a global look."""
import unittest
from looktool.compilelook import color_reference_settings

class ReferencePipelineTests(unittest.TestCase):
    def test_defaults_keep_numerical_references_lens_free(self):
        value=color_reference_settings({}, {})
        self.assertEqual(value['LensProfileEnable'],0)
        self.assertEqual(value['Exposure2012'],0)
        self.assertEqual(value['Temperature'],5000)

    def test_partial_override_keeps_shared_calibration_and_lens_free_defaults(self):
        metadata={'reference_settings':{'Temperature':5100,'Tint':8}}
        config={'reference_settings':{'Exposure2012':.1}}
        value=color_reference_settings(metadata,config)
        self.assertEqual(value['LensProfileEnable'],0)
        self.assertEqual((value['Temperature'],value['Tint'],value['Exposure2012']),(5100,8,.1))
        self.assertEqual(metadata,{'reference_settings':{'Temperature':5100,'Tint':8}})

    def test_spatial_lens_profile_is_rejected_as_a_color_fit_target(self):
        for metadata,config in [({'reference_settings':{'LensProfileEnable':1}},{}),
                                ({},{'reference_settings':{'LensProfileEnable':1}})]:
            with self.assertRaisesRegex(ValueError,'spatial lens correction'):
                color_reference_settings(metadata,config)

if __name__=='__main__':unittest.main()
