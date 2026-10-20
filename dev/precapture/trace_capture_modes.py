"""Trace original AP capture-mode encoding and CP parameter-copy ownership.

No shutter operation runs. AP execution stops before its first conversion
dependency; CP executes only message-field stores and original memcpy.
The resulting raw capture-mode numbers are NOT electronic-shutter proof.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM64, UC_ARCH_ARM, UC_MODE_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_SP, UC_ARM64_REG_LR
from unicorn.arm_const import UC_ARM_REG_R1, UC_ARM_REG_R4, UC_ARM_REG_R6, UC_ARM_REG_R8, UC_ARM_REG_SP, UC_ARM_REG_PC
from support.reference import SPECS
from verify_ap_transport import AP_HASHES
from support.memory import MEM, STACK, STOP

MASTER, PARAM = 0x165A720, 0x171F4D8


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    folder = args.firmware_root / 'a7c2-2.01/components'
    ap, cp = (folder / 'appFw.so').read_bytes(), (folder / 'cpapp-b.bin').read_bytes()
    if hashlib.sha256(ap).hexdigest() != AP_HASHES['a7c2-2.01'] or hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original target firmware')
    assert struct.unpack_from('<2I', cp, 0xFF2D80) == (0x4014, 0x24D650 + 0x108001)
    assert b'FW: SET_CAP_MODE[' in cp[0x24D7E4:0x24D820]
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for at, size in [(0x3546000, 0x2000), (0x4C7D000, 4096)]:
        u.mem_map(at, size)
        u.mem_write(at, ap[at:at + size])
    for at, size in [(MEM, 4096), (STACK, 0x4000), (STOP, 4096),
                     (0x3519000, 4096), (0x36E9000, 4096)]:
        u.mem_map(at, size)
    captured = []

    def stop(cpu, address, size, user):
        if address in [0x3519048, 0x354651C, 0x36E9310]:
            stack = cpu.reg_read(UC_ARM64_REG_SP)
            packet = bytes(cpu.mem_read(stack + 0x68, 24))
            captured.append({'boundary': hex(address), 'executed': False, 'packet': packet})
            cpu.emu_stop()

    u.hook_add(UC_HOOK_CODE, stop)
    c = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for at, size in [(0x24D000, 4096), (0xA06000, 4096), (0x516000, 0x4000)]:
        c.mem_map(at, size)
        c.mem_write(at, cp[at:at + size])
    for at, size in [(MASTER & ~4095, 0x3000), (PARAM & ~4095, 0x3000),
                     (MEM, 4096), (STACK, 0x4000)]:
        c.mem_map(at, size)

    def cp_propagate(packet):
        c.mem_write(MASTER, b'\xA5' * 0xD64)
        c.mem_write(PARAM, b'\x5A' * 0x1000)
        c.mem_write(MEM, packet)
        for register, value in [(UC_ARM_REG_R4, MEM), (UC_ARM_REG_R8, MASTER),
                                (UC_ARM_REG_R1, packet[8]), (UC_ARM_REG_SP, STACK + 0x3000)]:
            c.reg_write(register, value)
        c.emu_start(0x24D725, 0x24D762, count=100)
        assert c.reg_read(UC_ARM_REG_PC) == 0x24D762
        source = bytes(c.mem_read(MASTER, 0xD64))
        assert struct.unpack_from('<I', source, 0x138)[0] == packet[8]
        # Real target memcpy executes, including ARM/Thumb interworking.
        c.reg_write(UC_ARM_REG_R4, PARAM)
        c.reg_write(UC_ARM_REG_R6, MASTER)
        c.emu_start(0xA060AD, 0xA060BA, count=10000)
        assert c.reg_read(UC_ARM_REG_PC) == 0xA060BA
        target = bytes(c.mem_read(PARAM, 0x1000))
        assert target[:0x28] == b'\x5A' * 0x28
        assert target[0x28:0x28 + len(source)] == source
        assert target[0x28 + len(source):] == b'\x5A' * (0x1000 - 0x28 - len(source))
        assert struct.unpack_from('<I', target, 0x160)[0] == packet[8]
        return packet[8]

    cases = []
    for request_mode in [0, 1, 3, 5, 7, 8, 9, 10, 11, 12]:
        for option in range(4):
            fields = [0x12345678, request_mode, option, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
            raw = struct.pack('<15I', *fields)
            u.mem_write(MEM, raw)
            u.mem_write(STACK + 0x2000, bytes(0x1000))
            for register, value in [(UC_ARM64_REG_X0, MEM), (UC_ARM64_REG_X1, MEM + 0x200),
                                    (UC_ARM64_REG_SP, STACK + 0x3000), (UC_ARM64_REG_LR, STOP)]:
                u.reg_write(register, value)
            before = len(captured)
            u.emu_start(0x35463D8, STOP, count=200)
            assert len(captured) == before + 1
            item = captured[-1]
            if int(item['boundary'], 16) == 0x36E9310:
                raise AssertionError('Input reached native error diagnostics')
            packet = item.pop('packet')
            assert struct.unpack_from('<H', packet, 2)[0] == 0x4014
            assert struct.unpack_from('<I', packet, 4)[0] == fields[0]
            mode = cp_propagate(packet)
            # These checks pin the crucial ordinary/alternate continuous
            # capture-mode branch without assigning a shutter-type meaning.
            if request_mode == 1:
                assert mode == (0x1A if option == 3 else 1)
            cases.append({'AP_request_mode_raw': request_mode, 'AP_option_8_raw': option,
                          'CP_mode_word_138': mode, 'parameter_mode_word_160': mode,
                          'partial_packet_hex': packet.hex(), **item})
    report = {'mode': 'OFFLINE_CAPTURE_MODE_OWNERSHIP', 'camera_io': False,
              'firmware_modified': False, 'cases': cases,
              'target_command': '0x4014', 'native_memcpy_executed': True,
              'limits': ['AP stops before shutter-related fields and actual transport',
                         'No sensor or hardware callback executes',
                         'Mode word is capture mode, not established as electronic-shutter setting',
                         'CP master+0x138 must not be used for donor enabled state']}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(f'Native AP -> CP stores -> original parameter memcpy: {len(cases)} cases; no shutter operation.')


if __name__ == '__main__':
    main()
