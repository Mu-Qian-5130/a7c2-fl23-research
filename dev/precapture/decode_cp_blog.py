"""Offline ULOG 4.0 BLOG decoder; never opens a camera or modifies its input.

RBUF semantics follow original target CP recorder 0x460370: oldest +0x10,
write +0x14, retained record count +0x1c. Parse count records from oldest,
not from write+free. Preserve arrival order; timestamps need not be monotonic.
Header discovery is bounded and validated, not an arbitrary magic match.
"""
import argparse
import collections
import hashlib
import json
import struct
from pathlib import Path


class FormatError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise FormatError(message)


def inventory(blob):
    require(len(blob) >= 60 and blob[:4] == b'ULOG', 'Not a complete ULOG header')
    require(blob[16:20] == b'4.0\0', 'Unsupported ULOG version')
    count = struct.unpack_from('<I', blob, 12)[0]
    size = struct.unpack_from('<I', blob, 36)[0]
    require(size == len(blob), 'BLOG extent differs from declared extent')
    require(struct.unpack_from('<I', blob, 56)[0] == size - 60, 'Invalid log extent')
    result, occupied = {}, []
    for at in range(60, len(blob) - 19, 4):
        if blob[at:at + 4] != b'SUBS':
            continue
        sid, extent = struct.unpack_from('<II', blob, at + 4)
        rings, snapshot_rings = struct.unpack_from('<hh', blob, at + 14)
        if not (0 <= snapshot_rings <= rings <= 4096 and
                20 + rings * 8 <= extent <= len(blob) - at):
            continue
        headers = []
        for index in range(rings):
            allocated, off = struct.unpack_from('<II', blob, at + 20 + index * 8)
            require(at + 20 + rings * 8 <= off and off + allocated <= at + extent,
                    'Ring outside owning subsystem')
            require(allocated >= 40 and blob[off:off + 4] == b'RBUF', 'Invalid ring header')
            words = struct.unpack_from('<10I', blob, off)
            base, capacity, free, oldest, write, read, records = words[1:8]
            require(base == off + 40 and capacity + 40 == allocated and capacity > 16,
                    'Invalid ring allocation')
            require(free < capacity and records <= (capacity - 1) // 16,
                    'Invalid free space or record count')
            require(all(base <= p <= base + capacity for p in (oldest, write, read)),
                    'Cursor outside ring')
            headers.append(dict(index=index, offset=off, base=base, capacity=capacity,
                free=free, oldest=oldest, write=write, read=read, count=records,
                snapshot=index >= rings - snapshot_rings))
        require(sid not in result, 'Duplicate subsystem identifier')
        require(not any(at < end and begin < at + extent for begin, end in occupied),
                'Overlapping subsystems')
        occupied.append((at, at + extent))
        result[sid] = dict(offset=at, size=extent, rings=headers)
    require(len(result) == count, 'Declared subsystem count does not match validated inventory')
    return result


def decode_ring(blob, sid, ring):
    base, cap = ring['base'], ring['capacity']
    def normalize(p):
        return base + (p - base) % cap
    def read(p, n):
        require(0 <= n < cap, 'Record exceeds ring')
        k = normalize(p) - base
        return blob[base + k:base + min(cap, k + n)] + blob[base:base + max(0, k + n - cap)]
    pos, used, result = normalize(ring['oldest']), 0, []
    for index in range(ring['count']):
        length, recorded_sid, recorded_ring, timestamp = struct.unpack('<IHHQ', read(pos, 16))
        expected_ring = (ring['index'] if not ring['snapshot'] else
                         ring['index'] - ring['normal_ring_count'] + 0x8000)
        require(recorded_sid == sid and recorded_ring == expected_ring,
                f'Record identity mismatch at 0x{pos:x}')
        used += 16 + length
        require(used < cap, 'Records exceed ring capacity')
        payload = read(normalize(pos + 16), length)
        record = dict(index=index, offset=pos, timestamp=timestamp, payload_hex=payload.hex())
        if length == 12:
            component, event, arg1, arg2 = struct.unpack('<HHII', payload)
            record.update(component=component, event=event, arg1=arg1, arg2=arg2)
        result.append(record)
        pos = normalize(pos + 16 + length)
    require(pos == normalize(ring['write']), 'Record walk does not end at write cursor')
    require(used == cap - 1 - ring['free'], 'Record bytes disagree with free-space counter')
    return result


def decode(blob, selections):
    subsystems = inventory(blob)
    report = dict(schema='OFFLINE_CP_BLOG/1', camera_io=False,
        blog_sha256=hashlib.sha256(blob).hexdigest(), subsystem_count=len(subsystems),
        ring_count=sum(len(s['rings']) for s in subsystems.values()), rings=[])
    for sid, index in selections:
        require(sid in subsystems and 0 <= index < len(subsystems[sid]['rings']), 'Unknown ring')
        subsystem = subsystems[sid]
        ring = dict(subsystem['rings'][index])
        ring['normal_ring_count'] = sum(not r['snapshot'] for r in subsystem['rings'])
        records = decode_ring(blob, sid, ring)
        counts = collections.Counter((r['component'], r['event']) for r in records if 'event' in r)
        report['rings'].append(dict(subsystem=sid, header=ring, records=records,
            event_counts=[dict(component=c, event=e, count=n) for (c, e), n in sorted(counts.items())],
            timestamp_backsteps=sum(a['timestamp'] > b['timestamp'] for a, b in zip(records, records[1:]))))
    report['limits'] = ['Timestamps are not converted to UTC or globally sorted',
        'Decoded events do not by themselves identify the failed physical experiment',
        'Payload12 fields are raw numbers until matched to the original logging caller',
        'This is a log parser, not a pre-capture implementation or installation permission']
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--skip-export-header', type=int, default=0)
    parser.add_argument('--ring', action='append', required=True, help='Subsystem:ring, e.g. 4:0')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(args.skip_export_header >= 0, 'Negative export offset')
    blob = args.input.read_bytes()[args.skip_export_header:]
    selections = [tuple(int(v, 0) for v in value.split(':')) for value in args.ring]
    require(all(len(s) == 2 for s in selections), 'Expected subsystem:ring')
    report = decode(blob, selections)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(f"Validated {report['subsystem_count']} subsystems, {report['ring_count']} rings; "
          f"decoded {sum(len(r['records']) for r in report['rings'])} records. No camera I/O.")


if __name__ == '__main__':
    main()
