"""Signed native-stage measurement protocol, without USB or fitting claims.

Seventeen shared-plane controls are measured in both directions. Independent
compound and mixed-table cases test the local model; call order is never used
to infer the ISP pixel order. Names/resources are deliberately untouched.
"""
import itertools
import math
from . import native

SCHEMA = 'a7c2-native-photo-measurement/1'
AMPLITUDES = (64, 128, 128) + (32,) * 14
LABELS = ('tone_gain', 'tone_toe', 'tone_shoulder') + tuple(
    'matrix_' + str(i) for i in range(6)) + tuple('chroma_' + str(i) for i in range(8))
CASES = ('fit-baseline',) + tuple('fit-probe-' + str(i) for i in range(1, 7)) + ('fit-check',)


def knobs(controls):
    if len(controls) != 17 or any(not math.isfinite(x) or abs(x) > 1 for x in controls):
        raise ValueError('Seventeen finite normalized controls in -1..1 required')
    values = [round(x * step) for x, step in zip(controls, AMPLITUDES)]
    return {'tone': values[:3], 'matrices': [values[3:9] for _ in range(3)],
            'chroma': [values[9:17] for _ in range(3)]}


def quantized(controls):
    spec = knobs(controls)
    values = spec['tone'] + spec['matrices'][0] + spec['chroma'][0]
    return [value / step for value, step in zip(values, AMPLITUDES)]


def compound(index):
    # Both signs and all three families occur in each untouched test vector.
    return [((1 if (i * (index + 1) + index) % 3 else -1) *
             (0.25 if index == 0 else 0.375)) for i in range(17)]


def rows():
    result = []
    for dimension in range(17):
        for sign, label in ((-1, 'minus'), (1, 'plus')):
            values = [0.] * 17; values[dimension] = sign
            result.append({'id': LABELS[dimension] + '_' + label,
                           'controls': values, 'table': 'zero', 'role': 'identification'})
    for i in range(2):
        result.append({'id': 'compound_' + str(i), 'controls': compound(i),
                       'table': 'zero', 'role': 'validation'})
    for table in ('ramp', 'wave'):
        for i in range(2):
            result.append({'id': table + '_compound_' + str(i), 'controls': compound(i),
                           'table': table, 'role': 'validation'})
    for table in ('ramp', 'wave'):
        result.append({'id': table + '_only', 'controls': [0.] * 17,
                       'table': table, 'role': 'validation'})
    return result


def table(name):
    if name not in ('zero', 'axis1', 'axis2', 'axis3', 'ramp', 'wave'):
        raise ValueError('Unknown measurement table')
    values = []
    for a, b, c in itertools.product(range(5), range(9), range(9)):
        x, y, z = a / 4, b / 8, c / 8
        if name == 'zero':row = (0, 0, 0)
        elif name.startswith('axis'):row = tuple(12 if i == int(name[-1])-1 else 0 for i in range(3))
        elif name == 'ramp':row = (round(32*(x-.5)), round(32*(y-.5)), round(32*(z-.5)))
        else:row = (round(12*math.sin(math.pi*y)), round(-12*math.sin(math.pi*z)),
                    round(12*math.cos(math.pi*x)))
        values.append(row)
    return native.encode(values)


def case(name):
    if name not in CASES:raise ValueError('Unknown native measurement case')
    if name == 'fit-baseline':
        return [{'id': label, 'controls': [0.] * 17, 'table': source,
                 'role': 'table_validation' if label == 'holdout' else 'table_identification'}
                for label, source in zip(('zero', 'axis1', 'axis2', 'axis3', 'ramp', 'holdout'),
                                         ('zero', 'axis1', 'axis2', 'axis3', 'ramp', 'wave'))]
    start = 36 if name == 'fit-check' else (int(name.rsplit('-', 1)[1])-1)*6
    return rows()[start:start+6]


def plan():
    return {'schema': SCHEMA, 'control_labels': LABELS, 'amplitudes': AMPLITUDES,
            'scope': 'Shared matrix/chroma planes; local measured response, not full dense format',
            'fit_control_bound': .5, 'captures_per_round': ['ST', 1, 2, 3, 4, 5, 6, 'ST'],
            'cases': [{'case': name, 'slots': case(name)} for name in CASES],
            'camera_io': False, 'pixel_stage_order_assumed': False}
