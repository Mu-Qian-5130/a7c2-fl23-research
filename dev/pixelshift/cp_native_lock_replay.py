"""Execute original ARM reference-lock APIs against synthetic OS memory.

Native LDREX/STREX, holder bookkeeping and release/barriers run without a
host-supplied return value. Single-core uncontended execution and native
rejections are checked. Contention stops BEFORE WFE: no wakeup, cross-core
ordering, interrupt scheduling or physical hardware completion is supplied.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_group_end_replay import profile as group_profile
from cp_sequence_replay import machine
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    data, group = group_profile(directory)
    entries = {name: at for at, name in group['locks'].items()}
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def literal(at, size, register):
        values = [v for r, v in literals(code(at, size)) if r == register]
        if len(values) != 1:
            raise ValueError('Native reference-lock state binding is not unique')
        return values[0]

    task = entries['acquire_task']
    table = literal(task + 0x64, 12, 'r1')
    context = literal(task, 20, 'ip')
    maximum = code(task + 0x48, 8)
    if [i.mnemonic for i in maximum] != ['movwge', 'movtge']:
        raise ValueError('Original reference-lock ID bound changed')
    low, high = [int(i.op_str.split('#')[1], 0) for i in maximum]
    maximum_address = low | high << 16
    maximum_id = struct.unpack_from('<I', data, maximum_address - 0x108000)[0]
    if context != group['context_table'] or maximum_id < 0x36:
        raise ValueError('Native lock context/ID range does not cover the reference methods')
    regions, waits, mnemonics = [], [], {}
    for name, at in entries.items():
        size = 0x150 if name.startswith('acquire') else 0xe0
        rows = code(at, size)
        if name.startswith('acquire') and not {'ldrex', 'strex', 'dmb'}.issubset({i.mnemonic for i in rows}):
            raise ValueError('Native acquisition no longer executes its atomic/barrier instructions')
        if name.startswith('release') and not {'dmb', 'dsb', 'sev'}.issubset({i.mnemonic for i in rows}):
            raise ValueError('Native release no longer executes its barrier/event instructions')
        regions.append((at, at + size))
        waits += [i.address for i in rows if i.mnemonic == 'wfe']
        mnemonics.update({i.address: i.mnemonic for i in rows})
    return data, dict(entries=entries, table=table, context_table=context,
                      maximum_id=maximum_id, regions=regions, waits=waits, mnemonics=mnemonics)


def setup(cpu, directory, *, interrupt_context, irq_masked=False, locked=False, owner=0):
    import unicorn.arm_const as arm
    _, p = profile(directory)
    obj, tcb = 0x30014000, 0x30001000
    for address in (p['table'] + (0x36 - 1) * 4, p['context_table']):
        page = address & ~4095
        if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
            cpu.mem_map(page, 4096)
    for core in range(4):
        cpu.mem_write(p['context_table'] + core * 4, struct.pack('<I', tcb))
    cpu.mem_write(tcb + 0x40, struct.pack('<I', interrupt_context))
    cpu.mem_write(tcb + 0x10, struct.pack('<I', owner))
    cpu.mem_write(obj - 4, b'\x6b' * 4 + struct.pack('<3I', int(locked), 0, int(owner != 0)) + b'\x6b' * 4)
    cpu.mem_write(p['table'] + (0x36 - 1) * 4, struct.pack('<I', obj))
    cpsr = cpu.reg_read(arm.UC_ARM_REG_CPSR)
    cpu.reg_write(arm.UC_ARM_REG_CPSR, cpsr | 0x80 if irq_masked else cpsr & ~0x80)
    return dict(object=obj, tcb=tcb)


def replay(directory, case):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    cpu = machine(data, [])
    state = setup(cpu, directory, interrupt_context=case['context'], irq_masked=case.get('masked', False),
                  locked=case.get('locked', False), owner=case.get('owner', 0))
    obj, tcb, stack, finish = state['object'], state['tcb'], 0x3001f000, 0x3001e000
    boundary, steps, atomics, barriers = None, 0, [], []
    names = case['calls']

    def hook(uc, at, size, unused):
        nonlocal boundary, steps
        if at in p['waits']:
            boundary = 'wait_for_event'
            uc.emu_stop()
            return
        if not any(lo <= at and at + size <= hi for lo, hi in p['regions']):
            raise ValueError('Native lock reached an unmodeled function: ' + hex(at))
        # Count only actually executed original instructions, not static presence.
        mnemonic = p['mnemonics'][at]
        if mnemonic in ('ldrex', 'strex'):
            atomics.append(mnemonic)
        if mnemonic in ('dmb', 'dsb', 'sev'):
            barriers.append(mnemonic)
        steps += 1

    def write_hook(uc, access, address, size, value, unused):
        allowed = [(obj, 12), (tcb + 0x10, 4), (stack - 512, 512)]
        if not any(lo <= address and address + size <= lo + length for lo, length in allowed):
            raise ValueError('Native lock changed unrelated synthetic state: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    rows = []
    for name in names:
        cpu.reg_write(arm.UC_ARM_REG_R0, case.get('ident', 0x36))
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(p['entries'][name], finish, count=2000)
        if boundary is None and (cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack):
            raise ValueError('Original lock API did not return with its own balanced stack')
        value = cpu.reg_read(arm.UC_ARM_REG_R0)
        signed = value if value < 0x80000000 else value - 0x100000000
        rows.append(dict(call=name, boundary=boundary or 'returned', status=None if boundary else signed,
                         words=list(struct.unpack('<3I', cpu.mem_read(obj, 12))),
                         owner=struct.unpack('<I', cpu.mem_read(tcb + 0x10, 4))[0],
                         irq_masked=bool(cpu.reg_read(arm.UC_ARM_REG_CPSR) & 0x80)))
        if boundary:
            break
    if (bytes(cpu.mem_read(obj - 4, 4)) != b'\x6b' * 4
            or bytes(cpu.mem_read(obj + 12, 4)) != b'\x6b' * 4
            or struct.unpack('<I', cpu.mem_read(tcb + 0x40, 4))[0] != case['context']):
        raise ValueError('Native lock changed its bounds or context input')
    if case['kind'] == 'cycle':
        if ([r['status'] for r in rows] != [0, 0] or rows[0]['words'] != [1, 0, 1]
                or rows[0]['owner'] != 0x36 or not rows[0]['irq_masked']
                or rows[1]['words'] != [0, 0, 0] or rows[1]['owner'] != 0 or rows[1]['irq_masked']
                or atomics != ['ldrex', 'strex'] or barriers != ['dmb', 'dmb', 'dsb', 'sev']):
            raise ValueError('Original native lock/unlock state transition differs')
    elif case['kind'] == 'busy':
        if (boundary != 'wait_for_event' or rows[0]['words'] != [1, 0, 0] or rows[0]['owner'] != 0
                or rows[0]['irq_masked'] or atomics != ['ldrex']):
            raise ValueError('Native contention did not stop at the actual wait boundary')
    else:
        expected_words = [int(case.get('locked', False)), 0, int(case.get('owner', 0) != 0)]
        if (rows[0]['status'] != case['expected'] or rows[0]['words'] != expected_words
                or rows[0]['owner'] != case.get('owner', 0) or atomics):
            raise ValueError('Native rejection changed lock state or returned a different error')
    return dict(calls=rows, original_atomic_instructions=atomics, original_barriers=barriers,
                native_steps=steps, host_assigned_return_value=False, synthetic_os_memory=True,
                actual_interrupt_or_cross_core_scheduling_executed=False, wake_or_cross_core_effect_verified=False)


def cases(maximum_id):
    rows = []
    for context, suffix in ((0, 'task'), (1, 'irq')):
        acquire, release = 'acquire_' + suffix, 'release_' + suffix
        rows += [dict(kind='cycle', context=context, calls=[acquire, release]),
                 dict(kind='reject', context=1 - context, calls=[acquire], expected=-25),
                 dict(kind='reject', context=context, masked=True, calls=[acquire], expected=-25)]
        rows += [dict(kind='reject', context=context, ident=ident, calls=[acquire], expected=-18)
                 for ident in (0, maximum_id + 1)]
        rows += [dict(kind='reject', context=context, owner=0x35, locked=True, calls=[release], expected=-28),
                 dict(kind='reject', context=1 - context, calls=[release], expected=-25),
                 dict(kind='busy', context=context, locked=True, calls=[acquire])]
    return rows


def compare(c2, reference):
    _, p = profile(c2)
    _, r = profile(reference)
    if p['maximum_id'] != r['maximum_id']:
        raise ValueError('C2/A7CR native reference-lock bounds differ')
    rows = []
    for case in cases(p['maximum_id']):
        a, b = replay(c2, case), replay(reference, case)
        if a != b:
            raise ValueError('C2/A7CR native reference-lock execution differs')
        rows.append(dict(input=case, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-native-reference-lock/1', paired_cases=len(rows),
                cases=rows, camera_io=False, installable=False, physical_shift_verified=False)


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
