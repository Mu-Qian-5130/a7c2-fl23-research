"""Extract a complete private FDAT file corpus without mounting or device I/O.

Requires the existing fwtool Python sources. Extracts every regular archive
file and every regular file in recognized ext2/FAT partitions, including ELF
libraries, rather than a name-based subset. Symlinks are recorded, not followed.
Firmware content and this tool's output must remain private.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
from stat import S_ISREG
import sys
import tarfile


def extract(source, output, fwtool):
    sys.path.insert(0, str(fwtool))
    from fwtool.sony import fdat
    from fwtool.archive import ext2, fat

    output.mkdir(parents=True, exist_ok=False)
    files = output / 'files'
    files.mkdir()
    rows = []

    def save(stream, logical_path, expected_size):
        # Archive paths are metadata only, never destination paths.
        base = re.sub(r'[^a-zA-Z0-9_.-]', '_', logical_path.rsplit('/', 1)[-1])[:140]
        dest = files / ('%05d-' % len(rows) + (base or 'unnamed'))
        stream.seek(0)
        head = stream.read(16)
        stream.seek(0)
        with dest.open('xb') as handle:
            shutil.copyfileobj(stream, handle, length=1024 * 1024)
        size = dest.stat().st_size
        if size != expected_size:
            raise ValueError('Extracted size differs from archive metadata: ' + logical_path)
        row = dict(source=logical_path, file=dest.relative_to(output).as_posix(), bytes=size,
                   kind='elf' if head.startswith(b'\x7fELF') else
                        'script' if head.startswith(b'#!') else 'other')
        if row['kind'] == 'elf':
            row.update(elf_class=head[4], elf_endianness=head[5])
        rows.append(row)

    with Path(source).open('rb') as decoded:
        contents = fdat.readFdat(decoded)
        with tarfile.open(fileobj=contents.firmware, mode='r:') as archive:
            for member in archive:
                if not member.isfile():
                    rows.append(dict(source=member.name, bytes=member.size, kind='archive_nonregular'))
                    continue
                stream = archive.extractfile(member)
                if not member.name.startswith('0700_part_image/') or not member.size:
                    save(stream, member.name, member.size)
                    continue
                reader = ext2.readExt2 if ext2.isExt2(stream) else fat.readFat if fat.isFat(stream) else None
                if reader is None:
                    save(stream, member.name, member.size)
                    continue
                count = len(rows)
                for entry in reader(stream):
                    logical = member.name + ':' + entry.path
                    if S_ISREG(entry.mode):
                        save(entry.contents, logical, entry.size)
                    else:
                        rows.append(dict(source=logical, bytes=entry.size, kind='filesystem_nonregular',
                                         mode=entry.mode))
                print(json.dumps(dict(partition=member.name, entries=len(rows)-count)), flush=True)
    report = dict(schema='a7c2-firmware-corpus/1', source=str(Path(source).resolve()),
                  camera_io=False, source_modified=False, complete=True, entries=rows,
                  regular_files=sum('file' in row for row in rows),
                  elf_files=sum(row['kind'] == 'elf' for row in rows))
    (output / 'inventory.private.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('complete', 'regular_files', 'elf_files')}))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fdat', type=Path, required=True)
    parser.add_argument('--fwtool', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    extract(args.fdat, args.output, args.fwtool)


if __name__ == '__main__':
    main()
