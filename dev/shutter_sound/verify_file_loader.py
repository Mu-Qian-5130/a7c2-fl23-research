"""Offline original boot sound-file loader with explicit hardware stand-ins.

This executes allocation/map/read/copy/registration sequencing in original AP
code. OSAL/DMM/DMA and device calls are simulated. Stop before model publication;
no camera access, actual allocation, physical boot or playback is established.
"""
import argparse
import json
from pathlib import Path
import struct


def execute(ap, payload, mode):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
        UC_ARM64_REG_X2, UC_ARM64_REG_X30, UC_ARM64_REG_X29,
        UC_ARM64_REG_PC, UC_ARM64_REG_SP)
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(0, (len(ap) + 4095) & ~4095)
    cpu.mem_write(0, ap)
    ram, stack = 0x10000000, 0x20000000
    cpu.mem_map(ram, 0x40000)
    cpu.mem_map(stack, 0x20000)
    table, context, mapped = ram, ram + 0x4000, ram + 0x10000
    row = bytearray(176)
    row[:3] = b'\x06\x03\x07'
    struct.pack_into('<Q', row, 16, len(payload))
    path = b'/usr/share/avsystemsound/custom-shutter.bin\0'
    row[44:44 + len(path)] = path
    cpu.mem_write(table + 352, bytes(row))
    cpu.mem_write(context + 0x40, struct.pack('<I', mode))
    cpu.mem_write(context + 0x688, struct.pack('<I', 7))
    cpu.mem_write(mapped, bytes([0xa5]) * 51200)
    for reg, value in ((UC_ARM64_REG_X0, context), (UC_ARM64_REG_X1, 2),
                       (UC_ARM64_REG_X2, 0x8099e8e00),
                       (UC_ARM64_REG_SP, stack + 0x1f000)):
        cpu.reg_write(reg, value)
    calls, registrations, held = [], [], set()

    def cstring(at):
        return bytes(cpu.mem_read(at, 128)).split(b'\0', 1)[0]

    def hook(uc, at, size, _):
        if at == 0x305f750:
            uc.emu_stop()
            return
        if 0x305f020 <= at < 0x305f928:
            return
        x0, x1, x2 = (uc.reg_read(r) for r in (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2))
        result = 0
        if at in (0x2e06cc0, 0x2e068cc):
            pass  # Original global model lock/unlock are external to this trace.
        elif at == 0x3058fb4:
            result = table
        elif at == 0x165d270:
            uc.mem_write(x0, bytes([x1 & 255]) * x2)
            result = x0
        elif at == 0x165d3e0:
            uc.mem_write(x0, bytes(uc.mem_read(x1, x2)))
            result = x0
        elif at == 0x34d35e8:
            unit, remote = struct.unpack('<II', uc.mem_read(x0, 8))
            assert unit == 0x70817 and remote in (0, 1)
            handle = 0x8123 if remote else 0x123
            held.add(handle)
            uc.mem_write(x1, struct.pack('<IIQIIII', unit, handle,
                0x809900000 if remote else 0x47d200000, 51200, 0, 0, 0))
            calls.append(['allocate', remote])
        elif at == 0x34d37e8:
            pathptr, physical, length = struct.unpack('<QQI', uc.mem_read(x0, 20))
            assert cstring(pathptr) == b'/dev/mem'
            assert (physical, length) == (0x47d200000, 51200)
            uc.mem_write(x1, struct.pack('<QIIQIIII', mapped, 51200, 50, mapped, 51200, 0, 0, 0))
            calls.append(['map_owned_AP', length])
        elif at == 0x34d3868:
            name, address, limit = struct.unpack('<3Q', uc.mem_read(x0, 24))
            assert cstring(name) == path[:-1] and address == mapped and limit == 51200
            uc.mem_write(mapped, payload)
            uc.mem_write(x1, struct.pack('<IIQ', 0, 0, len(payload)))
            calls.append(['read_private_audio', len(payload)])
        elif at == 0x34cb5e8:
            source, soff, dest, doff, count = struct.unpack('<5I', uc.mem_read(x0, 20))
            assert (source, soff, dest, doff, count) == (0x123, 0, 0x8123, 0, 51200)
            assert bytes(uc.mem_read(mapped, len(payload))) == payload
            uc.mem_write(x1, bytes(4))
            calls.append(['simulated_DMA_AP_to_CP', count])
        elif at == 0x34d3828:
            address, count, fd = struct.unpack('<QII', uc.mem_read(x0, 16))
            assert (address, count, fd) == (mapped, 51200, 50)
            uc.mem_write(x1, bytes(4))
            calls.append(['unmap_AP', count])
        elif at == 0x34d36e8:
            handle = struct.unpack('<I', uc.mem_read(x0, 4))[0]
            assert handle in held
            held.remove(handle)
            uc.mem_write(x1, bytes(4))
            calls.append(['release', handle])
        elif at == 0x34c7458:
            value = struct.unpack('<IIQQ6I', uc.mem_read(x0, 48))
            enabled, kind, address, count, priority, form, continuous, loop, first, pad = value
            assert kind == 3 and not any((form, continuous, loop, first))
            if enabled:
                assert (address, count, priority) == (0x809900000, len(payload), 6)
            registrations.append({'enabled': enabled, 'kind': kind, 'address': address,
                                  'bytes': count, 'priority': priority, 'format': form})
            uc.mem_write(x1, bytes(4))
            calls.append(['registration', enabled])
        elif at == 0x34c74d8:
            uc.mem_write(x1, bytes(4))
            calls.append(['original_volume_setup'])
        elif at == 0x1797d44:
            result = 9
        elif at == 0x36804c8:
            pass
        else:
            raise ValueError('Unsimulated original file-loader call ' + hex(at))
        uc.reg_write(UC_ARM64_REG_X0, result)
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_X30))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(0x305f020, 0x40000000, count=200000)
    if cpu.reg_read(UC_ARM64_REG_PC) != 0x305f750 or held != {0x8123}:
        raise ValueError('Original loader did not retain CP and release AP at success boundary')
    frame = cpu.reg_read(UC_ARM64_REG_X29)
    target = bytes(cpu.mem_read(frame + 0x1b0, 176))
    if struct.unpack_from('<Q', target, 16)[0] != len(payload) or struct.unpack_from('<QI', target, 32) != (0x809900000, 0x8123):
        raise ValueError('Original loader descriptor lost actual file length or CP lease')
    return {'boot_mode': mode, 'calls': calls, 'registrations': registrations,
            'AP_lease_released': True, 'CP_lease_retained_in_descriptor': True,
            'registration_length_is_actual_file_length': True,
            'stopped_before_model_publication': True,
            'hardware_calls_simulated': True, 'camera_io': False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ap', type=Path, required=True)
    p.add_argument('--native-bin', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    cases = [execute(a.ap.read_bytes(), a.native_bin.read_bytes(), mode) for mode in (0, 1, 2, 3)]
    with a.output.open('x', encoding='utf-8') as f:
        json.dump({'original_file_loader_cases': len(cases), 'cases': cases,
                   'camera_boot_or_playback_verified': False}, f, indent=2)
        f.write('\n')
    print('Original native boot file-loader:', len(cases), 'offline cases passed')


if __name__ == '__main__':
    main()
