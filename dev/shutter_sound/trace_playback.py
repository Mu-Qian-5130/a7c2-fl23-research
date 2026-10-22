"""Offline CP PIN playback descriptor trace, not audio decoding or camera I/O.

Run original code from the request constructor through original registry lookup
and format normalization. External policy/device queries are synthetic; output
is a descriptor handed to a later playback layer, not proof of DSP acceptance.
"""
import argparse
import json
from pathlib import Path
import struct

from custom_sound import registration


def execute(cp, wire_format, *, policy, reserve, mode):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
        UC_ARM_REG_R3, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_SP)
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    base = 0x108000
    size = (len(cp) + 4095) & ~4095
    cpu.mem_map(base, size)
    cpu.mem_write(base, cp)
    ram, stack, stop = 0x10000000, 0x20000000, 0x50000000
    for at, count in ((ram, 0x10000), (stack, 0x10000), (stop, 4096),
                      (0x1788000, 4096), (0x1ac8000, 4096)):
        cpu.mem_map(at, count)
    table, request, output, context = 0x1230770, ram, ram + 0x1000, ram + 0x2000
    physical, translated, length = 0x8099f0000, 0x99f0000, 13376
    cpu.mem_write(table, bytes(8 + 30 * 40))
    data = registration(3, physical, length, audio_format=wire_format)[8:] + struct.pack('<II', translated, 0)
    cpu.mem_write(table + 8, data)
    cpu.mem_write(request, bytes((1, 0, 3, 0)) + struct.pack('<I', 0x12345678))
    for reg, value in ((UC_ARM_REG_R0, context), (UC_ARM_REG_R1, output),
                       (UC_ARM_REG_R2, request), (UC_ARM_REG_R3, reserve),
                       (UC_ARM_REG_SP, stack + 0xf000), (UC_ARM_REG_LR, stop | 1)):
        cpu.reg_write(reg, value)
    queries = []

    def hook(uc, at, size, _):
        if at == stop:
            uc.emu_stop()
            return
        if at == 0x61ed00:
            uc.mem_write(uc.reg_read(UC_ARM_REG_R0), bytes(uc.reg_read(UC_ARM_REG_R1)))
        elif at == 0x67f692:
            queries.append('synthetic_pin_policy')
            uc.reg_write(UC_ARM_REG_R0, policy)
        elif at == 0x66679e:
            queries.append('synthetic_mode_object')
            uc.reg_write(UC_ARM_REG_R0, ram + 0x3000)
        elif at == 0x6667ac:
            queries.append('synthetic_mode')
            uc.reg_write(UC_ARM_REG_R0, mode)
        else:
            return
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(0x67f7a0 | 1, stop + 2, count=2000)
    if cpu.reg_read(UC_ARM_REG_PC) != stop or cpu.reg_read(UC_ARM_REG_R0):
        raise ValueError('Original CP constructor did not return success')
    raw = bytes(cpu.mem_read(output, 64))
    command, flags, codec, address, buffer_size, start, end = struct.unpack_from('<7I', raw)
    if (command, flags, codec, address, buffer_size, start, end) != (
            0x10e, 0x100, wire_format, translated, length + 64, translated, translated + length):
        raise ValueError('Original CP playback descriptor differs')
    return {'wire_format': wire_format, 'synthetic_policy': policy,
            'synthetic_reserve': reserve, 'synthetic_mode': mode,
            'playback_command': command, 'codec_field': codec,
            'source_bytes': end - start, 'output_capacity_bytes': buffer_size,
            'source_pointer_not_advanced_by_64': start == address,
            'external_queries': queries}


def verify(cp):
    rows = [execute(cp, form, policy=policy, reserve=reserve, mode=mode)
            for form in (0, 1) for policy in (0, 1)
            for reserve in (0, 1) for mode in (0, 3)]
    text = b' - arg4:format  [0:ADPCM 1:LPCM]'
    if cp.find(text) < 0:
        raise ValueError('Original sound-debug format description was not found')
    return {'schema': 'a7c2-cp-pin-playback-trace/1', 'camera_io': False,
            'native_cases': len(rows), 'cases': rows,
            'original_debug_usage_names_formats_ADPCM_0_LPCM_1': True,
            'tested_constructor_preserves_format_1': True,
            'PCM_width_endianness_channel_layout_rate_verified': False,
            'actual_hardware_route_or_decoding_executed': False,
            'limits': ['Policy and device queries are synthetic',
                       'Constructor execution does not prove the capture event used this path',
                       'No DSP decoder or physical playback is emulated']}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('cp', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    result = verify(a.cp.read_bytes())
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print('Original CP PIN playback constructor:', result['native_cases'], 'offline cases passed')


if __name__ == '__main__':
    main()
