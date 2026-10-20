"""Read-only BK4 scalar fixtures. No camera access, editing or body admission.

The host format checks are independent of the original loader instructions.
Only the explicitly requested fixed-size 1/2/4/8-byte scalar records are exposed.
"""
import hashlib
import struct

FACTORY_BACKUPS = {
    '98a4981d9090797c04d3290dca3c248056ebfc6673e2d1797255c8d9076e7f74': 'CX89700_ALLLANG',
    '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47': 'CX89701_ALLLANG',
}


def scalar_segment(raw, offset, keys):
    if offset < 0 or offset + 0x100 > len(raw):
        raise ValueError('Truncated BK4 header')
    data = memoryview(raw)[offset:]
    if bytes(data[12:16]) != b'BK4\0':
        raise ValueError('Unsupported backup revision')
    subsystems, properties, start, length, checksum = struct.unpack_from('<5I', data, 16)
    size = start + length
    table = 0x100 + 6*subsystems
    if not subsystems or size > len(data) or table + 6*properties > start or start < 0x100:
        raise ValueError('Invalid BK4 layout')
    if sum(data[:32]) + sum(data[36:size]) != checksum:
        raise ValueError('Invalid BK4 checksum')
    records = {}
    for key in keys:
        subsystem, index = key >> 16, key & 65535
        if subsystem >= subsystems:
            raise ValueError('Scalar subsystem absent')
        count, first = struct.unpack_from('<HI', data, 0x100+6*subsystem)
        if first + count > properties or index >= count:
            raise ValueError('Scalar property absent')
        prop = table + 6*(first+index)
        attr, pointer = struct.unpack_from('<HI', data, prop)
        width, location = pointer >> 24, pointer & 0xffffff
        if pointer == 0xffffffff or width not in (1,2,4,8) or location < start or location+width > size:
            raise ValueError('Unsupported or out-of-range scalar')
        records[key] = dict(attr=attr, data=bytes(data[location:location+width]),
                            property_offset=prop, data_offset=location)
    return dict(offset=offset,size=size,subsystems=subsystems,property_table=table,records=records)


def factory_segments(raw, keys):
    name = FACTORY_BACKUPS.get(hashlib.sha256(raw).hexdigest())
    if name is None:
        raise ValueError('Unsupported exact factory backup; no body-data admission')
    segments = [scalar_segment(raw, offset, keys) for offset in (0,0xed000)]
    if segments[0]['size'] > 0xed000:
        raise ValueError('Overlapping factory backup segments')
    return name, segments
