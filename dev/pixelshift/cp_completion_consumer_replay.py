"""Original capture-thread event query/status branch, offline only.

Executes the original event-reference API and the selected capture-thread
slice, not a blocking wait or a woken task. Event/core/frame state are synthetic
unless the helper is attached to an earlier native producer in the same RAM.
Status bits/classifier enums are reported without naming them hardware-ready.
Recovery bit0x2000 stops before its unmodeled recovery operations.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_completion_replay import profile as completion_profile, setup as setup_completion
from cp_group_end_replay import profile as group_profile
from cp_serial_replay import literals
from cp_sequence_replay import machine


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_ARM
    data, group = group_profile(directory)
    _, producer = completion_profile(directory)
    thumb, arm = Cs(CS_ARCH_ARM, CS_MODE_THUMB), Cs(CS_ARCH_ARM, CS_MODE_ARM)

    def code(at, size, decoder=thumb):
        return list(decoder.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def literal(at, size, register, decoder=arm):
        values = [v for r, v in literals(code(at, size, decoder)) if r == register]
        if len(values) != 1:
            raise ValueError('Native completion consumer binding is not unique')
        return values[0]

    entry = 0x4907ce if group['end'] == 0x4757e8 else 0x4909ea
    call = code(entry + 4, 4)[0]
    if call.mnemonic != 'blx':
        raise ValueError('Native consumer event-reference call changed')
    api = int(call.op_str.lstrip('#'), 0)
    table = literal(api + 0x6c, 16, 'r0')
    guard = literal(api + 0x6c, 16, 'r3')
    if table != producer['table'] or guard != producer['guard']:
        raise ValueError('Native producer/consumer do not reference the same event state')
    mark_call = code(entry + 0x80, 4)[0]
    if mark_call.mnemonic != 'bl':
        raise ValueError('Native consumer frame-status update call changed')
    mark = int(mark_call.op_str.lstrip('#'), 0)
    if [i.op_str for i in code(mark, 14)[-4:]] != ['r3, [r0, r2]', 'r1, r3', 'r1, [r0, r2]', 'lr']:
        raise ValueError('Native frame-status setter changed')
    offset = int(code(mark + 2, 4)[0].op_str.split('#')[1], 0)
    classifier = mark + 14
    waits = [i.address for i in code(api, 0x1ec, arm) if i.mnemonic == 'wfe']
    return data, dict(entry=entry, stop=entry + 0x84, recovery=entry + 0x22,
                      api=api, guard=guard, mark=mark, classifier=classifier, status_offset=offset,
                      waits=waits, regions=[(entry, entry + 0x84), (api, api + 0x1ec),
                                            (mark, mark + 14), (classifier, classifier + 0x1a)])


def consume(cpu, directory, *, initial_status=0, invoke_classifier=True):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, p = profile(directory)
    if not any(lo <= 0x32000000 <= hi for lo, hi, _ in cpu.mem_regions()):
        cpu.mem_map(0x32000000, 0x10000)
    frame, stack, finish = 0x32000000, 0x3200f000, 0x3200e000
    status_address = frame + p['status_offset']
    cpu.mem_write(status_address - 4, b'\x6b' * 4 + struct.pack('<I', initial_status) + b'\x6b' * 4)
    cpu.mem_write(stack + 0xb0, b'\x6b' * 12)
    boundary, reference_status, marker_calls = None, None, []

    def hook(uc, at, size, unused):
        nonlocal boundary, reference_status
        if at == p['entry'] + 8:
            value = uc.reg_read(arm.UC_ARM_REG_R0)
            reference_status = value if value < 0x80000000 else value - 0x100000000
            if reference_status != 0:
                boundary = 'reference_rejected'
                uc.emu_stop()
                return
        if at == p['recovery'] or at in p['waits']:
            boundary = 'recovery_branch' if at == p['recovery'] else 'wait_for_event'
            uc.emu_stop()
            return
        if at == p['mark']:
            marker_calls.append(uc.reg_read(arm.UC_ARM_REG_R1))
        if not any(lo <= at and at + size <= hi for lo, hi in p['regions']):
            raise ValueError('Native consumer reached an unmodeled function: ' + hex(at))

    def write_hook(uc, access, address, size, value, unused):
        allowed = [(status_address, 4), (p['guard'], 4), (stack - 1024, 1024), (stack + 0xb0, 8)]
        if not any(lo <= address and address + size <= lo + length for lo, length in allowed):
            raise ValueError('Native consumer wrote unrelated frame/event state: ' + hex(address))

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_R4, frame)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(p['entry'] | 1, p['stop'], count=5000)
        if boundary is None and cpu.reg_read(arm.UC_ARM_REG_PC) != p['stop']:
            raise ValueError('Original consumer slice did not finish')
        queried = None if reference_status != 0 else list(struct.unpack('<2I', cpu.mem_read(stack + 0xb0, 8)))
        after = struct.unpack('<I', cpu.mem_read(status_address, 4))[0]
        expected = initial_status
        if queried is not None and not queried[1] & 0x2000:
            expected |= 0x20 if queried[1] & 0x10000 else 8 if queried[1] & 0x8000 else 0
        if (after != expected or bytes(cpu.mem_read(status_address - 4, 4)) != b'\x6b' * 4
                or bytes(cpu.mem_read(status_address + 4, 4)) != b'\x6b' * 4
                or bytes(cpu.mem_read(stack + 0xb8, 4)) != b'\x6b' * 4):
            raise ValueError('Original consumer status update/bounds differ')
        classification = None
        if boundary is None and invoke_classifier:
            cpu.reg_write(arm.UC_ARM_REG_R0, frame)
            cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
            cpu.emu_start(p['classifier'] | 1, finish, count=30)
            if cpu.reg_read(arm.UC_ARM_REG_PC) != finish:
                raise ValueError('Native frame-status classifier did not return')
            classification = cpu.reg_read(arm.UC_ARM_REG_R0)
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    return dict(boundary=boundary or 'consumer_slice_boundary', reference_api_status=reference_status,
                queried_waiter_and_bits=queried, native_status_markers=marker_calls,
                frame_status_before=initial_status, frame_status_after=after,
                native_status_classification=classification, event_query_not_blocking_wait=True,
                host_assigned_event_or_api_result=False, actual_waiting_task_woken=False,
                remainder_of_capture_thread_executed=False, physical_ready_verified=False)


def replay(directory, case):
    data, _ = profile(directory)
    cpu = machine(data, [])
    cpu.mem_map(0x1700000, 0x440000)
    state = setup_completion(cpu, directory, initial_bits=case['bits'],
                             context=case.get('context', 0), masked=case.get('masked', False),
                             kernel_busy=case.get('kernel_busy', False))
    result = consume(cpu, directory, initial_status=case.get('status', 0))
    if struct.unpack('<I', cpu.mem_read(state['event'] + 12, 4))[0] != case['bits']:
        raise ValueError('Native reference query changed the event bits')
    return result


def compare(c2, reference):
    inputs = [dict(bits=n) for n in (0, 0x8000, 0x10000, 0x18000, 0x12000)]
    inputs += [dict(bits=0x10000, status=0x40), dict(bits=0x10000, context=1),
               dict(bits=0x10000, masked=True), dict(bits=0x10000, kernel_busy=True)]
    rows = []
    for args in inputs:
        a, b = replay(c2, args), replay(reference, args)
        if a != b:
            raise ValueError('C2/A7CR native completion consumer differs')
        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-completion-consumer/1', paired_cases=len(rows), cases=rows,
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
