"""Measured local native-stage + correction-field fit. Never opens USB.

J and Q are measured from signed camera pulses in encoded output RGB. Their
composition with the correction field is an empirical local approximation,
not an assumed ISP order. Untouched compounds and mixed residual tables must
predict correctly before any joint candidate is exported. New-scene physical
verification is always separate.
"""
import numpy as np
from scipy.interpolate import RBFInterpolator
from scipy.optimize import least_squares
from scipy.sparse import csr_matrix, hstack, vstack, eye, block_diag
from . import coupledfit, measuredfit, photomeasure


class Response:
    def __init__(self, base, coordinates, zero, minus, plus, train):
        self.base = base
        coordinates, zero, minus, plus = map(np.asarray, (coordinates, zero, minus, plus))
        n = len(coordinates)
        if (coordinates.shape != (n, 3) or zero.shape != (n, 3) or
            minus.shape != (n, 17, 3) or plus.shape != minus.shape or
            not all(np.isfinite(a).all() for a in (coordinates, zero, minus, plus))):
            raise ValueError('Matching finite zero and signed seventeen-control camera measurements required')
        train = np.asarray(train, dtype=bool)
        if train.shape != (n,) or train.sum() < 40 or (~train).sum() < 25:
            raise ValueError('Separate identification and untouched color groups required')
        self.samples = coordinates[train]
        j = (plus - minus) / 2
        q = (plus + minus) / 2 - zero[:, None, :]
        self.local = RBFInterpolator(self.samples, np.stack((j[train], q[train]), axis=1),
                                     kernel='thin_plate_spline', smoothing=.001,
                                     neighbors=min(80, int(train.sum())))
        self.validation = None

    def effect(self, coordinates):
        value = self.local(np.asarray(coordinates))
        return value[:, 0], value[:, 1]

    def predict(self, coordinates, coefficients, controls):
        j, q = self.effect(coordinates)
        controls = np.asarray(controls)
        return np.clip(self.base.predict_table(coordinates, coefficients) +
                       np.einsum('ndc,d->nc', j, controls) +
                       np.einsum('ndc,d->nc', q, controls**2), 0, 1)

    def validate(self, coordinates, observations):
        """All compound/mixed captures are validation only, never training data."""
        self.validation = None
        checks = [row for row in photomeasure.rows() if row['role'] == 'validation']
        if set(observations) != {row['id'] for row in checks}:
            raise ValueError('All independent compound and mixed-table observations are required')
        reports = []
        from . import native
        for row in checks:
            actual = np.asarray(observations[row['id']])
            predicted = self.predict(coordinates, native.decode(photomeasure.table(row['table'])), row['controls'])
            if actual.shape != predicted.shape or not np.isfinite(actual).all():
                raise ValueError('Invalid independent native-stage observation')
            report = coupledfit.require_validation(predicted, actual)
            reports.append({'case': row['id'], **report})
        self.validation = {'compound_and_mixed_predictions': reports,
                           'pixel_stage_order_assumed': False,
                           'new_scene_camera_verified': False}
        return self.validation


def solve(response, coordinates, target, *, smooth, native_penalty=.001,
          max_evaluations=75):
    if response.validation is None:
        raise ValueError('Validate untouched compound and mixed-table captures before fitting')
    coordinates, target = np.asarray(coordinates), np.asarray(target)
    if coordinates.shape != target.shape or coordinates.ndim != 2 or coordinates.shape[1] != 3:
        raise ValueError('Matching coordinates and reference RGB required')
    if not np.isfinite(target).all() or not np.isfinite(coordinates).all() or np.any((target < 0)|(target > 1)):
        raise ValueError('Finite coordinates and reference RGB in 0..1 required')
    seed, _ = coupledfit.solve(response.base, coordinates, target, smooth=smooth)
    initial = np.r_[seed.ravel(), np.zeros(17)]
    j, q = response.effect(coordinates)
    ids, weights = measuredfit.interpolation(np.clip(coordinates, 0, 1))
    regularizer = block_diag((coupledfit.native_curvature()*np.sqrt(smooth),
                               eye(17)*native_penalty), format='csr')
    cache = {}

    def evaluate(vector):
        if 'vector' not in cache or not np.array_equal(cache['vector'], vector):
            corrections = (vector[:1215].reshape(405, 3)[ids]*weights[..., None]).sum(1)
            at = coordinates + corrections * response.base.scale
            controls = vector[1215:]
            rgb = (response.base.forward(at) + np.einsum('ndc,d->nc', j, controls) +
                   np.einsum('ndc,d->nc', q, controls**2))
            cache.update(vector=vector.copy(), at=at, rgb=rgb)
        return cache['at'], cache['rgb']

    def residual(vector):
        _, rgb = evaluate(vector)
        return np.r_[(np.clip(rgb, 0, 1)-target).ravel(), regularizer @ vector]

    def jacobian(vector):
        at, rgb = evaluate(vector)
        derivative = np.empty((len(at), 3, 3))
        for axis in range(3):
            step = np.eye(3)[axis]*response.base.scale[axis]*.25
            derivative[:, axis, :] = (response.base.forward(at+step)-
                                      response.base.forward(at-step))/.5
        unclipped = (rgb > 0) & (rgb < 1)
        derivative *= unclipped[:, None, :]
        native_j = (j+2*q*vector[1215:][None, :, None]).transpose(0, 2, 1)
        native_j *= unclipped[:, :, None]
        return vstack((hstack((measuredfit.design(np.clip(coordinates, 0, 1), derivative),
                                csr_matrix(native_j.reshape(-1, 17)))), regularizer), format='csr')

    lower = np.r_[np.full(1215, -64.), np.full(17, -.5)]
    upper = np.r_[np.full(1215, 63.), np.full(17, .5)]
    result = least_squares(residual, initial, jac=jacobian, bounds=(lower, upper),
                           method='trf', tr_solver='lsmr', max_nfev=max_evaluations,
                           ftol=1e-5, xtol=1e-5, gtol=1e-6)
    if not result.success:raise ValueError('Joint native-stage optimizer did not converge: '+result.message)
    coefficients = np.rint(result.x[:1215]).reshape(405, 3)
    controls = np.asarray(photomeasure.quantized(result.x[1215:]))
    # Integer-native quantization must be evaluated, not just float predictions.
    prediction = response.predict(coordinates, coefficients, controls)
    report = {'method': 'measured-local-signed-native-plus-residual-v1',
              'optimizer_converged': True, 'evaluations': result.nfev,
              'integer_prediction': coupledfit.metrics(prediction, target),
              'native_control_bound': .5, 'native_penalty': native_penalty,
              'native_controls': controls.tolist(), 'curvature_strength': smooth,
              'pixel_stage_order_assumed': False, 'physical_color_accuracy_verified': False}
    return coefficients, controls, report
