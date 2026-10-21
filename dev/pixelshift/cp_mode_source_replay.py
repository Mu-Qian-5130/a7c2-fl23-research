"""Trace dispatched mode through the native current-settings/TC input route.

Original post-semaphore settings-copy slice, pointer binding, flag-update slice,
340-byte TC input copy, flag export and 192-byte publication/snapshot execute
in the dispatcher's RAM. Context addresses, unrelated data and previous flag
are synthetic. Host invokes the stages separately; semaphore admission, task
scheduling, delay notification, capture completion and hardware do not execute.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_dispatch_replay import _dispatch, profile as dispatch_profile
from cp_vector_replay import profile as vector_profile
from trinity_replay import configure


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, d = dispatch_profile(directory)
    _, vector = vector_profile(directory)
    target = d['dispatcher'] == 0x35cf70
    p = dict(settings_copy=0x8dad66 if target else 0x8daf7e,
             binding=0xb2ebce if target else 0xb2ea2c,
             update=0xb3cdd0 if target else 0xb3cc2e,
             input_copy=0xac02e4 if target else 0xac0142)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    at = p['update']
    first = next(md.disasm(data[at - 0x108000:at - 0x108000 + 4], at))
    if (first.mnemonic, first.op_str) != ('ldr.w', 'r1, [r8, #0x180]'):
        raise ValueError('Native TC flag source is no longer the inspected mode field')
    p['changed'], p['unchanged'] = p['update'] + 0x22, p['update'] + 0x30
    return data, d, vector, p


def propagate(directory, *, mode, previous_flag):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                                   UC_ARM_REG_R6, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10,
                                   UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
    data, d, v, p = profile(directory)
    packet = configure(directory, mode=mode)['packet']
    cpu, _, dispatched = _dispatch(directory, packet)
    source = d['parameter'] - 0x180
    context, bindings, tc_input, exported = 0x31000000, 0x31008000, 0x31008400, 0x31008800
    stack, finish = 0x3000f000, 0x30002000
    cpu.mem_map(context, 0x10000)
    required = [(source, 0xd64), (v['flag'] - 0x14c, 340), (v['export_root'], 4),
                (v['buffers'], 384), (v['bank'], 1), (v['snapshot_data'], 192)]
    for address, length in required:
        for page in range(address & ~4095, (address + length + 4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
    unrelated = bytes((i * 37 + 19) & 255 for i in range(0xd64))
    cpu.mem_write(source, unrelated[:0x180])
    cpu.mem_write(source + 0x184, unrelated[0x184:])
    original = bytes(cpu.mem_read(source, 0xd64))
    cpu.mem_write(bindings, b'\xa5' * 200)
    cpu.mem_write(tc_input + 0x14c, bytes([previous_flag]))
    cpu.mem_write(v['export_root'], struct.pack('<I', exported))
    phase, update_boundary, copies = 'settings', None, []
    regions = [(p['settings_copy'], p['settings_copy'] + 0x12),
               (p['binding'], p['binding'] + 0x118), (p['update'], p['changed']),
               (p['input_copy'], p['input_copy'] + 0x18),
               (v['flag_getter'], v['flag_getter'] + 14),
               (v['export'], v['export'] + 12), (v['publish'], v['publish'] + 0x4c),
               (v['snapshot'], v['snapshot'] + 0x26), (v['copy'], v['copy'] + 0x300)]
    writes = dict(settings=[(context, 0xd64)], binding=[(bindings, 200)],
                  update=[(tc_input + 0x14c, 1)], input=[(v['flag'] - 0x14c, 340)],
                  export=[(exported + 0x6f, 1)], publish=[(v['buffers'], 384), (v['bank'], 1)],
                  snapshot=[(v['snapshot_data'], 192)])

    def hook(uc, address, size, unused):
        nonlocal update_boundary
        if phase == 'update' and address in (p['changed'], p['unchanged']):
            update_boundary = address
            uc.emu_stop()
            return
        if not any(lo <= address and address + size <= hi for lo, hi in regions):
            raise ValueError('Mode-source replay reached omitted code: ' + hex(address))
        if address == v['copy']:
            copies.append((phase, uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1),
                           uc.reg_read(UC_ARM_REG_R2)))

    def write_hook(uc, access, address, size, value, unused):
        if stack - 2048 <= address and address + size <= stack:
            return
        if not any(lo <= address and address + size <= lo + n for lo, n in writes[phase]):
            raise ValueError('Mode-source replay changed unrelated ' + phase + ' state: ' + hex(address))

    def run(at, end=finish):
        cpu.reg_write(UC_ARM_REG_SP, stack)
        cpu.reg_write(UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(at | 1, end, count=5000)
        if phase != 'update' and cpu.reg_read(UC_ARM_REG_PC) != end:
            raise ValueError('Native mode-source stage exceeded its bound')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.reg_write(UC_ARM_REG_R6, context)
    run(p['settings_copy'], p['settings_copy'] + 0x12)
    if bytes(cpu.mem_read(context, 0xd64)) != original:
        raise ValueError('Native current-settings copy lost dispatched mode/source bytes')
    phase = 'binding'
    cpu.reg_write(UC_ARM_REG_R0, context)
    cpu.reg_write(UC_ARM_REG_R1, bindings)
    run(p['binding'])
    first = struct.unpack('<I', cpu.mem_read(bindings, 4))[0]
    if first != context:
        raise ValueError('Native control pointer registry lost its first settings context')
    phase = 'update'
    cpu.reg_write(UC_ARM_REG_R8, first)
    cpu.reg_write(UC_ARM_REG_R9, tc_input)
    run(p['update'], 0)
    # AP selection values 1/2 both encode native CP enable value 1.
    # They are not native CP mode values 1/2.
    expected = int(dispatched['mode'] == 1)
    if update_boundary is None or cpu.mem_read(tc_input + 0x14c, 1)[0] != expected:
        raise ValueError('Native settings-mode to TC flag conversion differs: ' + repr(dict(
            input_mode=mode, previous_flag=previous_flag, boundary=update_boundary,
            copied_mode=struct.unpack('<I', cpu.mem_read(context + 0x180, 4))[0],
            actual=cpu.mem_read(tc_input + 0x14c, 1)[0])))
    phase = 'input'
    cpu.reg_write(UC_ARM_REG_R0, tc_input)
    run(p['input_copy'], p['input_copy'] + 0x18)
    if bytes(cpu.mem_read(v['flag'] - 0x14c, 340)) != bytes(cpu.mem_read(tc_input, 340)):
        raise ValueError('Native complete TC input copy differs from its source')
    phase = 'export'
    cpu.reg_write(UC_ARM_REG_R10, v['export_root'])
    run(v['export'], v['export'] + 12)
    publication = bytes(cpu.mem_read(exported, 192))
    phase = 'publish'
    for register, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3),
                               struct.unpack('<4I', publication[:16])):
        cpu.reg_write(register, value)
    cpu.mem_write(stack, publication[16:])
    run(v['publish'])
    phase = 'snapshot'
    cpu.reg_write(UC_ARM_REG_R2, 192)
    run(v['snapshot'], v['snapshot'] + 0x26)
    if (bytes(cpu.mem_read(v['snapshot_data'], 192)) != publication or publication[0x6f] != expected
            or bytes(cpu.mem_read(source, 0xd64)) != original
            or [c[3] for c in copies] != [0xd64, 340, 192, 192]):
        raise ValueError('Native mode-source propagation or complete-copy lengths differ')
    return dict(mode=mode, previous_flag=previous_flag, mode_dispatch=dispatched,
                copied_settings_mode=struct.unpack('<I', cpu.mem_read(context + 0x180, 4))[0],
                published_trinity_flag=publication[0x6f], native_copy_lengths=[c[3] for c in copies],
                native_first_pointer_bound=True, host_reassigned_mode=False,
                semaphore_admission_executed=False, scheduler_executed=False,
                changed_flag_notification_executed=False, capture_end_executed=False,
                camera_io=False, physical_shift_verified=False)


def compare(c2, reference):
    cases = []
    for mode in (0, 1, 2):
        for previous in (0, 1):
            a = propagate(c2, mode=mode, previous_flag=previous)
            b = propagate(reference, mode=mode, previous_flag=previous)
            if a != b:
                raise ValueError('C2/A7CR settings-to-TC mode propagation differs')
            cases.append(dict(target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-mode-source/1', paired_cases=len(cases), cases=cases,
                camera_io=False, installable=False, physical_shift_verified=False)


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
