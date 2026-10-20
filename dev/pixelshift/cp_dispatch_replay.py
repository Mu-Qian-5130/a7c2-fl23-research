"""Replay the native CP dispatcher on AP-built TRINITY mode packets.

This executes the original lookup, optional consistency callback, mode handler
and parameter-change flag setter. Initial CP RAM and the pending-check field are
synthetic. Only diagnostic printing is omitted. No transport, CP scheduler,
capture, actuator, persistence or success acknowledgement is supplied.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_metadata_replay import program
from trinity_replay import configure, profile as mode_profile


@lru_cache(maxsize=2)
def profile(directory):
    data, model, _, _ = program(directory)
    _, info, _, handler, parameter = mode_profile(directory)
    if model != info['model']:
        raise ValueError('AP/CP model mismatch')
    target = model == 'ILCE-7CM2'
    values = dict(dispatcher=0x35cf70 if target else 0x35d0d0,
                  support=0xd939f0 if target else 0xd95f64,
                  source=0x186fbf8 if target else 0x186e9a8,
                  row=0x10fbca8 if target else 0x10faca8,
                  check=0x364b00 if target else 0x364c60,
                  getter=0x8db1b8 if target else 0x8db3d0,
                  debug=0x1a533d6 if target else 0x1a52186,
                  notify=0x996fec if target else 0x99706a,
                  changed=0x1b16058 if target else 0x1b14c7c,
                  trace=0xb4457a if target else 0xb443d8,
                  handler=handler, parameter=parameter)
    at = values['row'] - 0x108000
    if struct.unpack_from('<5I', data, at) != (0x40ee, handler | 1, 0, 0, values['check'] | 1):
        raise ValueError('Native TRINITY command record changed')
    support = values['support'] + (0x40ee - 0x4000) * 8 - 0x108000
    if data[support:support + 8] != struct.pack('<IBBBB', 0x40ee, 1, 0, 0, 0):
        raise ValueError('Native TRINITY support record changed')
    return data, values


def _dispatch(directory, wire, *, source_id=0x90030001, initial_mode=0, pending=0):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP,
                                   UC_ARM_REG_LR, UC_ARM_REG_PC)
    data, p = profile(directory)
    packet = bytes.fromhex(wire)
    if len(packet) != 12 or struct.unpack_from('<H', packet, 2)[0] != 0x40ee:
        raise ValueError('Expected one native 12-byte TRINITY mode packet')
    if pending not in (0, 1):
        raise ValueError('Pending consistency input must be 0 or 1')
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    cpu.mem_map(0x108000, (len(data) + 4095) & ~4095)
    cpu.mem_write(0x108000, data)
    state = (p['parameter'], p['source'], p['debug'], p['changed'])
    for page in sorted({at & ~4095 for at in state}):
        cpu.mem_map(page, 4096)
    cpu.mem_map(0x30000000, 0x10000)
    args, finish, stack = 0x30001000, 0x30002000, 0x3000f000
    cpu.mem_write(args, packet)
    cpu.mem_write(p['parameter'] - 4, struct.pack('<III', 0xa5a5a5a5, initial_mode, 0xa5a5a5a5))
    cpu.mem_write(p['row'] + 12, struct.pack('<I', pending))
    cpu.reg_write(UC_ARM_REG_R0, args)
    cpu.reg_write(UC_ARM_REG_R1, source_id)
    cpu.reg_write(UC_ARM_REG_SP, stack)
    cpu.reg_write(UC_ARM_REG_LR, finish | 1)
    result = dict(check_executed=False, handler_executed=False,
                  notification_flag_setter_executed=False, diagnostic_calls_omitted=0,
                  synthetic_initial_state=True, transport_executed=False,
                  capture_executed=False, physical_shift_verified=False)
    regions = [(p['dispatcher'], p['dispatcher'] + 0x120),
               (p['handler'], p['handler'] + 0x30),
               (p['check'], p['check'] + 0x28),
               (p['getter'], p['getter'] + 10), (p['notify'], p['notify'] + 14)]
    writes = []

    def hook(uc, address, size, unused):
        if address == p['trace']:
            result['diagnostic_calls_omitted'] += 1
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
        elif not any(begin <= address < end for begin, end in regions):
            raise ValueError('CP dispatcher reached unhandled code: ' + hex(address))
        if address == p['check']:
            result['check_executed'] = True
        elif address == p['handler']:
            result['handler_executed'] = True
        elif address == p['notify']:
            result['notification_flag_setter_executed'] = True

    def write_hook(uc, access, address, size, value, unused):
        if 0x30008000 <= address and address + size <= stack:
            return
        allowed = {p['source']: 4, p['parameter']: 4, p['row'] + 12: 4, p['changed']: 1}
        if allowed.get(address) != size:
            raise ValueError('Unexpected native CP write: ' + hex(address))
        writes.append((address, size, value))

    code_hook = cpu.hook_add(UC_HOOK_CODE, hook)
    memory_hook = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.emu_start(p['dispatcher'] | 1, finish, count=10000)
    if cpu.reg_read(UC_ARM_REG_PC) != finish or cpu.reg_read(UC_ARM_REG_R0) != 1:
        raise ValueError('Native dispatcher did not return success')
    output_mode = struct.unpack('<I', cpu.mem_read(p['parameter'], 4))[0]
    output_pending = struct.unpack('<I', cpu.mem_read(p['row'] + 12, 4))[0]
    expected_check = source_id == 0x80020002
    expected_diag = int(expected_check and pending == 1 and initial_mode != packet[8])
    expected = [(p['source'], 4, source_id)]
    if expected_check:
        expected.append((p['row'] + 12, 4, 0))
    expected += [(p['parameter'], 4, packet[8]), (p['changed'], 1, 1)]
    if (writes != expected or output_mode != packet[8]
            or output_pending != (0 if expected_check else pending)
            or result['check_executed'] != expected_check
            or result['diagnostic_calls_omitted'] != expected_diag
            or not result['handler_executed'] or not result['notification_flag_setter_executed']
            or bytes(cpu.mem_read(args, 12)) != packet):
        raise ValueError('Unexpected native TRINITY dispatch result')
    cpu.hook_del(code_hook)
    cpu.hook_del(memory_hook)
    return cpu, p, dict(result, mode=output_mode, pending=output_pending,
                        parameter_changed_flag=bytes(cpu.mem_read(p['changed'], 1))[0],
                        nonstack_writes=len(writes))


def dispatch(directory, wire, *, source_id=0x90030001, initial_mode=0, pending=0):
    return _dispatch(directory, wire, source_id=source_id, initial_mode=initial_mode, pending=pending)[2]


def compare(c2, reference):
    inputs = [dict(mode=m, interval=n) for m in (1, 2) for n in range(9)]
    inputs += [dict(mode=0), dict(mode=1, test=1)]
    cases = []
    for values in inputs:
        a, b = configure(c2, **values), configure(reference, **values)
        if a != b:
            raise ValueError('Original AP mode packets differ')
        requested = bytes.fromhex(a['packet'])[8]
        for args in (dict(source_id=0x90030001, initial_mode=0, pending=1),
                     dict(source_id=0x80020002, initial_mode=requested, pending=1),
                     dict(source_id=0x80020002, initial_mode=requested ^ 1, pending=1),
                     dict(source_id=0x80020002, initial_mode=requested ^ 1, pending=0)):
            target, donor = dispatch(c2, a['packet'], **args), dispatch(reference, b['packet'], **args)
            if target != donor:
                raise ValueError('Native C2/A7CR mode dispatch differs')
            cases.append(dict(input=values, dispatch_input=args, target=target, reference=donor))
    return dict(schema='a7c2-pixelshift-cp-dispatch/1', camera_io=False,
                installable=False, physical_shift_verified=False, paired_cases=len(cases), cases=cases)


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
