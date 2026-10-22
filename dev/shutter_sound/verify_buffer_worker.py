"""Offline compiled empty-buffer worker tests with simulated native calls.

Native allocation/release outcomes here are deliberately synthetic. These
cases check cleanup, no retries and durable progress before blocking calls;
they do not prove camera allocation, available capacity or custom playback.
"""
import argparse
import json
from pathlib import Path
import struct

from buffer_trial import parse
from verify_probe import execute


def case(worker, ap, fault, payload=None, register=False, wire_format=1):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X30, UC_ARM64_REG_PC
    calls = []
    addresses = {'alloc': 0x3552790, 'release': 0x3552978}
    if payload is not None:
        addresses['transfer'] = 0x3514f54
    if register:
        addresses['register'] = 0x34ec05c
    headers = {addresses['alloc']: ap[addresses['alloc']:addresses['alloc'] + 56],
               addresses['release']: ap[addresses['release']:addresses['release'] + 48]}
    if payload is not None:
        headers[addresses['transfer']] = ap[addresses['transfer']:addresses['transfer'] + 56]
    if register:
        headers[addresses['register']] = ap[addresses['register']:addresses['register'] + 56]
    if fault == 'instruction':
        headers[addresses['alloc']] = bytes(56)

    mapped, cp_data = 0x71000000, [b'']
    def setup(cpu, base):
        cpu.mem_map(mapped, 0x10000)
        for page in {(base + at) & ~4095 for at in addresses.values()}:
            cpu.mem_map(page, 4096)

        def hook(uc, at, size, _):
            if at not in [base + value for value in addresses.values()]:
                return
            source = uc.reg_read(UC_ARM64_REG_X0)
            dest = uc.reg_read(UC_ARM64_REG_X1)
            if at == base + addresses['alloc']:
                unit, space = struct.unpack('<II', uc.mem_read(source, 8))
                assert unit == 0x70817 and space in (0, 1)
                calls.append(('alloc', space))
                failed = fault == ('cp_alloc' if space else 'ap_alloc')
                handle = (0x8123 if space else 0x123) if not failed else 0xffffffff
                length = 51200 if not failed else 0
                if fault == 'small' and space:
                    length = 32
                reply = struct.pack('<IIQIIII', unit, handle,
                    (0x809900000 if space else 0x18000000) if not failed else 0,
                    length, 0, 2 if failed else 0, 0)
                uc.mem_write(dest, reply)
            elif at == base + addresses['release']:
                handle = struct.unpack('<I', uc.mem_read(source, 4))[0]
                assert handle in (0x123, 0x8123)
                calls.append(('release', 1 if handle & 0x8000 else 0))
                uc.mem_write(dest, struct.pack('<I', 2 if fault == 'release' else 0))
            elif at == base + addresses.get('transfer', 0):
                src, soff, dst, doff, size = struct.unpack('<5I', uc.mem_read(source, 20))
                assert not soff and not doff and size == len(payload)
                assert (src, dst) in ((0x123, 0x8123), (0x8123, 0x123))
                direction = 'forward' if src == 0x123 else 'reverse'
                calls.append((direction, size))
                failed = fault == direction
                if not failed:
                    if direction == 'forward':
                        cp_data[0] = bytes(uc.mem_read(mapped, size))
                        assert cp_data[0] == payload
                    else:
                        assert bytes(uc.mem_read(mapped, size)) == bytes(size)
                        value = cp_data[0]
                        if fault == 'compare':
                            value = bytes([value[0] ^ 1]) + value[1:]
                        uc.mem_write(mapped, value)
                uc.mem_write(dest, struct.pack('<I', 2 if failed else 0))
            else:
                enabled, kind, address, size, priority, form, continuous, loop, first, _ = struct.unpack(
                    '<IIQQ6I', uc.mem_read(source, 48))
                assert kind == 3 and not (continuous or loop or first)
                mode = 'register' if enabled and address == 0x809900000 else 'restore' if enabled else 'unregister'
                calls.append((mode, kind))
                if mode == 'register':
                    assert (address, size, priority, form) == (0x809900000, len(payload), 6, wire_format)
                elif mode == 'restore':
                    assert (address, size, priority, form) == (0x405000000, 1216, 6, 0)
                else:
                    assert not any((address, size, priority, form))
                uc.mem_write(dest, struct.pack('<I', 2 if fault == mode else 0))
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_X30))

        cpu.hook_add(UC_HOOK_CODE, hook)

    def extra_syscall(uc, no, args):
        if no == 222:
            assert args == [0, len(payload) + (-len(payload) % 4096), 3, 1]
            # fd and offset are x4/x5, outside the reader harness's common args.
            from unicorn.arm64_const import UC_ARM64_REG_X5
            assert uc.reg_read(UC_ARM64_REG_X5) == 0x18000000
            return -12 if fault == 'map' else mapped
        if no == 215:
            assert args[0] == mapped
            return -5 if fault == 'unmap' else 0
        return None

    result = execute(worker, ap,
        'model' if fault == 'model' else 'none', extra_headers=headers,
        setup_native=setup, decode=parse, allow_device_mapping=payload is not None,
        extra_syscall=extra_syscall if payload is not None else None,
        extra_outputs={'/tmp/jiritsu/shutter.custom.lease': 0xc1} if register else None)
    expected = [('alloc', 0), ('alloc', 1), ('release', 1), ('release', 0)]
    if fault in ('instruction', 'model'):
        expected = []
    elif fault == 'ap_alloc':
        expected = [('alloc', 0)]
    elif fault == 'cp_alloc':
        expected = [('alloc', 0), ('alloc', 1), ('release', 0)]
    elif payload is not None and fault not in ('small', 'map'):
        expected[2:2] = [('forward', len(payload)), ('reverse', len(payload))]
        if fault == 'forward':
            expected = expected[:3]
        elif fault == 'reverse':
            expected = expected[:4]
    if register and fault in ('none', 'release', 'unregister', 'register'):
        expected.remove(('release', 1))
        position = len(expected) - 1
        registrations = [('unregister', 3)]
        if fault != 'unregister':
            registrations.append(('register', 3))
        if fault == 'register':
            registrations.append(('restore', 3))
        expected[position:position] = registrations
    if calls != expected:
        raise ValueError('Compiled worker retried or released a failed allocation: ' + repr(calls))
    success = result['temporary_pcm_registered'] if register else result['all_empty_buffers_released']
    if success != (fault == 'none'):
        raise ValueError('Compiled worker promoted an incomplete buffer trial')
    return {'fault': fault, 'native_calls': calls, 'phase': result['phase'], 'status': result['status']}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker', type=Path, required=True)
    p.add_argument('--ap', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--wav', type=Path)
    p.add_argument('--native-bin', type=Path)
    p.add_argument('--temporary-register', action='store_true')
    a = p.parse_args(argv)
    payload = None
    faults = ('none', 'ap_alloc', 'cp_alloc', 'small', 'release', 'instruction', 'model')
    if a.wav:
        from custom_sound import pcm_candidate
        payload = pcm_candidate(a.wav, 3)[0]
        faults += ('map', 'forward', 'reverse', 'compare', 'unmap')
    elif a.native_bin:
        payload = a.native_bin.read_bytes()
        faults += ('map', 'forward', 'reverse', 'compare', 'unmap')
    if a.temporary_register:
        faults += ('unregister', 'register')
    rows = [case(a.worker, a.ap.read_bytes(), fault, payload, a.temporary_register,
                 0 if a.native_bin else 1) for fault in faults]
    result = {'compiled_empty_buffer_cases': len(rows), 'camera_io': False,
              'native_allocation_release_simulated': True, 'cases': rows}
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print('Compiled empty-buffer trial:', len(rows), 'offline cases passed')


if __name__ == '__main__':
    main()
