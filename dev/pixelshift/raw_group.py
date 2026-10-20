"""Read Sony PixelShiftInfo and validate a four-source-image RAW group.

Metadata is necessary evidence, not proof of physical sensor movement. This
does not rewrite MakerNotes, forge a supported camera model, or merge images.
"""
import argparse
import json
from pathlib import Path
import struct


SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2,
         9: 4, 10: 8, 11: 4, 12: 8, 13: 4}


class Tiff:
    def __init__(self, path):
        self.path = Path(path)
        self.handle = self.path.open('rb')
        self.size = self.path.stat().st_size
        header = self.read(0, 8)
        if header[:2] not in (b'II', b'MM'):
            raise ValueError('Not a TIFF-based ARW')
        self.order = '<' if header[:2] == b'II' else '>'
        if struct.unpack_from(self.order + 'H', header, 2)[0] != 42:
            raise ValueError('Only classic TIFF ARW is supported')
        self.first = struct.unpack_from(self.order + 'I', header, 4)[0]

    def read(self, offset, size):
        if offset < 0 or size < 0 or offset + size > self.size:
            raise ValueError('TIFF field outside file')
        self.handle.seek(offset)
        data = self.handle.read(size)
        if len(data) != size:
            raise ValueError('Truncated TIFF')
        return data

    def directory(self, offset, *, end=None):
        if offset < 8:
            raise ValueError('Invalid IFD offset')
        count = struct.unpack(self.order + 'H', self.read(offset, 2))[0]
        length = 2 + count * 12 + 4
        if end is not None and offset + length > end:
            raise ValueError('IFD exceeds MakerNote')
        raw = self.read(offset, length)
        records = {}
        for i in range(count):
            tag, kind, number, pointer = struct.unpack_from(self.order + 'HHII', raw, 2 + i * 12)
            if tag in records or kind not in SIZES:
                raise ValueError('Duplicate TIFF tag or unsupported type')
            size = number * SIZES[kind]
            start = offset + 2 + i * 12 + 8 if size <= 4 else pointer
            if start + size > self.size:
                raise ValueError('TIFF payload outside file')
            records[tag] = (kind, number, start, size)
        return records

    def payload(self, record):
        return self.read(record[2], record[3])

    def scalar(self, record):
        kind, count, _, _ = record
        if kind not in (3, 4) or count != 1:
            raise ValueError('Expected a TIFF integer pointer')
        return struct.unpack(self.order + ('H' if kind == 3 else 'I'), self.payload(record))[0]

    def inspect(self):
        root = self.directory(self.first)
        model = self.payload(root[272]).rstrip(b'\0').decode('ascii')
        if model not in ('ILCE-7CM2', 'ILCE-7CR'):
            raise ValueError('Choose a C2 or A7CR source RAW')
        if 34665 not in root:
            raise ValueError('Missing EXIF directory')
        exif = self.directory(self.scalar(root[34665]))
        if 37500 not in exif:
            raise ValueError('Missing Sony MakerNotes')
        maker = exif[37500]
        start = maker[2]
        header = self.read(start, 12)
        # Sony ARW writes a bare IFD; JPEG-style notes may prepend 12 bytes.
        note_ifd = start + 12 if header.startswith((b'SONY DSC ', b'SONY CAM ')) else start
        notes = self.directory(note_ifd, end=start + maker[3])
        info = None
        if 0x202f in notes:
            field = notes[0x202f]
            if field[:2] != (7, 6):
                raise ValueError('PixelShiftInfo is not six undefined bytes')
            raw = self.payload(field)
            group, shot, count = struct.unpack(self.order + 'IBB', raw)
            if any(raw):
                info = {'group_id': group, 'shot': shot, 'count': count}
        # Exact EXIF payloads avoid floating-point equality for exposure settings.
        settings = {str(key): self.payload(exif[key]).hex()
                    for key in (33434, 33437, 34855) if key in exif}
        return {'file': str(self.path), 'model': model, 'pixel_shift': info,
                'exposure_fields': settings}


def inspect(path):
    image = Tiff(path)
    try:
        return image.inspect()
    finally:
        image.handle.close()


def validate(records):
    if len(records) != 4:
        raise ValueError('The first implementation accepts exactly four source RAWs')
    if len({Path(row['file']).resolve() for row in records}) != 4:
        raise ValueError('Repeated source file')
    if len({row['model'] for row in records}) != 1:
        raise ValueError('Mixed camera models')
    if any(not row['pixel_shift'] for row in records):
        raise ValueError('Ordinary burst RAWs are not a pixel-shift group')
    info = [row['pixel_shift'] for row in records]
    if any(row['count'] != 4 for row in info):
        raise ValueError('Not a four-shot source group')
    if {row['shot'] for row in info} != {1, 2, 3, 4}:
        raise ValueError('Need source shots 1, 2, 3 and 4; no duplicates/composites')
    if len({row['group_id'] for row in info}) != 1:
        raise ValueError('Mixed PixelShift group IDs')
    fields = [row['exposure_fields'] for row in records]
    if any(not all(str(k) in row for k in (33434, 33437, 34855)) for row in fields):
        raise ValueError('Missing shutter/aperture/ISO metadata')
    if any(row != fields[0] for row in fields[1:]):
        raise ValueError('Exposure metadata differs between source frames')
    return {'status': 'FOUR_SHOT_METADATA_CONTRACT_PASSED',
            'ordered_files': [row['file'] for row in sorted(records, key=lambda x: x['pixel_shift']['shot'])],
            'physical_shift_verified': False, 'composition_verified': False,
            'camera_io': False, 'raw_modified': False,
            'limits': ['Metadata can be forged; no proof of optical displacement',
                       'Same model does not establish same camera body',
                       'CFA geometry, calibration, WB, physical alignment and compatible composition remain unchecked']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw', nargs='+', type=Path)
    parser.add_argument('--validate-four', action='store_true')
    args = parser.parse_args(argv)
    rows = [inspect(p) for p in args.raw]
    result = validate(rows) if args.validate_four else {'camera_io': False, 'files': rows}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
