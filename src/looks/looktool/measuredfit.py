"""Fit native color tables from measured ISP responses and real reference RGB.

The input coordinates and RGB response are measured with independent probe
captures. No ST-to-RAW inverse, provisional YCbCr matrix, or simplified DCP
renderer is used. A local response is still an approximation: a new physical
capture is required to verify a fitted table.
"""
import itertools
import numpy as np
from scipy.optimize import lsq_linear
from scipy.sparse import coo_matrix, eye, vstack
from . import native


def linearize(rgb, model):
    rgb = np.asarray(rgb)
    return np.stack([np.interp(rgb[:, c], model['axis'], model['inverse'][c])
                     for c in range(3)], axis=1)


def encode_rgb(rgb, model):
    rgb = np.asarray(rgb)
    return np.stack([np.interp(rgb[:, c], model['inverse'][c], model['axis'])
                     for c in range(3)], axis=1)


def fit_response_curves(baseline, probes, *, step=12, knots=65, smooth=.0001):
    """Identify monotone post-LUT curves and channel mixing from probe shifts.

    For each output channel, g(probe)-g(baseline)=step*mixing_axis.
    Solve monotone inverse-curve increments jointly with three mixing values.
    Two observed quantiles normalize an unobservable affine scale. Unobserved
    black/white endpoints must not let a noisy solution collapse its slope
    throughout the measured range.
    No DCP reference or retained look-table output enters this identification.
    """
    base = np.asarray(baseline, dtype=float)
    probes = np.asarray(probes, dtype=float)
    if base.ndim != 2 or base.shape[1] != 3 or probes.shape != (len(base), 3, 3):
        raise ValueError('Matching baseline and three independent probe captures required')
    if not np.isfinite(base).all() or not np.isfinite(probes).all() or step <= 0:
        raise ValueError('Finite probe measurements and positive step required')
    axis = np.linspace(0, 1, knots)
    cumulative = np.tril(np.ones((knots, knots-1)), k=-1)
    def interpolation_matrix(x):
        at = np.clip(x, 0, 1) * (knots-1)
        lo = np.minimum(at.astype(int), knots-2)
        f = at-lo
        p = np.zeros((len(x), knots))
        p[np.arange(len(x)), lo] = 1-f
        p[np.arange(len(x)), lo+1] = f
        return p
    inverse, response, reports, gauges = [], np.zeros((3, 3)), [], []
    for channel in range(3):
        equations, outputs = [], []
        for probe_axis in range(3):
            x, y = base[:, channel], probes[:, probe_axis, channel]
            keep = (x > .015) & (x < .985) & (y > .015) & (y < .985)
            if keep.sum() < 20:
                raise ValueError('Insufficient unclipped probe pairs')
            difference = (interpolation_matrix(y[keep])-interpolation_matrix(x[keep])) @ cumulative
            row = np.zeros((keep.sum(), knots-1+3))
            row[:, :knots-1] = difference
            row[:, knots-1+probe_axis] = -step
            equations.append(row / np.sqrt(keep.sum()))
            outputs.append(np.zeros(keep.sum()))
        observed = np.r_[base[:, channel], probes[:, :, channel].ravel()]
        observed = observed[(observed > .015) & (observed < .985)]
        low, high = np.quantile(observed, [.02, .98])
        if high-low < .15:
            raise ValueError('Insufficient observed output range for a response curve')
        normalization = np.zeros((1, knots-1+3))
        normalization[0, :knots-1] = ((interpolation_matrix(np.array([high]))-
            interpolation_matrix(np.array([low]))) @ cumulative)[0]*1000
        equations.append(normalization); outputs.append(np.array([1000.]))
        curvature = np.zeros((knots-2, knots-1+3))
        for i in range(knots-2):
            curvature[i, i:i+2] = [1, -1]
        equations.append(curvature*np.sqrt(smooth)); outputs.append(np.zeros(knots-2))
        # A tiny slope prior resolves regions with no observations without
        # imposing a gamma curve on measured regions.
        prior = np.zeros((knots-1, knots-1+3))
        prior[:, :knots-1] = np.eye(knots-1)*1e-5
        equations.append(prior); outputs.append(np.full(knots-1, 1e-5/(knots-1)))
        lower = np.r_[np.full(knots-1, 1e-7), np.full(3, -np.inf)]
        result = lsq_linear(np.vstack(equations), np.concatenate(outputs),
                            bounds=(lower, np.full(knots-1+3, np.inf)), tol=1e-10, max_iter=300)
        if not result.success:
            raise ValueError('Monotone camera-response identification did not converge')
        curve = np.r_[0., np.cumsum(result.x[:knots-1])]
        total = np.interp(high,axis,curve)-np.interp(low,axis,curve)
        curve = (curve-np.interp(low,axis,curve))/total
        inverse.append(curve.tolist())
        response[:, channel] = result.x[knots-1:]/total
        reports.append({'cost': float(result.cost), 'optimality': float(result.optimality)})
        gauges.append([float(low),float(high)])
    return {'schema': 'a7c2-measured-response/1', 'axis': axis.tolist(),
            'inverse': inverse, 'response': response.tolist(), 'fit': reports,
            'observed_affine_gauge':gauges,
            'gamma_assumed': False, 'independent_table_validation_required': True}


