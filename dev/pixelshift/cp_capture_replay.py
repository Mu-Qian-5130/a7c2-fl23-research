"""Original CP capture-mode selection, with synthetic configuration/state only.

No capture, sensor, motor, driver or settling callback is executed. Configuration
byte 0xd88 is traced as an input, not assumed to originate from the AP packet.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_metadata_replay import program


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, model, _, _ = program(directory)
    delta = 0 if model == 'ILCE-7CM2' else 0x218
    begin, end = 0x475116 + delta, 0x47514a + delta
    consistency, finish = 0x47702c + delta, 0x477048 + delta
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def dis(at, length):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + length], at))

    first = dis(begin, 4)
    if len(first) != 1 or first[0].mnemonic != 'bl':
        raise ValueError('Native state getter call changed')
    getter = int(first[0].op_str.lstrip('#'), 16)
    code = dis(getter, 12)
    if [i.mnemonic for i in code] != ['movw', 'movt', 'ldrb', 'bx']:
        raise ValueError('State getter is not the audited byte read')
    if [i.op_str for i in code[2:]] != ['r0, [r0]', 'lr']:
        raise ValueError('State getter has additional behavior')
    low, high = [int(i.op_str.split('#', 1)[1], 16) for i in code[:2]]
    state_address = low | high << 16
    trace = [i for i in dis(consistency, finish - consistency) if i.mnemonic == 'bl']
    if len(trace) != 1:
        raise ValueError('Expected one diagnostic-only call in the consistency check')
    return data, dict(model=model, begin=begin, end=end, getter=getter,
                      state_address=state_address, consistency=consistency,
                      finish=finish, trace=int(trace[0].op_str.lstrip('#'), 16))


def machine(directory, regions):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB
    data, p = profile(directory)
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    pages = set()
    for begin, end in regions:
        for page in range(begin & ~4095, (end + 4095) & ~4095, 4096):
            if page not in pages:
                off = page - 0x108000
                if not 0 <= off < len(data) - 4095:
                    raise ValueError('Instruction page is outside the private CP program')
                cpu.mem_map(page, 4096)
                cpu.mem_write(page, data[off:off + 4096])
                pages.add(page)
    cpu.mem_map(0x30000000, 0x4000)
    cpu.mem_write(0x30000000, b'\xa5' * 0x1000)
    return cpu, p


def select(directory, *, mode, flag_d88, flag_d8e, native_state):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R6, UC_ARM_REG_PC
    _, p = profile(directory)
    regions = [(p['begin'], p['end']), (p['getter'], p['getter'] + 12)]
    cpu, _ = machine(directory, regions)
    state = p['state_address']
    cpu.mem_map(state & ~4095, 4096)
    cpu.mem_write(state, bytes([native_state]))
    frame = 0x30000000
    cpu.mem_write(frame + 0x158, struct.pack('<II', mode, 0x12345678))
    cpu.mem_write(frame + 0xd88, bytes([flag_d88]))
    cpu.mem_write(frame + 0xd8e, bytes([flag_d8e]))
    before = bytes(cpu.mem_read(frame, 0x1000))
    cpu.reg_write(UC_ARM_REG_R6, frame)
    visited = []

    def hook(uc, at, size, _):
        if not any(a <= at < b for a, b in regions):
            raise ValueError('Mode selection attempted an unhandled call')
        visited.append(at)

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(p['begin'] | 1, p['end'], count=100)
    if cpu.reg_read(UC_ARM_REG_PC) != p['end']:
        raise ValueError('Mode selection did not reach the next boundary')
    actual = bytes(cpu.mem_read(frame, 0x1000))
    if before[:0x158] != actual[:0x158] or before[0x160:] != actual[0x160:]:
        raise ValueError('Mode selection changed unrelated configuration')
    if bytes(cpu.mem_read(state, 1)) != bytes([native_state]):
        raise ValueError('Mode selection changed its synthetic state input')
    chosen, adjacent = struct.unpack_from('<II', actual, 0x158)
    return dict(mode=chosen, adjacent=adjacent, instructions=len(visited),
                hardware_calls=0, configuration_inputs_synthetic=True)


def consistency(directory, *, mode, trinity):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R5, UC_ARM_REG_R8, UC_ARM_REG_PC, UC_ARM_REG_LR
    _, p = profile(directory)
    regions = [(p['consistency'], p['finish']), (p['trace'], p['trace'] + 4)]
    cpu, _ = machine(directory, regions)
    frame = 0x30000000
    cpu.mem_write(frame + 0x1a0, struct.pack('<I', trinity))
    before = bytes(cpu.mem_read(frame, 0x1000))
    cpu.reg_write(UC_ARM_REG_R5, frame)
    cpu.reg_write(UC_ARM_REG_R8, mode)
    traces = []

    def hook(uc, at, size, _):
        if at == p['trace']:
            traces.append(at)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
        elif not p['consistency'] <= at < p['finish']:
            raise ValueError('Consistency check attempted an unhandled call')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(p['consistency'] | 1, p['finish'], count=100)
    if cpu.reg_read(UC_ARM_REG_PC) != p['finish']:
        raise ValueError('Consistency check did not finish')
    actual = bytes(cpu.mem_read(frame, 0x1000))
    if actual[:0x1a0] != before[:0x1a0] or actual[0x1a4:] != before[0x1a4:]:
        raise ValueError('Consistency check changed unrelated configuration')
    return dict(trinity=struct.unpack_from('<I', actual, 0x1a0)[0],
                diagnostic_calls_omitted=len(traces), hardware_calls=0)


def compare(c2, reference):
    cases = []
    for mode in (0, 1, 2, 0x17, 0x21, 255):
        for flag_d88 in (0, 1):
            for flag_d8e in (0, 1):
                for native_state in (0, 1):
                    values = dict(mode=mode, flag_d88=flag_d88, flag_d8e=flag_d8e, native_state=native_state)
                    a, b = select(c2, **values), select(reference, **values)
                    expected, adjacent = mode, 0x12345678
                    if not native_state:
                        if mode == 2 and flag_d88:
                            expected, adjacent = 0x17, 1
                        elif mode == 0x21 and (flag_d88 or flag_d8e):
                            expected = 1
                    if a != b or (a['mode'], a['adjacent']) != (expected, adjacent):
                        raise ValueError('Native C2/A7CR mode selection differs')
                    cases.append(dict(kind='selection', input=values, target=a, reference=b))
    for mode in (0, 1, 2, 0x17, 0x21):
        for trinity in (0, 1, 2):
            values = dict(mode=mode, trinity=trinity)
            a, b = consistency(c2, **values), consistency(reference, **values)
            expected = 0 if mode != 0x17 and trinity == 1 else trinity
            if a != b or a['trinity'] != expected:
                raise ValueError('Native TRINITY consistency differs')
            cases.append(dict(kind='consistency', input=values, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-capture-replay/1', paired_cases=len(cases), cases=cases,
                camera_io=False, physical_shift_verified=False, settling_verified=False,
                limit='Synthetic CP configuration and native byte getter only; AP-to-flag provenance and actuator path remain unverified')


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
