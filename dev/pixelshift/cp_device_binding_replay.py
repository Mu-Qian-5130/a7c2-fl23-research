"""Execute native device-descriptor binding into the DevEdge input consumer.

The original per-channel binder and its complete helper generate getter-bank
handles from device descriptors. Original bank assignment/context binding and
the register-to-snapshot path then execute in the same RAM. Device descriptors,
their addresses/register responses and invocation order are fixtures. This is
neither backend/device construction nor actual sensor feedback, settling or
exposure. The separate hard-coded setter-address mapper is NOT attached here.
No host assigns output handles or native API success.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_context_source_replay import initialize
from cp_input_source_replay import profile as source_profile, replay as source_replay


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, s = source_profile(directory)
    delta = -0x218 if s['select'] != 0xb3bff2 else 0
    p = dict(bind=0x79b196+delta, edge=0x79b5d6+delta)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    code = list(md.disasm(data[p['bind']-0x108000:p['bind']-0x108000+0x160], p['bind']))
    branch = [int(row.op_str.lstrip('#'), 0) for row in code if row.mnemonic == 'b.w']
    if branch != [p['edge']]:
        raise ValueError('Original descriptor binder no longer tail-calls its edge helper')
    return data, p


def bind_devices(cpu, directory, bank, *, register_bases, present, descriptors_present):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, p = profile(directory)
    stack, finish = 0x3001f000, 0x3001e000
    devices, edges = (0x30018000, 0x30018100), (0x30018200, 0x30018300)
    # Other fields are absent fixtures, so the binder's inspected optional
    # branches do not stand in for device discovery or virtual API success.
    for n, (device, edge, base) in enumerate(zip(devices, edges, register_bases)):
        cpu.mem_write(device, bytes(0xe4))
        cpu.mem_write(edge, b'\x5a'*32)
        cpu.mem_write(edge+4, struct.pack('<I', base))
        cpu.mem_write(device+0x38, struct.pack('<I', edge if present[n] else 0))
    inputs = [(at, bytes(cpu.mem_read(at, length))) for at, length in
              [(at, 0xe4) for at in devices]+[(at, 32) for at in edges]]
    original = bytes(cpu.mem_read(bank, 0x39c))
    expected = bytearray(original)
    expected_writes = []
    for channel, base in enumerate(register_bases):
        if not descriptors_present[channel] or not present[channel]:
            continue
        struct.pack_into('<I', expected, 0x368+channel*4, edges[channel]+0x20)
        expected_writes.append((0x368+channel*4, edges[channel]+0x20))
        for offset in range(0x64+channel*8, 0x135+channel*8, 0x10):
            struct.pack_into('<I', expected, offset, base)
            expected_writes.append((offset, base))
    # Missing sources leave existing handles untouched. Start these two
    # consumed handles at zero before the native calls, never clear afterward.
    for channel in range(2):
        offset = 0x84+channel*8
        cpu.mem_write(bank+offset, bytes(4))
        if not descriptors_present[channel] or not present[channel]:
            expected[offset:offset+4] = bytes(4)
    cpu.mem_write(bank-4, b'\x6b'*4)
    cpu.mem_write(bank+0x39c, b'\x6b'*4)
    writes = []
    protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
    saved = [0x55660000+n for n in range(8)]

    def code_hook(uc, at, length, unused):
        if not any(lo <= at and at+length <= lo+n for lo, n in
                   ((p['bind'], 0x160), (p['edge'], 0x3a))):
            raise ValueError('Native device binder entered an unresolved dependency: '+hex(at))

    def write_hook(uc, access, at, length, value, unused):
        if stack-4096 <= at and at+length <= stack:
            return
        if not bank <= at or at+length > bank+0x39c or length != 4:
            raise ValueError('Native device binder changed unrelated state: '+hex(at))
        writes.append((at-bank, value))

    ch = cpu.hook_add(UC_HOOK_CODE, code_hook)
    wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        for channel, device in enumerate(devices):
            for reg, value in zip(protected, saved):
                cpu.reg_write(reg, value)
            cpu.reg_write(arm.UC_ARM_REG_R0, bank)
            cpu.reg_write(arm.UC_ARM_REG_R1, device if descriptors_present[channel] else 0)
            cpu.reg_write(arm.UC_ARM_REG_R2, channel)
            cpu.reg_write(arm.UC_ARM_REG_SP, stack)
            cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
            cpu.emu_start(p['bind'] | 1, finish, count=2000)
            if (cpu.reg_read(arm.UC_ARM_REG_PC) != finish
                    or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                    or [cpu.reg_read(reg) for reg in protected] != saved):
                raise ValueError('Complete native device binder did not preserve its return/ABI')
        if bytes(cpu.mem_read(bank, 0x39c)) != bytes(expected) or writes != expected_writes:
            raise ValueError('Original device binding differs from independent field/offset expectations')
        if (any(bytes(cpu.mem_read(at, len(value))) != value for at, value in inputs)
                or cpu.mem_read(bank-4, 4) != b'\x6b'*4
                or cpu.mem_read(bank+0x39c, 4) != b'\x6b'*4):
            raise ValueError('Native binder changed source descriptors or neighboring canaries')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    return dict(native_device_binder_calls=2, native_written_words=len(writes),
                native_full_getter_bank_checked_bytes=924,
                native_function_returns_and_callee_saved_registers_verified=True,
                source_descriptors_preserved=True, missing_source_handles_left_unchanged=True,
                device_descriptors_are_fixtures=True, output_base_words_host_assigned=False,
                hardcoded_setter_mapper_used_as_getter=False,
                physical_mmio_access_executed=False, normal_shooting_entry_verified=False)


def replay(directory, *, flags=(1, 1), present=(1, 1), descriptors_present=(1, 1)):
    actual = tuple(a and b for a, b in zip(present, descriptors_present))
    return source_replay(directory, flags=flags, present=actual,
        initialize_context=lambda cpu, obj, child, bases, available: initialize(
            cpu, directory, obj, child, bases, available,
            source_initializer=lambda uc, bank: bind_devices(uc, directory, bank,
                register_bases=bases, present=present, descriptors_present=descriptors_present)))


def compare(c2, reference):
    cases = []
    for flags in ((0, 0), (1, 0), (0, 1), (1, 1)):
        for present in ((0, 0), (1, 0), (0, 1), (1, 1)):
            for descriptors_present in ((1, 1), (1, 0), (0, 1), (0, 0)):
                args = dict(flags=flags, present=present, descriptors_present=descriptors_present)
                a, b = replay(c2, **args), replay(reference, **args)
                if a != b:
                    raise ValueError('Native C2/CR device/context/input behavior differs')
                cases.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-native-device-binding-input-source/1', paired_cases=len(cases), cases=cases,
                camera_io=False, physical_shift_verified=False, installable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.c2, args.reference)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'physical_shift_verified')}))


if __name__ == '__main__':
    main()