def coordinates_from_curves(baseline, probes, ramp, model, *, ramp_span=32):
    base = linearize(baseline, model)
    delta = linearize(ramp, model)-base
    response = np.asarray(model['response'])
    if np.linalg.cond(response) > 40:
        raise ValueError('Measured channel response is not sufficiently identifiable')
    coefficients = np.linalg.solve(response.T, delta.T).T
    coordinates = coefficients/ramp_span+.5
    valid = np.isfinite(coordinates).all(1)
    valid &= (coordinates.min(1) >= -.05) & (coordinates.max(1) <= 1.05)
    valid &= (np.asarray(baseline).min(1) > .02) & (np.asarray(baseline).max(1) < .98)
    valid &= (np.asarray(probes).min((1, 2)) > .005) & (np.asarray(probes).max((1, 2)) < .995)
    return np.clip(coordinates, 0, 1), np.tile(response, (len(base), 1, 1)), valid


def diagnostic_tables(step=12, ramp_span=32):
    if not isinstance(step, int) or not 1 <= step <= 24:
        raise ValueError('Probe step must be an integer in 1..24')
    if ramp_span != 32:
        raise ValueError('This probe protocol uses a 32-unit ramp')
    zero = np.zeros((405, 3), dtype=int)
    values = {'zero': native.encode(zero)}
    for channel, name in enumerate(('axis1', 'axis2', 'axis3')):
        table = zero.copy()
        table[:, channel] = step
        values[name] = native.encode(table)
    at = np.array(list(itertools.product(range(5), range(9), range(9)))) / [4, 8, 8]
    values['ramp'] = native.encode(np.rint((at - .5) * ramp_span).astype(int))
    return values


def measured_coordinates(baseline, probes, ramp, *, step=12, ramp_span=32, max_condition=40):
    """Return observed grid coordinates, local coefficient-to-RGB Jacobians.

    baseline/ramp are Nx3. probes is Nx3x3: patch, probe axis, RGB.
    A native coefficient row c changes RGB by c @ response, in coefficient
    units (no hidden 1/256 scaling or fixed channel mixing).
    """
    base = np.asarray(baseline, dtype=float)
    probes = np.asarray(probes, dtype=float)
    ramp = np.asarray(ramp, dtype=float)
    if base.ndim != 2 or base.shape[1] != 3 or probes.shape != (len(base), 3, 3) or ramp.shape != base.shape:
        raise ValueError('Matching Nx3 baseline/ramp and Nx3x3 probe observations required')
    if not all(np.isfinite(v).all() for v in (base, probes, ramp)) or step <= 0:
        raise ValueError('Finite capture observations and a positive probe step required')
    response = (probes - base[:, None, :]) / step
    condition = np.linalg.cond(response)
    usable = np.isfinite(condition) & (condition <= max_condition)
    usable &= (base.min(1) > .02) & (base.max(1) < .98)
    usable &= (probes.min((1, 2)) > .005) & (probes.max((1, 2)) < .995)
    coordinates = np.full_like(base, np.nan)
    if usable.any():
        coefficients = np.linalg.solve(response[usable].transpose(0, 2, 1),
                                       (ramp[usable] - base[usable])[..., None])[..., 0]
        coordinates[usable] = coefficients / ramp_span + .5
        usable &= np.isfinite(coordinates).all(1)
        usable &= (coordinates.min(1) >= -.05) & (coordinates.max(1) <= 1.05)
    return np.clip(coordinates, 0, 1), response, usable, condition


