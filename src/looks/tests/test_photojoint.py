"""Synthetic local-response recovery and rejection; no camera accuracy claims."""
import unittest
import numpy as np
from looktool import photojoint, photomeasure, native, photobasis, photoformat
from test_coupledfit import identity_response
from test_photoformat import curve


class PhotoJointTests(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(96)
        self.at = self.rng.uniform(.15, .65, (180, 3))
        self.base = identity_response()
        self.j = np.zeros((180, 17, 3));self.q = np.zeros_like(self.j)
        self.j[:, 0, 0] = .18 + self.at[:, 1]*.1
        self.j[:, 4, 1] = -.12
        self.j[:, 10, 2] = .08
        self.q[:, 0, 0] = .012
        self.train = np.arange(180) % 3 != 0
        self.response = photojoint.Response(self.base, self.at, self.at,
            self.at[:, None, :]-self.j+self.q, self.at[:, None, :]+self.j+self.q, self.train)

    def checks(self):
        return {row['id']: np.clip(self.base.predict_table(self.at[~self.train],
                native.decode(photomeasure.table(row['table']))) +
                np.einsum('ndc,d->nc', self.j[~self.train], row['controls']) +
                np.einsum('ndc,d->nc', self.q[~self.train], np.asarray(row['controls'])**2), 0, 1)
                for row in photomeasure.rows() if row['role'] == 'validation'}

    def test_signed_protocol_has_full_rank_and_portable_exact_parameters(self):
        rows = [row for row in photomeasure.rows() if row['role'] == 'identification']
        self.assertEqual(len(rows), 34)
        self.assertEqual(np.linalg.matrix_rank([row['controls'] for row in rows]), 17)
        baseline = photoformat.PhotoBank(curve(), curve(), bytes(576), bytes(64))
        for case in photomeasure.CASES:
            for row in photomeasure.case(case):
                blob, delta = photobasis.pack(baseline, **photomeasure.knobs(row['controls']))
                self.assertEqual(blob, photobasis.compile_delta(baseline, delta))
                self.assertEqual(len(photomeasure.table(row['table'])), 1215)

    def test_new_stages_require_compound_and_mixed_capture_validation(self):
        with self.assertRaisesRegex(ValueError, 'Validate'):
            photojoint.solve(self.response, self.at, self.at, smooth=1e-10)
        checks = self.checks()
        checks.pop('wave_compound_1')
        with self.assertRaisesRegex(ValueError, 'All independent'):
            self.response.validate(self.at[~self.train], checks)
        checks = self.checks();checks['ramp_compound_0'] += .1
        with self.assertRaisesRegex(ValueError, 'prediction'):
            self.response.validate(self.at[~self.train], checks)

    def test_signed_local_model_predicts_untouched_combinations(self):
        report = self.response.validate(self.at[~self.train], self.checks())
        self.assertEqual(len(report['compound_and_mixed_predictions']), 8)
        self.assertLess(max(r['RGB_MAE_8bit'] for r in report['compound_and_mixed_predictions']), 1e-6)
        self.assertFalse(report['pixel_stage_order_assumed'])

    def test_joint_solver_quantizes_native_controls_and_predicts_unseen_colors(self):
        self.response.validate(self.at[~self.train], self.checks())
        controls = np.zeros(17);controls[[0, 4, 10]] = [.375, -.25, .25]
        target = self.response.predict(self.at, np.zeros((405, 3)), controls)
        table, fitted, report = photojoint.solve(self.response, self.at[self.train], target[self.train],
                                                 smooth=1e-8, max_evaluations=60)
        prediction = self.response.predict(self.at[~self.train], table, fitted)
        self.assertLess(np.abs(prediction-target[~self.train]).mean()*255, .7)
        self.assertTrue(report['optimizer_converged'])
        self.assertFalse(report['physical_color_accuracy_verified'])
        self.assertLessEqual(np.abs(fitted).max(), .5)
        self.assertEqual(photomeasure.quantized(fitted), fitted.tolist())
        self.assertEqual(len(native.encode(table)), 1215)


if __name__ == '__main__':unittest.main()
