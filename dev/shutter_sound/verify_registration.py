"""Compare authored registration templates with original AP instructions.

Unicorn runs the stock 2.01 builder and stops BEFORE its first external send.
No transport success, DSP decoder, memory allocation or playback is simulated.
"""
import argparse
import json
from pathlib import Path
import struct

from custom_sound import registration


def native_request(ap, kind, address, length, enabled, audio_format, access,
                   continuous, loop_length, first_length):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_SP
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    start, boundary = 0x34ec05c, 0x34e552c
    cpu.mem_map(start & ~4095, 4096)
    cpu.mem_write(start, ap[start:start + 0xd8])
    cpu.mem_map(boundary & ~4095, 4096)
    cpu.mem_map(0x10000000, 0x10000)
    cpu.mem_map(0x20000000, 0x4000)
    source = bytearray(48)
    struct.pack_into('<IIQQIIIII', source, 0, enabled, kind, address, length,
                     access, audio_format, continuous, loop_length, first_length)
    cpu.mem_write(0x10000000, bytes(source))
    cpu.reg_write(UC_ARM64_REG_X0, 0x10000000)
    cpu.reg_write(UC_ARM64_REG_X1, 0x10001000)
    cpu.reg_write(UC_ARM64_REG_SP, 0x20003000)
    captured = []

    def stop_at_send(uc, va, size, user):
        if va == boundary:
            if uc.reg_read(UC_ARM64_REG_X0) != 0x92840747 or uc.reg_read(UC_ARM64_REG_X2) != 40:
                raise ValueError('Original AP command ID/length differs')
            captured.append(bytes(uc.mem_read(uc.reg_read(UC_ARM64_REG_X1), 40)))
            uc.emu_stop()

    cpu.hook_add(UC_HOOK_CODE, stop_at_send)
    cpu.emu_start(start, boundary + 4, count=128)
    if len(captured) != 1:
        raise ValueError('Original AP did not reach the inspected send boundary')
    return captured[0]


def verify(ap):
    count = 0
    for kind in (1, 2, 3, 6, 15, 16):
        for enabled in (False, True):
            for audio_format in (0, 1):
                for access in (0, 1):
                    for continuous in (0, 1):
                        values = dict(kind=kind, address=0x123456780, length=0x200,
                                      enabled=enabled, audio_format=audio_format,
                                      access=access, continuous=continuous,
                                      loop_length=64, first_length=128)
                        expected = native_request(ap, **values)
                        if registration(**values) != expected:
                            raise ValueError('Authored request differs from native AP bytes')
                        count += 1
    return {'native_cases': count, 'request_bytes': 40,
            'format_field_byte': 23, 'adpcm_value': 0, 'lpcm_value': 1,
            'stopped_before_first_external_send': True,
            'transport_or_playback_success_simulated': False, 'camera_io': False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('ap', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args(argv)
    result = verify(a.ap.read_bytes())
    text = json.dumps(result, indent=2)
    if a.output:
        with a.output.open('x', encoding='utf-8') as f:
            f.write(text + '\n')
    else:
        print(text)


if __name__ == '__main__':
    main()
