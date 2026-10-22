"""Ground-truth checks of fitting with a spatially varying measured ISP."""
import unittest
import numpy as np
from looktool import measuredfit, native


def experiment(count=1000, seed=719):
    rng = np.random.default_rng(seed)
    coordinates = rng.uniform(.02, .98, (count, 3))
    baseline = rng.uniform(.2, .75, (count, 3))
    matrix = np.array([[1., 1., 1.], [0., -.34, 1.77], [1.4, -.71, 0.]]) / 256
    # Response varies with each patch's brightness. A fixed response matrix
    # cannot reproduce this synthetic camera's measurements.
    response = np.tile(matrix, (count, 1, 1)) * (.6 + baseline[:, None, :])
    return coordinates, baseline, response


class MeasuredFitTests(unittest.TestCase):
    def test_measured_curves_predict_nonlinear_camera_without_assumed_gamma(self):
        rng = np.random.default_rng(173)
        coordinates = rng.uniform(.1, .9, (2000, 3))
        physical = rng.uniform(.07, .85, (2000, 3))
        response = np.array([[1., 1., 1.], [0., -.34, 1.77], [1.4, -.71, 0.]])/512
        powers = np.array([2.0, 2.4, 1.8])
        encode = lambda x: np.clip(x, 0, 1)**(1/powers)
        baseline = encode(physical)
        probes = encode(physical[:, None, :]+12*response[None, :, :])
        ramp = encode(physical+((coordinates-.5)*32)@response)
        model = measuredfit.fit_response_curves(baseline, probes)
        actual, local_response, valid = measuredfit.coordinates_from_curves(baseline, probes, ramp, model)
        self.assertGreater(valid.sum(), 1800)
        self.assertLess(np.median(np.abs(actual[valid]-coordinates[valid])), .015)
        # Validate with a correction not used in the probe identification.
        grid = np.array(list(__import__('itertools').product(range(5), range(9), range(9))))/[4,8,8]
        correction = lambda x: np.column_stack([8+8*x[:,0]-8*x[:,1],
                                                -4+8*x[:,1]+8*x[:,2],
                                                4-8*x[:,0]+8*x[:,2]])
        c = np.rint(correction(grid)).astype(int)
        predicted_linear = measuredfit.predict(measuredfit.linearize(baseline[valid], model),
                                                actual[valid], local_response[valid], c,clip=False)
        predicted = measuredfit.encode_rgb(predicted_linear, model)
        expected = encode(physical[valid]+correction(coordinates[valid])@response)
        self.assertLess(np.abs(predicted-expected).mean(), 1/255)
        self.assertFalse(model['gamma_assumed'])

    def test_independent_probes_recover_unknown_coordinates_and_varying_response(self):
        coordinates, base, response = experiment()
        probes = base[:, None, :] + response * 12
        ramp = base + np.einsum('ni,nij->nj', (coordinates - .5) * 32, response)
        actual, measured, usable, condition = measuredfit.measured_coordinates(base, probes, ramp)
        self.assertTrue(usable.all())
        np.testing.assert_allclose(actual, coordinates, atol=1e-12)
        np.testing.assert_allclose(measured, response, atol=1e-14)

    def test_clipped_or_singular_observations_are_excluded(self):
        coordinates, base, response = experiment(3)
        probes = base[:, None, :] + response * 12
        probes[0] = base[0]
        probes[1, 0, 0] = 1.
        ramp = base + np.einsum('ni,nij->nj', (coordinates - .5) * 32, response)
        actual, measured, usable, condition = measuredfit.measured_coordinates(base, probes, ramp)
        np.testing.assert_array_equal(usable, [False, False, True])

    def test_joint_bounded_fit_predicts_unseen_colors_with_measured_response(self):
        coordinates, base, response = experiment(1800)
        def coefficients(x):
            return np.column_stack([4 + 12*x[:, 0] - 8*x[:, 1],
                                    -5 + 8*x[:, 1] + 4*x[:, 2],
                                    6 - 8*x[:, 0] + 8*x[:, 2]])
        target = base + np.einsum('ni,nij->nj', coefficients(coordinates), response)
        raw, report = measuredfit.fit(base, target, coordinates, response,
                                     smooth=1e-9, prior=1e-12)
        c = native.decode(raw)
        x, b, r = experiment(500, seed=991)
        expected = b + np.einsum('ni,nij->nj', coefficients(x), r)
        prediction = measuredfit.predict(b, x, r, c)
        self.assertLess(np.abs(prediction-expected).mean(), .8/255)
        self.assertEqual(len(raw), 1215)
        self.assertFalse(report['actual_camera_accuracy_verified'])

    def test_diagnostics_keep_all_native_coefficients_representable(self):
        tables = measuredfit.diagnostic_tables()
        self.assertEqual(set(tables), {'zero', 'axis1', 'axis2', 'axis3', 'ramp'})
        for raw in tables.values():
            c = native.decode(raw)
            self.assertTrue(np.all((c >= -16) & (c <= 16)))


if __name__ == '__main__':
    unittest.main()
