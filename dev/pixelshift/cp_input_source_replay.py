"""Trace original register-word selection into the TC input snapshot/getter.

Original register readers, source selector, cache-store slice, fixed-point
getter, frame-field stores and full 340-byte snapshot copy execute. Register
objects/values, source flags/bounds/policy and stage ordering are fixtures.
No device, peripheral initialization, ready/settled acknowledgement or exposure
is supplied or inferred. MMIO addresses are synthetic memory, not board mappings.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_metadata_replay import program
from cp_sequence_replay import machine
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, model, _, _ = program(directory)
    target = model == 'ILCE-7CM2'
    delta = 0x1a2 if target else 0
    p = dict(select=0xb3bff2+delta, cache_store=0xb3bafc+delta,
             frame_store=0xb3ca58+delta, copy=0xac0142+delta,
             getter=0xac0aea+delta, memcpy=0x61e60c if target else 0x61e824)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at-0x108000:at-0x108000+size], at))

    def call(at):
        row = code(at, 4)
        if len(row) != 1 or row[0].mnemonic not in ('bl', 'blx'):
            raise ValueError('Native TC input-source call changed')
        return int(row[0].op_str.lstrip('#'), 0)

    def literal(at, size, register):
        values = [value for reg, value in literals(code(at, size)) if reg == register]
        if len(values) != 1:
            raise ValueError('Native TC input-source binding is not unique')
        return values[0]

    p['reader'] = call(p['select']+0x3a)
    p['round'] = call(p['frame_store']+8)
    p['cache'] = literal(p['round'], 8, 'r2')
    p['available'] = literal(p['round']+0x1c, 8, 'r0')
    p['a_flag'], p['b_flag'], p['chosen'] = p['available']+3, p['available']+4, p['available']+5
    p['offset'] = literal(p['select']+0x7c, 12, 'r1')
    p['policy'] = literal(p['select']+0x96, 12, 'r6')
    bounds = [value for reg, value in literals(code(p['select']+0x170, 24)) if reg == 'r0']
    if len(bounds) != 2:
        raise ValueError('Native TC selector bounds changed')
    p['bounds'] = [value+8 for value in bounds]
    p['debug_getter'] = call(p['select']+0xe6)
    p['debug'] = literal(p['debug_getter'], 8, 'r1')+0x32
    p['snapshot'] = literal(p['copy']+6, 16, 'r0')
    p['extra_getter'] = call(p['copy']+0x1a)
    p['extra'] = literal(p['extra_getter'], 8, 'r0')+0x36
    if literal(p['getter'], 8, 'r2') != p['snapshot'] or call(p['copy']+0x14) != p['memcpy']:
        raise ValueError('Native input copy/getter no longer share their actual source')
    p['regions'] = [(p['select'], p['select']+0x19c), (p['reader'], p['reader']+0x1c),
                    (p['cache_store'], p['cache_store']+0x10),
                    (p['frame_store'], p['frame_store']+0x1a),
                    (p['round'], p['round']+0x28), (p['copy'], p['copy']+0x22),
                    (p['getter'], p['getter']+0x16),
                    (p['memcpy'], p['memcpy']+0x300),
                    (p['extra_getter'], p['extra_getter']+10),
                    (p['debug_getter'], p['debug_getter']+12)]
    return data, p


def replay(directory, *, flags=(1, 1), present=(1, 1), same_rows=False, policy=1, available=0,
           observe_snapshot=None):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    pages = set()
    for at, length in [(p['cache'], 8), (p['available'], 8), (p['offset'], 2),
                       (p['policy'], 1), (p['bounds'][0], 4), (p['bounds'][1], 4),
                       (p['debug'], 1), (p['snapshot'], 340), (p['extra'], 2)]:
        pages.update(range(at & ~4095, (at+length+4095) & ~4095, 4096))
    cpu = machine(data, pages)
    obj, child, frame, output = 0x30001000, 0x30003000, 0x30006000, 0x30008000
    stack, caller_frame, finish = 0x3001f000, 0x3001ee00, 0x3001e000
    register_bases = (0x32000000, 0x32010000)
    raw = [(0xdead0123, 0xbeef0456), (0xffff2180, 0x80004111)]
    register_addresses = []
    for n, base in enumerate(register_bases):
        cpu.mem_map(base+0xb000, 4096)
        at = child+0x1304+8*n
        cpu.mem_write(at, struct.pack('<II', 0, base if present[n] else 0))
        cpu.mem_write(base+0xbb1c, struct.pack('<2I', *raw[n]))
        register_addresses += [base+0xbb1c, base+0xbb20] if present[n] else []
    cpu.mem_write(obj+12, struct.pack('<I', child))
    for at, value in ((p['a_flag'], flags[0]), (p['b_flag'], flags[1]),
                      (p['policy'], policy), (p['available'], available), (p['debug'], 0)):
        cpu.mem_write(at, bytes([value]))
    cpu.mem_write(p['offset'], struct.pack('<H', 3))
    for at, value in zip(p['bounds'], (256, 512)):
        cpu.mem_write(at, struct.pack('<I', value))
    cpu.mem_write(frame, b'\x5a'*340)
    cpu.mem_write(p['snapshot'], b'\xa5'*340)
    cpu.mem_write(p['cache']-4, b'\x6b'*16)
    phase, reads, copies, getter_status = 'select', [], [], None

    def code_hook(uc, at, length, unused):
        if not any(lo <= at and at+length <= hi for lo, hi in p['regions']):
            raise ValueError('Native TC source entered an unresolved dependency: ' + hex(at))
        if phase == 'frame' and at == p['frame_store']+0xc:
            nonlocal getter_status
            getter_status = uc.reg_read(arm.UC_ARM_REG_R0)
        if at == p['memcpy']:
            copies.append(tuple(uc.reg_read(reg) for reg in
                                (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2)))

    def read_hook(uc, access, at, length, value, unused):
        if 0x32000000 <= at < 0x32020000:
            reads.append((at, length))

    def write_hook(uc, access, at, length, value, unused):
        if stack-4096 <= at and at+length <= stack:
            return
        ranges = dict(select=[(p['chosen'], 1)], cache=[(p['cache'], 8)],
                      frame=[(frame+0xa2, 4)], copy=[(p['snapshot'], 340), (p['extra'], 2)],
                      getter=[(output, 8)])[phase]
        if not any(lo <= at and at+length <= lo+n for lo, n in ranges):
            raise ValueError('Native TC source changed unrelated state: ' + hex(at))

    ch = cpu.hook_add(UC_HOOK_CODE, code_hook)
    rh = cpu.hook_add(UC_HOOK_MEM_READ, read_hook)
    wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)

    def run(at, end=finish, sp=stack):
        cpu.reg_write(arm.UC_ARM_REG_SP, sp)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(at | 1, end, count=5000)
        if cpu.reg_read(arm.UC_ARM_REG_PC) != end:
            raise ValueError('Native TC source stage exceeded its instruction bound')
        if end == finish and cpu.reg_read(arm.UC_ARM_REG_SP) != sp:
            raise ValueError('Original TC source function returned with an unbalanced stack')

    cpu.reg_write(arm.UC_ARM_REG_R0, obj)
    cpu.reg_write(arm.UC_ARM_REG_R1, 0)
    cpu.reg_write(arm.UC_ARM_REG_R2, 100)
    cpu.reg_write(arm.UC_ARM_REG_R3, 512)
    cpu.mem_write(caller_frame, struct.pack('<II', 100 if same_rows else 200, caller_frame+8))
    run(p['select'], sp=caller_frame)
    a = [raw[0][0] & 8191, raw[0][1] & 16383] if present[0] else [0, 0]
    b = [raw[1][0] & 8191, raw[1][1] & 16383] if present[1] else [0, 0]
    x, y, bx, by = (a[0] if flags[0] else 0), (a[1] if flags[0] else 0), 0, 0
    chosen = False
    if flags[1]:
        bx, by = b[0]+3, b[1]
        if not flags[0]:
            chosen = True
        elif not same_rows:
            chosen = by < y
        elif policy:
            chosen = bx <= x
        else:
            x = x if x <= 256 else 0
            bx = bx if bx <= 515 else 0
            chosen = x <= bx
    expected = [bx, by] if chosen else [x, y]
    expected_q12 = struct.pack('<2I', *(value << 12 for value in expected))
    if (bytes(cpu.mem_read(caller_frame+8, 8)) != expected_q12
            or cpu.mem_read(p['chosen'], 1)[0] != int(chosen)
            or reads != [(at, 4) for at in register_addresses]):
        raise ValueError('Native register masks/selection disagree with independent fixture logic')
    phase = 'cache'
    run(p['cache_store'], p['cache_store']+0x10, caller_frame)
    if bytes(cpu.mem_read(p['cache']-4, 16)) != b'\x6b'*4+expected_q12+b'\x6b'*4:
        raise ValueError('Native cache store changed the selected words or adjacent data')
    phase = 'frame'
    cpu.reg_write(arm.UC_ARM_REG_R9, frame)
    run(p['frame_store'], p['frame_store']+0x1a, caller_frame)
    if getter_status != available or struct.unpack('<2H', cpu.mem_read(frame+0xa2, 4)) != tuple(expected):
        raise ValueError('Native frame writer lost words or substituted availability status')
    before = bytes(cpu.mem_read(frame, 340))
    phase = 'copy'
    cpu.reg_write(arm.UC_ARM_REG_R0, frame)
    run(p['copy'])
    if (bytes(cpu.mem_read(p['snapshot'], 340)) != before
            or copies != [(p['snapshot'], frame, 340)]
            or cpu.mem_read(p['extra'], 2) != before[0x22:0x24]):
        raise ValueError('Complete native input-snapshot copy/metadata differs')
    phase = 'getter'
    cpu.reg_write(arm.UC_ARM_REG_R0, output)
    cpu.reg_write(arm.UC_ARM_REG_R1, output+4)
    run(p['getter'])
    if struct.unpack('<2I', cpu.mem_read(output, 8)) != tuple(expected):
        raise ValueError('Original calibration-side getter read a different input snapshot')
    for base, values in zip(register_bases, raw):
        if bytes(cpu.mem_read(base+0xbb1c, 8)) != struct.pack('<2I', *values):
            raise ValueError('Native register reading altered the independent peripheral inputs')
    cpu.hook_del(ch)
    cpu.hook_del(rh)
    cpu.hook_del(wh)
    continuation = observe_snapshot(cpu, p, expected) if observe_snapshot else None
    result = dict(flags=flags, present=present, same_rows=same_rows, policy=policy, availability_input=available,
                selected_source=int(chosen), decoded_words=expected,
                native_register_reads=len(reads), register_masks_bits=[13, 14],
                native_fixed_point_fraction_bits=12, native_snapshot_copied_bytes=340,
                native_availability_return=getter_status, original_source_words_preserved=True,
                host_assigned_selected_or_snapshot_bytes=False, host_assigned_api_returns=False,
                peripheral_register_values_and_mappings_are_synthetic=True,
                backend_initialization_executed=False, full_cache_update_caller_executed=False,
                automatically_scheduled=False, physical_feedback_identity_verified=False,
                physical_ready_or_settled_ack_verified=False, camera_io=False, installable=False)
    if continuation is not None:
        result['snapshot_continuation'] = continuation
    return result


def compare(c2, reference):
    rows = []
    for flags in ((0, 0), (1, 0), (0, 1), (1, 1)):
        for present in ((0, 0), (1, 0), (0, 1), (1, 1)):
            for same_rows in (False, True):
                for policy in (0, 1):
                    args = dict(flags=flags, present=present, same_rows=same_rows, policy=policy,
                                available=(sum(flags)+sum(present)+policy) % 2)
                    a, b = replay(c2, **args), replay(reference, **args)
                    if a != b:
                        raise ValueError('Native C2/CR register-to-input source behavior differs')
                    rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-native-tc-input-source/1', paired_cases=len(rows), cases=rows,
                camera_io=False, physical_shift_verified=False, installable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.c2, args.reference)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'physical_shift_verified')}))


if __name__ == '__main__':
    main()
