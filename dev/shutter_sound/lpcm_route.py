"""Offline kind-3 LPCM registration experiment; no device installation.

Repack the existing native AP message-builder block in its original 68 bytes.
This avoids a trampoline or new storage area. It is NOT sufficient to import
audio: the original kind-3 buffer is ADPCM and must never be reinterpreted.
An owned, persistent PCM buffer, its rate/layout, loading and inverse still
need independent implementation and physical validation.
"""
import argparse
import json
from pathlib import Path

from verify_registration import native_request

OFFSET = 0x34ec0ac
BEFORE = bytes.fromhex(
    'a133013922008052010440f9a23b0139a12300f9010840f9a14b00b9'
    '011840b9a1370139012040b9a1430139012440b9a15700b9012840b9'
    '001c40b9a15b00b9a03f0139')
AFTER = bytes.fromhex(
    'a1330139241c00539f0c007122008052a23b0139018c40a9a12300f9'
    'a34b00b9010c43294300831aa1370139a33f0139012040b9a1430139'
    '01804429a15700b9a05b00b9')
ASSEMBLY = '''strb w1,[x29,#0x4c]
uxtb w4,w1
cmp w4,#3
mov w2,#1
strb w2,[x29,#0x4e]
ldp x1,x3,[x0,#8]
str x1,[x29,#0x40]
str w3,[x29,#0x48]
ldp w1,w3,[x0,#0x18]
csel w3,w2,w3,eq
strb w1,[x29,#0x4d]
strb w3,[x29,#0x4f]
ldr w1,[x0,#0x20]
strb w1,[x29,#0x50]
ldp w1,w0,[x0,#0x24]
str w1,[x29,#0x54]
str w0,[x29,#0x58]'''


def patch(ap, *, restore=False):
    old, new = (AFTER, BEFORE) if restore else (BEFORE, AFTER)
    if len(old) != 68 or len(new) != 68 or ap[OFFSET:OFFSET + 68] != old:
        raise ValueError('Kind-3 registration block conflicts')
    out = bytearray(ap)
    out[OFFSET:OFFSET + 68] = new
    return bytes(out)


def verify(ap):
    from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN
    if bytes(Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN).asm(ASSEMBLY, OFFSET)[0]) != AFTER:
        raise ValueError('LPCM route instruction encoding differs')
    trial = patch(ap)
    if patch(trial, restore=True) != ap:
        raise ValueError('Registration inverse differs')
    count = 0
    for kind in (1, 2, 3, 4, 8, 14, 15, 16, 0x103, 0xffffffff):
        for enabled in (False, True):
            for audio_format in (0, 1):
                for priority in (1, 6, 10):
                    for continuous in (0, 1):
                        for address in (0x10000000, 0x8099e9340):
                            values = dict(kind=kind, enabled=enabled, audio_format=audio_format,
                                priority=priority, continuous=continuous, address=address,
                                length=0x3440, loop_length=1824, first_length=1248)
                            original = native_request(ap, **values)
                            expected = bytearray(original)
                            if enabled and kind & 255 == 3:
                                expected[23] = 1
                            actual = native_request(trial, **values)
                            if actual != expected:
                                raise ValueError('Native request changed beyond selected kind-3 format')
                            count += 1
    return {'native_cases': count, 'original_and_trial_executions': count * 2,
            'single_existing_block_bytes': 68, 'trampoline_or_allocation': False,
            'only_selected_message_format_changes': True, 'inverse_byte_equal': True,
            'stopped_before_external_send': True, 'camera_io': False,
            'audio_buffer_supplied': False, 'sample_rate_or_layout_verified': False,
            'installable': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ap', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    ap = a.ap.read_bytes()
    report = verify(ap)
    report['window'] = dict(offset=hex(OFFSET), before_hex=BEFORE.hex(), after_hex=AFTER.hex())
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2); f.write('\n')
    print({k: report[k] for k in ('native_cases', 'single_existing_block_bytes', 'camera_io', 'installable')})


if __name__ == '__main__': main()
