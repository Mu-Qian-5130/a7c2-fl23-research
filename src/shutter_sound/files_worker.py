"""Offline construction/decoding of the two fixed sound-file transaction.

No USB command is exposed here. Physical boot/codec validation and an explicitly
ordered files-before-hook / hook-before-files-removal controller are separate.
"""
import argparse
import json
from pathlib import Path
import struct

import candidate


def build(audio, csv, output, zig=None,*,audio_path=None,previous_csv=None,temporary_files=None):
    from looktool import nativebuild
    if not 0 < len(audio) <= 51200 or len(audio) % 64 or not 0 < len(csv) < 4096:
        raise ValueError('Sound resource size exceeds its native limits')
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    lines = []
    if previous_csv is not None:
        if len(previous_csv)>=4096 or not audio_path:raise ValueError('Invalid sound update reference')
        lines.extend(['#define SOUND_UPDATE 1','static const u8 previous_csv[]={' +
            ','.join(map(str,previous_csv or b'\0'))+'};','static const u32 previous_csv_size='+str(len(previous_csv))+';'])
    if audio_path:
        if audio_path not in ('/usr/share/avsystemsound/custom-shutter.bin','/usr/share/avsystemsound/custom-shutter-a.bin','/usr/share/avsystemsound/custom-shutter-b.bin'):
            raise ValueError('Unknown private sound filename')
        lines.append('#define SOUND_AUDIO_PATH '+json.dumps(audio_path))
    if temporary_files is not None:
        if previous_csv is None or len(temporary_files)!=2:raise ValueError('Temporary replacement requires a current update plan')
        signatures=[];sizes=[]
        for i,data in enumerate(temporary_files):
            if data is None:sizes.append(-1);signatures.append(0);continue
            if len(data)>(51200 if i==0 else 4096):raise ValueError('Existing sound temporary file is oversized')
            value=14695981039346656037
            for byte in data:value=((value^byte)*1099511628211)&((1<<64)-1)
            sizes.append(len(data));signatures.append(value)
        lines.extend(['#define REPLACE_RECORDED_TEMPORARIES 1',
            'static const i64 previous_temporary_sizes[]={'+','.join(map(str,sizes))+'};',
            'static const u64 previous_temporary_hashes[]={'+','.join(str(n)+'UL' for n in signatures)+'};'])
    for index, data in enumerate((audio, csv)):
        lines.append('static const u8 sound_' + str(index) + '[]={' + ','.join(map(str, data)) + '};')
    lines += ['static const u8 *sound_data[]={sound_0,sound_1};',
              'static const u32 sound_sizes[]={' + str(len(audio)) + ',' + str(len(csv)) + '};']
    header = root / 'files.private.h'
    header.write_text('\n'.join(lines) + '\n', encoding='ascii')
    destination = root / 'files.so'
    nativebuild.compile_worker((Path(__file__).parent / 'native/sound_files.c'), header,
                               destination, zig, fingerprints=False)
    return destination


def parse(raw):
    if len(raw) != 88:
        raise ValueError('Incomplete native sound-file transaction report')
    magic, version, mode, phase, created, *values = struct.unpack('<8s4I8q', raw)
    if (magic, version) != (b'A7SFILE1', 1) or mode not in (0, 1, 2):
        raise ValueError('Unexpected sound-file report header')
    result = dict(zip(('status', 'rollback', 'remount', 'readonly', 'cleanup',
                       'euid', 'pid', 'model_status'), values))
    result.update(mode=mode, phase=phase, created_mask=created)
    result['native_success'] = phase == 9 and not any(result[name] for name in
        ('status', 'rollback', 'remount', 'readonly', 'cleanup', 'euid', 'model_status'))
    result['firmware_or_settings_written'] = False
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--native-bin', type=Path, required=True)
    p.add_argument('--csv', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--zig')
    a = p.parse_args(argv)
    print(build(a.native_bin.read_bytes(), a.csv.read_bytes(), a.output, a.zig))


if __name__ == '__main__':
    main()
