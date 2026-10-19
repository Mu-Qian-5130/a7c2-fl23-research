"""Original CAP_MGR construction, cancellation mask and request13 admission.

All owners/requests/modes are synthetic. Run pure original constructors and
field operations. Separate post-log slices take explicit input registers;
no logging, timer, allocation, IPC or hardware call is made successful.
This is not an installer or a camera recording/retention test.
"""
import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
    UC_ARM_REG_R8, UC_ARM_REG_R10, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from verify_extension_layout import PINNED

BASE, OWNER, WIRE, STACK, STOP = 0x108000, 0x30000000, 0x30002000, 0x40000000, 0x20000000
DEBUG = 0x1a533a4


def words(*v):
    return struct.pack('<' + 'I' * len(v), *v)


class NativeCapture:
    def __init__(self, cp):
        self.u = u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        u.mem_map(BASE, (len(cp) + 4095) & ~4095)
        u.mem_write(BASE, cp)
        for at, size in [(OWNER, 0x10000), (STACK, 0x10000), (STOP, 4096),
                          (DEBUG & ~4095, 4096)]:
            u.mem_map(at, size)
        self.stops, self.observed = set(), []
        # External/native service boundaries never execute in this audit.
        self.external = {BASE + n for n in (0xa3c516, 0xa3c57a, 0x69f488,
            0x9dc38e, 0x9dc4de, 0x9dbcca, 0x9dbbfa, 0x45d204, 0x45cb38, 0xae133a,
            0xa3b61c)}
        def trace(cpu, at, size, user):
            if at in self.stops or at in self.external:
                self.observed.append(dict(address=at, args=[cpu.reg_read(r) for r in
                    (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)], executed=False))
                cpu.emu_stop()
        u.hook_add(UC_HOOK_CODE, trace)

    def run(self, start, stops, inputs=()):
        u = self.u
        for reg, value in inputs:
            u.reg_write(reg, value)
        self.stops = {BASE + n for n in stops} | {STOP}
        self.observed.clear()
        try:
            u.emu_start(BASE + start | 1, 0xffffffff, count=15000)
        except UcError as error:
            raise RuntimeError('Original execution failed at ' + hex(u.reg_read(UC_ARM_REG_PC)) +
                ' args=' + repr([hex(u.reg_read(r)) for r in
                    (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)])) from error
        assert len(self.observed) == 1
        got = self.observed[0]
        assert u.reg_read(UC_ARM_REG_PC) == got['address']
        assert got['address'] in self.stops, 'Unexpected external boundary: ' + hex(got['address'])
        return got

    def call(self, start, values):
        inputs = list(zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), values))
        inputs += [(UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)]
        return self.run(start, (), inputs)

    def fixture(self):
        u = self.u
        u.mem_write(OWNER, bytes(0x1000))  # Native global normally follows BSS clear.
        u.mem_write(OWNER + 0x1000, bytes([0xa5]) * 64)
        self.call(0x9da010, [OWNER])  # Whole original constructor, including native ARM bzero.
        # Separate original pointer/init slice AFTER backup/timer binding.
        # The omitted binding reads hardware/configuration; no return is supplied.
        self.run(0x9d94be, (0x9d9556,), [(UC_ARM_REG_R4, OWNER),
            (UC_ARM_REG_R8, OWNER + 0x2ac), (UC_ARM_REG_SP, STACK + 0x8000)])
        assert struct.unpack('<I', u.mem_read(OWNER + 0x15c, 4))[0] == BASE + 0x350559
        assert struct.unpack('<3I', u.mem_read(OWNER + 0x27c, 12)) == (
            OWNER + 0x158, OWNER + 0x298, OWNER + 0x2ac)
        self.call(0x9d940e, [OWNER + 0x298, 0x4000000])
        assert struct.unpack('<I', u.mem_read(OWNER + 0x2a0, 4))[0] == 0x4000000
        # Explicit pre-existing synthetic timer metadata, rather than the
        # omitted configuration reader's return. It contains no pixel buffer.
        u.mem_write(OWNER + 0x5000, words(2, 0, 0, 0))
        u.mem_write(OWNER + 0x2b0, words(OWNER + 0x5000))
        self.call(0x9d89e6, [OWNER + 0x2ac])
        assert bytes(u.mem_read(OWNER + 0x1000, 64)) == bytes([0xa5]) * 64
        return bytes(u.mem_read(OWNER, 0x1000))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cp = a.cp.read_bytes()
    digest = hashlib.sha256(cp).hexdigest()
    if digest not in PINNED:
        raise ValueError('Unsupported complete target CP')
    # Pin native queue's command dispatch, rather than assigning the handler.
    assert 0x3511a0 + 2 * cp[0x3511a0 + 0x403d - 0x4036] == 0x3511fa
    n = NativeCapture(cp)
    u = n.u
    fixture = n.fixture()
    cancelled = []
    for mask, action in itertools.product((0, 4, 0x8000, 0x20000, 0x4000000, 0x220402, 0xffffffff), (0, 1)):
        u.mem_write(OWNER, fixture)
        u.mem_write(OWNER + 0x2a0, words(mask))
        wire = bytes([5, 0, 0x3d, 0x40]) + words(0, 4) + bytes([action, 0, 0, 0])
        u.mem_write(WIRE, wire)
        before = bytearray(u.mem_read(OWNER, 0x1000))
        got = n.run(0x9d9686, (0x9d972e,), [(UC_ARM_REG_R4, OWNER),
            (UC_ARM_REG_R5, WIRE), (UC_ARM_REG_R6, WIRE + 12),
            (UC_ARM_REG_R10, 0x90030001), (UC_ARM_REG_SP, STACK + 0x8000)])
        expected = mask | 4 if action else mask & ~4
        struct.pack_into('<I', before, 0x2a0, expected)
        assert bytes(u.mem_read(OWNER, 0x1000)) == bytes(before)
        assert bytes(u.mem_read(WIRE, 16)) == wire
        assert got['args'][0] == OWNER + 0x278
        cancelled.append(dict(mask_before=hex(mask), cancel=bool(action), mask_after=hex(expected),
            stopped_before_native_arbitration=True))
    # Release of a controller with its native +0x1a set may send an additional
    # service notification. Stop there; do not make it return successfully.
    u.mem_write(OWNER, fixture)
    u.mem_write(OWNER + 0x292, b'\x01')
    u.mem_write(OWNER + 0x2a0, words(4))
    u.mem_write(WIRE, bytes([5, 0, 0x3d, 0x40]) + words(0, 4) + bytes(4))
    got = n.run(0x9d9686, (0x9dc38e,), [(UC_ARM_REG_R4, OWNER),
        (UC_ARM_REG_R5, WIRE), (UC_ARM_REG_R6, WIRE + 12),
        (UC_ARM_REG_R10, 0x90030001), (UC_ARM_REG_SP, STACK + 0x8000)])
    assert got['args'][:2] == [0x40000000, 0]
    assert struct.unpack('<I', u.mem_read(OWNER + 0x2a0, 4))[0] == 0
    release_service = dict(address=hex(got['address']), args=got['args'], executed=False)

    admission = []
    for mode, mask, suppress in itertools.product((0, 1, 10, 22),
            (0, 4, 0x8000, 0x20000, 0x40000, 0x100000, 2, 0x4000000), (0, 4)):
        u.mem_write(OWNER, fixture)
        # Native admission reads flags-context+4, not CAP owner+4 (callback).
        n.call(0x9d9470, [OWNER + 0x298, mode])
        u.mem_write(OWNER + 0x2a0, words(mask, suppress))
        # Explicit native request slot13, not an acquired frame/RAW ID.
        u.mem_write(OWNER + 0x158 + 13 * 16 + 0x14, b'\x01')
        u.mem_write(OWNER + 0x158 + 13 * 16 + 0x18, words(0x12345678, 0x90030001))
        # Native pure priority/selector execute together on the constructed owner.
        n.call(0x9d917c, [OWNER + 0x158])
        assert u.reg_read(UC_ARM_REG_R0) == 13
        # Separate original post-diagnostic arbitration slice, with explicit
        # selected request/context. The preceding timer/config logging is not
        # executed or made to return. No successful dispatch is fabricated.
        got = n.run(0x9da36e, (0xa3b61c, 0x9dc38e, 0x9da430), [
            (UC_ARM_REG_R5, OWNER + 0x278), (UC_ARM_REG_R4, 13),
            (UC_ARM_REG_R10, 0x12345678), (UC_ARM_REG_SP, STACK + 0x8000)])
        boundary = got['address'] - BASE
        expected_admission = mask & ~suppress == 0 and mode in (1, 22)
        assert (boundary == 0xa3b61c) == expected_admission, (mode, hex(mask), hex(suppress), hex(boundary))
        if boundary == 0xa3b61c:
            assert got['args'] == [4, 0x2000, 0, 0]
            # Explicit post-diagnostic slice, not a manufactured log return.
            got = n.run(0x9da394, (0x69f488,), [(UC_ARM_REG_R5, OWNER + 0x278),
                (UC_ARM_REG_R4, 13), (UC_ARM_REG_R10, 0x12345678),
                (UC_ARM_REG_SP, STACK + 0x8000)])
            assert u.mem_read(OWNER + 0x290, 2) == b'\x01\x01'
            result = 'admitted-before-diagnostic-and-separate-slice-reaches-timer'
        elif boundary == 0x9dc38e:
            assert mask & ~suppress
            result = 'native-cancellation-service-boundary'
        else:
            result = 'native-nonadmission-continuation'
        admission.append(dict(mode_raw=mode, reason_mask=hex(mask), suppression=hex(suppress),
            result=result, boundary_file=hex(boundary),
            separate_postdiagnostic_boundary_file=hex(got['address'] - BASE)
                if expected_admission else None, external_executed=False))
    report = dict(schema='OFFLINE_ORIGINAL_CAPTURE_TRANSITION/1', cp_sha256=digest,
        camera_io=False, firmware_candidate_written=False, original_constructor_executed=True,
        original_pointer_binding_slice_executed=True,
        timer_descriptor_is_synthetic=True,
        positive_request13_admission_cases=sum(x['result'].startswith('admitted-') for x in admission),
        timer_backup_binding_executed=False, cancel_masks=cancelled,
        release_extra_service=release_service, request13_admission=admission,
        limits=['Owners, configuration masks, request slots and modes are synthetic',
            'No lock, timer, IPC, allocation, sensor, image save or release service executes',
            'Selected request13 is not evidence of pre-trigger exposure or saved pixels',
            'Passing cancellation send is not evidence that CAP_MGR processed it',
            'No cached parameter refresh event or cross-task synchronization is supplied'])
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print('Original CAP owner, 14 reason-mask transitions, extra release and 64 admission paths checked.')


if __name__ == '__main__':
    main()
