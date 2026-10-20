"""Original CP steady-capture timer request, stopping before timer creation.

This is evidence of a time-based scheduling path, not an actuator-settled signal.
Neither OS timer/event APIs nor any camera hardware function is executed.
"""
import argparse
import json
from pathlib import Path
import struct

from cp_metadata_replay import program


def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, model, _, _ = program(directory)
    delta = 0 if model == 'ILCE-7CM2' else 0x21c
    p = dict(model=model, entry=0x49dcec + delta, send=0x49dd1a + delta,
             trace=0x49dd00 + delta, callback=0x4a602c + delta,
             callback_name=0x4a6078 + delta, timer_api=0x4b23c0 + delta)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    at = p['send'] - 0x108000
    ins = list(md.disasm(data[at:at + 4], p['send']))
    if len(ins) != 1 or (ins[0].mnemonic, ins[0].op_str) != ('bl', '#' + hex(p['timer_api'])):
        raise ValueError('Original timer request call changed')
    at = p['callback_name'] - 0x108000
    if not data[at:].startswith(b'eventCallback_End_Wait_StartSteadyCap\0'):
        raise ValueError('Steady-capture timer callback label differs')
    return data, p


def request(directory, exposure_offset_us):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1,
        UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_PC)
    if not 0 <= exposure_offset_us <= 0xffffffff:
        raise ValueError('Expected an unsigned native exposure-offset value')
    data, p = profile(directory)
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    page = p['entry'] & ~4095
    cpu.mem_map(page, 4096)
    off = page - 0x108000
    cpu.mem_write(page, data[off:off + 4096])
    cpu.mem_map(0x30000000, 0x10000)
    cpu.mem_write(0x30000000, b'\xa5' * 0x2000)
    cpu.mem_write(0x3000137c, struct.pack('<I', exposure_offset_us))
    before = bytes(cpu.mem_read(0x30000000, 0x2000))
    cpu.reg_write(UC_ARM_REG_R0, 0x30000000)
    cpu.reg_write(UC_ARM_REG_SP, 0x3000f000)
    diagnostic = []

    def hook(uc, at, size, _):
        if at == p['send']:
            uc.emu_stop()
        elif at == p['trace']:
            # Omit the diagnostic BL instruction before its target is entered.
            diagnostic.append(at)
            uc.reg_write(UC_ARM_REG_PC, (at + 4) | 1)
        elif not p['entry'] <= at < p['send']:
            raise ValueError('Timer request reached an unhandled function')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(p['entry'] | 1, p['send'] + 4, count=100)
    if cpu.reg_read(UC_ARM_REG_PC) != p['send']:
        raise ValueError('Original timer request did not reach its boundary')
    if bytes(cpu.mem_read(0x30000000, 0x2000)) != before:
        raise ValueError('Original timer request changed its synthetic input')
    callback = cpu.reg_read(UC_ARM_REG_R2)
    if callback != p['callback'] | 1:
        raise ValueError('Timer request uses a different callback')
    return dict(timer_id=cpu.reg_read(UC_ARM_REG_R0), delay_us=cpu.reg_read(UC_ARM_REG_R1),
                callback='eventCallback_End_Wait_StartSteadyCap',
                diagnostic_calls_omitted=len(diagnostic), timer_api_executed=False,
                actuator_acknowledgement_verified=False)


def compare(c2, reference):
    cases = []
    for value in (0, 1, 8999, 9000, 9001, 10000, 100000, 0xffffffff):
        a, b = request(c2, value), request(reference, value)
        expected = 1 if value < 9000 else value - 9000
        if a != b or a['timer_id'] != 0 or a['delay_us'] != expected:
            raise ValueError('C2/A7CR steady-capture timer request differs')
        cases.append(dict(exposure_offset_us=value, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-timing-replay/1', paired_cases=len(cases), cases=cases,
                camera_io=False, settling_verified=False, physical_shift_verified=False,
                limit='Native timer-request formation only; callback/event execution and actual sensor settling are not tested')


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
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}))


if __name__ == '__main__':
    main()
