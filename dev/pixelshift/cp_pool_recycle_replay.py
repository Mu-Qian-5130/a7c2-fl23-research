"""Replay native pool range-check/free-list recycling, offline only.

Original checked lock APIs run on synthetic OS/pool state. This starts inside
the pool-return subpath, not its outer resource/entry-lock wrapper. Range-check
return values and actual list updates are observed separately. No allocation,
real resource return, wakeup or group completion is supplied.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_group_end_replay import profile as group_profile
from cp_native_lock_replay import profile as lock_profile, setup as setup_locks
from cp_sequence_replay import machine
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, group = group_profile(directory)
    _, locks = lock_profile(directory)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def call(at):
        rows = code(at, 4)
        if len(rows) != 1 or rows[0].mnemonic != 'bl':
            raise ValueError('Original pool helper call changed')
        return int(rows[0].op_str.lstrip('#'), 0)

    retire = call(group['pool'] + 0x24)
    validate = call(retire + 0x12)
    free = call(validate + 0x12)
    roots = [v for r, v in literals(code(retire + 8, 8)) if r == 'r4']
    if len(roots) != 1 or (code(validate + 0x16, 2)[0].mnemonic, code(validate + 0x16, 2)[0].op_str) != ('movs', 'r0, #1'):
        raise ValueError('Native pool metadata/range-return behavior changed')
    if (code(free + 0x20, 2)[0].mnemonic, code(free + 0x20, 2)[0].op_str) != ('cbz', 'r0, #' + hex(free + 0x26)):
        raise ValueError('Native free-list helper no longer checks acquisition status')
    return data, dict(validate=validate, free=free, root=roots[0], trace=call(validate + 0x22),
                      context=group['context'], locks=locks,
                      regions=[(validate, validate + 0x2a), (free, free + 0x4c),
                               (group['context'], group['context'] + 0x34)] + locks['regions'])


def replay(directory, case):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    cpu = machine(data, [])
    state = setup_locks(cpu, directory, interrupt_context=case['context'], irq_masked=case.get('masked', False))
    root, base, slot_size, stack, finish = p['root'], 0x30008000, 0x5c20, 0x3001f000, 0x3001e000
    if not any(lo <= root <= hi for lo, hi, _ in cpu.mem_regions()):
        cpu.mem_map(root & ~4095, 4096)
    slot = case.get('slot', 0)
    node, old_head = base + slot * slot_size, base + (1 - slot) * slot_size
    pointer = {'valid': node, 'below': base - 4, 'end': base + 2 * slot_size, 'null': 0}[case['pointer']]
    before = struct.pack('<6I', old_head, 2, 1, 0xffffffff, base, 2 * slot_size)
    cpu.mem_write(root - 4, b'\x6b' * 4 + before + b'\x6b' * 4)
    cpu.mem_write(node, struct.pack('<I', 0x12345678))
    cpu.mem_write(old_head, bytes(4))
    traces, lock_calls, helper_status, lock_status = 0, [], None, None

    def signed(value):
        return value if value < 0x80000000 else value - 0x100000000

    def hook(uc, at, size, unused):
        nonlocal traces, helper_status, lock_status
        if at == p['trace']:
            # Original diagnostic return is overwritten by MOVS R0,#0.
            traces += 1
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR) | 1)
            return
        if at == p['free'] + 0x20:
            lock_status = signed(uc.reg_read(arm.UC_ARM_REG_R0))
        if at == p['validate'] + 0x16:
            helper_status = signed(uc.reg_read(arm.UC_ARM_REG_R0))
        if at in p['locks']['entries'].values():
            lock_calls.append(next(k for k, v in p['locks']['entries'].items() if v == at))
        if at in p['locks']['waits']:
            raise ValueError('Uncontended recycle fixture unexpectedly reached WFE')
        if not any(lo <= at and at + size <= hi for lo, hi in p['regions']):
            raise ValueError('Native pool recycle reached an omitted function: ' + hex(at))

    def write_hook(uc, access, address, size, value, unused):
        allowed = [(root, 24), (node, 4), (state['object'], 12),
                   (state['tcb'] + 0x10, 4), (stack - 512, 512)]
        if not any(lo <= address and address + size <= lo + length for lo, length in allowed):
            raise ValueError('Native pool recycle changed unrelated state: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.reg_write(arm.UC_ARM_REG_R0, root)
    cpu.reg_write(arm.UC_ARM_REG_R1, pointer)
    cpu.reg_write(arm.UC_ARM_REG_SP, stack)
    cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
    cpu.emu_start(p['validate'] | 1, finish, count=2000)
    status = signed(cpu.reg_read(arm.UC_ARM_REG_R0))
    after = bytes(cpu.mem_read(root, 24))
    words = list(struct.unpack('<6I', after))
    recycled = words[0] == node and words[2] == 2
    valid = case['pointer'] == 'valid'
    should_recycle = valid and not case.get('masked', False)
    expected = bytearray(before)
    if should_recycle:
        struct.pack_into('<I', expected, 0, node)
        struct.pack_into('<I', expected, 8, 2)
    suffix = 'irq' if case['context'] else 'task'
    expected_calls = ([] if not valid else ['acquire_' + suffix] if case.get('masked') else
                      ['acquire_' + suffix, 'release_' + suffix])
    if (cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack
            or status != int(valid) or after != expected or recycled != should_recycle
            or helper_status != (1 if should_recycle else 0 if valid else None)
            or lock_status != (0 if should_recycle else -25 if valid else None)
            or lock_calls != expected_calls or traces != int(not valid)
            or bytes(cpu.mem_read(node, 4)) != struct.pack('<I', old_head if should_recycle else 0x12345678)
            or bytes(cpu.mem_read(old_head, 4)) != bytes(4)
            or bytes(cpu.mem_read(root - 4, 4)) != b'\x6b' * 4
            or bytes(cpu.mem_read(root + 24, 4)) != b'\x6b' * 4
            or bytes(cpu.mem_read(state['object'], 12)) != bytes(12)
            or bytes(cpu.mem_read(state['tcb'] + 0x10, 4)) != bytes(4)):
        raise ValueError('Original recycle range/lock/list-update behavior differs')
    return dict(range_validator_return=status, checked_lock_status=lock_status,
                recycle_helper_return=helper_status, actual_list_update=recycled,
                free_count=words[2], native_lock_calls=lock_calls, diagnostic_calls_omitted=traces,
                host_assigned_return_value=False, synthetic_pool_and_os_state=True,
                complete_pool_return_wrapper_executed=False, group_completion_executed=False)


def compare(c2, reference):
    inputs = [dict(context=c, pointer='valid', slot=s) for c in (0, 1) for s in (0, 1)]
    inputs += [dict(context=c, pointer='valid', masked=True) for c in (0, 1)]
    inputs += [dict(context=c, pointer=kind) for c in (0, 1) for kind in ('below', 'end', 'null')]
    rows = []
    for args in inputs:
        a, b = replay(c2, args), replay(reference, args)
        if a != b:
            raise ValueError('C2/A7CR native pool recycling differs')
        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-pool-recycle/1', paired_cases=len(rows), cases=rows,
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
