"""Narrow, offline-only CP sound trial and native-worker construction.

No USB imports. Physical preflight and writing are separate explicit commands
in trial.py. No donor firmware or sound resources are distributed.
"""
import argparse
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/looks'))
OFFSET = 0x3935ca
BEFORE, AFTER = bytes.fromhex('0021'), bytes.fromhex('0321')
START = 0x3935bc
CONTEXT = bytes.fromhex('dbf33afc0321002845f61c4018bf002121502044')
# The context is read from the actual stock instructions when authored below;
# this explicit literal is checked independently, not a firmware SHA gate.


def guard(ap, cp, *, installed=False):
    if ap[:4] != b'\x7fELF' or len(ap) < 0x288549c:
        raise ValueError('Expected the A7C II 2.01 AArch64 AP')
    expected = AFTER if installed else BEFORE
    if cp[OFFSET:OFFSET + 2] != expected:
        raise ValueError('Sound trial instruction conflicts; no write planned')
    # Preserve branch/query/register/store boundaries around the only edit.
    original = bytearray(cp[START:START + len(CONTEXT)])
    original[OFFSET - START:OFFSET - START + 2] = BEFORE
    if bytes(original) != CONTEXT:
        raise ValueError('CP sound-selector context differs from 2.01')
    getters = ((0x286cde8, bytes.fromhex('20af029000601391008c409100800391c0035fd6')),
               (0x2885488, bytes.fromhex('40ae02f0006013910004429100002f91c0035fd6')))
    for at, code in getters:
        if ap[at:at + 20] != code:
            raise ValueError('AP sound getter conflicts; no native access planned')


def patch(ap, cp, *, restore=False):
    guard(ap, cp, installed=restore)
    out = bytearray(cp)
    out[OFFSET:OFFSET + 2] = BEFORE if restore else AFTER
    return {'appFw.so': ap, 'cpapp-b.bin': bytes(out)}


def build(ap, cp, out, zig=None, *, restore=False):
    from looktool import nativebuild
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    target = patch(ap, cp, restore=restore)
    old, new = (AFTER, BEFORE) if restore else (BEFORE, AFTER)
    cbytes = lambda b: '{' + ','.join(map(str, b)) + '}'
    program_header = out / 'program.private.h'
    program_header.write_text('\n'.join([
        '#define BYTE_WINDOWS_ONLY 1',
        'static const u8 old_0[]=' + cbytes(old) + ';',
        'static const u8 new_0[]=' + cbytes(new) + ';',
        'static const struct Window windows[]={{' + str(OFFSET) + 'UL,2,1,old_0,new_0}};',
        'static const u32 window_count=1;',
        'static const u64 file_sizes[]={' + str(len(ap)) + 'UL,' + str(len(cp)) + 'UL};',
    ]) + '\n', encoding='ascii')
    nativebuild.compile_worker(ROOT / 'src/fl23/native/installer.c', program_header,
                               out / 'program.so', zig, fingerprints=False)
    program = {'path': str(out / 'program.so'), 'windows': 1, 'sizes': [len(ap), len(cp)]}
    lines = []
    for name, at in (('audio_getter', 0x286cde8), ('table_getter', 0x2885488)):
        lines.append('static const u8 ' + name + '[]={' + ','.join(map(str, ap[at:at + 20])) + '};')
    header = out / 'probe.private.h'
    header.write_text('\n'.join(lines) + '\n', encoding='ascii')
    nativebuild.compile_worker(Path(__file__).with_name('sound_probe.c'), header,
                               out / 'probe.so', zig, fingerprints=False)
    nativebuild.compile_worker(ROOT / 'src/fl23/native/wbi.c', header,
                               out / 'wbi.so', zig, fingerprints=False)
    plan = {'schema': 'a7c2-shutter-trial/1', 'model': 'ILCE-7CM2', 'firmware': '2.01',
            'offset': OFFSET, 'before': (AFTER if restore else BEFORE).hex(),
            'after': (BEFORE if restore else AFTER).hex(), 'bytes': 2,
            'native_program': program, 'restore': restore,
            'camera_io': False, 'physical_sound_verified': False,
            'native_registry_preflight_required': True}
    (out / 'plan.private.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    return plan, target


def parse_probe(raw):
    if len(raw) != 1256:
        raise ValueError('Incomplete sound preflight report')
    magic, version, index, status, base, audio, reserved = struct.unpack_from('<8sIIqQII', raw)
    if (magic, version, index, status, reserved) != (b'A7SND001', 1, 16, 0, 0):
        raise ValueError('Sound preflight failed: ' + repr((version, index, status)))
    entries = []
    for i in range(25):
        entry = raw[40 + i * 48:40 + (i + 1) * 48]
        entries.append({'slot': i, 'priority': entry[0], 'kind': entry[1],
                        'access': struct.unpack_from('<I', entry, 4)[0],
                        'length': struct.unpack_from('<Q', entry, 16)[0],
                        'address': struct.unpack_from('<Q', entry, 32)[0]})
    image_mode = raw[1240:1256].split(b'\0')[0].decode('ascii').strip()
    return {'model_index': index, 'audio_signals': audio, 'entries': entries,
            'image_mode': image_mode, 'camera_firmware_or_settings_written': False}


def require_registry(probe):
    # Original CP mode3 sends kind3. Stock AP run() unregisters indices0..5
    # for Audio Signals enum1 (Off); confirm kind3 belongs to that group.
    for kind in (1, 2, 3):  # counter-limited KA/SHA pair and ordinary KASHA
        selected = [e for e in probe['entries'][:6] if e['kind'] == kind]
        if not selected or any(not e['address'] or not e['length'] for e in selected):
            raise ValueError('Live shutter registration does not match kind' + str(kind) + '; stop at read-only preflight')
    if probe['image_mode'] not in ('0', '2'):
        raise ValueError('Unrecognized retained-image mode; stop at read-only preflight')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ap', required=True, type=Path)
    p.add_argument('--cp', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--zig')
    p.add_argument('--restore', action='store_true')
    a = p.parse_args()
    if a.output.exists():
        raise ValueError('Use a new private candidate directory')
    plan, target = build(a.ap.read_bytes(), a.cp.read_bytes(), a.output, a.zig, restore=a.restore)
    (a.output / 'cpapp-b.candidate.private.bin').write_bytes(target['cpapp-b.bin'])
    print(json.dumps({k: plan[k] for k in ('bytes', 'offset', 'before', 'after', 'camera_io')}))


if __name__ == '__main__':
    main()
