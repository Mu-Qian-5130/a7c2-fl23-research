"""Ground-truth predictions, interpolation and native-range limitations."""
import itertools
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from looktool import coupledfit, native


def identity_response():
    knots = np.r_[np.zeros(4), .5, np.ones(4)]
    greville = [knots[i + 1:i + 4].mean() for i in range(5)]
    control = np.array(list(itertools.product(greville, repeat=3)))
    samples = np.array(list(itertools.product(np.linspace(0, 1, 6), repeat=3)))
    return coupledfit.Response(knots, control, np.full(3, 1 / 256), samples, samples)


class CoupledFitTests(unittest.TestCase):
    def test_iteration_stop_keeps_finite_seed_and_reports_nonconvergence(self):
        response=identity_response()
        at=np.array([[.2,.3,.4],[.6,.5,.4]])
        stopped=SimpleNamespace(x=np.zeros(1215),success=False,status=0,nit=100,
            message='The maximum number of iterations is exceeded.')
        with patch.object(coupledfit,'lsq_linear',return_value=stopped):
            coefficients,report=coupledfit.solve(response,at,at,smooth=1e-11)
        np.testing.assert_array_equal(coefficients,np.zeros((405,3)))
        self.assertFalse(report['seed_optimizer']['converged'])
        self.assertEqual(report['seed_optimizer']['status'],0)
        self.assertEqual(report['seed_optimizer']['iterations'],100)

    def test_nonfinite_or_numerically_failed_seed_still_reports_error(self):
        response=identity_response();at=np.array([[.2,.3,.4],[.6,.5,.4]])
        for status,x in [(-1,np.zeros(1215)),(0,np.full(1215,np.nan))]:
            with self.subTest(status=status),patch.object(coupledfit,'lsq_linear',
                    return_value=SimpleNamespace(x=x,success=False,status=status,message='numerical failure')):
                with self.assertRaisesRegex(ValueError,'seed failed'):
                    coupledfit.solve(response,at,at,smooth=1e-11)

    def test_spline_coordinates_work_with_noncontiguous_and_partial_gamut_inputs(self):
        response = identity_response()
        values = np.random.default_rng(1).uniform(.1, .4, (100, 3, 3))[:, 1, :]
        self.assertFalse(values.flags.c_contiguous)
        np.testing.assert_allclose(response.coordinates(values), values, atol=1e-12)

    def test_native_curvature_preserves_affine_fields(self):
        grid = np.array(list(itertools.product(range(5), range(9), range(9)))) / [4, 8, 8]
        coefficients = np.column_stack([3 + 8 * grid[:, 0] - 4 * grid[:, 1],
                                       12 * grid[:, 2], 6 - 8 * grid[:, 1]])
        np.testing.assert_allclose(coupledfit.native_curvature() @ coefficients.ravel(), 0,
                                   atol=1e-10)
        coefficients[:, 0] += 8 * grid[:, 1] ** 2
        self.assertGreater(np.linalg.norm(coupledfit.native_curvature() @ coefficients.ravel()), 1)

    def test_joint_field_predicts_unseen_colors_after_native_quantization(self):
        response = identity_response()
        rng = np.random.default_rng(18)
        at = rng.uniform(.08, .92, (700, 3))
        correction = lambda x: np.column_stack([4 + 8 * x[:, 0] - 8 * x[:, 1],
                                                -4 + 8 * x[:, 1], 6 - 8 * x[:, 2]])
        target = at + correction(at) / 256
        coefficients, report = coupledfit.solve(response, at, target, smooth=1e-11)
        raw = coupledfit.quantize(coefficients)
        actual = native.decode(raw)
        unseen = rng.uniform(.15, .85, (90, 3))
        prediction = response.predict_table(unseen, actual)
        self.assertLess(np.abs(prediction - (unseen + correction(unseen) / 256)).mean(), .6 / 255)
        self.assertEqual(len(raw), 1215)
        self.assertFalse(report['new_scene_camera_verified'])


if __name__ == '__main__':
    unittest.main()