def interpolation(coordinates):
    coordinates = np.asarray(coordinates, dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[1] != 3 or not np.isfinite(coordinates).all():
        raise ValueError('Finite Nx3 measured grid coordinates required')
    if np.any((coordinates < 0) | (coordinates > 1)):
        raise ValueError('Measured grid coordinates must be in 0..1')
    at = coordinates * [4, 8, 8]
    lo = np.minimum(at.astype(int), [3, 7, 7])
    fraction = at - lo
    ids, weights = [], []
    for d in itertools.product((0, 1), repeat=3):
        ids.append((lo[:, 0] + d[0]) * 81 + (lo[:, 1] + d[1]) * 9 + lo[:, 2] + d[2])
        weights.append(np.prod(np.where(d, fraction, 1 - fraction), axis=1))
    return np.stack(ids, 1), np.stack(weights, 1)


def design(coordinates, response):
    ids, weights = interpolation(coordinates)
    response = np.asarray(response, dtype=float)
    if response.shape != (len(ids), 3, 3) or not np.isfinite(response).all():
        raise ValueError('One finite 3x3 measured response per patch required')
    rows, columns, values = [], [], []
    for node, channel, output in itertools.product(range(8), range(3), range(3)):
        rows.append(np.arange(len(ids)) * 3 + output)
        columns.append(ids[:, node] * 3 + channel)
        values.append(weights[:, node] * response[:, channel, output])
    return coo_matrix((np.concatenate(values), (np.concatenate(rows), np.concatenate(columns))),
                      shape=(3 * len(ids), 1215)).tocsr()


def smoothness():
    rows, columns, values = [], [], []
    row = 0
    for y, u, v in itertools.product(range(5), range(9), range(9)):
        i = y * 81 + u * 9 + v
        for exists, j in ((y < 4, i + 81), (u < 8, i + 9), (v < 8, i + 1)):
            if exists:
                for c in range(3):
                    rows.extend([row, row]); columns.extend([i * 3 + c, j * 3 + c])
                    values.extend([1., -1.]); row += 1
    return coo_matrix((values, (rows, columns)), shape=(row, 1215)).tocsr()


def predict(baseline, coordinates, response, coefficients, *, clip=True):
    delta = (design(coordinates, response) @ np.asarray(coefficients).reshape(-1)).reshape(-1, 3)
    result=np.asarray(baseline)+delta
    return np.clip(result,0,1) if clip else result


def solve_table(baseline, target, coordinates, response, *, smooth=.0001, prior=.000001,
                anchor=None, patch_weight=None, bounded=True):
    baseline, target = np.asarray(baseline), np.asarray(target)
    if baseline.shape != target.shape or baseline.shape != (len(coordinates), 3):
        raise ValueError('Matching measured baseline and real reference RGB required')
    if not np.isfinite(baseline).all() or not np.isfinite(target).all():
        raise ValueError('Finite image observations required')
    if smooth < 0 or prior < 0:
        raise ValueError('Regularization must be nonnegative')
    anchor = np.zeros(1215) if anchor is None else np.asarray(anchor, dtype=float).reshape(1215)
    a = design(coordinates, response)
    b = (target - baseline).reshape(-1)
    if patch_weight is not None:
        w = np.repeat(np.sqrt(np.asarray(patch_weight)), 3)
        if w.shape != b.shape or not np.isfinite(w).all():
            raise ValueError('One finite nonnegative weight per patch required')
        a = a.multiply(w[:, None]); b = b * w
    matrices, targets = [a], [b]
    if smooth:
        g = smoothness() * np.sqrt(smooth)
        matrices.append(g); targets.append(g @ anchor)
    if prior:
        g = eye(1215, format='csr') * np.sqrt(prior)
        matrices.append(g); targets.append(g @ anchor)
    result = lsq_linear(vstack(matrices, format='csr'), np.concatenate(targets),
                        bounds=(-64, 63) if bounded else (-np.inf, np.inf),
                        tol=1e-8, lsmr_tol=1e-8, max_iter=100)
    if not result.success:
        raise ValueError('Measured table fit did not converge: ' + result.message)
    coefficients = result.x.reshape(405, 3)
    return coefficients, {'status': 'MEASURED_RESPONSE_FIT',
        'patches': len(baseline), 'smoothness': smooth, 'prior': prior,
        'bounded_solution': bounded,
        'cost': float(result.cost), 'optimality': float(result.optimality),
        'response_model_requires_physical_validation': True, 'actual_camera_accuracy_verified': False}


def fit(baseline, target, coordinates, response, **kwargs):
    coefficients, report = solve_table(baseline, target, coordinates, response, **kwargs)
    coefficients = np.rint(coefficients).astype(int)
    report['bounded_coefficients'] = int(np.count_nonzero((coefficients == -64) | (coefficients == 63)))
    return native.encode(coefficients), report
