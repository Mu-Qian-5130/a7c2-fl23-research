"""Trace the native nine-pair unit0b producer, with synthetic image geometry.

Executes original point scaling, original dimension-table/mode getter and
original runtime/shadow stores. A separately invoked original sampler then
uses a generated point to read four bytes from a synthetic image buffer.
The producer stops BEFORE the backup-write API; no success
is substituted and no persistence, actuator, real image or exposure executes.
This distinguishes numerical coordinate provenance from guessed IBIS units.
It does not establish every consumer or the complete purpose of unit0b.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_metadata_replay import program
from cp_sequence_replay import machine
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, model, _, _ = program(directory)
    target = model == 'ILCE-7CM2'
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    p = dict(entry=0x2371f0 if target else 0x237210,
             dimension=0x24d560 if target else 0x24d580,
             store=0x745f34 if target else 0x74614c,
             context_getter=0x746428 if target else 0x746640,
             sampler=0x745a8a if target else 0x745ca2)

    def code(at, length):
        return list(md.disasm(data[at-0x108000:at-0x108000+length], at))

    def call(at):
        row = code(at, 4)
        if len(row) != 1 or row[0].mnemonic != 'bl':
            raise ValueError('Native grid source call changed')
        return int(row[0].op_str.lstrip('#'), 0)

    p['mode_getter'] = call(p['dimension']+4)
    constants = literals(code(p['mode_getter'], 8))
    if len(constants) != 1:
        raise ValueError('Native grid mode source changed')
    p['mode'] = constants[0][1]
    bindings = [v for reg, v in literals(code(p['store']+0x14, 14)) if reg == 'r2']
    if len(bindings) != 1:
        raise ValueError('Native unit0b store binding changed')
    p['shadow'] = bindings[0]
    p['sample_format'] = next(v for reg, v in literals(code(p['sampler']+0x4c, 8)) if reg == 'r0')+0x22
    p['stop'] = p['store']+0x74
    if call(p['stop']) not in (0xbe938e, 0xbe91e8):
        raise ValueError('Native grid store no longer stops at backup-write API')
    p['regions'] = [(p['entry'], p['entry']+0xea),
                    (p['dimension'], p['dimension']+0x28),
                    (p['mode_getter'], p['mode_getter']+0x12),
                    (p['context_getter'], p['context_getter']+8),
                    (p['store'], p['stop']), (p['sampler'], p['sampler']+0x114)]
    return data, p


def replay(directory, *, mode=0, width=640, height=480):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ
    import unicorn.arm_const as arm
    data, p = profile(directory)
    if mode not in range(8) or not 2 <= width <= 65535 or not 1 <= height <= 65535:
        raise ValueError('Use a bounded synthetic geometry/mode fixture')
    pages = {p['mode'] & ~4095, p['shadow'] & ~4095, (p['shadow']+255) & ~4095,
             p['sample_format'] & ~4095}
    cpu = machine(data, pages)
    obj, root, config, geometry, request, grid, working = [0x30001000+n*0x1000 for n in range(7)]
    stack, finish = 0x3001f000, 0x3001e000
    points = [(12+x*40, 14+y*30) for y in range(3) for x in range(3)]
    # Distinct control values; these are geometry inputs, never calibration.
    tail = (47, 91)
    templates = struct.pack('<20H', *(v for pair in points for v in pair), *tail)
    cpu.mem_write(obj, struct.pack('<III', root, 0, geometry))
    cpu.mem_write(root+0x2d8, struct.pack('<II', config, working))
    cpu.mem_write(config+0x25, b'\1')
    cpu.mem_write(config+0x5c, templates)
    cpu.mem_write(geometry+0x6c, struct.pack('<HHI', width, height, 0x12345678))
    cpu.mem_write(request+0x34, struct.pack('<I', grid))
    cpu.mem_write(p['mode'], bytes([mode]))
    cpu.mem_write(p['shadow'], b'\xa5' * 256)
    cpu.mem_write(working, b'\x6b' * 0x100)
    cpu.mem_write(grid, b'\x7c' * 0x80)
    writes, visited = [], []

    def hook(uc, at, length, unused):
        if at == p['stop']:
            uc.emu_stop()
            return
        if not any(lo <= at and at+length <= hi for lo, hi in p['regions']):
            raise ValueError('Native grid source entered an unresolved dependency: ' + hex(at))
        visited.append(at)

    def write_hook(uc, access, at, length, value, unused):
        if stack-2048 <= at and at+length <= stack:
            return
        ranges = [(grid, 40), (working+0x2c, 48), (p['shadow'], 48)]
        if not any(lo <= at and at+length <= lo+n for lo, n in ranges):
            raise ValueError('Native grid producer changed unrelated state: ' + hex(at))
        writes.append((at, length))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.reg_write(arm.UC_ARM_REG_SP, stack)
    cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
    # Execute the original dimension getter first for an independent table
    # inspection; then the producer executes it again, not a host return hook.
    cpu.emu_start(p['dimension'] | 1, finish, count=100)
    raw = cpu.reg_read(arm.UC_ARM_REG_R0)
    original_width, original_height = raw & 65535, raw >> 16
    expected = []
    for x, y in points+[tail]:
        expected += [((width >> 1)*x+(original_width >> 1))//original_width,
                     (height*y+(original_height >> 1))//original_height]
    cpu.reg_write(arm.UC_ARM_REG_R0, 1)  # Select the fully initialized9-pair branch.
    cpu.reg_write(arm.UC_ARM_REG_R1, obj)
    cpu.reg_write(arm.UC_ARM_REG_R2, request)
    cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
    cpu.emu_start(p['entry'] | 1, finish, count=10000)
    if cpu.reg_read(arm.UC_ARM_REG_PC) != p['stop']:
        raise ValueError('Native grid source did not stop before persistence')
    if [cpu.reg_read(reg) for reg in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2)] != [
            0x2a4, 0x02a4000b, p['shadow']]:
        raise ValueError('Native point producer does not target the actual unit0b shadow')
    expected_grid = struct.pack('<20H', *expected)
    expected_record = expected_grid + struct.pack('<HHI', width >> 1, height, 0x12345678)
    if (bytes(cpu.mem_read(grid, 40)) != expected_grid
            or bytes(cpu.mem_read(working+0x2c, 48)) != expected_record
            or bytes(cpu.mem_read(p['shadow'], 48)) != expected_record
            or bytes(cpu.mem_read(p['shadow']+48, 208)) != b'\xa5' * 208
            or bytes(cpu.mem_read(config+0x5c, 40)) != templates):
        raise ValueError('Native grid coordinates/stores differ from source dimension scaling')

    # Feed one ORIGINAL generated point into the original image-buffer sampler.
    # This is a separately invoked consumer, not automatic camera scheduling.
    x, y = struct.unpack('<HH', cpu.mem_read(grid+16, 4))
    pixel_address = 0x31000000+4*((width >> 1)*y+x)
    page = pixel_address & ~4095
    cpu.mem_map(page, 4096)
    if pixel_address+4 > page+4096:
        cpu.mem_map(page+4096, 4096)
    cpu.mem_write(pixel_address, bytes([200, 100, 40, 180]))
    cpu.mem_write(geometry+0x70, struct.pack('<I', 0x31000000))
    cpu.mem_write(p['sample_format'], b'\1')
    sampled = []

    def read_hook(uc, access, at, length, value, unused):
        if 0x31000000 <= at < 0x32000000:
            sampled.extend(range(at, at+length))

    cpu.hook_add(UC_HOOK_MEM_READ, read_hook)
    cpu.reg_write(arm.UC_ARM_REG_R0, x)
    cpu.reg_write(arm.UC_ARM_REG_R1, y)
    cpu.reg_write(arm.UC_ARM_REG_R2, obj)
    cpu.reg_write(arm.UC_ARM_REG_SP, stack)
    cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
    cpu.emu_start(p['sampler'] | 1, finish, count=300)
    if (cpu.reg_read(arm.UC_ARM_REG_PC) != finish
            or cpu.reg_read(arm.UC_ARM_REG_R0) != 0x8c48a8
            or sorted(sampled) != list(range(pixel_address, pixel_address+4))):
        raise ValueError('Generated coordinate did not address the original image-buffer sample')
    return dict(mode=mode, image_width_field=width, image_height_field=height,
                original_dimension_table=[original_width, original_height],
                transformed_pairs=[expected[n:n+2] for n in range(0, 20, 2)],
                coordinate_pairs_copied=9, shadow_bytes_written=48,
                native_pending_backup_unit='0x2a4000b',
                original_dimension_getter_executed=True, runtime_and_shadow_stores_match=True,
                separately_invoked_image_sampler_executed=True,
                native_generated_coordinate_addresses_image_buffer=True,
                sampled_image_bytes=4, sampled_value=hex(0x8c48a8),
                image_geometry_inputs_are_synthetic=True, physical_units_identified=False,
                persistence_api_executed=False, actuator_or_exposure_executed=False,
                host_assigned_api_returns=False, instructions=len(visited),
                camera_io=False, installable=False)


def compare(c2, reference):
    rows = []
    for mode in range(8):
        for width, height in ((640, 480), (1280, 720), (1024, 682)):
            args = dict(mode=mode, width=width, height=height)
            a, b = replay(c2, **args), replay(reference, **args)
            if a != b:
                raise ValueError('Native C2/CR grid-coordinate provenance differs')
            rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-unit0b-grid-source/1', paired_cases=len(rows), cases=rows,
                camera_io=False, physical_shift_verified=False, installable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.c2, args.reference)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'physical_shift_verified')}))


if __name__ == '__main__':
    main()
