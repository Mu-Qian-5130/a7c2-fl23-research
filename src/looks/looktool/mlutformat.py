"""Offline model of one original AP user-LUT packing path.

The AP parser accepts 17/33-point cubes. Its integer packing helper samples
17 active nodes per axis and pads each parity bank to 10x10x10. Scalar values
are rounded after multiplication by8192 and clamped to unsigned16. This
describes a software payload, not proven still/live-view routing or ISP output.
There is no camera adapter or USB entry in this module.
"""
import itertools
import numpy as np

ACTIVE = 17
BANK_WIDTH = 10
PAYLOAD_BYTES = 48000


def pack_absolute_cube(values):
    """Convert standard .cube axes [blue,green,red,channel] to the AP payload.

    On this particular native path, a33-point input is sampled at every second
    node. It does not preserve33 active hardware nodes. The separate floating
    conversion path has not been reconstructed here.
    """
    values = np.asarray(values, dtype=float)
    size = values.shape[0] if values.ndim == 4 else 0
    if size not in (17, 33) or values.shape != (size, size, size, 3):
        raise ValueError('Expected a17 or33-point RGB cube, red varying fastest')
    if not np.isfinite(values).all():
        raise ValueError('Cube values must be finite')
    scalar = np.clip(np.floor(values * 8192 + .5), 0, 65535).astype('<u2')
    stride = (size - 1) // 16
    logical = scalar[::stride, ::stride, ::stride]
    planes = np.zeros((3, 8, 10, 10, 10), dtype='<u2')
    for bank, (r0, g0, b0) in enumerate(itertools.product((0, 1), repeat=3)):
        rr, gg, bb = [np.arange(start, ACTIVE, 2) for start in (r0, g0, b0)]
        block = logical[np.ix_(bb, gg, rr)].transpose(3, 2, 1, 0)
        planes[:, bank, :len(rr), :len(gg), :len(bb)] = block
    return planes.tobytes()


def unpack_active_cube(payload):
    """Read the active17-cube from the software bank payload."""
    if len(payload) != PAYLOAD_BYTES:
        raise ValueError('AP user-LUT bank payload must contain48000 bytes')
    planes = np.frombuffer(payload, dtype='<u2').reshape(3, 8, 10, 10, 10)
    result = np.zeros((17, 17, 17, 3), dtype='<u2')
    for bank, (r0, g0, b0) in enumerate(itertools.product((0, 1), repeat=3)):
        rr, gg, bb = [np.arange(start, ACTIVE, 2) for start in (r0, g0, b0)]
        result[np.ix_(bb, gg, rr)] = planes[:, bank, :len(rr), :len(gg), :len(bb)].transpose(3, 2, 1, 0)
    return result.astype(float) / 8192
