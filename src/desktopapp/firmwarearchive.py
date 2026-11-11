"""R5-style same-length TAR payload replacement, preserving all other bytes."""
import os
from pathlib import Path
import shutil
import tarfile

CHUNK = 4 << 20


def replace_members(source, replacements, destination):
    """Copy a seekable TAR and replace existing regular-file data extents only."""
    source.seek(0)
    with tarfile.open(fileobj=source, mode='r:') as archive:
        members = archive.getmembers()
    by = {m.name: m for m in members}
    if len(by) != len(members):
        raise ValueError('Original TAR contains duplicate members')
    ranges = []
    for name, value in replacements.items():
        member = by.get(name)
        path = Path(value)
        if member is None or not member.isfile():
            raise ValueError('Replacement must name an existing regular TAR member: ' + name)
        if path.stat().st_size != member.size:
            raise ValueError('R5-style TAR replacement must retain member length: ' + name)
        ranges.append((member.offset_data, member.offset_data + member.size, name, path))
    ranges.sort()
    if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])):
        raise ValueError('Replacement TAR data extents overlap')
    destination = Path(destination)
    source.seek(0)
    with destination.open('xb') as target:
        shutil.copyfileobj(source, target, CHUNK)
        total = target.tell()
        for start, end, name, path in ranges:
            if end > total:
                raise ValueError('Original TAR member exceeds archive extent: ' + name)
            target.seek(start)
            with path.open('rb') as payload:
                shutil.copyfileobj(payload, target, CHUNK)
        target.flush()
        os.fsync(target.fileno())
    # Compare all bytes, including headers, per-member padding, and the trailer.
    cursor = 0
    with destination.open('rb') as result:
        for start, end, name, path in ranges + [(total, total, '', None)]:
            source.seek(cursor)
            result.seek(cursor)
            remaining = start - cursor
            while remaining:
                block = source.read(min(CHUNK, remaining))
                if not block or result.read(len(block)) != block:
                    raise ValueError('TAR bytes changed outside replacement data')
                remaining -= len(block)
            if path is not None:
                result.seek(start)
                with path.open('rb') as expected:
                    remaining = end - start
                    while remaining:
                        block = expected.read(min(CHUNK, remaining))
                        if not block or result.read(len(block)) != block:
                            raise ValueError('TAR replacement data differs: ' + name)
                        remaining -= len(block)
                    if expected.read(1):
                        raise ValueError('TAR replacement grew during preparation: ' + name)
            cursor = end
        if result.read(1):
            raise ValueError('TAR output length changed')
    return dict(method='R5_SAME_LENGTH_MEMBER_OVERLAY', bytes=total,
                original_headers_padding_trailer_preserved=True,
                unchanged_ranges_byte_compared=True,
                changed_members=[row[2] for row in ranges])
