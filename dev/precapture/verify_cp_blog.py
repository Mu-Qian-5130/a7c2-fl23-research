"""Compare BLOG parsing with the original CP recorder on synthetic memory.

Only recorder instructions execute. Lookup returns a synthetic subsystem;
mutexes are explicit single-thread no-ops, memcpy copies synthetic bytes,
and snprintf is skipped after cursor commit. No camera IPC, OS operation,
sensor call or real frame allocation is executed or reported successful.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from audit_control import SPECS
from decode_cp_blog import decode, FormatError

MEM, STACK, STOP = 0x30000000, 0x40000000, 0x60000000
SUB, RING, DATA = 60, 88, 128
MESSAGE = MEM + 0x1000


def synthetic(capacity):
    blob = bytearray(DATA + capacity)
    blob[:4] = b'ULOG'
    struct.pack_into('<I', blob, 12, 1)
    blob[16:20] = b'4.0\0'
    struct.pack_into('<I', blob, 36, len(blob))
    struct.pack_into('<I', blob, 56, len(blob) - 60)
    struct.pack_into('<4sIIHhhH', blob, SUB, b'SUBS', 4, len(blob) - SUB, 0, 1, 0, 0)
    struct.pack_into('<II', blob, SUB + 20, capacity + 40, RING)
    struct.pack_into('<4s9I', blob, RING, b'RBUF', DATA, capacity, capacity - 1,
                     DATA, DATA, DATA, 0, 0, 0)
    return bytes(blob)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cp = args.cp.read_bytes()
    if hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original CP')
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for address in [0x460000, 0xAE4000, 0xAE3000, 0x516000, 0x51F000, 0x1A7E000]:
        u.mem_map(address, 4096)
        if address < len(cp):
            u.mem_write(address, cp[address:address + 4096])
    u.mem_map(MEM, 0x4000)
    u.mem_map(STACK, 0x4000)
    u.mem_map(STOP, 4096)
    mocked_calls = {}

    def boundary(cpu, address, size, user):
        if address == STOP:
            cpu.emu_stop()
            return
        if address not in (0xAE4DA2, 0xAE37DC, 0xAE3838, 0x51660C, 0x51FA2C):
            return
        mocked_calls[address] = mocked_calls.get(address, 0) + 1
        if address == 0xAE4DA2:
            if cpu.reg_read(UC_ARM_REG_R0) != 4:
                raise AssertionError('Unexpected synthetic subsystem lookup')
            cpu.reg_write(UC_ARM_REG_R0, MEM + SUB)
        elif address == 0x51660C:
            dst, src, count = (cpu.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
            if not (MEM <= dst <= dst + count <= MEM + 0x4000 or
                    STACK <= dst <= dst + count <= STACK + 0x4000):
                raise AssertionError('Synthetic copy escaped memory')
            cpu.mem_write(dst, bytes(cpu.mem_read(src, count)))
        cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

    u.hook_add(UC_HOOK_CODE, boundary)
    cases, latest = [], None
    for capacity in (65, 97, 128, 257):
        original = synthetic(capacity)
        u.mem_write(MEM, original)
        u.mem_write(0x1A7E990, struct.pack('<I', MEM))
        u.mem_write(0x1A7E988, struct.pack('<I', MEM))
        u.mem_write(0x1A7E9C4, bytes(4))
        expected, overwritten = [], 0
        for index in range(36):
            length = (0, 1, 4, 12, 17, 24)[index % 6]
            payload = bytes((index + n) & 255 for n in range(length))
            stamp = index * 71 + 3
            message = struct.pack('<HHIIIQ', 2, 4, 0, length, 0, stamp) + payload
            u.mem_write(MESSAGE, message)
            u.reg_write(UC_ARM_REG_R0, MESSAGE)
            u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
            u.reg_write(UC_ARM_REG_LR, STOP | 1)
            u.emu_start(0x460371, 0xFFFFFFFF, count=3000)
            if u.reg_read(UC_ARM_REG_PC) != STOP:
                raise AssertionError('Native recorder did not return')
            expected.append((stamp, payload.hex()))
            while sum(16 + len(bytes.fromhex(p)) for _, p in expected) >= capacity:
                expected.pop(0)
                overwritten += 1
            latest = bytes(u.mem_read(MEM, len(original)))
            report = decode(latest, [(4, 0)])
            observed = [(r['timestamp'], r['payload_hex']) for r in report['rings'][0]['records']]
            if observed != expected:
                raise AssertionError('Parser differs from native synthetic recording order')
        cases.append(dict(capacity=capacity, sequential_appends=36, evicted_records=overwritten))
    # Reject corrupt input rather than manufacturing a partial trusted trace.
    rejected = []
    for label, offset, data in [
        ('magic', 0, b'FAIL'), ('version', 16, b'5.0\0'),
        ('extent', 36, struct.pack('<I', 1)), ('subsystem_count', 12, struct.pack('<I', 2)),
        ('ring_escape', SUB + 24, struct.pack('<I', len(latest))),
        ('oldest_escape', RING + 16, struct.pack('<I', DATA - 1)),
        ('record_count', RING + 28, struct.pack('<I', 0xFFFFFFFF)),
        ('free_mismatch', RING + 12, bytes(4)),
    ]:
        bad = bytearray(latest)
        bad[offset:offset + len(data)] = data
        try:
            decode(bytes(bad), [(4, 0)])
        except FormatError:
            rejected.append(label)
        else:
            raise AssertionError('Accepted corrupt ' + label)
    output = dict(schema='OFFLINE_CP_BLOG_NATIVE_RECORDER/1', camera_io=False,
        original_cp_sha256=hashlib.sha256(cp).hexdigest(), cases=cases,
        native_appends=144, corrupt_inputs_rejected=rejected,
        synthetic_boundaries={hex(k): v for k, v in mocked_calls.items()},
        limits=['Lookup, memcpy and single-thread mutex boundaries are synthetic',
                'Tests establish recorder layout and parsing, not real camera capture'])
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(output, stream, indent=2)
        stream.write('\n')
    print('144 original recorder appends/overwrites and 8 corruption rejections passed. No camera I/O.')


if __name__ == '__main__':
    main()
