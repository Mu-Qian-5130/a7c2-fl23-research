"""Replay the original CC backup-shadow read path on private firmware.

Native table initialization and complete ShadowReadBackup -> wrapper -> BK4
lookup/size/pointer -> ARM memcpy execute. The callback-registration/startup
caller is not executed. Only the existing reader's void mutex boundaries are
omitted. Optional unit0b bytes replace that unit in EMULATED BK4 input only;
they are supplied data, not a calibration patch or proven hardware parameters.
No camera, persistent write, actuator, capture or physical success is modeled.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_defaults_replay import _defaults_machine, factory_bank
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    from cp_defaults_replay import profile as defaults_profile
    data, d = defaults_profile(directory)
    target = d['model'] == 'ILCE-7CM2'
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at-0x108000:at-0x108000+size], at))

    def constant(at, size, register):
        values = [value for reg, value in literals(code(at, size)) if reg == register]
        if len(values) != 1:
            raise ValueError('Native shadow table binding is not unique')
        return values[0]

    begin = 0x23cc32 if target else 0x23cc52
    read = 0x23cd50 if target else 0x23cd70
    table = constant(begin, 0x22, 'r0')
    ids = constant(begin, 0x22, 'fp')
    destinations = constant(begin, 0x22, 'r4')
    sizes = constant(begin, 0x22, 'r2')
    records = [struct.unpack_from('<III', data, table-0x108000+n*12) for n in range(20)]
    if ([r[0] for r in records] != list(range(0x02a40000, 0x02a40013)) + [0]
            or records[11][2] != 256 or records[14][2] != 1792):
        raise ValueError('Native nineteen-unit shadow table differs')
    p = dict(begin=begin, end=begin+0x40, read=read, table=table, ids=ids,
             destinations=destinations, sizes=sizes, records=records,
             single_wrapper=0x510728 if target else 0x510948,
             single_api=0xbe91ea if target else 0xbe9044,
             bulk_wrapper=0x510800 if target else 0x510a20,
             bulk_api=0x55c024 if target else 0x55c23c)
    p['regions'] = [(begin, p['end']), (read, read+0x84),
                    (p['single_wrapper'], p['single_wrapper']+0x32),
                    (p['single_api'], p['single_api']+0x40),
                    (p['bulk_wrapper'], p['bulk_wrapper']+0x30),
                    (p['bulk_api'], p['bulk_api']+0xb8)] + d['regions']
    return data, d, p


def replay(directory, *, bank=0, key=0, unit0b=None):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, d, p = profile(directory)
    cpu, _, bootstrap = _defaults_machine(directory, bank)
    _, source = factory_bank(directory, bank)
    source = bytearray(source)
    base, stack, finish = 0x4000000, 0x3001f000, 0x3001e000

    def map_range(at, length):
        for page in range(at & ~4095, (at+length+4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)

    destinations = [(at, size) for _, at, size in p['records'] if size]
    for at, size in [(p['ids'], 240)] + destinations:
        map_range(at-4, size+8)
    for at, size in destinations:
        cpu.mem_write(at, b'\xa5' * size)
    cpu.mem_write(p['ids'], b'\xa5' * 240)
    copies, mutexes, calls = [], [], []
    phase = 'tables'

    def run(at, end=finish):
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(at | 1, end, count=500000)
        if cpu.reg_read(arm.UC_ARM_REG_PC) != end:
            raise ValueError('Native shadow path did not reach its explicit boundary')

    def hook(uc, at, size, unused):
        if at in d['locks']:
            mutexes.append(at)
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR) | 1)
            return
        if not any(lo <= at and at+size <= hi for lo, hi in p['regions']):
            raise ValueError('Native shadow path entered an unresolved dependency: ' + hex(at))
        if phase == 'read' and at == d['copy']:
            dst, src, length = [uc.reg_read(reg) for reg in
                               (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2)]
            if not base <= src <= base+len(source)-length:
                raise ValueError('Native shadow reader copied from outside its original BK4 input')
            copies.append((dst, src-base, length))
        if phase == 'read' and at in (p['single_api'], p['bulk_api'], d['read']):
            calls.append(at)

    def write_hook(uc, access, at, size, value, unused):
        allowed = [(p['ids'], 240)] if phase == 'tables' else destinations
        if stack-8192 <= at and at+size <= stack:
            return
        if not any(lo <= at and at+size <= lo+length for lo, length in allowed):
            raise ValueError('Native shadow reader wrote outside its shadow/stack: ' + hex(at))

    ch = cpu.hook_add(UC_HOOK_CODE, hook)
    wh = cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    run(p['begin'], p['end'])
    for n, record in enumerate(p['records']):
        actual = tuple(struct.unpack('<I', cpu.mem_read(at+n*4, 4))[0]
                       for at in (p['ids'], p['destinations'], p['sizes']))
        if actual != record:
            raise ValueError('Original table initializer lost a unit/destination/size')

    if unit0b is not None:
        if len(unit0b) != 256:
            raise ValueError('A supplied unit0b must be exactly256 bytes')
        # Ask the original reader for its actual storage pointer; no hardcoded
        # backup offset, structure guess or physical write is used.
        phase = 'locate'
        cpu.reg_write(arm.UC_ARM_REG_R0, 0x02a4000b)
        run(d['lookup'])
        run(d['pointer'])
        at = cpu.reg_read(arm.UC_ARM_REG_R0)
        if not base <= at <= base+len(source)-256:
            raise ValueError('Original BK4 unit pointer was not in the emulated input')
        source[at-base:at-base+256] = unit0b
        cpu.mem_write(at, unit0b)

    phase = 'read'
    cpu.reg_write(arm.UC_ARM_REG_R0, key)
    run(p['read'])
    result = cpu.reg_read(arm.UC_ARM_REG_R0)
    expected = [r for r in p['records'][:-1] if key == 0 or r[0] == key]
    if result != (0 if expected else 0xffffffff) or len(copies) != len(expected):
        raise ValueError('Native shadow path returned an unexpected result/copy count')
    verified = []
    for (identity, dst, length), (copied_dst, source_offset, copied_length) in zip(expected, copies):
        if ((dst, length) != (copied_dst, copied_length)
                or bytes(cpu.mem_read(dst, length)) != source[source_offset:source_offset+length]):
            raise ValueError('Complete native shadow copy differs from its own BK4 input')
        verified.append(dict(key=hex(identity), bytes=length))
    for identity, dst, length in p['records'][:-1]:
        if key != 0 and key != identity and bytes(cpu.mem_read(dst, length)) != b'\xa5' * length:
            raise ValueError('Single-unit read modified another unit shadow')
    if bytes(cpu.mem_read(base, len(source))) != bytes(source):
        raise ValueError('Native read changed the emulated BK4 source')
    cpu.hook_del(ch)
    cpu.hook_del(wh)
    return dict(bank=bank, key=hex(key), native_status=result, table_records=20,
                units=verified, copied_bytes=sum(r['bytes'] for r in verified),
                native_api_calls=len(calls), void_mutex_calls_omitted=len(mutexes),
                unit0b_input='supplied_emulated_payload' if unit0b is not None else 'official_default',
                bootstrap_mutex_calls_omitted=bootstrap['mutex_calls_omitted'],
                original_shadow_read_wrapper_executed=True, native_arm_memcpy_executed=bool(copies),
                callback_registration_executed=False, full_startup_executed=False,
                host_copied_bytes_into_shadow=False, source_preserved=True,
                parameter_physical_units_identified=False, actuator_or_exposure_executed=False,
                persistent_write_executed=False, camera_io=False, installable=False)


def compare(c2, reference):
    rows = []
    for bank in (0, 1):
        for key in (0, 0x02a4000b, 0x02a4000e, 0x02a40013):
            for supplied in (False, True):
                fixture = bytes((i*37+11) & 255 for i in range(256)) if supplied else None
                args = dict(bank=bank, key=key, unit0b=fixture)
                a, b = replay(c2, **args), replay(reference, **args)
                if a != b:
                    raise ValueError('C2/CR native shadow read contracts differ')
                rows.append(dict(input=dict(bank=bank, key=hex(key), supplied_fixture=supplied), target=a, reference=b))
    return dict(schema='a7c2-native-shadow-read/1', paired_cases=len(rows), cases=rows,
                source_bytes_may_differ_by_model=True, camera_io=False,
                physical_shift_verified=False, installable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--unit0b', type=Path, help='Optional private256-byte input, injected only in emulator BK4')
    args = parser.parse_args()
    if args.unit0b:
        payload = args.unit0b.read_bytes()
        report = dict(target=replay(args.c2, unit0b=payload),
                      reference=replay(args.reference, unit0b=payload),
                      camera_io=False, physical_shift_verified=False, installable=False,
                      supplied_payload_identity_verified=False,
                      supplied_payload_is_emulated_input_only=True)
    else:
        report = compare(args.c2, args.reference)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k not in ('cases', 'target', 'reference')}))


if __name__ == '__main__':
    main()
