"""Follow factory-selected alternate TC through native buffering, offline only.

BK4 loading and branch selection execute in the SAME emulator RAM as TC. Frame
inputs and shared control flags are synthetic; their producer/scheduler does
not execute. Native GPIO wrappers receive a deliberately invalid port (255),
so their own bounds check returns before hardware access. This is a software
propagation test, not a valid camera GPIO configuration or movement test.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_defaults_replay import _defaults_machine, profile as defaults_profile
from cp_serial_replay import literals, profile as serial_profile


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, default = defaults_profile(directory)
    _, serial = serial_profile(directory)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(address, size):
        return list(md.disasm(data[address - 0x108000:address - 0x108000 + size], address))

    def literal(address, size, register, index=0):
        return [value for reg, value in literals(code(address, size)) if reg == register][index]

    branch = [row for row in code(serial['tc'], 0x12) if row.mnemonic == 'b.w']
    if len(branch) != 1:
        raise ValueError('Native TC alternate branch changed')
    alternate = int(branch[0].op_str.lstrip('#'), 0)
    rows = code(alternate, 0x1d8)
    calls = [int(row.op_str.lstrip('#'), 0) for row in rows if row.mnemonic == 'bl']
    if len(calls) != 9 or calls[3] != calls[7] or calls[5] != calls[6]:
        raise ValueError('Native alternate TC helper layout changed')
    low, scale, gate, shared, high_gpio, low_gpio, _, _, publish = calls
    snapshot = 0xaa8e1c if default['model'] == 'ILCE-7CM2' else 0xaa8cb6
    getter = 0xaa9272 if default['model'] == 'ILCE-7CM2' else 0xaa910c
    p = dict(wrapper=serial['tc'], alternate=alternate, publish=publish,
             low=low, scale=scale, gate=gate, shared=shared,
             high_gpio=high_gpio, low_gpio=low_gpio, snapshot=snapshot, getter=getter,
             state=literal(alternate, 0x1d8, 'r5'),
             gate_state=literal(gate, 0x12, 'r0') + 8,
             shared_state=literal(shared, 10, 'r0'),
             port=literal(alternate + 0xbc, 0x32, 'r0', 1),
             pin=literal(alternate + 0xbc, 0x32, 'r0'),
             counter=literal(alternate + 0x140, 0x28, 'r0'),
             pending=literal(alternate, 0x30, 'r0'),
             buffer=literal(publish, 0x22, 'r4'),
             bank=literal(publish, 0x22, 'r6'),
             observed=literal(getter, 10, 'r0'))
    if (literal(snapshot, 0x2a, 'r0') != p['bank']
            or literal(snapshot, 0x2a, 'r1') != p['buffer']
            or literal(snapshot, 0x2a, 'r1', -1) != p['observed']):
        raise ValueError('Native alternate TC snapshot no longer matches its publisher/getter')
    p['regions'] = [(p['wrapper'], p['wrapper'] + 0x12),
                    (alternate, alternate + 0x1d8), (publish, publish + 0x96),
                    (snapshot, snapshot + 0x2a), (getter, getter + 10),
                    (low, low + 12), (scale, scale + 0x38),
                    (gate, gate + 0x12), (shared, shared + 10),
                    (high_gpio, high_gpio + 12), (low_gpio, low_gpio + 12)]
    addresses = [value for begin, end in p['regions'] for _, value in literals(code(begin, end - begin))
                 if 0x1100000 <= value < 0x2000000]
    p['pages'] = sorted({a & ~4095 for a in addresses})
    return data, p


def _sequence(directory, *, shared_flag, gate, first, variant=0, observe=None):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP,
                                   UC_ARM_REG_LR, UC_ARM_REG_PC)
    if shared_flag not in (0, 1) or gate not in (0, 1) or first not in (0, 1):
        raise ValueError('Needs binary synthetic shared flag, gate and first-frame input')
    cpu, default, loaded = _defaults_machine(directory, variant)
    data, p = profile(directory)
    for page in p['pages']:
        if not any(begin <= page <= end for begin, end, _ in cpu.mem_regions()):
            cpu.mem_map(page, 4096)
    entry, finish, stack = 0x30004000, 0x3001e000, 0x3001f000
    # Deliberate negative GPIO case; the actual native bounds check must execute.
    cpu.mem_write(p['port'], struct.pack('<I', 255))
    cpu.mem_write(p['pin'], bytes(4))
    cpu.mem_write(p['gate_state'], struct.pack('<I', gate))
    cpu.mem_write(p['shared_state'] + 0x6f, bytes([shared_flag]))
    cpu.mem_write(p['buffer'], b'\x6b' * 64)
    cpu.mem_write(p['observed'] - 4, b'\x7c' * 40)
    cpu.mem_write(p['state'], bytes(32))
    cpu.mem_write(p['counter'], struct.pack('<I', 10))
    cpu.mem_write(p['bank'], bytes(1))
    phase, gpio_calls, reached = 'tc', [], set()
    allowed_tc = [(p['state'], 32), (p['buffer'], 64), (p['bank'], 1),
                  (p['counter'], 4)]
    # Inspect exactly the native state stores materialized by the alternate body.
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    rows = list(md.disasm(data[p['alternate'] - 0x108000:p['alternate'] - 0x108000 + 0x1d8], p['alternate']))
    for reg, address in literals(rows):
        if 0x1100000 <= address < 0x2000000 and address not in (p['port'], p['pin'], p['state'], p['counter']):
            # These are standalone flags/reset counters, not broad mapped pages.
            allowed_tc.append((address, 4))

    def hook(uc, address, size, unused):
        if not any(begin <= address and address + size <= end for begin, end in p['regions']):
            raise ValueError('Alternate TC reached omitted native code: ' + hex(address))
        reached.add(address)
        if address in (p['high_gpio'], p['low_gpio']):
            args = (uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1))
            if args != (255, 0):
                raise ValueError('Replay GPIO would not take its native invalid-port return')
            gpio_calls.append('set' if address == p['high_gpio'] else 'clear')

    def write_hook(uc, access, address, size, value, unused):
        if stack - 512 <= address and address + size <= stack:
            return
        allowed = allowed_tc if phase == 'tc' else [(p['observed'], 32)]
        if not any(begin <= address and address + size <= begin + length for begin, length in allowed):
            raise ValueError('Alternate TC changed unrelated ' + phase + ' state: ' + hex(address))

    def run(start, stop=finish):
        cpu.reg_write(UC_ARM_REG_SP, stack)
        cpu.reg_write(UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(start | 1, stop, count=2000)
        if cpu.reg_read(UC_ARM_REG_PC) != stop or cpu.reg_read(UC_ARM_REG_SP) != stack:
            raise ValueError('Native alternate TC did not finish with balanced stack')

    code_hook = cpu.hook_add(UC_HOOK_CODE, hook)
    memory_hook = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    shots = []
    immutable = [(default['selector_flag'], bytes(cpu.mem_read(default['selector_flag'], 1))),
                 (default['interface_data'], bytes(cpu.mem_read(default['interface_data'], 256)))]
    for ordinal in range(4):
        packet = bytearray(32)
        struct.pack_into('<I', packet, 0, first if ordinal == 0 else 0)
        struct.pack_into('<H', packet, 4, 0x1234)
        struct.pack_into('<I', packet, 12, 1)
        struct.pack_into('<I', packet, 24, ordinal)
        struct.pack_into('<I', packet, 28, 0x76543210)
        cpu.mem_write(entry, b'\x8d' * 4 + packet + b'\x8d' * 4)
        before = bytes(cpu.mem_read(p['buffer'], 64))
        old_bank = cpu.mem_read(p['bank'], 1)[0]
        phase = 'tc'
        cpu.reg_write(UC_ARM_REG_R0, entry + 4)
        run(p['wrapper'])
        bank = cpu.mem_read(p['bank'], 1)[0]
        emitted = bytes(cpu.mem_read(p['state'], 32))
        if (bank != 1 - old_bank
                or bytes(cpu.mem_read(p['buffer'] + bank * 32, 32)) != emitted
                or bytes(cpu.mem_read(p['buffer'] + old_bank * 32, 32)) != before[old_bank * 32:old_bank * 32 + 32]):
            raise ValueError('Native alternate TC did not toggle/preserve its double buffer')
        phase = 'snapshot'
        run(p['snapshot'], p['snapshot'] + 0x2a)
        run(p['getter'])
        observed = bytes(cpu.mem_read(cpu.reg_read(UC_ARM_REG_R0), 32))
        if (cpu.reg_read(UC_ARM_REG_R0) != p['observed'] or observed != emitted
                or struct.unpack_from('<I', observed, 12)[0] != ordinal
                or struct.unpack_from('<I', observed, 20)[0] != 11 + ordinal
                or struct.unpack_from('<I', observed, 28)[0] != 0x76543210
                or bytes(cpu.mem_read(entry, 40)) != b'\x8d' * 4 + packet + b'\x8d' * 4
                or bytes(cpu.mem_read(p['observed'] - 4, 4)) != b'\x7c' * 4
                or bytes(cpu.mem_read(p['observed'] + 32, 4)) != b'\x7c' * 4):
            raise ValueError('Native alternate TC lost its input, ordinal, generation or snapshot bounds')
        shots.append(dict(ordinal=ordinal, bank=bank, bytes=observed.hex(),
                          request_category=observed[24], control_mode=observed[25]))
        if observe is not None:
            cpu.hook_del(code_hook)
            cpu.hook_del(memory_hook)
            shots[-1]['observation'] = observe(cpu, p, default, ordinal)
            code_hook = cpu.hook_add(UC_HOOK_CODE, hook)
            memory_hook = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    if (p['alternate'] not in reached or p['publish'] not in reached
            or any(bytes(cpu.mem_read(at, len(raw))) != raw for at, raw in immutable)
            or bytes(cpu.mem_read(0x108000, len(data))) != data):
        raise ValueError('Native alternate entry, official selector or immutable code changed')
    cpu.hook_del(code_hook)
    cpu.hook_del(memory_hook)
    return dict(official_interface_type=loaded['decoded_interface_type'],
                official_selector_preserved=True, shared_state_and_input_synthetic=True,
                native_alternate_entry_executed=True, shots=shots,
                gpio_native_invalid_port_returns=gpio_calls, gpio_port=255,
                gpio_hardware_access_executed=False, scheduler_executed=False,
                serial_transport_executed=False, physical_shift_verified=False, camera_io=False)


def sequence(directory, *, shared_flag, gate, first, variant=0):
    return _sequence(directory, shared_flag=shared_flag, gate=gate, first=first, variant=variant)


def compare(c2, reference):
    cases = []
    for shared_flag in (0, 1):
        for gate in (0, 1):
            for first in (0, 1):
                args = dict(shared_flag=shared_flag, gate=gate, first=first)
                a, b = sequence(c2, **args), sequence(reference, **args)
                if a != b:
                    raise ValueError('C2/A7CR factory-selected alternate TC behavior differs')
                cases.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-alternate/1', paired_sequences=len(cases),
                paired_cases=len(cases) * 4, cases=cases, camera_io=False,
                installable=False, physical_shift_verified=False)


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
    print(json.dumps({key: report[key] for key in ('paired_sequences', 'paired_cases', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
