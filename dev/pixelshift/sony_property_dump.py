"""Parse a saved Sony GetAllExtDevicePropInfo payload; no USB support.

Supports scalar, array and UTF-16 values, range forms and Sony's optional
secondary enumeration. Reads every declared record in order without searching
for guessed property-code anchors or skipping malformed bytes. Source behavior:
libgphoto2 camlibs/ptp2/ptp-pack.c, ptp_unpack_Sony_DPD.
"""
import argparse
import json
from pathlib import Path
import struct


PIXEL_SHIFT_PROPERTIES = {
    0xd239: 'PixelShiftShootingMode2', 0xd23a: 'PixelShiftShootingNumber',
    0xd23b: 'PixelShiftShootingInterval', 0xd23c: 'PixelShiftShootingStatus',
    0xd23d: 'PixelShiftShootingProgress', 0xd2d3: 'CancelPixelShiftShooting',
    0xd2d4: 'PixelShiftShootingMode',
}


def parse(data):
    offset = 0

    def take(size):
        nonlocal offset
        if size > len(data) - offset:
            raise ValueError(f'Truncated Sony property data at {offset:#x}: needs {size} bytes')
        result = data[offset:offset+size]
        offset += size
        return result

    def number(size):
        return int.from_bytes(take(size), 'little')

    def value(dtype):
        if dtype == 0xffff:
            count = number(1)
            text = take(2 * count).decode('utf-16-le')
            return text[:-1] if text.endswith('\0') else text
        if dtype & 0x4000:
            return [value(dtype & ~0x4000) for _ in range(number(4))]
        sizes = {1: 1, 2: 1, 3: 2, 4: 2, 5: 4, 6: 4, 7: 8, 8: 8, 9: 16, 10: 16}
        if dtype not in sizes:
            raise ValueError(f'Unsupported PTP data type {dtype:#x} at {offset:#x}')
        return int.from_bytes(take(sizes[dtype]), 'little', signed=bool(dtype & 1))

    declared, reserved = number(4), number(4)
    rows = []
    for _ in range(declared):
        start = offset
        code, dtype, get_set, enabled = number(2), number(2), number(1), number(1)
        default, current, form = value(dtype), value(dtype), number(1)
        row = dict(code=hex(code), data_type=hex(dtype), get_set_raw=get_set,
                   enabled_raw=enabled, default=default, current=current, form=form,
                   offset=start)
        if form == 1:
            row['range'] = dict(zip(('minimum', 'maximum', 'step'), (value(dtype) for _ in range(3))))
        elif form == 2:
            row['enum'] = [value(dtype) for _ in range(number(2))]
            # A following property starts at 0x5xxx/0xdxxx. Match libgphoto2's
            # secondary-list discriminator; never scan forward to another code.
            if offset+2 <= len(data) and struct.unpack_from('<H', data, offset)[0] < 0x200:
                row['secondary_enum'] = [value(dtype) for _ in range(number(2))]
        elif form != 0:
            raise ValueError(f'Unknown Sony property form {form} at {offset-1:#x}')
        row['end'] = offset
        rows.append(row)
    if offset != len(data):
        raise ValueError(f'Unconsumed bytes after {declared} properties: {len(data)-offset}')
    codes = {int(row['code'], 16) for row in rows}
    return dict(schema='a7c2-offline-sony-properties/1', declared=declared, parsed=len(rows),
                reserved=reserved, consumed_bytes=offset, total_bytes=len(data), skipped_bytes=0,
                pixel_shift_properties_present=[dict(code=hex(code), name=name)
                                               for code, name in PIXEL_SHIFT_PROPERTIES.items() if code in codes],
                properties=rows, camera_io=False, source_identity_verified=False,
                device_functionality_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = parse(args.input.read_bytes())
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    print(json.dumps({key: report[key] for key in ('declared', 'parsed', 'consumed_bytes',
                     'total_bytes', 'skipped_bytes', 'pixel_shift_properties_present', 'camera_io')}))


if __name__ == '__main__':
    main()
