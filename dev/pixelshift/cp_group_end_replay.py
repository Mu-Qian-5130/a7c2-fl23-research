"""Replay native group construction and TRINITY end/release boundaries offline.

Object storage, active state and OS context are synthetic. The original caller
builds constructor/destructor records, the post-allocation factory slice and
constructor execute, and native end follows its vtable release. Context detection
executes; void reference-lock calls are explicitly omitted. Stop BEFORE actual
resource release, pool return or a pending callback: no successful completion,
capture cancellation, motor centering or RTOS admission is supplied.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_metadata_replay import program
from cp_sequence_replay import machine
from cp_serial_replay import literals
from cp_steady_event_replay import profile as event_profile


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, model, _, _ = program(directory)
    _, event = event_profile(directory)
    target = model == 'ILCE-7CM2'
    p = dict(factory=0x473c10 if target else 0x473e28,
             descriptor=0x475af8 if target else 0x475d10,
             constructor=0xb0cb40 if target else 0xb0c99e,
             end=0x4757e8 if target else 0x475a00,
             release=0x473df4 if target else 0x47400c,
             addref=0x473d50 if target else 0x473f68,
             cleanup=0x473fd8 if target else 0x4741f0,
             handler=0x359e88 if target else 0x359fe8,
             context=event['context'], context_table=event['context_table'])
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def literal(at, size, register):
        values = [value for reg, value in literals(code(at, size)) if reg == register]
        if len(values) != 1:
            raise ValueError('Native group-end state binding is not unique')
        return values[0]

    def call(at, mnemonic='bl'):
        row = code(at, 4)
        if len(row) != 1 or row[0].mnemonic != mnemonic:
            raise ValueError('Original group call boundary changed')
        return int(row[0].op_str.lstrip('#'), 0)

    p['debug'] = literal(p['end'] + 4, 8, 'r0')
    p['group'] = literal(p['end'] + 0x22, 0x14, 'r5')
    p['ended'] = literal(p['end'] + 0x22, 0x14, 'r0')
    p['callback'] = literal(p['end'] + 0x42, 12, 'r1') + 8
    p['mode'] = literal(p['handler'], 14, 'r0') + 0x180
    if call(p['descriptor'] + 0x3c) != p['factory']:
        raise ValueError('Original descriptor builder no longer calls this factory')
    p['pool'] = call(p['release'] + 0x8a)
    p['resource'] = call(p['cleanup'] + 0x78)
    flag_getter = call(p['cleanup'] + 0xba)
    p['cleanup_flag'] = literal(flag_getter, 12, 'r0') + 0x20
    direct = [int(row.op_str.lstrip('#'), 0) for row in code(p['release'], 0x48)
              if row.mnemonic == 'blx']
    if len(direct) != 6 or direct[0] != p['context'] or direct[3] != p['context']:
        raise ValueError('Native release context/lock call ordering changed')
    p['semaphores'] = dict(zip([direct[1], direct[2], direct[4], direct[5]],
                               ['acquire_irq', 'acquire_task', 'release_irq', 'release_task']))
    p['reference_lock_returns'] = [row.address + row.size
                                  for row in code(p['release'], 0x48) + code(p['addref'], 0x38)
                                  if row.mnemonic == 'blx'
                                  and int(row.op_str.lstrip('#'), 0) in p['semaphores']]
    entry = call(p['end'] + 0x1e)
    p['reset_chain'] = []
    for _ in range(4):
        p['reset_chain'].append(entry)
        row = code(entry, 4)[0]
        if row.mnemonic != 'b.w':
            break
        entry = int(row.op_str.lstrip('#'), 0)
    else:
        raise ValueError('Native next-ordinal reset chain did not reach its setter')
    setter = code(entry, 12)
    if [(i.mnemonic, i.op_str) for i in setter[-2:]] != [('strb', 'r0, [r1]'), ('bx', 'lr')]:
        raise ValueError('Native next-ordinal setter changed')
    p['ordinal'] = literal(entry, 12, 'r1')
    return data, p


def replay(directory, *, references, pending_callback, interrupt_context, resource=False):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    if references not in (0, 1, 2) or pending_callback not in (0, 1) or interrupt_context not in (0, 1):
        raise ValueError('Expected the inspected reference/callback/context fixture values')
    if resource and references != 1:
        raise ValueError('Resource boundary is tested only at the final owned reference')
    data, p = profile(directory)
    cpu = machine(data, [])
    cpu.mem_map(0x1700000, 0x440000)
    for address in (p['context_table'], p['mode'], p['ordinal']):
        page = address & ~4095
        if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
            cpu.mem_map(page, 4096)
    body, stack, finish, callback = 0x30008000, 0x3001f000, 0x3001e000, 0x30018000
    for core in range(4):
        cpu.mem_write(p['context_table'] + 4 * core, struct.pack('<I', 0x30001000))
    cpu.mem_write(0x30001040, struct.pack('<I', interrupt_context))
    cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0x00f00000)
    cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
    cpu.mem_write(p['mode'], struct.pack('<I', 1))
    cpu.mem_write(p['cleanup_flag'], bytes([1]))
    cpu.mem_write(body - 4, b'\x6b' * 4 + bytes(0x5c20) + b'\x6b' * 4)
    phase, boundary, semaphores, contexts = 'descriptor', None, [], 0
    cleanup_started, cleanup_finished = False, False

    def hook(uc, at, size, unused):
        nonlocal boundary, contexts, cleanup_started, cleanup_finished
        if at == p['context']:
            contexts += 1
        if at in p['semaphores']:
            # These two reference-method call sites do not consume R0's result.
            # No acquired/success value is invented; lock scheduling is omitted.
            if uc.reg_read(arm.UC_ARM_REG_R0) != 0x36:
                raise ValueError('Native reference lock no longer uses semaphore 0x36')
            if uc.reg_read(arm.UC_ARM_REG_LR) & ~1 not in p['reference_lock_returns']:
                raise ValueError('Only the reference methods unused-return lock calls may be omitted')
            semaphores.append(p['semaphores'][at])
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR) | 1)
            return
        if at in (p['pool'], p['resource'], callback):
            boundary = ('pool_return' if at == p['pool'] else
                        'resource_release' if at == p['resource'] else 'pending_callback')
            cleanup_finished = at == p['pool']
            uc.emu_stop()
            return
        if at == p['cleanup']:
            cleanup_started = True
        if not 0x108000 <= at or at + size > 0x108000 + len(data):
            raise ValueError('Group replay reached an omitted execution region: ' + hex(at))

    def write_hook(uc, access, address, size, value, unused):
        allowed = [(body, 0x5c20), (stack - 4096, 4096 + (64 if phase == 'descriptor' else 0)),
                   (p['ordinal'], 1), (p['ended'], 1), (p['group'], 4),
                   (p['callback'], 4), (p['cleanup_flag'], 1)]
        if not any(lo <= address and address + size <= lo + length for lo, length in allowed):
            raise ValueError('Native group replay changed unrelated state: ' + hex(address))

    def run(at, stop=finish):
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(at | 1, stop, count=30000)
        if boundary is None and cpu.reg_read(arm.UC_ARM_REG_PC) != stop:
            raise ValueError('Native group stage missed its bounded end')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    if references:
        run(p['descriptor'], p['descriptor'] + 0x3c)
        destructor = cpu.reg_read(arm.UC_ARM_REG_R1)
        constructor_record = cpu.reg_read(arm.UC_ARM_REG_R0)
        if (struct.unpack('<I', cpu.mem_read(destructor + 8, 4))[0] != p['cleanup'] | 1
                or struct.unpack('<I', cpu.mem_read(constructor_record + 8, 4))[0] != p['constructor'] | 1):
            raise ValueError('Original caller built different group callbacks')
        cpu.reg_write(arm.UC_ARM_REG_R4, body)
        cpu.reg_write(arm.UC_ARM_REG_R9, destructor)
        phase = 'post_allocation_factory'
        run(p['factory'] + 0x3a, p['factory'] + 0xb4)
        cpu.reg_write(arm.UC_ARM_REG_R0, body)
        cpu.reg_write(arm.UC_ARM_REG_R1, 0)
        phase = 'constructor'
        run(p['constructor'])
        table, count = struct.unpack('<2I', cpu.mem_read(body, 8))
        if (count != 1 or struct.unpack('<2I', cpu.mem_read(table + 8, 8)) != (p['addref'] | 1, p['release'] | 1)
                or bytes(cpu.mem_read(body + 0x52e8, 36)) != b'\xff' * 36):
            raise ValueError('Native group vtable, reference or empty handles differ')
        if references == 2:
            cpu.reg_write(arm.UC_ARM_REG_R0, body)
            phase = 'add_reference'
            run(p['addref'])
        if resource:
            cpu.mem_write(body + 0x52ec, struct.pack('<I', 0x1234))
    cpu.mem_write(p['group'], struct.pack('<I', body if references else 0))
    cpu.mem_write(p['callback'], struct.pack('<I', callback if pending_callback else 0))
    cpu.mem_write(p['ordinal'], bytes([3]))
    phase = 'group_end'
    run(p['end'])
    actual_boundary = boundary or 'returned'
    expected_boundary = ('resource_release' if resource else 'pool_return' if references == 1 else
                         'pending_callback' if pending_callback else 'returned')
    group_retained = struct.unpack('<I', cpu.mem_read(p['group'], 4))[0] != 0
    callback_retained = struct.unpack('<I', cpu.mem_read(p['callback'], 4))[0] != 0
    count = struct.unpack('<I', cpu.mem_read(body + 4, 4))[0] if references else None
    if (actual_boundary != expected_boundary or group_retained != (references == 1)
            or callback_retained != (bool(pending_callback) and references == 1)
            or (references and count != references - 1)
            or cpu.mem_read(p['ordinal'], 1)[0] != 0 or cpu.mem_read(p['ended'], 1)[0] != 1
            or bytes(cpu.mem_read(p['mode'], 4)) != struct.pack('<I', 1)
            or bytes(cpu.mem_read(body - 4, 4)) != b'\x6b' * 4
            or bytes(cpu.mem_read(body + 0x5c20, 4)) != b'\x6b' * 4):
        raise ValueError('Native end/reference/callback state differs at its boundary')
    if references == 1 and not resource:
        if bytes(cpu.mem_read(body + 0x1c, 0x5c04)) != bytes(0x5c04) or cpu.mem_read(p['cleanup_flag'], 1)[0] != 0:
            raise ValueError('Native empty-resource cleanup did not clear the object/software flag')
    if resource and struct.unpack('<I', cpu.mem_read(body + 0x52ec, 4))[0] != 0x1234:
        raise ValueError('Resource handle was modified before its native release boundary')
    expected_pairs = (2 if references == 2 else 1 if references == 1 else 0)
    suffix = 'irq' if interrupt_context else 'task'
    if semaphores != ['acquire_' + suffix, 'release_' + suffix] * expected_pairs or contexts != expected_pairs * 2:
        raise ValueError('Native context detection/reference-lock selection differs')
    return dict(boundary=actual_boundary, reference_count=count, next_ordinal=0, end_marker=1,
                group_pointer_retained=group_retained, pending_callback_retained=callback_retained,
                native_constructor_executed=bool(references), native_cleanup_started=cleanup_started,
                native_empty_resource_cleanup_finished=cleanup_finished,
                void_reference_semaphore_calls_omitted=semaphores,
                original_context_detector_calls=contexts, synthetic_cp_enable_word_unchanged=True,
                pool_return_executed=False, pending_callback_executed=False, resource_release_executed=False,
                object_storage_and_os_state_synthetic=True, allocation_executed=False,
                scheduler_executed=False, centering_verified=False)


def compare(c2, reference):
    rows = []
    inputs = [dict(references=r, pending_callback=c, interrupt_context=i)
              for r in (0, 1, 2) for c in (0, 1) for i in (0, 1)]
    inputs += [dict(references=1, pending_callback=0, interrupt_context=i, resource=True) for i in (0, 1)]
    for args in inputs:
        a, b = replay(c2, **args), replay(reference, **args)
        if a != b:
            raise ValueError('C2/A7CR native group-end behavior differs')
        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-group-end/1', paired_cases=len(rows), cases=rows,
                camera_io=False, installable=False, physical_shift_verified=False, centering_verified=False)


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
