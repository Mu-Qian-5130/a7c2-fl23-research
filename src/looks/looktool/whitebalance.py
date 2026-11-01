"""Optional C2 2.01 AWB priority override; never writes calibration properties.

The native mode selector and all downstream arithmetic stay in place. Only the
two loads of priority parameters become immediate loads. Disabling restores the
original instructions, so each body's own parameter bytes are used again.
"""

PRIORITIES = dict(white=97, ambience=-1)
WINDOWS = (
    (0x14f74e, bytes.fromhex('96f83019'), bytes.fromhex('4ff06101')),
    (0x14f758, bytes.fromhex('96f83119'), bytes.fromhex('4ff0ff01')),
)
# Native mode 1/2 branches and their independent companion-parameter loads.
CONTEXT = (
    (0x14f73c, bytes.fromhex('bbf1010fcdf81c80059307d0bbf1020f09d1')),
    (0x14f752, bytes.fromhex('96f8323906e0')),
    (0x14f75c, bytes.fromhex('96f8333901e000210023')),
)


def active(cp):
    for at, expected in CONTEXT:
        if cp[at:at + len(expected)] != expected:
            raise ValueError('A7C II 2.01 AWB priority code differs at ' + hex(at))
    states = []
    for at, original, changed in WINDOWS:
        current = cp[at:at + len(original)]
        if current not in (original, changed):
            raise ValueError('AWB priority instruction conflicts at ' + hex(at))
        states.append(current == changed)
    if len(set(states)) != 1:
        raise ValueError('Incomplete AWB priority change; preserve the previous transaction')
    return states[0]


def plan(cp, enabled):
    """Keep file size, mode routing, original properties and other code intact."""
    active(cp)
    result = bytearray(cp)
    for at, original, changed in WINDOWS:
        result[at:at + len(original)] = changed if enabled else original
    return bytes(result)
