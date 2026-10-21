"""Trace official CP parameter words into native type-7 controller packets.

Offline only. Original BK4 loading, parameter-cache comparison, packing and
checksum run. Cache differences and other RAM are synthetic; no transport,
board configuration, controller application or hardware success is supplied.
The fixture observes parameter 0x170006, not a live camera calibration block.
"""
import argparse
import json
from pathlib import Path
import struct

from cp_defaults_replay import _defaults_machine
from cp_phase_pair_replay import profile as pair_profile


def parameter_packets(directory, *, synthetic_words=None):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_PC,
                                   UC_ARM_REG_SP, UC_ARM_REG_LR)
    data, default, pair = pair_profile(directory)
    cpu, _, _ = _defaults_machine(directory)
    signature = struct.pack('<24I', *range(0x170000, 0x170018))
    index = data.find(signature)
    if index < 0 or data.find(signature, index + 1) >= 0:
        raise ValueError('Native controller parameter ID table is not unique')
    ids = index + 0x108000
    sources, caches = ids - 0xc8, ids - 0x64
    source = struct.unpack_from('<I', data, sources - 0x108000 + 6 * 4)[0]
    cache = struct.unpack_from('<I', data, caches - 0x108000 + 6 * 4)[0]
    # Derive the queue cursor from the actual native scanner called by the
    # formatter's parameter getter. Do not assume a C2/CR address delta.
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    getter_call = code(pair['pack'] + 0x56, 4)
    if len(getter_call) != 1 or getter_call[0].mnemonic != 'bl':
        raise ValueError('Native first-phase parameter getter call changed')
    getter = int(getter_call[0].op_str.lstrip('#'), 0)
    calls = [int(i.op_str.lstrip('#'), 0) for i in code(getter, 0x1c) if i.mnemonic == 'bl']
    if len(calls) != 1:
        raise ValueError('Native parameter scanner call changed')
    scanner = calls[0]
    from cp_serial_replay import literals
    cursor_candidates = [value for register, value in literals(code(scanner, 0x1e)) if register == 'r0']
    if len(cursor_candidates) != 1:
        raise ValueError('Native parameter scan cursor was not identified')
    cursor = cursor_candidates[0]
    for address, length in ((0x1700000, 0x440000), (cursor, 4)):
        for page in range(address & ~4095, (address + length + 4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
    stack, finish, phase, lock_calls = 0x3001f000, 0x3001e000, 'load', 0

    def hook(uc, at, size, unused):
        nonlocal lock_calls
        if phase == 'load' and at in default['locks']:
            lock_calls += 1
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
            return
        if not 0x108000 <= at < 0x108000 + len(data):
            raise ValueError('Parameter packet replay left the original CP program: ' + hex(at))

    def write_hook(uc, access, address, size, value, unused):
        if ((0x1700000 <= address and address + size <= 0x1b40000)
                or (stack - 2048 <= address and address + size <= stack)
                or (cursor <= address and address + size <= cursor + 4)):
            return
        raise ValueError('Parameter packet replay wrote outside synthetic RAM/stack: ' + hex(address))

    def run(at, end=finish):
        cpu.reg_write(UC_ARM_REG_SP, stack)
        cpu.reg_write(UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(at | 1, end, count=30000)
        if cpu.reg_read(UC_ARM_REG_PC) != end:
            raise ValueError('Native parameter packet path did not finish')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.reg_write(UC_ARM_REG_R0, ids + 6 * 4)
    cpu.reg_write(UC_ARM_REG_R1, sources + 6 * 4)
    run(default['initialize'], default['initialize'] + 0x6a)
    if cpu.reg_read(UC_ARM_REG_R0) != 256:
        raise ValueError('Native controller parameter load was incomplete')
    official = bytes(cpu.mem_read(source, 256))
    offsets = (0x60, 0x64, 0x6c)
    selected = bytearray(official)
    if synthetic_words is not None:
        if len(synthetic_words) != 12:
            raise ValueError('Three synthetic four-byte words are required')
        for i, offset in enumerate(offsets):
            selected[offset:offset + 4] = synthetic_words[4 * i:4 * i + 4]
        cpu.mem_write(source, bytes(selected))
    for offset in (38, 39, 40):
        cpu.reg_write(UC_ARM_REG_R0, default['ids'] + offset * 4)
        cpu.reg_write(UC_ARM_REG_R1, default['destinations'] + offset * 4)
        run(default['initialize'], default['initialize'] + 0x6a)
    # Prior controller cache is a synthetic mismatch, not a live board sample.
    # Official words or the explicitly selected sensitivity inputs are retained;
    # no packet fields are supplied directly by the host.
    previous = bytearray(selected)
    for offset in offsets:
        previous[offset] ^= 1
    cpu.mem_write(cache, bytes(previous))
    cpu.mem_write(cursor, struct.pack('<HH', 6, offsets[0]))
    phase, rows = 'pack', []
    for offset in offsets:
        run(pair['pack'])
        run(pair['checksum'], pair['checksum'] + 0x36)
        packet = bytes(cpu.mem_read(pair['packet'], 40))
        check = 0
        for word in struct.unpack('<20H', packet):
            check ^= word
        if (packet[:4] != bytes([0x39, 7, 7, 3]) or packet[7:10] != bytes([6, offset, 255])
                or packet[10:14] != selected[offset:offset + 4] or check != 0xf0f):
            raise ValueError('Original parameter scanner/formatter lost category, offset or source bytes')
        rows.append(dict(offset=offset, packet=packet.hex(), source_word=packet[10:14].hex()))
    if (bytes(cpu.mem_read(source, 256)) != selected
            or bytes(cpu.mem_read(cache, 256)) != selected):
        raise ValueError('Native parameter emission changed its source or failed to update the cache')
    return dict(parameter_id=0x170006, packets=rows, native_loader_and_cache_scanner_executed=True,
                source_bytes_preserved_by_emission=True, prior_cache_synthetic=True,
                source_words_synthetic=synthetic_words is not None,
                additional_void_lock_calls_omitted=lock_calls, camera_io=False,
                physical_configuration_verified=False, installable=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--components', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--h8-input', type=Path,
                        help='Export both official-default and explicitly synthetic word packets for H8 replay')
    args = parser.parse_args(argv)
    report = dict(cases=[parameter_packets(args.components), parameter_packets(
        args.components, synthetic_words=bytes.fromhex('1234fedc89abcdef1357fdb9'))],
        camera_io=False, installable=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    if args.h8_input is not None:
        args.h8_input.parent.mkdir(parents=True, exist_ok=True)
        with args.h8_input.open('x', encoding='utf-8') as handle:
            for index, case in enumerate(report['cases']):
                for row in case['packets']:
                    handle.write(f'variant{index}-offset{row["offset"]}\t{row["packet"]}\n')
    print(json.dumps(dict(packets=sum(len(c['packets']) for c in report['cases']),
                          camera_io=False, installable=False)))


if __name__ == '__main__':
    main()
