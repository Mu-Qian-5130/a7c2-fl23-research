"""Extract the primary H8 controller image for offline analysis, not installation.

The inspected 2.01 container has a 0x70-byte header followed by two separately
vectored images. Importing the entire file at base zero mislabels call targets.
No updater, camera interface, saved calibration or physical device is used.
"""
import argparse
import json
from pathlib import Path
import struct


def primary_image(container):
    raw = bytes(container)
    if len(raw) != 0x2a070 or raw[:4] != bytes.fromhex('22aa0000'):
        raise ValueError('Not the inspected Bonobo 2.01 container layout')
    primary = raw[0x70:0x14070]
    secondary = raw[0x14070:]
    if (struct.unpack_from('>I', primary)[0] != 0x100
            or struct.unpack_from('>I', secondary)[0] != 0x100
            or primary[0x100:0x106] != bytes.fromhex('7a0700014000')
            or primary[0x249a:0x24ac] != bytes.fromhex('0f8219000d1147086d2965901b5146f85470')):
        raise ValueError('Native reset/checksum instruction landmarks do not match this layout')
    return primary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('container', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    data = primary_image(args.container.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as handle:
        handle.write(data)
    print(json.dumps(dict(primary_bytes=len(data), header_bytes=0x70, logical_base=0,
                          reset=0x100, camera_io=False, installable=False)))


if __name__ == '__main__':
    main()
