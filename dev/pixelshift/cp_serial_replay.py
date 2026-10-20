"""Carry a synthetic frame's TRINITY flag/index into native serial packet 0x39.

Original instruction slices execute in one RAM image. TC calculation, other
payload fields, scheduling and the physical serial peer are outside this test.
Interface mode and packet-length flags are synthetic independent inputs; the
interface numbers are not camera model IDs. No
hardware completion is supplied, and this packet is NOT an identified sensor
movement command. Only the normal TC branch is covered.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_metadata_replay import program
from cp_sequence_replay import machine


def literals(code):
    """Collect MOVW/MOVT materializations in inspected straight-line regions."""
    pending, result = {}, []
    for row in code:
        if row.mnemonic in ('bl', 'blx', 'bx', 'b.w', 'b'):
            pending.clear()
        if row.mnemonic == 'movw':
            register, value = row.op_str.split(', #')
            pending[register] = int(value, 0)
        elif row.mnemonic == 'movt':
            register, value = row.op_str.split(', #')
            if register in pending:
                result.append((register, pending.pop(register) | (int(value, 0) << 16)))
    return result


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, model, _, _ = program(directory)
    target = model == 'ILCE-7CM2'
    p = dict(frame_slice=0xb3a2e0 if target else 0xb3a13e,
             flag_setter=0xac15ec if target else 0xac144a,
             flag_getter=0xac15de if target else 0xac143c,
             tc=0xa6cbe6 if target else 0xa6ca8c,
             index_slice=0xa6cdd6 if target else 0xa6cc7c,
             index_setter=0xa6b0a0 if target else 0xa6af46,
             pack=0xa6b0b0 if target else 0xa6af56,
             debug_getter=0xa6bc2c if target else 0xa6bad2,
             version_slice=0xa698c2 if target else 0xa69768,
             info_getter=0xac0284 if target else 0xac00e2,
             version_getter=0xa6994e if target else 0xa697f4,
             serializer=0xa69cec if target else 0xa69b92,
             packet_getter=0xa68994 if target else 0xa6883a,
             serialize_tail=0xa6a178 if target else 0xa6a01e,
             format_update=0xa6a22c if target else 0xa6a0d2,
             variant_getter=0xa6be44 if target else 0xa6bcea,
             wrapper=0x3eddd4 if target else 0x3edfec)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True

    def code(entry, size):
        return list(md.disasm(data[entry - 0x108000:entry - 0x108000 + size], entry))

    def literal(entry, size, register, index=0):
        return [value for reg, value in literals(code(entry, size)) if reg == register][index]

    p['flag'] = literal(p['flag_getter'], 14, 'r0')
    flag_load = [row for row in code(p['flag_getter'], 14) if row.mnemonic.startswith('ldrb')]
    if len(flag_load) != 1:
        raise ValueError('TRINITY flag getter changed')
    p['flag'] += flag_load[0].operands[1].mem.disp
    p['tc_state'] = literal(p['tc'], 0x54, 'fp')
    p['tc_selector'] = literal(p['tc'], 0x54, 'r1')
    p['tc_pending'] = literal(p['tc'], 0x54, 'r1', -1)
    p['index'] = literal(p['index_setter'], 16, 'r1')
    p['packed'] = literal(p['pack'], 0x30, 'r6')
    p['debug'] = literal(p['debug_getter'], 10, 'r0')
    p['info'] = literal(p['info_getter'], 10, 'r0')
    p['extended'] = literal(p['version_getter'], 12, 'r0')
    p['packet'] = literal(p['packet_getter'], 10, 'r0')
    p['changed'] = literal(p['serialize_tail'], 0xb4, 'r0', -1)
    p['variant'] = literal(p['variant_getter'], 12, 'r0')
    p['parameters'] = literal(p['wrapper'], 0x170, 'r8')
    p['descriptor'] = literal(p['wrapper'], 0x170, 'r4')
    p['interface_flags'] = literal(p['wrapper'], 0x170, 'r5')
    p['format_code'] = [value for register, value in literals(code(p['wrapper'], 0x170))
                        if register == 'r0' and 0x1b10000 <= value < 0x1c00000][0]
    stop = [row.address + row.size for row in code(p['wrapper'], 0x170)
            if (row.mnemonic, row.op_str) == ('str', 'r1, [r4, #0xc]')]
    if len(stop) != 1:
        raise ValueError('Serial descriptor length assignment changed')
    p['wrapper_stop'] = stop[0]
    checks = [(p['frame_slice'], 'ldr.w', 'r0, [r4, #0x1e8]'),
              (p['index_slice'], 'ldr.w', 'r0, [fp, #0x18]'),
              (p['serializer'] + 0x26, 'mov.w', 'r8, #1')]
    for address, mnemonic, operands in checks:
        instruction = code(address, 4)[0]
        if (instruction.mnemonic, instruction.op_str) != (mnemonic, operands):
            raise ValueError('Native serial-path slice changed: ' + hex(address))
    regions = [(p['frame_slice'], p['frame_slice'] + 0x1e),
               (p['flag_setter'], p['flag_setter'] + 14),
               (p['flag_getter'], p['flag_getter'] + 14),
               (p['tc'], p['tc'] + 0x54), (p['index_slice'], p['index_slice'] + 8),
               (p['index_setter'], p['index_setter'] + 16), (p['pack'], p['pack'] + 0x4e),
               (p['debug_getter'], p['debug_getter'] + 10),
               (p['version_slice'], p['version_slice'] + 0x1a),
               (p['info_getter'], p['info_getter'] + 10),
               (p['version_getter'], p['version_getter'] + 12),
               (p['serializer'], p['serializer'] + 0x1e),
               (p['serializer'] + 0x26, p['serializer'] + 0x2a),
               (p['packet_getter'], p['packet_getter'] + 10),
               (p['serialize_tail'], p['serialize_tail'] + 0xb4),
               (p['format_update'], p['format_update'] + 0x80),
               (p['variant_getter'], p['variant_getter'] + 12),
               (p['wrapper'], p['wrapper_stop'])]
    p['regions'] = regions
    addresses = [value for begin, end in regions for _, value in literals(code(begin, end - begin))
                 if 0x1100000 <= value < 0x2000000]
    p['pages'] = sorted({address & ~4095 for address in addresses})
    return data, p


def carry(directory, *, trinity, ordinal, interface_mode=5, long_packet=1):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R4, UC_ARM_REG_SP,
                                   UC_ARM_REG_LR, UC_ARM_REG_PC)
    data, p = profile(directory)
    cpu = machine(data, p['pages'])
    frame, stack_data, finish = 0x30004000, 0x3001d000, 0x3001e000
    cpu.mem_write(frame, b'\xa5' * 0x1000)
    cpu.mem_write(frame + 0x98, struct.pack('<I', trinity))
    cpu.mem_write(frame + 0x208, struct.pack('<I', ordinal))
    before_frame = bytes(cpu.mem_read(frame, 0x1000))
    cpu.mem_write(stack_data + 8, b'\0' * 32)
    cpu.mem_write(p['tc_selector'], b'\0')
    cpu.mem_write(p['flag'], b'\xa5')
    cpu.mem_write(p['index'], b'\xa5')
    cpu.mem_write(p['packed'], b'\xa5')
    cpu.mem_write(p['extended'], b'\0')
    cpu.mem_write(p['info'] + 8, struct.pack('<I', interface_mode))
    cpu.mem_write(p['packet'], b'\xa5' * 128)
    cpu.mem_write(p['parameters'] + 4, b'\0' * 4)
    cpu.mem_write(p['variant'], b'\0' * 4)
    cpu.mem_write(p['interface_flags'] + 0x3d, bytes([long_packet]))
    cpu.mem_write(p['descriptor'], b'\xa5' * 16)
    phase = 'frame'
    writes = {
        'frame': [(p['flag'], 1)],
        'copy': [(p['tc_state'], 32), (p['tc_pending'], 1)],
        'index': [(p['index'], 1)],
        'pack': [(p['packed'], 1), (p['debug'] + 0x2c5, 3)],
        'version': [(p['extended'], 1)],
        'serialize': [(p['packet'] + 0x64, 11), (p['changed'], 1)],
        'wrapper': [(p['packet'], 3), (p['packet'] + 0x44, 2),
                    (p['packet'] + 0x54, 2), (p['packet'] + 0x5a, 2),
                    (p['packet'] + 0x61, 3), (p['packet'] + 0x7d, 3),
                    (p['descriptor'], 16), (p['format_code'], 1)]}

    def hook(uc, address, size, unused):
        if not any(begin <= address < end for begin, end in p['regions']):
            raise ValueError('Serial path reached omitted native code: ' + hex(address))

    def write_hook(uc, access, address, size, value, unused):
        if 0x30018000 <= address and address + size <= 0x3001f000:
            return
        if any(begin <= address and address + size <= begin + length for begin, length in writes.get(phase, [])):
            return
        raise ValueError('Serial path changed unrelated state in ' + phase + ': ' + hex(address))

    def run(entry, end=finish):
        cpu.emu_start(entry | 1, end, count=5000)
        if cpu.reg_read(UC_ARM_REG_PC) != end:
            raise ValueError('Native serial slice did not reach its boundary')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.reg_write(UC_ARM_REG_SP, stack_data)
    cpu.reg_write(UC_ARM_REG_R4, frame + 0x20)
    run(p['frame_slice'], p['frame_slice'] + 0x1e)
    before_tc = bytes(cpu.mem_read(stack_data + 8, 32))
    phase = 'copy'
    cpu.reg_write(UC_ARM_REG_SP, 0x3001f000)
    cpu.reg_write(UC_ARM_REG_R0, stack_data + 8)
    run(p['tc'], p['tc'] + 0x54)
    if bytes(cpu.mem_read(p['tc_state'], 32)) != before_tc:
        raise ValueError('TC native copy lost the frame index')
    phase = 'index'
    run(p['index_slice'], p['index_slice'] + 8)
    phase = 'pack'
    cpu.reg_write(UC_ARM_REG_SP, 0x3001f000)
    cpu.reg_write(UC_ARM_REG_LR, finish | 1)
    run(p['pack'])
    phase = 'version'
    run(p['version_slice'], p['version_slice'] + 0x1a)
    phase = 'serialize'
    cpu.reg_write(UC_ARM_REG_SP, 0x3001f000)
    cpu.reg_write(UC_ARM_REG_LR, finish | 1)
    run(p['serializer'], p['serializer'] + 0x1e)
    # Execute the original constant initializer, omitting unrelated TC source pulls.
    run(p['serializer'] + 0x26, p['serializer'] + 0x2a)
    run(p['serialize_tail'])
    phase = 'wrapper'
    cpu.reg_write(UC_ARM_REG_SP, 0x3001f000)
    cpu.reg_write(UC_ARM_REG_LR, finish | 1)
    run(p['wrapper'], p['wrapper_stop'])
    packet = bytes(cpu.mem_read(p['packet'], 128))
    tx, rx, length, count, total = struct.unpack('<IIHHI', cpu.mem_read(p['descriptor'], 16))
    if (tx != p['packet'] or bytes(cpu.mem_read(frame, 0x1000)) != before_frame
            or bytes(cpu.mem_read(stack_data + 8, 32)) != before_tc):
        raise ValueError('Serial descriptor lost the native packet or changed its inputs')
    return dict(packet=packet.hex(), transmitted_bytes=length, repeat_count=count,
                rx_buffer_offset=rx - p['packet'],
                total_bytes=total, extended=bytes(cpu.mem_read(p['extended'], 1))[0],
                native_index=bytes(cpu.mem_read(p['index'], 1))[0],
                packed_index=bytes(cpu.mem_read(p['packed'], 1))[0],
                tc_first_frame=struct.unpack_from('<I', before_tc)[0],
                synthetic_frame_and_interface=True, native_slices_only=True,
                full_tc_calculation_executed=False, serial_transport_executed=False,
                serial_peer_identified=False, physical_shift_verified=False)


def compare(c2, reference):
    cases = []
    inputs = [dict(trinity=active, ordinal=ordinal, interface_mode=interface, long_packet=long)
              for active in (0, 1) for ordinal in range(4)
              for interface in (2, 4, 5) for long in (0, 1)]
    inputs += [dict(trinity=active, ordinal=ordinal, interface_mode=5, long_packet=1)
               for active in (0, 1) for ordinal in (15, 127, 128, 255)]
    for args in inputs:
        a, b = carry(c2, **args), carry(reference, **args)
        if a != b:
            raise ValueError('C2/A7CR native TRINITY serial packing differs')
        cases.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-serial/1', camera_io=False, installable=False,
                paired_cases=len(cases), cases=cases, physical_shift_verified=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    report = compare(args.c2, args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
