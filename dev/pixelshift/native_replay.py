"""Run original AP packet-building instructions offline, stopping before send.

Only a diagnostic trace call is omitted. No service/driver/sensor call receives
a simulated success. Matching this generic packet does not prove pixel shift.
"""
import argparse
import json
from pathlib import Path
import struct
from functools import lru_cache

from audit import Image, audit


@lru_cache(maxsize=2)
def source(directory):
    return Image(Path(directory) / 'appFw.so'), audit(directory)['profile']


def packet(directory, mode, capture_id, auxiliary):
    from unicorn import Uc, UcError, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
                                     UC_ARM64_REG_X2, UC_ARM64_REG_X3,
                                     UC_ARM64_REG_X4, UC_ARM64_REG_X5,
                                     UC_ARM64_REG_LR, UC_ARM64_REG_SP,
                                     UC_ARM64_REG_PC)
    image, info = source(directory)
    entry, send, trace = [int(info[k], 16) for k in ('marshalling', 'send', 'trace')]
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    mapped = set()

    def load(address, length):
        for page in range(address & ~4095, (address + length + 4095) & ~4095, 4096):
            if page in mapped:
                continue
            cpu.mem_map(page, 4096)
            offset = image.offset(page, 4096)
            cpu.mem_write(page, image.data[offset:offset + 4096])
            mapped.add(page)

    load(entry, 0x200)
    load(send, 4)
    load(trace, 4)
    # ADRP operands in the builder identify its switch-table/read-only pages.
    for ins in image.instructions(entry, 0x200):
        if ins.mnemonic == 'adrp':
            load(int(ins.op_str.split('#', 1)[1], 16), 4096)
    cpu.mem_map(0x10000000, 0x20000)
    args, output = 0x10001000, 0x10002000
    parameters = struct.pack('<III', capture_id, mode, auxiliary)
    cpu.mem_write(args, parameters)
    cpu.mem_write(output, b'\xa5' * 16)
    cpu.reg_write(UC_ARM64_REG_X0, args)
    cpu.reg_write(UC_ARM64_REG_X1, output)
    cpu.reg_write(UC_ARM64_REG_SP, 0x1001f000)
    cpu.reg_write(UC_ARM64_REG_LR, 0x10003000)
    result = {'trace_calls_omitted': 0, 'send_executed': False}

    def code(uc, address, size, _):
        if address == trace:
            result['trace_calls_omitted'] += 1
            # This call logs a diagnostic message; no capture return is faked.
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
        elif address == send:
            pointer = uc.reg_read(UC_ARM64_REG_X1)
            length = uc.reg_read(UC_ARM64_REG_X2)
            if length != 16:
                raise ValueError('Unexpected native packet length')
            result.update(packet=bytes(uc.mem_read(pointer, length)).hex(),
                          routing=uc.reg_read(UC_ARM64_REG_X0),
                          send_boundary=hex(send))
            uc.emu_stop()
        elif not entry <= address < entry + 0x200:
            raise ValueError('Unexpected native call; stopped: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, code)
    cpu.emu_start(entry, 0x10003000, count=500)
    if 'packet' not in result:
        raise ValueError('Native builder did not reach the send boundary')
    if bytes(cpu.mem_read(args, 12)) != parameters:
        raise ValueError('Native builder modified its input')
    if bytes(cpu.mem_read(output, 16)) != b'\xa5' * 16:
        raise ValueError('Output changed before the send boundary')
    result.update(mode=mode, capture_id=capture_id, auxiliary=auxiliary)
    return result


def select_sequence(directory, mode, interval):
    """Run the original 4/16 selection block; stop before shot configuration."""
    from unicorn import Uc, UcError, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm64_const import (UC_ARM64_REG_X19, UC_ARM64_REG_PC,
                                     UC_ARM64_REG_X0, UC_ARM64_REG_X1)
    image, info = source(directory)
    entry, stop = int(info['selection'], 16), int(info['configure_shot'], 16)
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    pages = {entry & ~4095, (entry + 0x300) & ~4095, stop & ~4095}
    for ins in image.instructions(entry, 0x300):
        if ins.mnemonic == 'adrp':
            pages.add(int(ins.op_str.split('#', 1)[1], 16))
    for page in pages:
        cpu.mem_map(page, 4096)
        offset = image.offset(page, 4096)
        cpu.mem_write(page, image.data[offset:offset + 4096])
    cpu.mem_map(0x10000000, 8192)
    obj = 0x10000000
    before = bytearray(b'\xa5' * 0x1000)
    struct.pack_into('<3I', before, 0xcd0, mode, interval, interval)
    cpu.mem_write(obj, bytes(before))
    cpu.reg_write(UC_ARM64_REG_X19, obj)
    reached = []

    def hook(uc, address, size, _):
        if address == stop:
            reached.append(address)
            uc.emu_stop()
        elif not entry <= address < entry + 0x300:
            raise ValueError('Invalid native selection reached external code: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, hook)
    try:
        cpu.emu_start(entry, 0x10001000, count=100)
    except UcError as exc:
        raise ValueError('Native selection left its bounded instruction/memory model') from exc
    if not reached or cpu.reg_read(UC_ARM64_REG_PC) != stop:
        raise ValueError('Sequence did not reach the pre-configuration boundary')
    if cpu.reg_read(UC_ARM64_REG_X0) != obj or cpu.reg_read(UC_ARM64_REG_X1) != 0:
        raise ValueError('Unexpected initial shot-configuration arguments')
    after = bytes(cpu.mem_read(obj, len(before)))
    count = struct.unpack_from('<I', after, 0xd08)[0]
    spacing = struct.unpack_from('<Q', after, 0xd10)[0]
    expected = bytearray(before)
    struct.pack_into('<I', expected, 0xd08, count)
    struct.pack_into('<Q', expected, 0xd10, spacing)
    if after != expected:
        raise ValueError('Native selection changed unrelated sequence state')
    return {'mode': mode, 'interval_index': interval, 'shots': count,
            'interval_native_value': spacing, 'configuration_executed': False,
            'external_calls_executed': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    cases = []
    for mode in range(11):
        for capture_id, auxiliary in [(0, 0), (1, 1), (0x12345678, 0x87654321),
                                      (0xffffffff, 0xffffffff)]:
            target = packet(args.c2, mode, capture_id, auxiliary)
            donor = packet(args.reference, mode, capture_id, auxiliary)
            if target['packet'] != donor['packet'] or target['routing'] != donor['routing']:
                raise ValueError('C2 and A7CR native packets differ')
            cases.append({'target': target, 'reference': donor})
    selections = []
    for mode in (1, 2):
        for interval in range(9):
            target = select_sequence(args.c2, mode, interval)
            donor = select_sequence(args.reference, mode, interval)
            if target != donor or target['shots'] != (4 if mode == 1 else 16):
                raise ValueError('Native four/sixteen-shot selection differs')
            selections.append(target)
    result = {'schema': 'a7c2-pixelshift-native-replay/1', 'paired_packet_cases': len(cases),
              'paired_selection_cases': len(selections), 'selections': selections,
              'camera_io': False, 'hardware_emulated': False,
              'limits': ['Only 4/16 selection and generic command 0x4036 marshalling are checked',
                         'Trace call is omitted; transport send is never executed',
                         'No capture, IBIS positioning, image output or boot verification'],
              'cases': cases}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k not in ('cases', 'selections')}, indent=2))


if __name__ == '__main__':
    main()
