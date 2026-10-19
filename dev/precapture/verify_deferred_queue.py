"""Compare actual target S1 deferred ring with its independent C primitive.

No OS call executes. Native empty-pop's real ARM bzero is executed rather
than stubbed. Ring inputs/messages are synthetic and never reach a camera.
"""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC
from audit_control import SPECS
from verify_offline import image_loader, codegen_flags, MEM, STACK, STOP

SIZE, MESSAGE, OUT = 0x23C, MEM + 0x400, MEM + 0x500


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-root', type=Path, required=True)
    parser.add_argument('--zig', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    images = {}
    for model, spec in SPECS.items():
        data = (args.firmware_root / model / 'components/cpapp-b.bin').read_bytes()
        if hashlib.sha256(data).hexdigest() != spec['sha256']:
            raise ValueError('Unsupported original CP')
        images[model] = data
    target = images['a7c2-2.01']
    # Enqueue bodies match exactly; no assumption about global ownership.
    assert target[0xA17EAE:0xA17F02] == images['a1ii-4.00'][0xAAC5EE:0xAAC642]
    native = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for at, length in [(0xA17000, 4096), (0x516000, 0x4000)]:
        native.mem_map(at, length)
        native.mem_write(at, target[at:at + length])
    for at, size in [(MEM, 4096), (STACK, 0x4000), (STOP, 4096)]:
        native.mem_map(at, size)
    symbols = {'enqueue': 0xA17EAF, 'pop': 0xA17F03, 'peek': 0xA17F61}
    args.output.mkdir(parents=True, exist_ok=False)
    results = {}
    for arch, triple in [('thumb', 'thumb-linux-gnueabi'), ('aarch64', 'aarch64-linux-gnu')]:
        dest = args.output / (arch + '-deferred.elf')
        command = [str(args.zig), 'cc', '-target', triple, '-O2', '-shared', '-fPIC',
                   '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
                   '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '-nostdlib',
                   '-Wl,--no-undefined,-Bsymbolic', '-o', str(dest),
                   str(Path(__file__).with_name('deferred_queue.c'))]
        command[4:4] = codegen_flags(arch)
        proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if proc.returncode:
            raise RuntimeError(proc.stderr[-2000:])
        wanted = ('precapture_defer', 'precapture_deferred_pop', 'precapture_deferred_peek')
        u, csyms = image_loader(dest, arch, wanted)
        compiled = dict(zip(symbols, [csyms[s] for s in wanted]))
        counts = dict.fromkeys(symbols, 0)

        def invoke(cpu, code, architecture, operation):
            if architecture == 'thumb':
                r0, r1, sp, lr, pc = UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
            else:
                r0, r1, sp, lr, pc = UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC
            args2 = [OUT, MEM] if operation == 'pop' else [MEM, MESSAGE]
            cpu.reg_write(r0, args2[0])
            cpu.reg_write(r1, args2[1])
            cpu.reg_write(sp, STACK + 0x3000)
            cpu.reg_write(lr, STOP | (architecture == 'thumb'))
            try:
                cpu.emu_start(code, STOP, count=500)
            except Exception as exc:
                raise RuntimeError((architecture, operation, hex(cpu.reg_read(pc)),
                                    bytes(cpu.mem_read(cpu.reg_read(pc), 8)).hex())) from exc
            assert cpu.reg_read(pc) == STOP
            return cpu.reg_read(r0)

        for read in range(20):
            for write in range(20):
                ring = bytearray((i * 17 + 7) % 256 for i in range(SIZE + 32))
                struct.pack_into('<2I', ring, 0x234, read, write)
                message = struct.pack('<7I', 0x8240, 0x12345678, 0, 1, 9, 0, 0)
                for operation in symbols:
                    for cpu in [native, u]:
                        cpu.mem_write(MEM, bytes(ring))
                        cpu.mem_write(MESSAGE, message)
                        cpu.mem_write(OUT, b'\xA5' * 60)
                    nstatus = invoke(native, symbols[operation], 'thumb', operation)
                    status = invoke(u, compiled[operation], arch, operation)
                    assert bytes(native.mem_read(MEM, len(ring))) == bytes(u.mem_read(MEM, len(ring)))
                    assert bytes(u.mem_read(MEM + SIZE, 32)) == bytes(ring[SIZE:])
                    assert bytes(native.mem_read(OUT, 60)) == bytes(u.mem_read(OUT, 60))
                    assert bytes(u.mem_read(OUT + 28, 32)) == b'\xA5' * 32
                    assert bytes(u.mem_read(MESSAGE, 28)) == message
                    if operation == 'enqueue':
                        assert status & 0xFFFFFFFF == nstatus & 0xFFFFFFFF
                    elif operation == 'pop':
                        assert status == int(read != write)
                    else:
                        assert status == nstatus
                    counts[operation] += 1
        # Stateful native/compiled FIFO wraparound, capacity, and empty checks.
        for cpu in [native, u]:
            cpu.mem_write(MEM, bytes(SIZE))
        transactions = 0
        for cycle in range(5):
            messages = []
            for index in range(19):
                raw = struct.pack('<7I', 0x8240, cycle, index, 1, 0, 0, 0)
                messages.append(raw)
                for cpu, table, architecture in [(native, symbols, 'thumb'), (u, compiled, arch)]:
                    cpu.mem_write(MESSAGE, raw)
                    assert invoke(cpu, table['enqueue'], architecture, 'enqueue') == 0
                transactions += 1
            before = bytes(u.mem_read(MEM, SIZE))
            for cpu, table, architecture in [(native, symbols, 'thumb'), (u, compiled, arch)]:
                assert invoke(cpu, table['enqueue'], architecture, 'enqueue') & 0xFFFFFFFF == 0xFFFFFFFF
                assert bytes(cpu.mem_read(MEM, SIZE)) == before
            for raw in messages:
                for cpu, table, architecture in [(native, symbols, 'thumb'), (u, compiled, arch)]:
                    invoke(cpu, table['pop'], architecture, 'pop')
                    assert bytes(cpu.mem_read(OUT, 28)) == raw
                transactions += 1
            assert bytes(native.mem_read(MEM, SIZE)) == bytes(u.mem_read(MEM, SIZE))
        results[arch] = {'index_matrix': counts, 'stateful_fifo_transactions': transactions,
                         'capacity': 19, 'full_rejects_without_mutation': 5}
    report = {'mode': 'OFFLINE_NATIVE_DEFERRED_RING', 'camera_io': False,
              'firmware_modified': False, 'checks': results,
              'limits': ['Owner task must serialize all accesses; no locks are provided',
                         'No internal event ID has been installed or delivered',
                         'Ring correctness does not establish sensor or OS scheduling']}
    (args.output / 'deferred-ring.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
