"""Original CP configuration RMW; explicit input words, no hardware response.

This is separate from the paired command request words. The original helper
returns its second MMIO read, not a success code. No reset value is supplied
to a native boot and no current on-disk source proves loaded RAM identity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn import arm_const as R
from support.reference import SPECS
from support.config_rmw import BASE, ENTRY, SOURCE_SPANS, compare_current

IO, STACK, STOP = 0xf5400000, 0x30000000, 0x31000000
WORD, SCRATCH = IO + 0x8038, 0x1a764f4


def audit(cp, current=None):
    if hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original stock CP')
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for address, size in ((0xb71000, 4096), (0xb74000, 4096), (0x685000, 4096)):
        u.mem_map(address, size)
        u.mem_write(address, cp[address-BASE:address-BASE+size])
    for address in (IO+0x8000, STACK, STOP, SCRATCH & ~4095):
        u.mem_map(address, 4096)
    reads, writes, terminal = [], [], []
    inputs = (0, 0)
    target = STOP
    def boundary(cpu, address, size, user):
        if address == target:
            terminal.append(address)
            cpu.emu_stop()
    def read(cpu, access, address, size, value, user):
        if IO <= address < IO+0x10000:
            assert address == WORD and size == 4 and len(reads) < 2
            value = inputs[len(reads)]
            reads.append((address, size, value))
            cpu.mem_write(address, struct.pack('<I', value))
    def write(cpu, access, address, size, value, user):
        if IO <= address < IO+0x10000 or address == SCRATCH:
            writes.append((address, size, value))
        else:
            assert STACK <= address and address+size <= STACK+4096
    u.hook_add(UC_HOOK_CODE, boundary)
    u.hook_add(UC_HOOK_MEM_READ, read)
    u.hook_add(UC_HOOK_MEM_WRITE, write)
    def start(entry, mask, select, stop):
        nonlocal target
        target = stop
        reads.clear(); writes.clear(); terminal.clear()
        u.reg_write(R.UC_ARM_REG_SP, STACK+0xf00)
        u.reg_write(R.UC_ARM_REG_LR, STOP | 1)
        for reg, value in ((R.UC_ARM_REG_R0, mask), (R.UC_ARM_REG_R1, select),
                           (R.UC_ARM_REG_R4, 0x12345678),
                           (R.UC_ARM_REG_R5, 0x89abcdef),
                           (R.UC_ARM_REG_R7, 0x13579bdf)):
            u.reg_write(reg, value)
        u.emu_start(entry | 1, 0xffffffff, count=100)
        assert terminal == [stop] and u.reg_read(R.UC_ARM_REG_PC) == stop
    cases = []
    for initial in (0, 0xffffffff, 0x55555555, 0xaaaaaaaa):
        for returned in (0, 0xffffffff, 0x13579bdf, 0x2468ace0):
            for mask in (0, 0x4000, 0x8000, 0x10000, 0x80000000, 0x55555555):
                for select in (0, 1, 2, 0xffffffff):
                    inputs = (initial, returned)
                    start(ENTRY, mask, select, STOP)
                    # Independent arithmetic oracle; only select == 1 sets.
                    expected = (initial | mask) if select == 1 else (initial & (0xffffffff ^ mask))
                    assert reads == [(WORD, 4, initial), (WORD, 4, returned)]
                    assert writes == [(WORD, 4, expected), (SCRATCH, 4, returned)]
                    assert u.reg_read(R.UC_ARM_REG_R0) == returned
                    assert struct.unpack('<I', u.mem_read(SCRATCH, 4))[0] == returned
                    assert u.reg_read(R.UC_ARM_REG_SP) == STACK+0xf00
                    assert [u.reg_read(reg) for reg in (R.UC_ARM_REG_R4, R.UC_ARM_REG_R5, R.UC_ARM_REG_R7)] == [0x12345678, 0x89abcdef, 0x13579bdf]
                    assert (expected & (0xffffffff ^ mask)) == (initial & (0xffffffff ^ mask))
                    cases.append(dict(initial=initial, second_read=returned, mask=mask,
                                      selector=select, written=expected, returned=returned))
    # Execute actual caller argument setup, stopping BEFORE the helper.
    start(0x68530a, 0, 0, ENTRY)
    assert not reads and not writes
    assert u.reg_read(R.UC_ARM_REG_R0) == 0x4000
    assert u.reg_read(R.UC_ARM_REG_R1) == 1
    assert u.reg_read(R.UC_ARM_REG_LR) == 0x685315
    # Prove that source admission notices a one-byte drift in every span.
    negative = []
    assert compare_current(cp, cp)['spans'] == 3
    for address, size in SOURCE_SPANS:
        altered = bytearray(cp); altered[address-BASE] ^= 1
        try:
            compare_current(cp, altered)
        except ValueError:
            negative.append(hex(address))
        else:
            raise AssertionError('Changed source admitted')
    report = dict(camera_io=False, CP_sha256=hashlib.sha256(cp).hexdigest(),
                  cases=cases, original_executions=len(cases)+1,
                  caller=dict(address='0x68530a', mask='0x4000', selector=1,
                              stopped_before_helper=True),
                  source_drift_rejections=negative,
                  hardware_reset_value_qualified=False,
                  limits=['Initial and second readback words are explicit independent fixtures',
                          'No ready/clock/reset/IRQ/sensor result or native-boot MMIO is supplied',
                          'R0 is the second readback word, not a software success status',
                          'Current-file equality is limited to three spans; loaded RAM is unverified',
                          'No exposure, retained pixels, saving, cancellation or physical restoration is tested'])
    if current is not None:
        report['current_source'] = compare_current(cp, current)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp', type=Path, required=True)
    parser.add_argument('--current-cp', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.cp.read_bytes(), args.current_cp.read_bytes() if args.current_cp else None)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2); stream.write('\n')
    print(f"{report['original_executions']} original executions; 3 drift rejections; no hardware initial value inferred")


if __name__ == '__main__':
    main()
