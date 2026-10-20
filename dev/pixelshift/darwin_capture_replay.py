"""Replay Darwin's native 34-byte receive/copy and parser prefix offline.

The host supplies synthetic bytes at the registered RX buffer. Original code
copies them into the stable buffer, fetches that snapshot and parses its prefix.
Serial reception, capture preparation, locking and later actuator code do not
execute. No peripheral access or hardware-success return is provided.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct


@lru_cache(maxsize=2)
def profile(path):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data = Path(path).read_bytes()
    base = 0x4200
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True

    def literal(address):
        row = next(md.disasm(data[address - base:address - base + 4], address))
        operand = row.operands[1]
        if row.mnemonic != 'ldr' or row.op_str.split(', ')[1].split(',')[0] != '[pc':
            raise ValueError('Darwin literal-load instruction changed')
        location = ((address + 4) & ~3) + operand.mem.disp
        return struct.unpack_from('<I', data, location - base)[0]

    table = literal(0x8784)
    tx, rx, length, code = struct.unpack_from('<4I', data, table + 16 - base)
    indices = literal(0x27f24)
    if (tx != 0 or not 0x20000000 <= rx < 0x20010000 - 34
            or length != 34 or code != 0x00020103 or data[indices + 6 - base] != 12):
        raise ValueError('Darwin capture-message registration changed')
    stable = literal(0x27f42) + 14
    state = literal(0x1e5e0)
    if not all(0x20000000 <= a < 0x2000d000 for a in (stable, state)):
        raise ValueError('Darwin receive/state buffers are outside inspected SRAM')
    return data, dict(base=base, rx=rx, stable=stable, state=state,
                      pointer=0x877a, length=0x8794, snapshot=0x27f18,
                      fetch=0x1d0b0, parse=0x1e674, parse_stop=0x1e73a,
                      regions=[(0x877a, 0x87a8), (0x27f18, 0x27f5a),
                               (0x1d0b0, 0x1d0b8), (0x27e76, 0x27ed4),
                               (0x1e674, 0x1e73a)])


def receive(path, payload, initial=0xa5):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R4, UC_ARM_REG_SP,
                                   UC_ARM_REG_LR, UC_ARM_REG_PC)
    if len(payload) != 34 or not 0 <= initial <= 255:
        raise ValueError('Needs exactly 34 synthetic packet bytes and one initial-state byte')
    data, p = profile(path)
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    cpu.mem_map(0x4000, (len(data) + 0x200 + 4095) & ~4095)
    cpu.mem_write(p['base'], data)
    cpu.mem_map(0x20000000, 0x10000)
    stack, finish = 0x2000f000, 0x40000000
    cpu.reg_write(UC_ARM_REG_SP, stack)
    cpu.mem_write(p['rx'] - 1, b'\x6b' + bytes(payload) + b'\x6b')
    cpu.mem_write(p['stable'] - 1, b'\x7c' + bytes(34) + b'\x7c')
    cpu.mem_write(stack + 3, b'\x8d' + bytes(34) + b'\x8d')
    cpu.mem_write(p['state'], bytes([initial]) * 256)
    phase = 'query'
    counts = {}

    def hook(uc, address, size, unused):
        if not any(begin <= address and address + size <= end for begin, end in p['regions']):
            raise ValueError('Darwin replay reached omitted code: ' + hex(address))
        counts[phase] = counts.get(phase, 0) + 1

    def write_hook(uc, access, address, size, value, unused):
        if stack - 256 <= address and address + size <= stack:
            return
        allowed = dict(query=[], snapshot=[(p['stable'], 34)],
                       fetch=[(stack + 4, 34)],
                       parse=[(p['state'] + 0x58, 24), (p['state'] + 0xf0, 4)])
        if not any(begin <= address and address + size <= begin + length
                   for begin, length in allowed[phase]):
            raise ValueError('Darwin ' + phase + ' changed unrelated state: ' + hex(address))

    def run(entry, end=finish):
        cpu.reg_write(UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(entry | 1, end, count=2000)
        if cpu.reg_read(UC_ARM_REG_PC) != end or cpu.reg_read(UC_ARM_REG_SP) != stack:
            raise ValueError('Darwin native slice did not finish with balanced stack')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.reg_write(UC_ARM_REG_R0, 12)
    run(p['pointer'])
    if cpu.reg_read(UC_ARM_REG_R0) != p['rx']:
        raise ValueError('Native message lookup did not select its registered RX pointer')
    cpu.reg_write(UC_ARM_REG_R0, 12)
    run(p['length'])
    if cpu.reg_read(UC_ARM_REG_R0) != 34:
        raise ValueError('Native message length differs from the 34-byte registration')
    phase = 'snapshot'
    cpu.reg_write(UC_ARM_REG_R0, 6)
    run(p['snapshot'])
    phase = 'fetch'
    cpu.reg_write(UC_ARM_REG_R0, stack + 4)
    run(p['fetch'])
    phase = 'parse'
    cpu.reg_write(UC_ARM_REG_R4, p['state'])
    run(p['parse'], p['parse_stop'])
    if (bytes(cpu.mem_read(p['rx'] - 1, 36)) != b'\x6b' + bytes(payload) + b'\x6b'
            or bytes(cpu.mem_read(p['stable'] - 1, 36)) != b'\x7c' + bytes(payload) + b'\x7c'
            or bytes(cpu.mem_read(stack + 3, 36)) != b'\x8d' + bytes(payload) + b'\x8d'
            or bytes(cpu.mem_read(p['base'], len(data))) != data):
        raise ValueError('Native snapshot/fetch changed packet bytes, bounds or ROM')
    expected = bytearray([initial] * 256)
    expected[0x58:0x64] = payload[:12]
    expected[0x65:0x67] = payload[13:15]
    expected[0x67:0x69] = payload[16:18]
    expected[0x69] = payload[15]
    expected[0x6a] = (initial & 0x10) | (payload[18] & 0xef)
    expected[0x6e] = (initial & 0xe3) | ((payload[12] >> 6) << 2) | ((payload[12] & 0x20) >> 1)
    struct.pack_into('<I', expected, 0xf0, struct.unpack_from('<H', payload, 10)[0] * 2)
    if bytes(cpu.mem_read(p['state'], 256)) != expected:
        raise ValueError('Native parser prefix differs from the inspected field/bit mapping')
    return dict(message_id=12, code='03/01/02', received_bytes=34,
                native_snapshot_bytes=34, native_fetch_bytes=34,
                parser_state_prefix=bytes(expected[0x58:0x70]).hex(),
                doubled_word_at_f0=struct.unpack_from('<I', expected, 0xf0)[0],
                native_instruction_counts=counts, external_calls_omitted=0,
                synthetic_rx_and_initial_state=True, parser_prefix_only=True,
                serial_transport_executed=False, capture_preparation_executed=False,
                physical_shift_verified=False, camera_io=False)


def compare(c2, reference):
    inputs = [bytes(34), b'\xff' * 34, bytes(range(34)), b'\xa5' * 34]
    for index in range(34):
        for bit in range(8):
            payload = bytearray(34)
            payload[index] = 1 << bit
            inputs.append(bytes(payload))
    cases = []
    for index, payload in enumerate(inputs):
        initial = 0xa5 if index & 1 else 0x5a
        a, b = receive(c2, payload, initial), receive(reference, payload, initial)
        if a != b:
            raise ValueError('C2/A7CR native capture-message receive/parser prefix differs')
        cases.append(dict(payload=payload.hex(), initial_state_byte=initial, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-darwin-capture/1', paired_cases=len(cases),
                cases=cases, camera_io=False, installable=False, physical_shift_verified=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True, help='Private extracted darwin_core.bin')
    parser.add_argument('--reference', type=Path, required=True, help='Private A7CR darwin_core.bin')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    report = compare(args.c2, args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
