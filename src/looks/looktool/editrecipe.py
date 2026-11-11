"""Lossless C2 Edit fit interchange. This is not a CP record codec.

Keep the frozen integer fit and its input basis together. Converting these
values to camera records requires a separately checked C2 runtime backend;
the former 54-int16 measurement payload cannot represent them.
"""
import hashlib
import re
import struct
import zlib

SCHEMA = 'a7c2-edit-native-fit/1'
MAGIC = b'A7C2ED02'
HEADER = struct.Struct('<8sII32s')
PARAM_BYTES = 276 + 16 + 512
BODY_BYTES = 32 + 512 + PARAM_BYTES * 2
KEYS = {'matrix_780f_hex', 'cc1_direct_raw', 'gamma_7806_y'}


def _ints(value, count, low, high, label):
    if (type(value) is not list or len(value) != count or
            any(type(v) is not int or not low <= v <= high for v in value)):
        raise ValueError('Invalid integer ' + label)


def parameters(value):
    if type(value) is not dict or set(value) != KEYS:
        raise ValueError('Incomplete C2 Edit parameters')
    encoded = value['matrix_780f_hex']
    if type(encoded) is not str or not re.fullmatch('[0-9a-f]{552}', encoded):
        raise ValueError('Expected canonical 276-byte packed matrix record')
    _ints(value['cc1_direct_raw'], 8, -32768, 32767, 'CC1')
    _ints(value['gamma_7806_y'], 128, 0, 0x3ffff, 'Gamma')
    y = value['gamma_7806_y']
    if y[0] != 0 or any(a > b for a, b in zip(y, y[1:])):
        raise ValueError('Edit Gamma must be monotone and start at zero')
    return bytes.fromhex(encoded) + struct.pack('<8h128I', *value['cc1_direct_raw'], *y)


def _decode(raw):
    values = struct.unpack_from('<8h128I', raw, 276)
    return dict(matrix_780f_hex=raw[:276].hex(), cc1_direct_raw=list(values[:8]),
                gamma_7806_y=list(values[8:]))


def validate(value):
    expected = {'schema', 'reference_sha256', 'gamma_7805_x', 'baseline', 'fitted', 'gamma_endpoint_policy'}
    if type(value) is not dict or set(value) != expected or value['schema'] != SCHEMA:
        raise ValueError('Unsupported C2 Edit fit format')
    if value['gamma_endpoint_policy'] != 'native-point128-at-least-point127':
        raise ValueError('The unmeasured 129th native ordinate must have an explicit policy')
    if not isinstance(value['reference_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', value['reference_sha256']):
        raise ValueError('Missing C2 source context identity')
    x = value['gamma_7805_x']
    _ints(x, 128, 0, 65535 * 32, 'Gamma axis')
    if x[0] != 0 or x[-1] != 65535 * 32 or any(a >= b for a, b in zip(x, x[1:])):
        raise ValueError('C2 Gamma axis must increase from zero to 65535*32')
    before, after = (parameters(value[k]) for k in ('baseline', 'fitted'))
    # Only block13's 96 coefficients are fitted. The angle, scale and native
    # configuration fields must continue to describe the same renderer.
    if before[:24] != after[:24] or before[216:276] != after[216:276]:
        raise ValueError('Fitted matrix changes unmodeled common fields')
    return before, after


def pack(value):
    before, after = validate(value)
    body = bytes.fromhex(value['reference_sha256'])
    body += struct.pack('<128I', *value['gamma_7805_x']) + before + after
    assert len(body) == BODY_BYTES
    return HEADER.pack(MAGIC, len(body), zlib.crc32(body), hashlib.sha256(body).digest()) + body


def unpack(raw):
    if len(raw) != HEADER.size + BODY_BYTES:
        raise ValueError('C2 Edit fit payload length differs')
    magic, length, crc, digest = HEADER.unpack_from(raw)
    body = raw[HEADER.size:]
    if (magic != MAGIC or length != len(body) or zlib.crc32(body) != crc or
            hashlib.sha256(body).digest() != digest):
        raise ValueError('C2 Edit fit payload integrity differs')
    result = dict(schema=SCHEMA, reference_sha256=body[:32].hex(), gamma_endpoint_policy='native-point128-at-least-point127',
                  gamma_7805_x=list(struct.unpack_from('<128I', body, 32)),
                  baseline=_decode(body[544:544+PARAM_BYTES]),
                  fitted=_decode(body[544+PARAM_BYTES:]))
    validate(result)
    return result


def from_fit(fitted, baseline, axis, reference_sha256):
    value = dict(schema=SCHEMA, reference_sha256=reference_sha256, gamma_endpoint_policy='native-point128-at-least-point127',
                 gamma_7805_x=list(axis), baseline={k: baseline[k] for k in KEYS},
                 fitted={k: fitted[k] for k in KEYS})
    validate(value)
    return value
