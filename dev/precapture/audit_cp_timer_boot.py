"""Pinned original timer descriptor, task arguments and peripheral admission.

All slices stop before timer-control, task-branch or MMIO instructions. They
do not deliver an interrupt, configure a peripheral or establish camera I/O.
The separate full-system experiments provide their own runtime evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm_const as R
from support.reference import SPECS

BASE, DATA, STOP = 0x108000, 0x30000000, 0x31000000


def audit(cp):
    if hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original stock CP')
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    for address in (0x631000, 0x5ff000, 0x5f5000):
        u.mem_map(address, 4096)
        u.mem_write(address, cp[address-BASE:address-BASE+4096])
    u.mem_map(DATA, 0x2000)
    u.mem_map(STOP, 4096)
    stops, seen = set(), []

    def boundary(cpu, address, size, user):
        if address in stops:
            seen.append(address)
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, boundary)

    def run(entry, targets, r0=0, r1=0):
        stops.clear(); stops.update(targets); seen.clear()
        for reg, value in ((R.UC_ARM_REG_R0, r0), (R.UC_ARM_REG_R1, r1),
                           (R.UC_ARM_REG_LR, STOP), (R.UC_ARM_REG_SP, DATA+0x1800)):
            u.reg_write(reg, value)
        u.emu_start(entry, 0xffffffff, count=100)
        assert len(seen) == 1 and u.reg_read(R.UC_ARM_REG_PC) == seen[0], 'Missing source boundary'
        return seen[0]

    cases = []
    before = bytes([0xa5])*64
    u.mem_write(DATA, before)
    assert run(0x6314d0, (0x631510,), r0=DATA) == 0x631510
    expected = bytearray(before)
    for offset, value in ((0,2000000),(4,0x7fffffff),(8,30),(12,0),
                          (16,0),(24,22),(28,0),(32,15),(36,0)):
        struct.pack_into('<I', expected, offset, value)
    assert bytes(u.mem_read(DATA,64)) == bytes(expected)
    cases.append(dict(case='native-timer-descriptor',counter_hz=2000000,IRQ=30,
                      timer_enable_executed=False,other_bytes_unchanged=True))

    for bank in (*range(10), 0xffffffff):
        before = bytes(u.mem_read(DATA,0x2000))
        at = run(0x5ffc5c, (0x5ffc78,STOP), r0=bank)
        if bank <= 8:
            assert at == 0x5ffc78
            effective = u.reg_read(R.UC_ARM_REG_R2) + (u.reg_read(R.UC_ARM_REG_R1) << 12)
            assert effective == 0xf1042000 + bank*0x1000
            assert u.reg_read(R.UC_ARM_REG_R0) == 0
        else:
            assert at == STOP and u.reg_read(R.UC_ARM_REG_R0) == 1
        assert bytes(u.mem_read(DATA,0x2000)) == before
        cases.append(dict(case='peripheral-bank-reset-admission',synthetic_bank=bank,
                          admitted=bank<=8,MMIO_executed=False))

    for arg, target in ((0,0x634780),(0x12345678,0x601c48),(0xffffffff,0x634780)):
        raw = bytearray([0xa5])*0x200
        struct.pack_into('<I',raw,8,DATA+0x100)
        struct.pack_into('<II',raw,0x104,arg,target)
        u.mem_write(DATA,bytes(raw))
        assert run(0x5f5914,(0x5f5920,),r1=DATA) == 0x5f5920
        assert (u.reg_read(R.UC_ARM_REG_R0),u.reg_read(R.UC_ARM_REG_R1)) == (arg,target)
        assert bytes(u.mem_read(DATA,len(raw))) == bytes(raw)
        cases.append(dict(case='task-trampoline-arguments',synthetic_argument=hex(arg),
                          synthetic_entry=hex(target),task_branch_executed=False))
    return dict(cases=cases,limits=[
        'No CP15 timer enable, IRQ delivery, MMIO store or task body is executed here',
        'Peripheral banking does not identify or emulate its hardware semantics',
        'Synthetic task fields are independent inputs, not native task creation evidence',
        'No sensor, AP peer, RAW ownership, saving or physical pre-capture is established'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    cp = args.cp.read_bytes()
    report = dict(schema='OFFLINE_CP_TIMER_TASK_PERIPHERAL_ADMISSION/1',camera_io=False,
                  CP_sha256=hashlib.sha256(cp).hexdigest(),**audit(cp))
    paths = [Path(__file__),Path(__file__).with_name('support')/'reference.py']
    report['sources'] = {str(p.relative_to(Path(__file__).parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(report,f,indent=2); f.write('\n')
    print(f"{len(report['cases'])} original timer/task/peripheral contracts; no physical capture claim.")


if __name__ == '__main__':
    main()
