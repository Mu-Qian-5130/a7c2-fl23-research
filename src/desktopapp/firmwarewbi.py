"""Apply R5's reviewed one-byte WBI2->WBI3 recipe to the original C2 image.

This edits a regular-file copy only. It does not clear device WBI or establish
that a physical bootloader has taken its cold-start fallback.
"""
import hashlib
import os
from pathlib import Path
import stat
import zlib

IMAGE_NAME = '0700_part_image/dev/nflasha5'
PARTITION_BYTES = 300 * 1024 * 1024
CHUNK = 4 << 20
SUM_NAME = '0701_part_image_sum/part_image.sum'


def audit_packaged_wbi(archive, original_image):
    """Verify the final member differs from its C2 source at byte 3 only."""
    selected = {name: [m for m in archive.getmembers() if m.name == name]
                for name in (IMAGE_NAME, SUM_NAME)}
    if any(len(rows) != 1 or not rows[0].isfile() for rows in selected.values()):
        raise ValueError('Final package must contain one WBI image and checksum list')
    member = selected[IMAGE_NAME][0]
    if not 512 <= member.size <= PARTITION_BYTES:
        raise ValueError('Final packaged WBI extent is unsupported')
    crc = length = 0
    digest = hashlib.sha256()
    with Path(original_image).open('rb') as original, archive.extractfile(member) as source:
        if original.read(4) != b'WBI2':
            raise ValueError('Final WBI comparison requires the original C2 WBI2')
        original.seek(0)
        while before := original.read(CHUNK):
            block = source.read(len(before))
            expected = b'WBI3' + before[4:] if length == 0 else before
            if block != expected:
                raise ValueError('Final WBI differs from the R5 one-byte recipe')
            crc = zlib.crc32(block, crc)
            digest.update(block)
            length += len(block)
        if source.read(1):
            raise ValueError('Final packaged WBI has trailing bytes')
    if length != member.size:
        raise ValueError('Final packaged WBI is incomplete')
    text = archive.extractfile(selected[SUM_NAME][0]).read().decode('ascii')
    rows = [line.split(',') for line in text.splitlines()]
    rows = [row for row in rows if len(row) > 10 and row[0] == '0' and row[10] == 'dev/nflasha5']
    if len(rows) != 1 or int(rows[0][1], 16) != crc & 0xffffffff or int(rows[0][2], 16) != length:
        raise ValueError('Final package WBI CRC or length differs')
    return dict(phase='R5_ONE_BYTE_RECIPE_AND_CRC_VERIFIED', bytes=length,
                source_magic='WBI2', output_magic='WBI3', changed_offsets=[3],
                all_other_bytes_preserved=True, sha256=digest.hexdigest(),
                crc32=f'{crc & 0xffffffff:08x}', physical_cold_start_verified=False)


def invalidate_packaged_wbi(source, destination):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError('Packaged WBI must be edited in a new file')
    with source.open('rb') as original:
        info = os.fstat(original.fileno())
        if not stat.S_ISREG(info.st_mode) or not 512 <= info.st_size <= PARTITION_BYTES:
            raise ValueError('Unsupported C2 packaged WBI extent')
        if original.read(4) != b'WBI2':
            raise ValueError('Expected original WBI2 snapshot; no output created')
        original.seek(0)
        before_sha = hashlib.sha256()
        first = True
        with destination.open('xb') as target:
            while block := original.read(CHUNK):
                before_sha.update(block)
                output = b'WBI3' + block[4:] if first else block
                first = False
                if target.write(output) != len(block):
                    raise ValueError('Short packaged WBI write')
            target.flush()
            os.fsync(target.fileno())
        # R5 changes only offset 3. Independently compare the entire output
        # against the C2 source, retaining all other header and payload bytes.
        original.seek(0)
        after_sha = hashlib.sha256()
        crc = offset = 0
        with destination.open('rb') as target:
            while before := original.read(CHUNK):
                after = target.read(len(before))
                expected = b'WBI3' + before[4:] if offset == 0 else before
                if after != expected:
                    raise ValueError('Packaged WBI differs outside the R5 marker change')
                after_sha.update(after)
                crc = zlib.crc32(after, crc)
                offset += len(after)
            if offset != info.st_size or target.read(1):
                raise ValueError('Packaged WBI size changed')
        current = os.fstat(original.fileno())
        if (current.st_size, current.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
            raise ValueError('Packaged WBI source changed during preparation')
    return dict(method='R5_WBI2_TO_WBI3', source_magic='WBI2', output_magic='WBI3',
                bytes=offset, changed_offsets=[3], all_other_bytes_preserved=True,
                source_sha256=before_sha.hexdigest(),
                output_sha256=after_sha.hexdigest(), output_crc32=f'{crc & 0xffffffff:08x}',
                full_readback_verified=True, physical_cold_start_verified=False)
