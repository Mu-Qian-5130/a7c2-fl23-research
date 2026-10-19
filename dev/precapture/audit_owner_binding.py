"""Derive and verify the target owner adapter from original initialization.

The native constructor and pointer-binding instructions execute on synthetic
objects. The property-registration call is a stop boundary; binding resumes
at the instruction following that call without executing or fabricating a
registration result. That unused result is not an OS-success mock.
"""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
    UC_ARM64_REG_X3, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC)
from audit_control import SPECS
from verify_offline import image_loader, codegen_flags, MEM, STACK, STOP


def words(*values):
    return struct.pack('<' + 'I' * len(values), *values)


def original_owner_fixture(cp, root):
    """Native synthetic constructor/binding; property registration omitted."""
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    u.mem_map(0, (len(cp) + 4095) & ~4095)
    u.mem_write(0, cp)
    u.mem_map(root & ~4095, 0x2000)
    u.mem_map(STACK, 0x4000)
    u.mem_map(STOP, 4096)
    def stop(cpu, address, size, user):
        if address == 0x3AE744:
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, stop)
    for start, end in ((0xA17B7E, STOP), (0xA17D1C, 0x3AE744), (0xA17D32, STOP)):
        if start != 0xA17D32:
            u.reg_write(UC_ARM_REG_R0, root)
            u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
            u.reg_write(UC_ARM_REG_LR, STOP | 1)
        u.emu_start(start | 1, end, count=20000)
        if u.reg_read(UC_ARM_REG_PC) != end:
            raise AssertionError('Unresolved synthetic native constructor')
    return bytes(u.mem_read(root, 0x600))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp', type=Path, required=True)
    parser.add_argument('--zig', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cp = args.cp.read_bytes()
    if hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original target')
    args.output.mkdir(parents=True, exist_ok=False)
    native = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    native.mem_map(0, (len(cp) + 4095) & ~4095)
    native.mem_write(0, cp)
    native.mem_map(MEM, 0x10000)
    native.mem_map(STACK, 0x4000)
    native.mem_map(STOP, 4096)
    stops, observed = {0x3AE744}, []
    def boundary(cpu, address, size, user):
        if address in stops:
            observed.append(address)
            cpu.emu_stop()
    native.hook_add(UC_HOOK_CODE, boundary)
    def run(start, end=STOP, registers=None):
        for reg, value in (registers or {}).items():
            native.reg_write(reg, value)
        native.emu_start(start | 1, end, count=20000)
        if native.reg_read(UC_ARM_REG_PC) != end:
            raise AssertionError('Unresolved original execution')
    # Derive static arguments from original getter/startup instructions.
    for entry in (0x7D31B8, 0xA17E10):
        run(entry, registers={UC_ARM_REG_LR: STOP | 1})
        if entry == 0x7D31B8:
            master = native.reg_read(UC_ARM_REG_R0)
        else:
            message_owner = native.reg_read(UC_ARM_REG_R0)
    stops.add(0xA17D1C)
    run(0xA19594, end=0xA17D1C, registers={UC_ARM_REG_SP: STACK + 0x3000})
    static_root = native.reg_read(UC_ARM_REG_R0)
    stops.remove(0xA17D1C)
    fixtures = []
    for root in (MEM + 0x1000, MEM + 0x2000, MEM + 0x3040):
        native.mem_write(root, bytes([0xA5]) * 0x600)
        run(0xA17B7E, registers={UC_ARM_REG_R0: root, UC_ARM_REG_SP: STACK + 0x3000,
                                UC_ARM_REG_LR: STOP | 1})
        run(0xA17D1C, end=0x3AE744, registers={UC_ARM_REG_R0: root,
            UC_ARM_REG_SP: STACK + 0x3000, UC_ARM_REG_LR: STOP | 1})
        # Native code after the omitted registration never consumes r0's result.
        run(0xA17D32)
        data = bytes(native.mem_read(root, 0x600))
        manager = struct.unpack_from('<5I', data, 0x98)
        controller = struct.unpack_from('<12I', data, 0xDC)
        assert manager == (0xE77A94, root + 0xAC, root + 0xDC, root + 0x108, root + 0x34)
        assert controller[:4] == (0xE77B40, root + 0x398, root + 0x34, root + 0x108)
        assert controller[7] == root + 0xAC and controller[9] == 0
        assert struct.unpack_from('<I', data, 0x108)[0] == 0xE77F08
        fixtures.append((root, data))
    # Dispatch method +0x18 leads to the already-traced S1 receiver.
    vtable = struct.unpack_from('<13I', cp, 0xE77B40 - 0x108000)
    assert (vtable[6] & ~1) - 0x108000 == 0x3ACCF0
    assert (vtable[8] & ~1) - 0x108000 == 0xA180DE
    # Execute native manager selection at real linked addresses, stopping
    # before either selected controller's admission predicate executes.
    linked = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    linked.mem_map(0x108000, (len(cp) + 4095) & ~4095)
    linked.mem_write(0x108000, cp)
    linked.mem_map(MEM, 0x10000)
    linked.mem_map(STACK, 0x4000)
    selected = []
    def selected_controller(cpu, address, size, user):
        if address in (0xA18220 + 0x108000, 0xA18476 + 0x108000):
            selected.append((address, cpu.reg_read(UC_ARM_REG_R0)))
            cpu.emu_stop()
    linked.hook_add(UC_HOOK_CODE, selected_controller)
    routing = []
    root, fixture = fixtures[0]
    for event, expected in ((0x8205, 0xDC), (0x8206, 0xDC), (0x8240, 0xAC), (0x8300, 0xDC)):
        linked.mem_write(root, fixture)
        linked.mem_write(MEM, words(event, 0, 0, 0, 0, 0, 0))
        linked.reg_write(UC_ARM_REG_R0, root + 0x98)
        linked.reg_write(UC_ARM_REG_R1, MEM)
        linked.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
        selected.clear()
        linked.emu_start(0xA17FBA + 0x108001, 0xFFFFFFFF, count=100)
        assert len(selected) == 1 and selected[0][1] == root + expected
        assert bytes(linked.mem_read(root, 0x600)) == fixture
        routing.append(dict(event=hex(event), selected_controller_offset=hex(expected),
            admission_boundary_va=hex(selected[0][0]), admission_executed=False))
    results = {}
    for arch, target in (('thumb', 'thumb-linux-gnueabi'), ('aarch64', 'aarch64-linux-gnu')):
        dest = args.output / (arch + '-owner-binding.elf')
        command = [str(args.zig), 'cc', '-target', target, *codegen_flags(arch), '-Oz', '-g',
            '-shared', '-fPIC', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
            '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '-nostdlib',
            '-Wl,--no-undefined,-Bsymbolic', '-o', str(dest),
            str(Path(__file__).with_name('cp_owner_binding.c'))]
        build = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if build.returncode:
            raise RuntimeError(build.stderr[-2500:])
        u, symbols = image_loader(dest, arch, ('precapture_target_bind_owner',))
        u.mem_map(MEM + 0x1000, 0x4000)
        if arch == 'thumb':
            regs = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
            sp, lr, pc, width = UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, 4
        else:
            regs = (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3)
            sp, lr, pc, width = UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC, 8
        checked = 0
        for root, data in fixtures:
            invalid = [(label, at, value) for label, at, value in (
                ('manager-vtable', 0x98, 0), ('wrong-controller', 0xA0, root + 0xC),
                ('wrong-context', 0xA4, root + 0x98), ('controller-vtable', 0xDC, 0),
                ('wrong-deferred-ring', 0xE0, root + 0x15C), ('controller-context', 0xE8, root),
                ('context-vtable', 0x108, 0))]
            cases = [('native-fixture', data, MEM, root + 0x98, 1)]
            for label, at, value in invalid:
                bad = bytearray(data)
                struct.pack_into('<I', bad, at, value)
                cases.append((label, bytes(bad), MEM, root + 0x98, -95))
            cases.extend([('output-alias', data, root + 0x500, root + 0x98, -22),
                          ('unaligned-manager', data, MEM, root + 0x99, -22),
                          ('null-manager', data, MEM, 0, -22)])
            for label, fixture, output, manager, expected in cases:
                u.mem_write(root, fixture)
                u.mem_write(MEM, bytes([0xA5]) * 64)
                for reg, value in zip(regs, (output, manager, master, message_owner)):
                    u.reg_write(reg, value)
                u.reg_write(sp, STACK + 0x3000)
                u.reg_write(lr, STOP | (arch == 'thumb'))
                u.emu_start(symbols['precapture_target_bind_owner'], STOP, count=500)
                assert u.reg_read(pc) == STOP
                assert u.reg_read(regs[0]) & 0xFFFFFFFF == expected & 0xFFFFFFFF
                assert bytes(u.mem_read(root, 0x600)) == fixture
                raw = bytes(u.mem_read(MEM, 64))
                if expected == 1:
                    fmt = '<5' + ('I' if width == 4 else 'Q')
                    assert raw[:5 * width] == struct.pack(fmt, master, root + 0x108,
                        root + 0xDC, root + 0x398, message_owner)
                    assert raw[5 * width:] == bytes([0xA5]) * (64 - 5 * width)
                else:
                    assert raw == bytes([0xA5]) * 64
                checked += 1
        results[arch] = dict(cases=checked, native_objects_preserved=True,
                            rejected_output_preserved=True)
    report = dict(schema='OFFLINE_NATIVE_CP_OWNER_BINDING/1', camera_io=False,
        original_cp_sha256=hashlib.sha256(cp).hexdigest(), native_constructor_cases=len(fixtures),
        omitted_property_registration=hex(0x3AE744), registration_result_assumed=False,
        static_addresses={k: hex(v) for k, v in dict(root=static_root, manager=static_root + 0x98,
            controller=static_root + 0xDC, context=static_root + 0x108,
            deferred_ring=static_root + 0x398, master=master, message_owner=message_owner).items()},
        compiled=results, native_manager_routes=routing,
        limits=['No task, sensor, registration or message send executes',
            'Adapter is not installed and does not intercept the proposed event0x8240',
            'Native manager admits a fixed event list; a leaf-only event hook is insufficient',
            'Live ownership, scheduling and pixel retention remain unverified'])
    (args.output / 'owner-binding.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('Original constructor/pointer binding and 66 compiled adapter cases passed. No camera I/O.')


if __name__ == '__main__':
    main()
