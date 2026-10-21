"""Native PowerOffDetect flag and local cache-query construction boundaries.

The original one-shot prefix stops BEFORE allocation. A separate explicit
post-allocation buffer fixture runs original source-header/payload construction,
stopping BEFORE send. Allocation, send, callback delivery and real PowerOffDetect
completion are not supplied or claimed. Already-set inputs return natively.
The native diagnostic names PowerOffDetect/offFactor; this is not an exposure
or sensor-settled notification. The old capture-stop/AP label was incorrect.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_completion_replay import profile as completion_profile
from cp_group_end_replay import profile as group_profile
from cp_serial_replay import literals
from cp_sequence_replay import machine


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, group = group_profile(directory)
    _, completion = completion_profile(directory)
    entry = 0x475630 if group['end'] == 0x4757e8 else 0x475848
    command_handler = 0x3578ac if group['end'] == 0x4757e8 else 0x357a0c
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def call(at):
        row = code(at, 4)
        if len(row) != 1 or row[0].mnemonic != 'bl':
            raise ValueError('Native PowerOffDetect call boundary changed')
        return int(row[0].op_str.lstrip('#'), 0)

    def literal(at, size, register):
        values = [v for r, v in literals(code(at, size)) if r == register]
        if len(values) != 1:
            raise ValueError('Native PowerOffDetect binding is not unique')
        return values[0]

    flag = literal(entry + 6, 8, 'r0')
    command_record = struct.pack('<4I', 0x4077, command_handler | 1, 0, 0)
    records = [n for n in range(0, len(data) - 16, 4) if data[n:n + 16] == command_record]
    if (len(records) != 1 or literal(command_handler + 0x48, 8, 'r0') != entry | 1
            or not data[entry + 0xdc - 0x108000:].startswith(b'FW: CapMgr)PowerOffDetect() offFactor=%d\0')):
        raise ValueError('Native command4077/PowerOffDetect role differs')
    getter, kind = call(entry + 0x18), call(entry + 0x1c)
    header = call(entry + 0x5a)
    if flag != completion['completed'] or flag == group['ended']:
        raise ValueError('Capture-stop/registration flag must agree and differ from object-end marker')
    return data, dict(entry=entry, flag=flag, getter=getter, kind=kind,
                      kind_state=literal(getter, 12, 'r0'), allocator=call(entry + 0x4c),
                      allocation_boundary=entry + 0x4c, payload=entry + 0x52,
                      send_boundary=entry + 0x74, header=header, end_marker=group['ended'])


def replay(directory, initial_flag):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    cpu = machine(data, [])
    cpu.mem_map(0x1700000, 0x440000)
    cpu.mem_map(0x33000000, 0x2000)
    cpu.mem_write(p['flag'], bytes([initial_flag]))
    cpu.mem_write(p['kind_state'], bytes(1))
    cpu.mem_write(p['end_marker'], b'\x6b')
    stack, finish, buffer = 0x3001f000, 0x3001e000, 0x33001010
    cpu.mem_write(buffer - 16, b'\x6b' * 36)
    phase, flag_writes, payload = 'prefix', [], None

    def hook(uc, at, size, unused):
        allowed = ([(p['entry'], p['allocation_boundary']), (p['entry'] + 0xac, p['entry'] + 0xb0),
                    (p['getter'], p['getter'] + 10), (p['kind'], p['kind'] + 4)] if phase == 'prefix' else
                   [(p['payload'], p['send_boundary']), (p['header'], p['header'] + 6)])
        if not any(lo <= at and at + size <= hi for lo, hi in allowed):
            raise ValueError('Capture-stop replay reached an unexecuted dependency: ' + hex(at))

    def write_hook(uc, access, address, size, value, unused):
        if address == p['flag']:
            flag_writes.append([size, value])
        allowed = [(p['flag'], 1), (stack - 512, 512)] if phase == 'prefix' else [(buffer - 12, 4), (buffer, 16)]
        if not any(lo <= address and address + size <= lo + length for lo, length in allowed):
            raise ValueError('Native PowerOffDetect construction wrote unrelated state: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.reg_write(arm.UC_ARM_REG_SP, stack)
    cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
    stop = p['allocation_boundary'] if initial_flag == 0 else finish
    cpu.emu_start(p['entry'] | 1, stop, count=500)
    if (cpu.reg_read(arm.UC_ARM_REG_PC) != stop or cpu.mem_read(p['flag'], 1)[0] != (initial_flag or 1)
            or flag_writes != ([[1, 1]] if initial_flag == 0 else [])
            or cpu.mem_read(p['end_marker'], 1)[0] != 0x6b):
        raise ValueError('Native PowerOffDetect one-shot state/marker behavior differs')
    if initial_flag == 0:
        if (cpu.reg_read(arm.UC_ARM_REG_R0) != 0x92a20845
                or cpu.reg_read(arm.UC_ARM_REG_R2) != 16 or cpu.reg_read(arm.UC_ARM_REG_R3) != 1):
            raise ValueError('Native local-query allocation request differs')
        # Explicit separate post-allocation input; allocator itself is not called.
        cpu.mem_write(cpu.reg_read(arm.UC_ARM_REG_SP) + 4, struct.pack('<I', buffer))
        phase = 'post_allocation_buffer_fixture'
        cpu.emu_start(p['payload'] | 1, p['send_boundary'], count=200)
        payload = bytes(cpu.mem_read(buffer, 16))
        if (cpu.reg_read(arm.UC_ARM_REG_PC) != p['send_boundary'] or payload != struct.pack('<4I', 0x920162, 0, 0, 0)
                or bytes(cpu.mem_read(buffer - 12, 4)) != struct.pack('<I', 0x90030001)
                or bytes(cpu.mem_read(buffer - 16, 4)) != b'\x6b' * 4
                or bytes(cpu.mem_read(buffer - 8, 8)) != b'\x6b' * 8
                or bytes(cpu.mem_read(buffer + 16, 4)) != b'\x6b' * 4):
            raise ValueError('Original local-query source/payload construction differs')
    elif cpu.reg_read(arm.UC_ARM_REG_SP) != stack:
        raise ValueError('Already-complete native PowerOffDetect did not restore its stack')
    return dict(initial_flag=initial_flag, poweroff_detect_flag=initial_flag or 1,
                native_poweroff_role_verified=True,
                native_flag_writes=flag_writes, already_complete_native_return=initial_flag != 0,
                prefix_reached_allocation_boundary=initial_flag == 0,
                original_payload=None if payload is None else payload.hex(),
                post_allocation_buffer_fixture_used=initial_flag == 0,
                allocation_api_executed=False, local_send_executed=False, completion_callback_executed=False,
                host_assigned_allocator_or_send_result=False, object_end_marker_unchanged=True,
                actual_poweroff_check_completed=False, physical_ready_verified=False)


def compare(c2, reference):
    rows = []
    for initial in (0, 1, 255):
        a, b = replay(c2, initial), replay(reference, initial)
        if a != b:
            raise ValueError('C2/A7CR PowerOffDetect construction differs')
        rows.append(dict(initial=initial, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-poweroff/1', paired_cases=len(rows), cases=rows,
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
    print(json.dumps({k: report[k] for k in ('paired_cases', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
