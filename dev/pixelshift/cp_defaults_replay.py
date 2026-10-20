"""Read official BK4 defaults through original CP code and trace TC selection.

No live camera state is read. Default parameter loading is not evidence that
later lens/device configuration leaves these values unchanged. No calibration
is exported or transferred to another body. Only two SIO settings, one native
parameter copy, and the resulting TC selector slice execute.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_metadata_replay import program
from cp_serial_replay import literals, profile as serial_profile
from cp_sequence_replay import machine


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, model, _, _ = program(directory)
    target = model == 'ILCE-7CM2'
    _, serial = serial_profile(directory)
    p = dict(model=model, header=0x55df9c if target else 0x55e1b4,
             config=0xa6963e if target else 0xa694e4,
             read32=0xbe92ec if target else 0xbe9146,
             lookup=0xbe98c6 if target else 0xbe9720,
             size=0xbe995c if target else 0xbe97b6,
             pointer=0xbe9990 if target else 0xbe97ea,
             read=0xbe9130 if target else 0xbe8f8a,
             initialize=0x55bf60 if target else 0x55c178,
             binding=0xabb3c2 if target else 0xabb220,
             decode=0xac01da if target else 0xac0038,
             selector=0xa6c622 if target else 0xa6c4c8,
             copy=0x61e60c if target else 0x61e824,
             info_getter=serial['info_getter'], info=serial['info'],
             selector_flag=serial['tc_selector'])
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(address, size):
        return list(md.disasm(data[address - 0x108000:address - 0x108000 + size], address))

    def literal(address, size, register, index=0):
        return [value for reg, value in literals(code(address, size)) if reg == register][index]

    p['registry'] = literal(p['header'], 0x74, 'r1')
    p['port'] = literal(p['config'], 0x3e, 'r1')
    p['rate'] = literal(p['config'], 0x3e, 'r1', -1)
    config_stores = [row.address + row.size for row in code(p['config'], 0x50)
                     if row.mnemonic.startswith('str') and row.op_str == 'r0, [r1]']
    if len(config_stores) < 2:
        raise ValueError('Native SIO configuration assignments changed')
    p['config_stop'] = config_stores[1]
    p['ids'] = literal(p['binding'], 0x30, 'sb')
    p['destinations'] = literal(p['binding'], 0x30, 'fp')
    p['interface_data'] = struct.unpack_from('<I', data, p['destinations'] - 0x108000)[0]
    p['lock_root'] = literal(p['read32'], 0x4e, 'r6')
    p['locks'] = [int(row.op_str.lstrip('#'), 0) for row in code(p['read32'], 0x4e)
                  if row.mnemonic == 'blx']
    if (len(p['locks']) != 2
            or struct.unpack_from('<I', data, p['ids'] - 0x108000)[0] != 0x000f0001):
        raise ValueError('Native default parameter binding changed')
    p['regions'] = [(p['header'], p['header'] + 0x74), (p['config'], p['config_stop']),
                    (p['read32'], p['read32'] + 0x4e), (p['lookup'], p['lookup'] + 0x96),
                    (p['size'], p['size'] + 0x34), (p['pointer'], p['pointer'] + 0x3e),
                    (p['read'], p['read'] + 0x62), (p['initialize'], p['initialize'] + 0xb0),
                    (p['decode'], p['decode'] + 0x2e), (p['selector'], p['selector'] + 0x24),
                    (p['info_getter'], p['info_getter'] + 10), (p['copy'], p['copy'] + 0x300)]
    addresses = [value for begin, end in p['regions'] for _, value in literals(code(begin, end - begin))
                 if 0x1100000 <= value < 0x2000000]
    addresses += [p['interface_data'], p['info'], p['selector_flag'], p['lock_root'] + 0x400]
    p['pages'] = sorted({address & ~4095 for address in addresses})
    return data, p


def factory_bank(directory, variant):
    matches = list(Path(directory).glob('CX*' + format(variant, '02d') + '_ALLLANG.bin'))
    if len(matches) != 1:
        raise ValueError('Needs one official CX*00/01_ALLLANG.bin beside the extracted programs')
    raw = matches[0].read_bytes()
    bank = raw[0xed000:]
    if bank[12:16] != b'BK4\0':
        raise ValueError('Expected the CP default BK4 bank at offset 0xed000')
    offset, size = struct.unpack_from('<II', bank, 0x18)
    if not 0x100 <= offset <= offset + size <= len(bank):
        raise ValueError('Factory BK4 bank exceeds its source file')
    return matches[0].name, bank[:offset + size]


def defaults(directory, variant=0):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP,
                                   UC_ARM_REG_LR, UC_ARM_REG_PC)
    data, p = profile(directory)
    source, bank = factory_bank(directory, variant)
    cpu = machine(data, p['pages'])
    base, finish = 0x4000000, 0x3001e000
    cpu.mem_map(base, (len(bank) + 4095) & ~4095)
    cpu.mem_write(base, bank)
    phase, lock_calls, copies = 'header', [], []
    writes = dict(header=[(p['registry'], 12)], config=[(p['port'], 4), (p['rate'], 4)],
                  initialize=[(p['interface_data'], 256)], decode=[(p['info'], 12)],
                  selector=[(p['selector_flag'], 1)])

    def hook(uc, address, size, unused):
        if address == p['copy']:
            copies.append(tuple(uc.reg_read(register) for register in
                                (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)))
        if address in p['locks']:
            # Void mutex boundaries only; no device return or success is supplied.
            lock_calls.append(address)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
        elif not any(begin <= address < end for begin, end in p['regions']):
            raise ValueError('Default loading reached omitted native code: ' + hex(address))

    def write_hook(uc, access, address, size, value, unused):
        if 0x30018000 <= address and address + size <= 0x3001f000:
            return
        if any(begin <= address and address + size <= begin + length for begin, length in writes[phase]):
            return
        raise ValueError('Default loading changed unrelated state in ' + phase + ': ' + hex(address))

    def run(entry, end=finish):
        cpu.reg_write(UC_ARM_REG_SP, 0x3001f000)
        cpu.reg_write(UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(entry | 1, end, count=10000)
        if cpu.reg_read(UC_ARM_REG_PC) != end:
            raise ValueError('Native default-loading slice did not finish')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.reg_write(UC_ARM_REG_R0, base)
    run(p['header'])
    if cpu.reg_read(UC_ARM_REG_R0) != 0:
        raise ValueError('Native CP code refused the factory BK4 header')
    phase = 'config'
    run(p['config'], p['config_stop'])
    phase = 'initialize'
    cpu.mem_write(p['interface_data'], b'\xa5' * 256)
    cpu.reg_write(UC_ARM_REG_R0, p['ids'])
    cpu.reg_write(UC_ARM_REG_R1, p['destinations'])
    run(p['initialize'], p['initialize'] + 0x6a)
    if cpu.reg_read(UC_ARM_REG_R0) != 256:
        raise ValueError('Native first parameter load did not copy its complete 256 bytes')
    if (len(copies) != 1 or copies[0][0] != p['interface_data'] or copies[0][2] != 256
            or not base <= copies[0][1] <= base + len(bank) - 256
            or bytes(cpu.mem_read(p['interface_data'], 256)) != bank[copies[0][1] - base:copies[0][1] - base + 256]):
        raise ValueError('Native parameter copy does not match its actual BK4 source')
    raw_word = struct.unpack('<H', cpu.mem_read(p['interface_data'], 2))[0]
    phase = 'decode'
    run(p['decode'], p['decode'] + 0x2e)
    interface = struct.unpack('<I', cpu.mem_read(p['info'] + 8, 4))[0]
    phase = 'selector'
    cpu.mem_write(p['selector_flag'], b'\0')
    run(p['selector'], p['selector'] + 0x24)
    if bytes(cpu.mem_read(base, len(bank))) != bank:
        raise ValueError('Native default loading changed its source bank')
    return dict(model=p['model'], source=source, backup_offset='0xed000',
                channel_parameter='0x00f900af', rate_parameter='0x00f9006b',
                sio_channel=struct.unpack('<I', cpu.mem_read(p['port'], 4))[0],
                sio_rate_code=struct.unpack('<I', cpu.mem_read(p['rate'], 4))[0],
                interface_parameter='0x000f0001', native_copied_bytes=256,
                raw_interface_word=raw_word, decoded_interface_type=interface,
                alternate_tc_if_defaults_retained=bool(cpu.mem_read(p['selector_flag'], 1)[0]),
                native_memcpy_executed=bool(copies), mutex_calls_omitted=len(lock_calls),
                runtime_overrides_executed=False, live_state_verified=False,
                camera_io=False, physical_shift_verified=False)


def compare(c2, reference):
    cases = []
    for variant in (0, 1):
        a, b = defaults(c2, variant), defaults(reference, variant)
        omit = {'model', 'source'}
        if {k: v for k, v in a.items() if k not in omit} != {k: v for k, v in b.items() if k not in omit}:
            raise ValueError('C2/A7CR native factory TC configuration differs')
        cases.append(dict(variant=variant, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-defaults/1', camera_io=False, installable=False,
                paired_cases=len(cases), cases=cases, physical_shift_verified=False)


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
