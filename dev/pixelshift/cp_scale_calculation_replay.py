"""Execute native adjustment arithmetic into the full CP vector producer.

Measurement records are synthetic numerical inputs, NOT actual sensor motion,
factory calibration or a proposed body patch. The original adjustment routine
executes from its prologue to just before its notification call. The harness
restores CPU registers at this partial-call boundary; calculated scale bytes
remain in the same RAM and feed the original consumer/full vector producer.
No adjustment-script scheduling, notification, motor or exposure executes.
"""
import argparse
from fractions import Fraction
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_phase_pair_replay import pair_sequence
from cp_serial_replay import literals
from cp_vector_replay import profile as vector_profile


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, vector = vector_profile(directory)
    target = vector['vector'] == 0xaa8738
    p = dict(entry=0x13ca30 if target else 0x13ca50,
             initialize=0xab12ce if target else 0xab112c,
             calculation=0x13d104 if target else 0x13d124,
             stop=0x13d3fc if target else 0x13d41c, scales=vector['scales'])
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def literal(at, size, register):
        matches = [value for reg, value in literals(code(at, size)) if reg == register]
        if len(matches) != 1:
            raise ValueError('Native scale arithmetic state binding is not unique')
        return matches[0]

    p['root'] = literal(p['entry'] + 0x24, 0x20, 'r1')
    p['disabled'] = literal(p['entry'] + 0x24, 0x20, 'r0')
    p['command'] = literal(p['entry'] + 0x48, 12, 'r4')
    p['measurements'] = literal(p['calculation'] + 4, 0x16, 'lr')
    if (literal(p['initialize'], 16, 'r0') != p['measurements']
            or literal(p['initialize'], 16, 'r2') != p['root']):
        raise ValueError('Native measurement-pointer initializer does not bind the arithmetic state')
    binding = literal(p['calculation'] + 0xd6, 0x10, 'ip')
    if binding + 0x70 != p['scales']:
        raise ValueError('Original scale arithmetic no longer writes the vector producer parameter')
    if [(i.mnemonic, i.op_str) for i in code(p['stop'], 10)] != [
            ('movs', 'r0, #0'), ('strh.w', 'r0, [sp, #0x14]'), ('str', 'r0, [sp, #0x10]')]:
        raise ValueError('Original scale calculation notification boundary changed')
    prologue = code(p['entry'], 0x24)
    p['zero'] = [int(i.op_str.lstrip('#'), 0) for i in prologue if i.mnemonic == 'blx']
    if len(set(p['zero'])) != 1 or len(p['zero']) != 2:
        raise ValueError('Original scale routine no longer has its two native zero helpers')
    p['zero'] = p['zero'][0]
    return data, p


def expected(case):
    """Independent rational calculation for the synthetic test record only."""
    numerator = case['range'] * case['span'] * 8
    gain = case['gain']
    denominators = [Fraction(case['x'] * gain, 16), Fraction(case['y'] * gain, 16),
                    Fraction(sum(case['z']) * gain, 32)]
    values, error = [], False
    for denominator in denominators:
        if denominator <= 0 or Fraction(numerator, 1) / denominator >= 256:
            values.append(0)
            error = True
        else:
            values.append(int(Fraction(numerator, 1) / denominator + Fraction(1, 2)) & 255)
    return values, int(error)


