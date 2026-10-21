"""Build original first/second alternate-TC packet pairs, without transport.

Native BK4 loading selects the first formatter's factory variant. The first
40-byte packet/checksum execute before the existing native second formatter.
Other RAM/frame data and optional scales are synthetic. A later H8 replay can
consume these bytes, but this module never opens a device or establishes a
hardware acknowledgement. The existing CP receive checks use synthetic replies.
With --full-control the original consumer and complete producer run in the
same RAM before the formatters; task stages are still invoked by the host.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_alternate_wire_replay import wire_sequence
from cp_defaults_replay import profile as defaults_profile
from cp_serial_replay import literals
from cp_vector_replay import profile as vector_profile


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, default = defaults_profile(directory)
    target = default['model'] == 'ILCE-7CM2'
    p = dict(pack=0x418b40 if target else 0x418d58,
             checksum=0xaa78fa if target else 0xaa7794)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    at = p['checksum']
    code = list(md.disasm(data[at - 0x108000:at - 0x108000 + 0x36], at))
    addresses = [v for r, v in literals(code) if r == 'r6']
    if len(addresses) != 1 or (code[-1].mnemonic, code[-1].op_str) != ('strh', 'r0, [r6, #0x26]'):
        raise ValueError('Native first-phase checksum buffer/store changed')
    p['packet'] = addresses[0]
    return data, default, p


def pair_sequence(directory, *, scales=None, full_control=False):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP,
                                   UC_ARM_REG_LR, UC_ARM_REG_PC)
    data, default, p = profile(directory)
    _, v = vector_profile(directory)
    stack, finish = 0x3001f000, 0x3001e000
    phase, lock_calls = 'load', 0

    def prepare(cpu, vector, ordinal):
        nonlocal phase, lock_calls
        # Unmapped control state is an explicit synthetic zero fixture.
        for page in range(0x1700000, 0x1b40000, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)

        def hook(uc, address, size, unused):
            nonlocal lock_calls
            if phase == 'load' and address in default['locks']:
                lock_calls += 1
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
                return
            if not (0x108000 <= address and address + size <= 0x108000 + len(data)):
                raise ValueError('First-phase packet replay left the private CP program')

        def write_hook(uc, access, address, size, value, unused):
            if ((0x1700000 <= address and address + size <= 0x1b40000)
                    or (stack - 2048 <= address and address + size <= stack)):
                return
            raise ValueError('First-phase packet wrote outside synthetic state/stack')

        def run(at, end=finish):
            cpu.reg_write(UC_ARM_REG_SP, stack)
            cpu.reg_write(UC_ARM_REG_LR, finish | 1)
            cpu.emu_start(at | 1, end, count=10000)
            if cpu.reg_read(UC_ARM_REG_PC) != end:
                raise ValueError('Native first-phase packet did not reach its boundary')

        before_vector = bytes(cpu.mem_read(v['vector_data'], 13))
        before_snapshot = bytes(cpu.mem_read(v['snapshot_data'], 192))
        ch = cpu.hook_add(UC_HOOK_CODE, hook)
        wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
        if ordinal == 0:
            phase = 'load'
            old_flag = bytes(cpu.mem_read(vector['shared_state'] + 0x6f, 1))
            cpu.reg_write(UC_ARM_REG_R0, default['ids'] + 40 * 4)
            cpu.reg_write(UC_ARM_REG_R1, default['destinations'] + 40 * 4)
            run(default['initialize'], default['initialize'] + 0x6a)
            if cpu.reg_read(UC_ARM_REG_R0) != 256:
                raise ValueError('Native first-phase configuration load was incomplete')
            cpu.mem_write(vector['shared_state'] + 0x6f, old_flag)
        phase = 'pack'
        run(p['pack'])
        phase = 'checksum'
        run(p['checksum'], p['checksum'] + 0x36)
        packet = bytes(cpu.mem_read(p['packet'], 40))
        check = 0
        for word in struct.unpack('<20H', packet):
            check ^= word
        if packet[:4] != bytes([0x39, 7, 7, 3]) or check != 0x0f0f:
            raise ValueError('Native first-phase type/header/checksum differs')
        if (bytes(cpu.mem_read(v['vector_data'], 13)) != before_vector
                or bytes(cpu.mem_read(v['snapshot_data'], 192)) != before_snapshot):
            raise ValueError('First-phase preparation changed the native vector or published frame')
        cpu.hook_del(ch)
        cpu.hook_del(wh)
        return dict(first_packet=packet.hex(), original_first_formatter_executed=True,
                    first_checksum_executed=True, native_vector_and_frame_preserved=True,
                    hardware_transfer_executed=False)

    result = wire_sequence(directory, scales=scales, prepare_wire=prepare, full_control=full_control)
    shots = []
    for shot in result['shots']:
        first = shot['preparation']['first_packet']
        shots.append(dict(first=first, second=shot['packet'],
                          vector_raw=shot['packet_vector_raw'], trinity=shot['trinity'],
                          native_vector_and_frame_preserved=shot['preparation']['native_vector_and_frame_preserved']))
    return dict(shots=shots, additional_void_lock_calls_omitted=lock_calls,
                native_first_then_second_formatters=True, host_selected_stage_invocations=True,
                full_control_producer_executed=full_control, precomputed_vector_supplied=False,
                camera_io=False, installable=False, physical_shift_verified=False)


def compare(c2, reference, *, full_control=False):
    cases = []
    for scales in (None, (3, 5, 7)):
        a = pair_sequence(c2, scales=scales, full_control=full_control)
        b = pair_sequence(reference, scales=scales, full_control=full_control)
        if a != b:
            raise ValueError('C2/A7CR native alternate packet pairs differ')
        cases.append(dict(scales=scales, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-phase-pair/1', paired_cases=8,
                cases=cases, camera_io=False, installable=False, physical_shift_verified=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--h8-input', type=Path)
    parser.add_argument('--full-control', action='store_true',
                        help='Execute native consumer and complete vector producer before packet construction')
    args = parser.parse_args(argv)
    report = compare(args.c2, args.reference, full_control=args.full_control)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    if args.h8_input is not None:
        rows = [f'variant{index}-ordinal{ordinal}\t{shot["first"]}\t{shot["second"]}'
                for index, case in enumerate(report['cases'])
                for ordinal, shot in enumerate(case['target']['shots'])]
        args.h8_input.parent.mkdir(parents=True, exist_ok=True)
        args.h8_input.write_text('\n'.join(rows) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
