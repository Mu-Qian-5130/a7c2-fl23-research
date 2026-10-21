"""Replay the original mode-23 callback's stage dispatch, offline only.

The existing native selector/descriptor replay identifies callbacks 4 and 9.
Each callback is then invoked separately with a SYNTHETIC context stage. Its
original TBB and tail branch execute; execution stops BEFORE the selected
child handler. This is a dispatch map, not an executed capture sequence,
scheduler, actuator operation, completion or cancellation test.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_sequence_replay import descriptors, machine, profile as sequence_profile, select


@lru_cache(maxsize=4)
def profile(directory, index):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    if index not in (4, 9):
        raise ValueError('Only the two mode-23 callback descriptors are inspected')
    data, sequence = sequence_profile(directory)
    entry = descriptors(directory)[index][2] & ~1
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    header = code(entry, 12)
    if ([i.mnemonic for i in header] != ['ldrb.w', 'cmp', 'bhi', 'tbb']
            or header[0].op_str != 'r1, [r0, #0x27]'
            or header[3].op_str != '[pc, r1]'):
        raise ValueError('Native callback no longer has the inspected stage dispatch')
    limit = int(header[1].op_str.split('#')[1], 0)
    if limit != (6 if index == 4 else 7):
        raise ValueError('Native callback stage count changed')
    table = entry + 12
    reject = int(header[2].op_str.lstrip('#'), 0)
    rejection = code(reject, 4)
    if ([i.mnemonic for i in rejection] != ['movs', 'bx']
            or [i.op_str for i in rejection] != ['r0, #5', 'lr']):
        raise ValueError('Native callback invalid-stage return changed')
    branches, children = [], []
    for value in data[table - 0x108000:table - 0x108000 + limit + 1]:
        branch = table + 2 * value
        rows = code(branch, 4)
        if len(rows) != 1 or rows[0].mnemonic != 'b.w':
            raise ValueError('Native stage table no longer points to a tail branch')
        branches.append(branch)
        children.append(int(rows[0].op_str.lstrip('#'), 0))
    # Model-specific inspected children, not a guessed inter-model address delta.
    target = sequence['selector'] == 0x48335c
    expected = ([0x487214, 0x49a970, 0x4875d0, 0xb17208, 0x49ae14, 0x497308, 0x487e60]
                if target else
                [0x487430, 0x49ab8c, 0x4877ec, 0xb17066, 0x49b030, 0x497524, 0x48807c])
    if index == 9:
        expected.insert(3, 0xb158ee if target else 0xb1574c)
    if children != expected:
        raise ValueError('Native mode-23 child ordering differs from the inspected path')
    return data, dict(entry=entry, limit=limit, reject=reject,
                      branches=branches, children=children)


def dispatch(directory, *, index, stage):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP, UC_ARM_REG_PC
    if not 0 <= stage <= 255:
        raise ValueError('Context stage is one byte')
    data, p = profile(directory, index)
    cpu = machine(data, [])
    context, finish, stack = 0x30010000, 0x3001e000, 0x3001f000
    original = bytearray(b'\xa5' * 64)
    struct.pack_into('<I', original, 0, 0x30000000)
    original[0x27] = stage
    cpu.mem_write(context, bytes(original))
    cpu.reg_write(UC_ARM_REG_R0, context)
    child = None

    def hook(uc, address, size, unused):
        nonlocal child
        if address in p['children']:
            child = address
            if uc.reg_read(UC_ARM_REG_R0) != context:
                raise ValueError('Native callback changed its context argument')
            uc.emu_stop()
            return
        allowed = [(p['entry'], p['entry'] + 12), (p['reject'], p['reject'] + 4)]
        allowed += [(at, at + 4) for at in p['branches']]
        if not any(lo <= address and address + size <= hi for lo, hi in allowed):
            raise ValueError('Stage replay reached omitted code: ' + hex(address))

    def write_hook(uc, access, address, size, value, unused):
        raise ValueError('Stage dispatcher unexpectedly wrote memory: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.emu_start(p['entry'] | 1, finish, count=32)
    valid = stage <= p['limit']
    if (bytes(cpu.mem_read(context, 64)) != original
            or cpu.reg_read(UC_ARM_REG_SP) != stack
            or (valid and child != p['children'][stage])
            or (not valid and (child is not None or cpu.reg_read(UC_ARM_REG_PC) != finish
                               or cpu.reg_read(UC_ARM_REG_R0) != 5))):
        raise ValueError('Native stage selection, rejection or unchanged-context check failed')
    return dict(stage=stage, selected_child=None if child is None else hex(child),
                child_index=stage if valid else None, rejected=not valid,
                native_return=5 if not valid else None, child_executed=False,
                scheduler_executed=False, camera_io=False, physical_shift_verified=False)


def compare(c2, reference):
    cases, selections = [], []
    for first, index in ((1, 4), (0, 9)):
        args = dict(mode=23, ordinal=0, first_flag=first, second_flag=0)
        a, b = select(c2, **args), select(reference, **args)
        if a['sequence_index'] != index or b['sequence_index'] != index:
            raise ValueError('Native mode-23 selector no longer chooses the inspected callback')
        selections.append(dict(input=args, target=a, reference=b))
        _, p = profile(c2, index)
        for stage in list(range(p['limit'] + 2)) + [255]:
            a, b = dispatch(c2, index=index, stage=stage), dispatch(reference, index=index, stage=stage)
            if ({k: v for k, v in a.items() if k != 'selected_child'}
                    != {k: v for k, v in b.items() if k != 'selected_child'}):
                raise ValueError('C2/A7CR native stage selection differs')
            cases.append(dict(index=index, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-stage/1', paired_cases=len(cases),
                selections=selections, cases=cases, separate_callback_invocations=True,
                camera_io=False, installable=False, physical_shift_verified=False,
                exposure_or_centering_executed=False)


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
