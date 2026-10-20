"""Replay donor trigger predicate and compile its independent replacement.

Native original leaf/gate instructions run on synthetic data, with no OS,
transport or sensor stubs. The remaining mask dependency is explicitly raw.
"""
import argparse
import hashlib
import itertools
import json
import random
import struct
from pathlib import Path

from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
)
from unicorn.arm64_const import (
    UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
    UC_ARM64_REG_X4, UC_ARM64_REG_X5, UC_ARM64_REG_X6,
    UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC,
)
from support.reference import SPECS
from support.native_gate import Native
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM, STACK, STOP


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-root', type=Path, required=True)
    parser.add_argument('--zig', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    donor = (args.firmware_root / 'a1ii-4.00/components/cpapp-b.bin').read_bytes()
    if hashlib.sha256(donor).hexdigest() != SPECS['a1ii-4.00']['sha256']:
        raise ValueError('Unsupported original donor')
    target = (args.firmware_root / 'a7c2-2.01/components/cpapp-b.bin').read_bytes()
    if hashlib.sha256(target).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original target')
    # The same registered command establishes the cross-model field
    # correspondence. Execute both original stores, not a guessed offset.
    for data, table, pointer in [(donor, 0x10E3748, 0x380939), (target, 0xFF32A8, 0x356D41)]:
        assert struct.unpack_from('<2I', data, table) == (0x4064, pointer)
    engine = Native(donor, True)
    n = engine.u
    n.mem_map(0xAAD000, 4096)
    n.mem_write(0xAAD000, donor[0xAAD000:0xAAE000])
    rng = random.Random(201)
    buttons = [0, 0x40002, 0xFFFFFFFF, *[1 << i for i in range(32)],
               *[rng.getrandbits(32) for _ in range(5)]]
    vectors = list(itertools.product([0, 1, 2], [0, 1, 0x1A, 0x21, 2],
                                    [0, 1, 2, 3], [0, 1], buttons,
                                    [0, 0x10], [0, 0x11, 0x21, 0x41, 0x81, 0xFF]))
    expected = []
    for enabled, mode, trigger, dependency, mask, flags, selection in vectors:
        n.mem_write(MEM, bytes(4096))
        n.mem_write(MEM + 0x13C, struct.pack('<I', trigger))
        n.mem_write(MEM + 0x148, struct.pack('<I', mode))
        n.mem_write(MEM + 0x86C, struct.pack('<I', dependency))
        n.mem_write(engine.debug + 0xF0, bytes([flags, selection]))
        before = bytes(n.mem_read(MEM, 4096))
        for register, value in [(UC_ARM_REG_R0, enabled), (UC_ARM_REG_R1, MEM),
                                (UC_ARM_REG_R2, mask), (UC_ARM_REG_SP, STACK + 0x3000),
                                (UC_ARM_REG_LR, STOP | 1)]:
            n.reg_write(register, value)
        n.emu_start(0xAAD013, STOP, count=150)
        assert n.reg_read(UC_ARM_REG_PC) == STOP
        assert bytes(n.mem_read(MEM, 4096)) == before
        expected.append(n.reg_read(UC_ARM_REG_R0))
    setter = Native(target, False).u
    setter.mem_map(0x24E000, 4096)
    setter.mem_write(0x24E000, target[0x24E000:0x24F000])
    setter.mem_map(0x165A000, 0x2000)
    n.mem_map(0x278000, 4096)
    n.mem_write(0x278000, donor[0x278000:0x279000])
    n.mem_map(0x1502000, 0x2000)
    setter_checks = []
    for value in [0, 1, 2, 255]:
        for cpu, start, end, root, offset in [(n, 0x278938, 0x278946, 0x1502EC8, 0x86C),
                                              (setter, 0x24ED40, 0x24ED4E, 0x165A720, 0x700)]:
            cpu.mem_write(MEM, bytes(8) + bytes([value]))
            cpu.mem_write(root, b'\xA5' * 0x1000)
            cpu.reg_write(UC_ARM_REG_R0, MEM)
            cpu.emu_start(start | 1, end, count=20)
            assert cpu.reg_read(UC_ARM_REG_PC) == end
            actual = bytes(cpu.mem_read(root, 0x1000))
            wanted = bytearray(b'\xA5' * 0x1000)
            struct.pack_into('<I', wanted, offset, value)
            assert actual == wanted
        setter_checks.append(value)
    args.output.mkdir(parents=True, exist_ok=False)
    results = {}
    for arch, triple in [('thumb', 'thumb-linux-gnueabi'), ('aarch64', 'aarch64-linux-gnu')]:
        dest = args.output / (arch + '-s1-trigger.elf')
        compile_shared(args.zig, arch, dest,
            [Path(__file__).with_name('s1_trigger.c'), Path(__file__).with_name('capture_gate.c')], optimization='-O2', debug=False)
        u, syms = image_loader(dest, arch, ('precapture_s1_active', 'precapture_target_s1_active'))
        regs = ([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3] if arch == 'thumb' else
                [UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
                 UC_ARM64_REG_X4, UC_ARM64_REG_X5, UC_ARM64_REG_X6])
        sp, lr, pc = ((UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC) if arch == 'thumb' else
                      (UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC))
        for values, wanted in zip(vectors, expected):
            enabled, mode, trigger, dependency, mask, flags, selection = values
            for symbol, inputs in [('precapture_s1_active', values),
                                   ('precapture_target_s1_active', [enabled, trigger, MEM, mask, flags, selection])]:
                u.mem_write(MEM + 0x138, struct.pack('<I', mode))
                u.mem_write(MEM + 0x700, struct.pack('<I', dependency))
                for register, value in zip(regs, inputs):
                    u.reg_write(register, value)
                u.reg_write(sp, STACK + 0x3000)
                u.reg_write(lr, STOP | (arch == 'thumb'))
                if arch == 'thumb':
                    u.mem_write(STACK + 0x3000, struct.pack('<' + 'I' * len(inputs[4:]), *inputs[4:]))
                u.emu_start(syms[symbol], STOP, count=200)
                assert u.reg_read(pc) == STOP
                assert u.reg_read(regs[0]) == wanted, (arch, symbol, values, wanted, u.reg_read(regs[0]))
        results[arch] = {'donor_predicate': len(vectors), 'target_adapter': len(vectors)}
    report = {'mode': 'OFFLINE_NATIVE_S1_PREDICATE_ONLY', 'camera_io': False,
              'firmware_modified': False, 'native_cases': len(vectors),
              'compiled_native_comparisons': results,
              'result_sha256': hashlib.sha256(bytes(expected)).hexdigest(),
              'native_SET_S1AF_values': setter_checks,
              'field_binding': 'Command0x4064: donor master+0x86c -> target master+0x700',
              'limits': ['Synthetic button states do not deliver physical events',
                         'No task hooks, native enqueue, sensor operations or pixel buffers execute',
                         'The target must provide independent state and correct field mapping']}
    (args.output / 's1-trigger.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
