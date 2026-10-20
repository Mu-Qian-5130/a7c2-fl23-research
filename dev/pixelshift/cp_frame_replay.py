"""Carry native TRINITY mode through frame mapping and a control-flag slice.

The original frame mapper executes on the snapshot produced by cp_config_replay.
The later setter/selector slices start after their normal preparation/gates,
with that same frame in RAM. Other snapshot fields and branch inputs are
synthetic. Full preparation, scheduler, transport and sensor positioning do not
execute; the candidate control value is not a transmitted actuator command.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_config_replay import _snapshot
from cp_dispatch_replay import profile as dispatch_profile


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, d = dispatch_profile(directory)
    target = d['dispatcher'] == 0x35cf70
    p = dict(mapper=0x4714ac if target else 0x4716c4,
             setter_slice=0xb3a2ee if target else 0xb3a14c,
             setter=0xac15ec if target else 0xac144a,
             getter=0xac15de if target else 0xac143c,
             flag=0x171ba5c if target else 0x171a80c,
             selector=0xab7334 if target else 0xab7192)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    for key in ('setter_slice', 'selector'):
        begin = p[key]
        instructions = list(md.disasm(data[begin - 0x108000:begin - 0x108000 + 32], begin))
        expected = p['setter'] if key == 'setter_slice' else p['getter']
        if not any(i.mnemonic == 'bl' and int(i.op_str.lstrip('#'), 0) == expected for i in instructions):
            raise ValueError('Native frame-control slice changed')
    return p


def propagate(directory, *, mode, test=0, seed=0, request_enabled=1, initial_request=0x27):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4,
                                   UC_ARM_REG_R6, UC_ARM_REG_R9, UC_ARM_REG_SP,
                                   UC_ARM_REG_LR, UC_ARM_REG_PC)
    cpu, snapshot_profile, d, previous = _snapshot(directory, mode=mode, test=test, seed=seed)
    p = profile(directory)
    for page in (p['flag'] & ~4095,):
        if not any(begin <= page <= end for begin, end, _ in cpu.mem_regions()):
            cpu.mem_map(page, 4096)
    frame, finish, stack = 0x30004000, 0x30002000, 0x3000f000
    source = snapshot_profile['root'] + 0x28
    source_before = bytes(cpu.mem_read(source, 0xd64))
    cpu.mem_write(frame, b'\xa5' * 0x1000)
    cpu.reg_write(UC_ARM_REG_R0, frame + 0x20)
    cpu.reg_write(UC_ARM_REG_R1, source)
    cpu.reg_write(UC_ARM_REG_SP, stack)
    cpu.reg_write(UC_ARM_REG_LR, finish | 1)

    def mapper_hook(uc, address, size, unused):
        if not p['mapper'] <= address < p['mapper'] + 0x5f0:
            raise ValueError('Frame mapper reached unhandled native code: ' + hex(address))

    def mapper_write(uc, access, address, size, value, unused):
        if frame + 0x20 <= address and address + size <= frame + 0x420:
            return
        if 0x3000e000 <= address and address + size <= stack:
            return
        raise ValueError('Frame mapper changed unrelated state: ' + hex(address))

    code_hook = cpu.hook_add(UC_HOOK_CODE, mapper_hook)
    memory_hook = cpu.hook_add(UC_HOOK_MEM_WRITE, mapper_write)
    cpu.emu_start(p['mapper'] | 1, finish, count=4000)
    cpu.hook_del(code_hook)
    cpu.hook_del(memory_hook)
    frame_mode = struct.unpack('<I', cpu.mem_read(frame + 0x98, 4))[0]
    if (cpu.reg_read(UC_ARM_REG_PC) != finish or frame_mode != previous['capture_configuration_trinity']
            or bytes(cpu.mem_read(source, 0xd64)) != source_before
            or bytes(cpu.mem_read(frame, 0x20)) != b'\xa5' * 0x20):
        raise ValueError('Native frame mapper lost the snapshot mode or changed its source')
    frame_before = bytes(cpu.mem_read(frame, 0x1000))
    cpu.mem_write(p['flag'] - 4, b'\xa5' * 9)
    cpu.reg_write(UC_ARM_REG_R4, frame + 0x20)
    phase = 'setter'

    def control_hook(uc, address, size, unused):
        if phase == 'selector' and address == p['selector'] + 0x14:
            uc.emu_stop()  # First join, before the following flag clears.
            return
        if phase == 'setter':
            allowed = [(p['setter_slice'], p['setter_slice'] + 0x10), (p['setter'], p['setter'] + 14)]
        else:
            allowed = [(p['selector'], p['selector'] + 0x34), (p['getter'], p['getter'] + 14)]
        if not any(begin <= address < end for begin, end in allowed):
            raise ValueError('Control slice reached unhandled native code: ' + hex(address))

    def control_write(uc, access, address, size, value, unused):
        if phase != 'setter' or address != p['flag'] or size != 1:
            raise ValueError('Control slice changed an unrelated field')

    code_hook = cpu.hook_add(UC_HOOK_CODE, control_hook)
    memory_hook = cpu.hook_add(UC_HOOK_MEM_WRITE, control_write)
    cpu.emu_start(p['setter_slice'] | 1, p['setter_slice'] + 0x10, count=30)
    flag = bytes(cpu.mem_read(p['flag'], 1))[0]
    if (flag != int(frame_mode == 1) or bytes(cpu.mem_read(p['flag'] - 4, 4)) != b'\xa5' * 4
            or bytes(cpu.mem_read(p['flag'] + 1, 4)) != b'\xa5' * 4):
        raise ValueError('Native setter did not propagate the actual frame mode')
    phase = 'selector'
    cpu.reg_write(UC_ARM_REG_R9, request_enabled)
    cpu.reg_write(UC_ARM_REG_R6, initial_request)
    cpu.emu_start(p['selector'] | 1, p['selector'] + 0x34, count=40)
    candidate = cpu.reg_read(UC_ARM_REG_R6)
    expected = 0x50 if not request_enabled else (0x51 if flag else initial_request)
    if (cpu.reg_read(UC_ARM_REG_PC) not in (p['selector'] + 0x14, p['selector'] + 0x34) or candidate != expected
            or bytes(cpu.mem_read(frame, 0x1000)) != frame_before):
        raise ValueError('Native control selection changed its input or selected an unexpected value')
    return dict(frame_mode=frame_mode, control_flag=flag, request_candidate=candidate,
                mode_never_reassigned_by_host=True, synthetic_unrelated_state=True,
                full_preparation_executed=False, later_request_overrides_executed=False,
                transport_executed=False, physical_shift_verified=False)


def compare(c2, reference):
    cases = []
    for values in (dict(mode=0), dict(mode=1), dict(mode=2), dict(mode=1, test=1)):
        for seed in (0, 255):
            for enabled, request in ((0, 0x13), (1, 0x13), (1, 0x27)):
                args = dict(values, seed=seed, request_enabled=enabled, initial_request=request)
                a, b = propagate(c2, **args), propagate(reference, **args)
                if a != b:
                    raise ValueError('C2/A7CR frame-to-control propagation differs')
                cases.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-frame/1', paired_cases=len(cases), camera_io=False,
                installable=False, physical_shift_verified=False, cases=cases)


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
