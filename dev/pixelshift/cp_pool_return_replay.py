"""Run the complete native outer pool-return function on synthetic task/pool state.

Original entry mutex, checked reference lock, bookkeeping and same-task kernel
context save/restore execute. Unretired synthetic descriptors avoid physical
allocation deletion. Busy ownership stops before waiting. No API result or
register restoration is supplied by the host; capture/group completion and
actual OS resource state are not established by this standalone replay.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_group_end_replay import profile as group_profile
from cp_native_mutex_replay import profile as mutex_profile, setup as setup_mutex
from cp_pool_recycle_replay import profile as recycle_profile
from cp_serial_replay import literals
from cp_sequence_replay import machine


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, group = group_profile(directory)
    _, mutex = mutex_profile(directory)
    _, recycle = recycle_profile(directory)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def call(at, mnemonic='bl'):
        rows = code(at, 4)
        if len(rows) != 1 or rows[0].mnemonic != mnemonic:
            raise ValueError('Original outer pool call changed')
        return int(rows[0].op_str.lstrip('#'), 0)

    def literal(at, size, register):
        values = [v for r, v in literals(code(at, size)) if r == register]
        if len(values) != 1:
            raise ValueError('Native pool state binding is not unique')
        return values[0]

    entry = group['pool']
    retire, deinit = call(entry + 0x24), call(entry + 0x2c)
    retired_check = call(retire + 0x3c)
    second_thunk = call(retire + 0x48, 'b.w')
    second_check = call(second_thunk + 8, 'b.w')
    state = literal(deinit + 8, 0x12, 'r4')
    second = literal(second_thunk, 8, 'r0')
    p = dict(entry=entry, root=recycle['root'], state=state, second=second,
             mutex=mutex, recycle=recycle, range_return=retire + 0x16,
             regions=[(entry, entry + 0x42), (retire, retire + 0x50), (deinit, deinit + 0x98),
                      (retired_check, retired_check + 0x38), (second_thunk, second_thunk + 12),
                      (second_check, second_check + 0x38),
                      (mutex['guard_destructor'], mutex['guard_destructor'] + 0x1c),
                      (mutex['unlock_wrapper'], mutex['unlock_wrapper'] + 0x34)]
                     + recycle['regions'] + mutex['regions'])
    if second != p['root'] + 24 or state + 16 != p['root']:
        raise ValueError('Native pool state/descriptors no longer have the inspected layout')
    return data, p


def setup(cpu, directory, *, base=0x30008000, free_count=0, initialize_nodes=True, **os_inputs):
    _, p = profile(directory)
    mutex = setup_mutex(cpu, directory, **os_inputs)
    for address in (p['state'], p['second'] + 24):
        page = address & ~4095
        if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
            cpu.mem_map(page, 4096)
    old_head = base + 0x5c20 if free_count else 0
    before = struct.pack('<4I', 2, 0, 0, 0) + struct.pack('<6I', old_head, 2, free_count, 0xffffffff, base, 0xb840)
    before += struct.pack('<6I', 0, 2, 0, 0xffffffff, 0, 0)
    cpu.mem_write(p['state'], before)
    if initialize_nodes:
        cpu.mem_write(base, struct.pack('<I', 0x12345678))
        cpu.mem_write(base + 0x5c20, bytes(4))
    return dict(mutex=mutex, before=before, base=base, old_head=old_head, free_count=free_count,
                writes=mutex['writes'] + [(p['root'], 24), (base, 4),
                                         (mutex['lock']['object'], 12), (mutex['core'] + 0x10, 4)])


def observer(cpu, p):
    import unicorn.arm_const as arm
    seen = dict(entry_mutex_status=None, entry_mutex_release_status=None, checked_recycle_lock_status=None,
                range_validator_status=None, same_task_scheduler_entries=0, boundary=None,
                pool_entry_executed=False, outer_pool_return_status=None, diagnostic_calls_omitted=0)
    returns = {}

    def signed(value):
        return value if value < 0x80000000 else value - 0x100000000

    def observe(at):
        if at in returns:
            seen[returns.pop(at)] = signed(cpu.reg_read(arm.UC_ARM_REG_R0))
        if at == p['entry']:
            seen['pool_entry_executed'] = True
            returns[cpu.reg_read(arm.UC_ARM_REG_LR) & ~1] = 'outer_pool_return_status'
        if at in (p['mutex']['acquire'], p['mutex']['release']):
            key = 'entry_mutex_status' if at == p['mutex']['acquire'] else 'entry_mutex_release_status'
            returns[cpu.reg_read(arm.UC_ARM_REG_LR) & ~1] = key
        if at == p['mutex']['scheduler']:
            seen['same_task_scheduler_entries'] += 1
        if at == p['recycle']['free'] + 0x20:
            seen['checked_recycle_lock_status'] = signed(cpu.reg_read(arm.UC_ARM_REG_R0))
        if at == p['range_return']:
            seen['range_validator_status'] = signed(cpu.reg_read(arm.UC_ARM_REG_R0))
        if at == p['mutex']['owner_wait'] or at in p['mutex']['waits']:
            seen['boundary'] = 'owner_wait_transition' if at == p['mutex']['owner_wait'] else 'wait_for_event'
            cpu.emu_stop()
    return seen, observe


def replay(directory, case):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    cpu = machine(data, [])
    state = setup(cpu, directory, free_count=case.get('free_count', 0),
                  **{k: case[k] for k in ('context', 'masked', 'dispatch', 'owner') if k in case})
    seen, observe = observer(cpu, p)
    base, stack, finish = state['base'], 0x3001f000, 0x3001e000
    pointer = base - 4 if case.get('outside') else base
    lock = state['mutex']['lock']

    def hook(uc, at, size, unused):
        observe(at)
        if seen['boundary']:
            return
        if at == p['recycle']['trace']:
            seen['diagnostic_calls_omitted'] += 1
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR) | 1)
            return
        if not any(lo <= at and at + size <= hi for lo, hi in p['regions']):
            raise ValueError('Outer pool return reached an omitted function: ' + hex(at))

    def write_hook(uc, access, address, size, value, unused):
        if not any(lo <= address and address + size <= lo + length for lo, length in state['writes'] + [(stack - 4096, 4096)]):
            raise ValueError('Native outer pool return changed unrelated state: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.reg_write(arm.UC_ARM_REG_R0, pointer)
    cpu.reg_write(arm.UC_ARM_REG_SP, stack)
    cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
    cpu.emu_start(p['entry'] | 1, finish, count=10000)
    returned = seen['boundary'] is None
    if returned:
        seen['outer_pool_return_status'] = cpu.reg_read(arm.UC_ARM_REG_R0)
    expected = bytearray(state['before'])
    recycled = not any(case.get(k) for k in ('outside', 'masked', 'owner'))
    if recycled:
        struct.pack_into('<I', expected, 16, base)
        struct.pack_into('<I', expected, 24, state['free_count'] + 1)
    should_schedule = not any(case.get(k) for k in ('masked', 'owner', 'context')) and case.get('dispatch', True)
    if (bytes(cpu.mem_read(p['state'], len(expected))) != expected
            or bytes(cpu.mem_read(base, 4)) != struct.pack('<I', state['old_head'] if recycled else 0x12345678)
            or returned != (not case.get('owner', False))
            or seen['same_task_scheduler_entries'] != int(should_schedule)):
        raise ValueError('Native outer pool return/list/scheduler behavior differs')
    if returned:
        if (cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
                or cpu.reg_read(arm.UC_ARM_REG_R0) != 0
                or bytes(cpu.mem_read(lock['object'], 12)) != bytes(12)
                or bytes(cpu.mem_read(lock['tcb'] + 0x10, 4)) != bytes(4)
                or bytes(cpu.mem_read(state['mutex']['entry'] + 12, 8)) != bytes(8)
                or bytes(cpu.mem_read(state['mutex']['task'] + 0x54, 4)) != bytes(4)
                or cpu.reg_read(arm.UC_ARM_REG_CPSR) & 0x80 != (0x80 if case.get('masked') else 0)):
            raise ValueError('Native outer pool return failed to unwind ownership/stack')
    return dict(**seen, complete_outer_pool_function_returned=returned,
                outer_return=0 if returned else None, node_recycled=recycled,
                free_count=state['free_count'] + int(recycled),
                host_assigned_api_or_scheduler_return=False, host_restored_registers=False,
                synthetic_os_pool_and_task_state=True, physical_allocation_deletion_executed=False,
                camera_group_completion_executed=False)


def compare(c2, reference):
    inputs = [dict(), dict(free_count=1), dict(outside=True), dict(masked=True),
              dict(dispatch=False), dict(context=1), dict(owner=True)]
    rows = []
    for args in inputs:
        a, b = replay(c2, args), replay(reference, args)
        if a != b:
            raise ValueError('C2/A7CR complete outer pool-return behavior differs')
        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-pool-return/1', paired_cases=len(rows), cases=rows,
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
