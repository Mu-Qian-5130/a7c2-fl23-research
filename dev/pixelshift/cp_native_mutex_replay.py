"""Run original pool-entry mutex and same-task kernel context save/restore.

OS, task, queue and attribute data are synthetic. No API result, scheduling
return or register restoration is supplied by the host. Only the same-task,
uncontended path completes; waiting/contended transitions stop before enqueue
or WFE. This is not real interrupt delivery or a camera capture scheduler.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_group_end_replay import profile as group_profile
from cp_native_lock_replay import setup as setup_locks
from cp_sequence_replay import machine
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_ARM
    data, group = group_profile(directory)
    thumb, arm = Cs(CS_ARCH_ARM, CS_MODE_THUMB), Cs(CS_ARCH_ARM, CS_MODE_ARM)

    def code(at, size, decoder=arm):
        return list(decoder.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def call(at, mnemonic, decoder=thumb):
        rows = code(at, 4, decoder)
        if len(rows) != 1 or rows[0].mnemonic != mnemonic:
            raise ValueError('Native mutex call boundary changed')
        return int(rows[0].op_str.lstrip('#'), 0)

    def literal(at, size, register):
        values = [v for r, v in literals(code(at, size)) if r == register]
        if len(values) != 1:
            raise ValueError('Native mutex OS binding is not unique')
        return values[0]

    acquire = call(group['pool'] + 0x18, 'blx')
    guard_destructor = call(group['pool'] + 0x38, 'bl')
    unlock_wrapper = call(guard_destructor + 0x14, 'bl')
    release = call(unlock_wrapper + 0x10, 'blx')
    helper1 = call(release + 0x178, 'bl', arm)
    helper2 = call(release + 0x18c, 'bl', arm)
    scheduler = call(release + 0x1c0, 'bl', arm)
    switch = call(scheduler + 0x50, 'b', arm)
    task_hook = call(switch + 0x18, 'bl', arm)
    maximum = code(acquire + 0x54, 8)
    if [i.mnemonic for i in maximum] != ['movwge', 'movtge']:
        raise ValueError('Original mutex ID bound changed')
    lo, hi = [int(i.op_str.split('#')[1], 0) for i in maximum]
    maximum_id = struct.unpack_from('<I', data, (lo | hi << 16) - 0x108000)[0]
    p = dict(acquire=acquire, release=release, scheduler=scheduler, switch=switch,
             task_hook=task_hook, table=literal(acquire + 0x90, 0x18, 'r1'),
             guard=literal(acquire + 0x90, 0x18, 'r6'), maximum_id=maximum_id,
             context_table=literal(acquire + 0x10, 12, 'ip'),
             owner_wait=acquire + 0x1a4, guard_destructor=guard_destructor, unlock_wrapper=unlock_wrapper)
    if p['context_table'] != group['context_table'] or maximum_id < 14:
        raise ValueError('Native mutex context/bound does not cover pool entry14')
    p['regions'] = [(acquire, acquire + 0x354), (release, release + 0x1f8),
                    (helper1, helper1 + 0x204), (helper2, helper2 + 0x180),
                    (scheduler, scheduler + 0xb0), (switch, switch + 0x30), (task_hook, task_hook + 0x24)]
    p['waits'] = [i.address for lo, end in p['regions'] for i in code(lo, end - lo) if i.mnemonic in ('wfe', 'wfi')]
    return data, p


def setup(cpu, directory, *, context=0, masked=False, dispatch=True, owner=False, kernel_busy=False):
    import unicorn.arm_const as arm
    _, p = profile(directory)
    lock = setup_locks(cpu, directory, interrupt_context=context, irq_masked=masked)
    core, task, other, attrs = lock['tcb'], 0x30002000, 0x30002400, 0x30003000
    entry = p['table'] + 20 * (14 - 1)
    for address in (entry, p['guard']):
        page = address & ~4095
        if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
            cpu.mem_map(page, 4096)
    cpu.mem_write(core, struct.pack('<4I', task, task, 0, int(dispatch)))
    cpu.mem_write(task, bytes(0x80))
    cpu.mem_write(attrs, bytes(8))
    cpu.mem_write(entry - 4, b'\x6b' * 4 + struct.pack('<5I', entry, entry, attrs, other if owner else 0, 0) + b'\x6b' * 4)
    cpu.mem_write(p['guard'], struct.pack('<I', int(kernel_busy)))
    cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0x00f00000)
    cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
    return dict(lock=lock, core=core, task=task, entry=entry, attrs=attrs,
                writes=[(entry, 20), (p['guard'], 4), (core, 4), (core + 0x5c, 4),
                        (task + 0x18, 8), (task + 0x54, 4)])


def replay(directory, case):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    cpu = machine(data, [])
    state = setup(cpu, directory, **{k: case[k] for k in ('context', 'masked', 'dispatch', 'owner', 'kernel_busy') if k in case})
    entry, task, stack, finish = state['entry'], state['task'], 0x3001f000, 0x3001e000
    fp = [getattr(arm, 'UC_ARM_REG_D' + str(i)) for i in range(16)]
    values = [0x3ff0000000000000 + (i << 20) for i in range(16)]
    for register, value in zip(fp, values):
        cpu.reg_write(register, value)
    before = bytes(cpu.mem_read(entry, 20)), bytes(cpu.mem_read(task + 0x54, 4)), bytes(cpu.mem_read(p['guard'], 4))
    boundary, switches, restores = None, 0, 0

    def hook(uc, at, size, unused):
        nonlocal boundary, switches, restores
        if at == p['owner_wait'] or at in p['waits']:
            boundary = 'owner_wait_transition' if at == p['owner_wait'] else 'wait_for_event'
            uc.emu_stop()
            return
        if at == p['scheduler']:
            switches += 1
        if at == p['scheduler'] + 0x54:
            restores += 1
        if not any(lo <= at and at + size <= hi for lo, hi in p['regions']):
            raise ValueError('Native mutex reached an omitted function: ' + hex(at))

    def write_hook(uc, access, address, size, value, unused):
        if not any(lo <= address and address + size <= lo + length for lo, length in state['writes'] + [(stack - 2048, 2048)]):
            raise ValueError('Native mutex/same-task scheduling wrote unrelated state: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    rows = []
    for call in case['calls']:
        cpu.reg_write(arm.UC_ARM_REG_R0, case.get('ident', 14))
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(p[call], finish, count=5000)
        if boundary is None and (cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack):
            raise ValueError('Native mutex did not return with its own balanced stack')
        value = cpu.reg_read(arm.UC_ARM_REG_R0)
        rows.append(dict(call=call, boundary=boundary or 'returned',
                         status=None if boundary else value if value < 0x80000000 else value - 0x100000000,
                         owner=struct.unpack('<I', cpu.mem_read(entry + 12, 4))[0],
                         task_head=struct.unpack('<I', cpu.mem_read(task + 0x54, 4))[0]))
        if boundary:
            break
    if ([r['status'] for r in rows] != case['statuses'] or boundary != case.get('boundary')
            or [cpu.reg_read(register) for register in fp] != values
            or switches != restores or switches != int(case['kind'] in ('cycle', 'reenter'))
            or bytes(cpu.mem_read(entry - 4, 4)) != b'\x6b' * 4
            or bytes(cpu.mem_read(entry + 20, 4)) != b'\x6b' * 4):
        raise ValueError('Native mutex status/context restoration/bounds differ')
    if case['kind'] in ('cycle', 'reenter'):
        if (rows[0]['owner'] != task or rows[0]['task_head'] != entry or rows[-1]['owner'] != 0
                or rows[-1]['task_head'] != 0 or bytes(cpu.mem_read(p['guard'], 4)) != bytes(4)
                or cpu.reg_read(arm.UC_ARM_REG_CPSR) & 0x80):
            raise ValueError('Native mutex cycle failed to release ownership/kernel guard')
    if case['kind'] == 'reject' and before != (bytes(cpu.mem_read(entry, 20)), bytes(cpu.mem_read(task + 0x54, 4)),
                                              bytes(cpu.mem_read(p['guard'], 4))):
        raise ValueError('Native mutex rejection changed ownership/queue/guard state')
    # Normalize synthetic addresses to roles for a meaningful model comparison.
    for row in rows:
        row['owner'] = 'current_task' if row['owner'] == task else 'other_task' if row['owner'] else None
        row['task_head'] = 'mutex14' if row['task_head'] == entry else None
    return dict(calls=rows, native_scheduler_save_restore_pairs=switches, vfp_values_preserved=True,
                host_assigned_api_or_scheduler_return=False, host_restored_registers=False,
                synthetic_os_and_task_state=True, task_switch_to_different_task_executed=False,
                wait_enqueue_or_wakeup_executed=False)


def cases(maximum):
    return [dict(kind='cycle', calls=['acquire', 'release'], statuses=[0, 0]),
            dict(kind='reenter', calls=['acquire', 'acquire', 'release'], statuses=[0, -41, 0]),
            dict(kind='reject', context=1, calls=['acquire'], statuses=[-25]),
            dict(kind='reject', masked=True, calls=['acquire'], statuses=[-25]),
            dict(kind='reject', dispatch=False, calls=['acquire'], statuses=[-25]),
            dict(kind='reject', ident=0, calls=['acquire'], statuses=[-18]),
            dict(kind='reject', ident=maximum + 1, calls=['acquire'], statuses=[-18]),
            dict(kind='reject', calls=['release'], statuses=[-41]),
            dict(kind='reject', context=1, calls=['release'], statuses=[-25]),
            dict(kind='reject', masked=True, calls=['release'], statuses=[-25]),
            dict(kind='reject', ident=0, calls=['release'], statuses=[-18]),
            dict(kind='reject', ident=maximum + 1, calls=['release'], statuses=[-18]),
            dict(kind='busy', owner=True, calls=['acquire'], statuses=[None], boundary='owner_wait_transition'),
            dict(kind='busy', kernel_busy=True, calls=['acquire'], statuses=[None], boundary='wait_for_event')]


def compare(c2, reference):
    _, p = profile(c2)
    _, r = profile(reference)
    if p['maximum_id'] != r['maximum_id']:
        raise ValueError('C2/A7CR mutex bounds differ')
    rows = []
    for args in cases(p['maximum_id']):
        a, b = replay(c2, args), replay(reference, args)
        if a != b:
            raise ValueError('C2/A7CR native mutex/same-task scheduling differs')
        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-native-mutex/1', paired_cases=len(rows), cases=rows,
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
