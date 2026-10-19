"""Native dequeue metadata slices and actual error/route leaf comparisons.

Synthetic frames contain sentinel RAW IDs. The slices never allocate/free
pixels, remove metadata nodes, run a scheduler, save a file, or access USB.
"""
import argparse
import hashlib
import itertools
import json
import struct
import subprocess
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R8, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC
from audit_control import SPECS
from verify_offline import image_loader, codegen_flags, MEM, STACK, STOP

FRAME, QUEUE, FRAME_SIZE = MEM, MEM + 0x10000, 0x6800


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--firmware-root', type=Path, required=True)
    p.add_argument('--zig', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    blob = (a.firmware_root / 'a7c2-2.01/components/cpapp-b.bin').read_bytes()
    if hashlib.sha256(blob).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported target CP')
    n = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for at in [0x372000, 0x37E000, 0xA11000]:
        n.mem_map(at, 4096)
        n.mem_write(at, blob[at:at + 4096])
    for at, size in [(MEM, 0x12000), (STACK, 0x4000), (STOP, 4096)]:
        n.mem_map(at, size)
    for at, size in [(0xA0C000, 0x2000), (0x379000, 4096), (0x37F000, 4096), (0xA10000, 4096),
                     (0x394000, 4096), (0xA04000, 4096), (0x36C000, 4096), (0x516000, 0x4000)]:
        n.mem_map(at, size);n.mem_write(at, blob[at:at + size])
    n.mem_map(0x1A4F000, 0x4000)
    stops, observed = set(), []

    def boundary(cpu, address, size, user):
        if address in stops:
            observed.append((address, [cpu.reg_read(r) for r in [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2]]))
            cpu.emu_stop()

    n.hook_add(UC_HOOK_CODE, boundary)

    # Execute the original pure descriptor initializer. These are function
    # descriptors, not live task execution or allocated image storage.
    n.reg_write(UC_ARM_REG_LR, STOP | 1)
    n.emu_start(0xA0C46B, STOP, count=3000)
    assert n.reg_read(UC_ARM_REG_PC) == STOP
    stage6 = struct.unpack('<5I', n.mem_read(0x1A500F4 + 8 * 20, 20))
    assert stage6 == (0xB0DD6F, 0, 0x481E39, 0, 0)
    phase_boundaries = [0xA0DEA0, 0xA0DEE2, 0xA1071E, 0x394A38, 0x37FFC0]
    dispatch = []
    pipeline = MEM + 0x10100
    for phase, target in enumerate(phase_boundaries):
        n.mem_write(pipeline, bytes(64))
        n.mem_write(pipeline, struct.pack('<I', FRAME))
        n.mem_write(pipeline + 0x27, bytes([phase]))
        n.reg_write(UC_ARM_REG_R0, pipeline)
        stops = set(phase_boundaries)
        before = len(observed)
        n.emu_start(stage6[2] - 0x108000, 0xFFFFFFFF, count=30)
        assert len(observed) == before + 1 and observed[-1][0] == target
        dispatch.append({'phase': phase, 'body_file': hex(target), 'body_executed': False})
    # Original bulk-cleanup loop scans35 IDs and preserves them until the
    # real native release routine is entered. Do not return fake success.
    releases = []
    for index in [0, 17, 34, None]:
        frame = bytearray(b'\xA5' * FRAME_SIZE)
        for i in range(35):
            struct.pack_into('<I', frame, 0x5AD8 + 4 * i, 0xFFFFFFFF)
        if index is not None:
            struct.pack_into('<I', frame, 0x5AD8 + 4 * index, 0x12340000 + index)
        n.mem_write(FRAME, bytes(frame))
        n.reg_write(UC_ARM_REG_R4, FRAME)
        n.reg_write(UC_ARM_REG_R5, 0x5AD8)
        n.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
        stops = {0x36C2AC, 0xA04D80}
        before = len(observed)
        n.emu_start(0xA10797, 0xFFFFFFFF, count=400)
        assert len(observed) == before + 1
        at, values = observed[-1]
        assert at == (0xA04D80 if index is None else 0x36C2AC)
        assert values[0] == FRAME
        if index is not None:
            assert values[1:] == [index, 0]
        assert bytes(n.mem_read(FRAME, FRAME_SIZE)) == bytes(frame)
        releases.append({'valid_ID_index': index, 'boundary_file': hex(at), 'ID_unchanged_before_release': True})
    # Separate post-service local slice. There is no emulated release
    # result: begin AFTER that service boundary with explicit inputs.
    frame = bytearray(b'\xA5' * FRAME_SIZE)
    struct.pack_into('<I', frame, 0x5AD8, 0x12345678)
    n.mem_write(FRAME, bytes(frame))
    n.reg_write(UC_ARM_REG_R4, FRAME + 0x5AD8)
    n.reg_write(UC_ARM_REG_R5, 0)
    n.reg_write(UC_ARM_REG_R6, FRAME)
    n.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
    stops = set()
    n.emu_start(0x36C2D1, 0x36C3A2, count=200)
    assert n.reg_read(UC_ARM_REG_PC) == 0x36C3A2
    struct.pack_into('<I', frame, 0x5AD8, 0xFFFFFFFF)
    frame[0x5EA8:0x5EBC] = bytes(20)
    assert bytes(n.mem_read(FRAME, FRAME_SIZE)) == bytes(frame)

    def native_meta(frame, queue, discard):
        n.mem_write(FRAME, frame)
        n.mem_write(QUEUE, queue)
        for reg, value in [(UC_ARM_REG_R4, FRAME), (UC_ARM_REG_R5, QUEUE),
                           (UC_ARM_REG_R8, FRAME + 0x6710)]:
            n.reg_write(reg, value)
        if discard:
            n.emu_start(0x372457, 0x372462, count=20)
            assert n.reg_read(UC_ARM_REG_PC) == 0x372462
        else:
            n.emu_start(0x372487, 0x3724AC, count=50)
            assert n.reg_read(UC_ARM_REG_PC) == 0x3724AC
            # Stop-before-logging first slice, then run the next actual
            # field-store block. No log or OS call is faked as successful.
            n.emu_start(0x3724C3, 0x3724CA, count=20)
            assert n.reg_read(UC_ARM_REG_PC) == 0x3724CA
        return bytes(n.mem_read(FRAME, FRAME_SIZE)), bytes(n.mem_read(QUEUE, 64))

    def native_route(frame):
        n.mem_write(FRAME, frame)
        n.mem_write(STACK + 0x3000, struct.pack('<4I', 0, 0, 0, STOP | 1))
        n.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
        n.reg_write(UC_ARM_REG_R4, FRAME)
        n.emu_start(0x37E047, STOP, count=100)
        assert n.reg_read(UC_ARM_REG_PC) == STOP
        return n.reg_read(UC_ARM_REG_R0)

    # The real shared frame-consumer dispatch descriptors, not inferred
    # record/delete function names. Route6 begins with native descriptor8.
    descriptors = {}
    for route in [4, 5, 6, 7]:
        pointer = struct.unpack_from('<I', blob, 0x110F2EC - 0x108000 + route * 4)[0]
        descriptors[str(route)] = {'pointer': hex(pointer),
                                  'words': list(struct.unpack_from('<12I', blob, pointer - 0x108000))}
    assert descriptors['6']['words'] == [8] + [0] * 11
    a.output.mkdir(parents=True, exist_ok=False)
    reports = {}
    for arch, triple in [('thumb', 'thumb-linux-gnueabi'), ('aarch64', 'aarch64-linux-gnu')]:
        dest = a.output / (arch + '-frame-route.elf')
        cmd = [str(a.zig), 'cc', '-target', triple, *codegen_flags(arch), '-O2', '-shared', '-fPIC',
               '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-fno-unwind-tables',
               '-fno-asynchronous-unwind-tables', '-nostdlib', '-Wl,--no-undefined,-Bsymbolic',
               '-o', str(dest), str(Path(__file__).with_name('frame_route.c'))]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
        u, syms = image_loader(dest, arch, ('precapture_dequeue_metadata', 'precapture_timeshift_route'))
        u.mem_map(MEM + 0x1000, 0x11000)
        regs = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2] if arch == 'thumb' else [UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2]
        sp, lr, pc = (UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC) if arch == 'thumb' else (UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC)

        def call(symbol, inputs):
            for reg, value in zip(regs, inputs):
                u.reg_write(reg, value)
            u.reg_write(sp, STACK + 0x3000)
            u.reg_write(lr, STOP | (arch == 'thumb'))
            u.emu_start(syms[symbol], STOP, count=200)
            assert u.reg_read(pc) == STOP
            return u.reg_read(regs[0]) & 0xFFFFFFFF

        cases = 0
        for first_group, frame_sequence, group, discard in itertools.product([0, 1], [0, 1, 5, 0xFFFFFFFF], [0, 5], [0, 1]):
            frame, queue = bytearray(b'\xA5' * FRAME_SIZE), bytearray(b'\x5A' * 64)
            struct.pack_into('<I', frame, 0x66E8, 2)
            struct.pack_into('<I', frame, 0x208, frame_sequence)
            struct.pack_into('<II', queue, 0x24, 13, group)
            queue[0x2C], queue[0x2D] = 1, first_group
            before_frame = bytes(frame)
            wanted_frame, wanted_queue = native_meta(bytes(frame), bytes(queue), discard)
            u.mem_write(FRAME, bytes(frame));u.mem_write(QUEUE, bytes(queue))
            assert call('precapture_dequeue_metadata', [QUEUE, FRAME, discard]) == int(not discard)
            actual = bytes(u.mem_read(FRAME, FRAME_SIZE))
            assert actual == wanted_frame and bytes(u.mem_read(QUEUE, 64)) == wanted_queue
            # All RAW IDs/descriptors remain untouched by dequeue decisions.
            assert actual[0x5AD8:0x5C10] == before_frame[0x5AD8:0x5C10]
            for error in [0, 1, 2, 7, 8, 0x10, 0x20, 0x80, 0xB8, 0x100]:
                final = bytearray(actual)
                struct.pack_into('<I', final, 0x617C, error)
                u.mem_write(FRAME, bytes(final))
                assert call('precapture_timeshift_route', [FRAME]) == native_route(bytes(final))
                assert bytes(u.mem_read(FRAME, FRAME_SIZE)) == bytes(final)
                cases += 1
        reports[arch] = {'metadata_and_route_cases': cases, 'RAW_ID_fields_preserved': True}
    report = {'mode': 'OFFLINE_NATIVE_DEQUEUE_METADATA_AND_ROUTING', 'camera_io': False,
              'firmware_modified': False, 'checks': reports, 'native_route_descriptors': descriptors,
              'native_descriptor_initializer_executed': True, 'native_route6_stage_dispatch': dispatch,
              'native_bulk_release_boundaries': releases, 'post_service_ID_descriptor_clear_slice_verified': True,
              'limits': ['Metadata node removal and native locks were not executed',
                         'No RAW release or image recording was synthesized',
                         'Route4/5/6 are native dispatch decisions, not physical saved/deleted images']}
    (a.output / 'frame-route.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