def calculate(cpu, directory, case):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    count = case['count']
    if count not in (1, 2, 4):
        raise ValueError('Only the inspected small synthetic sample counts are supported')
    for address, length in ((p['root'], 12), (p['disabled'], 1), (p['command'], 1),
                            (p['measurements'], 256), (p['scales'], 3)):
        for page in range(address & ~4095, (address + length + 4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
    diagnostic, stack = p['measurements'] + 0x18, 0x3001f000
    records = bytearray(256)
    struct.pack_into('<4H', records, 0x10, case['gain'], case['gain'], case['range'], case['span'])
    for index in range(count):
        struct.pack_into('<4h', records, 0x80 + 8 * index, 0, 0, case['x'], case['y'])
        struct.pack_into('<4h', records, 0x80 + 8 * count + 8 * index, 0, 0, *case['z'])
    records[0x18:0x68] = b'\x6b' * 80
    cpu.mem_write(p['measurements'], bytes(records))
    cpu.mem_write(p['command'], bytes([0x10 | (count - 1)]))
    cpu.mem_write(p['disabled'], bytes(1))
    neighbors = bytes(cpu.mem_read(p['scales'] - 1, 5))
    # Do not seed the calculated scale bytes, even with zero/canary values.
    registers = [getattr(arm, 'UC_ARM_REG_R' + str(i)) for i in range(13)]
    registers += [arm.UC_ARM_REG_SP, arm.UC_ARM_REG_LR, arm.UC_ARM_REG_PC, arm.UC_ARM_REG_CPSR]
    registers += [getattr(arm, 'UC_ARM_REG_D' + str(i)) for i in range(32)]
    registers += [arm.UC_ARM_REG_FPSCR, arm.UC_ARM_REG_FPEXC, arm.UC_ARM_REG_C1_C0_2]
    saved = [(register, cpu.reg_read(register)) for register in registers]
    cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0x00f00000)
    cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
    cpu.reg_write(arm.UC_ARM_REG_FPSCR, 0)
    cpu.reg_write(arm.UC_ARM_REG_SP, stack)
    steps, scale_stores, zero_calls = 0, [], []

    def hook(uc, at, size, unused):
        nonlocal steps
        if not (p['entry'] <= at and at + size <= p['stop']
                or p['initialize'] <= at and at + size <= p['initialize'] + 0x2e
                or p['zero'] <= at and at + size <= p['zero'] + 0x150):
            raise ValueError('Scale arithmetic reached omitted code: ' + hex(at))
        if at == p['zero']:
            zero_calls.append(uc.reg_read(arm.UC_ARM_REG_R1))
        steps += 1

    def write_hook(uc, access, address, size, value, unused):
        if p['scales'] <= address and address + size <= p['scales'] + 3:
            scale_stores.append([address - p['scales'], size])
        allowed = [(p['scales'], 3), (p['measurements'] + 2, 2),
                   (diagnostic, 72), (p['root'], 12), (stack - 2048, 2048)]
        if not any(lo <= address and address + size <= lo + length for lo, length in allowed):
            raise ValueError('Native scale calculation wrote unrelated state: ' + hex(address))

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        cpu.emu_start(p['initialize'] | 1, p['initialize'] + 0x2e, count=32)
        if (cpu.reg_read(arm.UC_ARM_REG_PC) != p['initialize'] + 0x2e
                or bytes(cpu.mem_read(p['root'], 12)) != struct.pack(
                    '<3I', diagnostic, diagnostic, p['measurements'] + 0x80)):
            raise ValueError('Original measurement pointer binding did not finish')
        cpu.emu_start(p['entry'] | 1, p['stop'], count=10000)
        if cpu.reg_read(arm.UC_ARM_REG_PC) != p['stop']:
            raise ValueError('Native scale calculation missed its notification boundary')
        values = list(cpu.mem_read(p['scales'], 3))
        error = struct.unpack('<H', cpu.mem_read(p['measurements'] + 2, 2))[0]
        records[2:4] = struct.pack('<H', error)
        after = bytes(cpu.mem_read(p['measurements'], 256))
        if (after[:0x18] != records[:0x18] or after[0x60:] != records[0x60:]
                or struct.unpack('<I', cpu.mem_read(p['root'] + 4, 4))[0] != diagnostic + 72
                or (values, error) != expected(case)
                or scale_stores != [[0, 1], [1, 1], [2, 1]] or zero_calls != [28, 56]
                or cpu.mem_read(p['scales'] - 1, 1)[0] != neighbors[0]
                or cpu.mem_read(p['scales'] + 3, 1)[0] != neighbors[-1]
                or bytes(cpu.mem_read(diagnostic + 72, 8)) != b'\x6b' * 8):
            raise ValueError('Native scale arithmetic, source preservation or write bounds differ')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
        # The partial native call stops before notification/epilogue. This
        # explicit harness boundary restores CPU registers, never output RAM.
        for register, value in saved:
            cpu.reg_write(register, value)
    return dict(scale_bytes=values, native_error_flag=error, native_steps=steps,
                native_measurement_pointer_binding_executed=True, native_diagnostic_record_bytes=72,
                native_scale_store_offsets=[r[0] for r in scale_stores],
                measurement_records_synthetic=True, host_assigned_scale_bytes=False,
                cpu_registers_restored_by_harness=True, notification_executed=False,
                physical_units_verified=False)


def cases():
    nominal = dict(gain=16, range=10, span=10, x=200, y=100, z=[100, 100])
    return [dict(nominal, count=n) for n in (1, 2, 4)] + [
        dict(nominal, count=1, x=0), dict(nominal, count=2, y=-100),
        dict(nominal, count=4, z=[1, 1]), dict(nominal, count=1, x=4),
        dict(nominal, count=1, range=32, x=1), dict(nominal, count=1, range=32, x=10),
        dict(nominal, count=1, range=511, span=1, x=16)]


def replay(directory, case):
    result = pair_sequence(directory, full_control=True,
                           scale_initializer=lambda cpu, vector: calculate(cpu, directory, case))
    return dict(scale_calculation=result['scale_initialization'],
                shots=result['shots'],
                full_native_consumer_and_producer_executed=result['full_control_producer_executed'],
                native_both_packet_formatters_executed=result['native_first_then_second_formatters'],
                same_ram=True, original_factory_scale_bytes=result['original_scale_bytes'],
                synthetic_inputs=case, scheduling_executed=False, camera_io=False, installable=False)


def compare(c2, reference):
    rows = []
    for case in cases():
        a, b = replay(c2, case), replay(reference, case)
        if a != b:
            raise ValueError('C2/A7CR native scale arithmetic or vector consumption differs')
        rows.append(dict(input=case, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-native-scale-calculation/1', paired_cases=len(rows),
                paired_vector_steps=4 * len(rows), cases=rows, camera_io=False,
                installable=False, physical_shift_verified=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--h8-input', type=Path)
    args = parser.parse_args(argv)
    report = compare(args.c2, args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    if args.h8_input is not None:
        args.h8_input.parent.mkdir(parents=True, exist_ok=True)
        with args.h8_input.open('x', encoding='utf-8') as handle:
            for index, case in enumerate(report['cases']):
                for ordinal, shot in enumerate(case['target']['shots']):
                    handle.write(f'calculation{index}-ordinal{ordinal}\t{shot["first"]}\t{shot["second"]}\n')
    print(json.dumps({k: report[k] for k in ('paired_cases', 'paired_vector_steps', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
