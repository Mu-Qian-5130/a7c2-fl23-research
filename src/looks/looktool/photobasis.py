"""Exact integer basis for the first native-photo measurement backend.

This describes native record edits, not RGB pixel behavior. Tone controls
operate on raw Sony ordinates with fixed-point arithmetic. Three independent
matrix planes are uniform over the sixteen native selectors; chroma can use
all three planes. The portable format remains capable of denser parameters.
"""
import struct
from . import photoformat as photo

SCHEMA = 'a7c2-photo-q10-endpoint-uniform-matrix/1'
STRIDE = 108


def curve(record, controls):
    values = photo.gamma_values(record)
    if len(controls) != 3 or any(type(v) is not int or not -1024 <= v <= 1024 for v in controls):
        raise ValueError('Three native Q10 tone controls in -1024..1024 required')
    top = values[-1]
    if not 0 < top <= 0x3ffff:
        raise ValueError('Tone basis requires a positive native endpoint')
    gain, toe, shoulder = controls
    result = []
    for y in values:
        x = (y << 12) // top
        v = 4096 - x
        a = (y * gain) >> 10
        b = ((((y * toe) >> 10) * v) >> 12) * v >> 12
        c = ((((y * shoulder) >> 10) * x) >> 12) * v >> 12
        result.append(max(0, min(0x3ffff, y + a + b + c)))
    return photo.replace_gamma_values(record, result)


def apply(baseline, tone=(0, 0, 0), matrices=None, chroma=None):
    matrices = matrices if matrices is not None else [[0] * 6 for _ in range(3)]
    chroma = chroma if chroma is not None else [[0] * 8 for _ in range(3)]
    if len(matrices) != 3 or any(len(row) != 6 for row in matrices):
        raise ValueError('Three six-coefficient matrix planes required')
    if len(chroma) != 3 or any(len(row) != 8 for row in chroma):
        raise ValueError('Three eight-coefficient chroma planes required')
    if any(type(v) is not int or not -1024 <= v <= 1024 for row in matrices + chroma for v in row):
        raise ValueError('Measurement matrix/chroma deltas must be integer -1024..1024')
    original = struct.unpack('<288h', baseline.matrices)
    changed = [v + matrices[j // 96][j % 6] for j, v in enumerate(original)]
    if any(not -32768 <= v <= 32767 for v in changed):
        raise ValueError('Matrix basis overflows native coefficients')
    delta = [v for row in chroma for v in row]
    planes = [v + d for v, d in zip(photo.expand_chroma(baseline.chroma), delta)]
    return photo.PhotoBank(curve(baseline.regular_curve, tone), curve(baseline.still_curve, tone),
                          struct.pack('<288h', *changed), photo.encode_chroma(planes, baseline.chroma))


def pack(baseline, tone=(0, 0, 0), matrices=None, chroma=None):
    matrices = matrices if matrices is not None else [[0] * 6 for _ in range(3)]
    chroma = chroma if chroma is not None else [[0] * 8 for _ in range(3)]
    candidate = apply(baseline, tone, matrices, chroma)
    expanded = [v for row in matrices for v in photo.expand_matrix(row, (0, 0, 0))]
    blob = struct.pack('<54h', *(list(tone) + expanded + [v for row in chroma for v in row]))
    assert len(blob) == STRIDE
    delta = photo.difference(baseline, candidate)
    delta['runtime_basis'] = {'schema': SCHEMA, 'tone_q10': list(tone),
                              'matrix_planes': matrices, 'chroma_planes': chroma}
    return blob, delta


def compile_delta(baseline, delta):
    basis = delta.get('runtime_basis', {})
    if basis.get('schema') != SCHEMA:
        raise ValueError('This measurement backend requires an explicit native integer basis')
    blob, rebuilt = pack(baseline, basis['tone_q10'], basis['matrix_planes'], basis['chroma_planes'])
    if photo.apply_delta(baseline, delta) != photo.apply_delta(baseline, rebuilt):
        raise ValueError('Full photo fields differ from their declared runtime basis')
    return blob
