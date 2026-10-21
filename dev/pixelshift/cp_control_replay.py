"""Continue native alternate control consumption through the full vector producer.

Offline only: factory parameters, synthetic RAM/frame inputs and optional
synthetic scales. Original consumer and full producer execute without a
precomputed vector. Post-request and next-frame-OFF calls are HOST-selected
experiments, not an automatic completion/abort sequence. GPIO stops before its
first helper; no MMIO, transport, hardware ack, settling or exposure executes.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_alternate_replay import profile as alternate_profile
from cp_defaults_replay import profile as defaults_profile
from cp_serial_replay import literals
from cp_vector_replay import _vector_sequence


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, default = defaults_profile(directory)
    _, alt = alternate_profile(directory)
    target = default['model'] == 'ILCE-7CM2'
    p = dict(consumer=0x418400 if target else 0x418618,
             producer=0xaa846c if target else 0xaa8306,
             mode_getter=0xaa98e0 if target else 0xaa977a,
             fallback_getter=0xaaf0fa if target else 0xaaef58,
             category4=0xa6c804 if target else 0xa6c6aa,
             category5=0xa6c8ae if target else 0xa6c754,
             idle=0xaa5e82 if target else 0xaa5d1c,
             gpio=0xaa5a70 if target else 0xaa590a,
             diagnostic=0xaa661a if target else 0xaa64b4)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    for key, register, size in (('mode_getter', 'r0', 12), ('fallback_getter', 'r1', 14)):
        at = p[key]
        code = list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))
        addresses = [v for r, v in literals(code) if r == register]
        if len(addresses) != 1 or (code[-1].mnemonic, code[-1].op_str) != ('bx', 'lr'):
            raise ValueError('Native control-state getter changed')
        p['mode' if key == 'mode_getter' else 'fallback'] = addresses[0]
    return data, p, default, alt


def control_sequence(directory, *, scales=None, observe_vector=None):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                                   UC_ARM_REG_R4, UC_ARM_REG_R10, UC_ARM_REG_PC,
                                   UC_ARM_REG_SP, UC_ARM_REG_LR)
    data, p, default, alt = profile(directory)
    finish, stack = 0x3001e000, 0x3001f000
    machine_holder, loaded = [], []
    phase, instruction_count = 'parameters', 0

    def hook(uc, at, size, unused):
        nonlocal instruction_count
        if phase == 'parameters' and at in default['locks']:
            # Inspected void parameter-loader locks only; no device return supplied.
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
            return
        if at in (p['gpio'], p['diagnostic']):
            raise ValueError('Control replay entered an omitted GPIO/diagnostic boundary')
        if not (0x108000 <= at and at + size <= 0x108000 + len(data)):
            raise ValueError('Control replay left the private CP program')
        instruction_count += 1

    def write_hook(uc, access, address, size, value, unused):
        if (phase == 'synthetic_next_frame_off' and size == 1
                and address == struct.unpack('<I', uc.mem_read(vector['export_root'], 4))[0] + 0x6f):
            return
        if ((0x1700000 <= address and address + size <= 0x1b40000)
                or (stack - 2048 <= address and address + size <= stack)):
            return
        raise ValueError('Native control code wrote outside synthetic RAM/stack: ' + hex(address))

    def run(cpu, at, end=finish):
        cpu.reg_write(UC_ARM_REG_SP, stack)
        cpu.reg_write(UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(at | 1, end, count=10000)
        if cpu.reg_read(UC_ARM_REG_PC) != end:
            raise ValueError('Native control code exceeded its instruction bound')

    def producer(cpu, vector, ordinal):
        nonlocal phase
        if ordinal == 0:
            machine_holder.append((cpu, vector))
            # Remaining unmapped native state is explicitly synthetic zero RAM.
            # No hardware/MMIO address is mapped.
            for page in range(0x1700000, 0x1b40000, 4096):
                if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                    cpu.mem_map(page, 4096)
        ch = cpu.hook_add(UC_HOOK_CODE, hook)
        wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
        if ordinal == 0:
            phase = 'parameters'
            for index in (38, 39, 40):
                cpu.reg_write(UC_ARM_REG_R0, default['ids'] + index * 4)
                cpu.reg_write(UC_ARM_REG_R1, default['destinations'] + index * 4)
                run(cpu, default['initialize'], default['initialize'] + 0x6a)
                if cpu.reg_read(UC_ARM_REG_R0) != 256:
                    raise ValueError('Native factory parameter load was incomplete')
                ident = struct.unpack_from('<I', data, default['ids'] - 0x108000 + index * 4)[0]
                loaded.append(ident)
            # Retain the upstream experiment's explicit synthetic shared flag.
            cpu.mem_write(vector['shared_state'] + 0x6f, b'\1')
        phase = 'consumer'
        run(cpu, p['consumer'])
        control_mode = cpu.mem_read(p['mode'], 1)[0]
        phase = 'producer'
        run(cpu, p['producer'])
        cpu.hook_del(ch)
        cpu.hook_del(wh)
        return dict(native_consumer_mode=control_mode, complete_producer_executed=True,
                    precomputed_vector_supplied=False)

    previous = _vector_sequence(directory, scales=scales, vector_producer=producer,
                                observe_vector=observe_vector)
    cpu, vector = machine_holder[0]
    requests = []
    ch = cpu.hook_add(UC_HOOK_CODE, hook)
    wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    last_vector = previous['shots'][-1]['vector_raw']
    for category, entry in ((4, p['category4']), (5, p['category5']), (0, p['idle'])):
        phase = 'post_request'
        cpu.reg_write(UC_ARM_REG_R0, 0x500)
        # Idle publishes before GPIO: stop at the first GPIO helper, do not skip it.
        run(cpu, entry, p['gpio'] if category == 0 else finish)
        run(cpu, alt['snapshot'], alt['snapshot'] + 0x2a)
        run(cpu, p['consumer'])
        run(cpu, p['producer'])
        actual = list(struct.unpack('<3i', cpu.mem_read(vector['vector_data'], 12)))
        trinity = cpu.mem_read(vector['snapshot_data'] + 0x6f, 1)[0]
        if (trinity != 1 or cpu.mem_read(alt['observed'] + 0x18, 1)[0] != category or actual != last_vector
                or cpu.mem_read(vector['vector_data'] + 12, 1)[0] != 2):
            raise ValueError('Inspected post-request path changed its TRINITY vector unexpectedly')
        requests.append(dict(category=category, vector_raw=actual,
                             native_consumer_mode=cpu.mem_read(p['mode'], 1)[0],
                             trinity_still_enabled=trinity == 1, gpio_executed=False))
    phase = 'synthetic_next_frame_off'
    fallback = [123456, -654321, 65536]
    cpu.mem_write(p['fallback'], struct.pack('<3i', *fallback))
    cpu.mem_write(0x30006000 + 0x98, bytes(4))
    cpu.reg_write(UC_ARM_REG_R4, 0x30006020)
    run(cpu, vector['flag_slice'], vector['flag_slice'] + 16)
    cpu.reg_write(UC_ARM_REG_R10, vector['export_root'])
    run(cpu, vector['export'], vector['export'] + 12)
    source = struct.unpack('<I', cpu.mem_read(vector['export_root'], 4))[0]
    exported = bytes(cpu.mem_read(source, 192))
    for register, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3),
                               struct.unpack('<4I', exported[:16])):
        cpu.reg_write(register, value)
    cpu.mem_write(stack, exported[16:])
    run(cpu, vector['publish'])
    cpu.reg_write(UC_ARM_REG_R2, 192)
    run(cpu, vector['snapshot'], vector['snapshot'] + 0x26)
    run(cpu, p['producer'])
    actual = list(struct.unpack('<3i', cpu.mem_read(vector['vector_data'], 12)))
    if (actual != fallback or cpu.mem_read(vector['snapshot_data'] + 0x6f, 1)[0] != 0
            or cpu.mem_read(vector['vector_data'] + 12, 1)[0] != 1
            or bytes(cpu.mem_read(0x108000, len(data))) != data):
        raise ValueError('Native next-frame OFF did not select fallback or changed its program')
    cpu.hook_del(ch)
    cpu.hook_del(wh)
    return dict(shots=[dict(vector_raw=s['vector_raw'], **s['producer'],
                           **({} if 'wire' not in s else {'wire': s['wire']})) for s in previous['shots']],
                original_scale_bytes=previous['original_scale_bytes'],
                additional_native_parameter_ids=loaded, post_requests=requests,
                off_next_frame=dict(vector_raw=actual, native_vector_mode=1, trinity=0,
                                    fallback_targets_synthetic=True),
                synthetic_initial_ram_and_frames=True, scales_synthetic=scales is not None,
                automatic_completion_or_abort_executed=False, physical_units_verified=False,
                camera_io=False, installable=False)


def compare(c2, reference):
    cases = []
    for scales in (None, (3, 5, 7)):
        a, b = control_sequence(c2, scales=scales), control_sequence(reference, scales=scales)
        if a != b:
            raise ValueError('C2/A7CR full native control path differs for the synthetic sequence')
        cases.append(dict(scales=scales, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-control/1', paired_cases=16,
                paired_frame_steps=8, paired_post_requests=6, paired_off_transitions=2,
                cases=cases, camera_io=False, installable=False, physical_shift_verified=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    report = compare(args.c2, args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
