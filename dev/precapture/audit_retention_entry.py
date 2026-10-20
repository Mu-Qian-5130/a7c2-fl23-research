"""Trace native pre-capture classification to its real retention task boundary.

Pinned private originals only. Executes original stage5 decisions, pure
descriptor initialization, phase dispatch and callback construction. Never
executes logging, OS enqueue, image processing or a sensor operation.
Raw fields are not assigned user-facing mode names without evidence.
"""
import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from support.reference import SPECS

MEM, STACK, STOP = 0x30000000, 0x40000000, 0x60000000
FRAME, HOLDER, PIPE = MEM, MEM + 0x10000, MEM + 0x10100
S = {
    'a7c2-2.01': dict(selector=0x3798D4, error=0xA11B90, logs=[0xA125CA, 0xA12614],
        marker=0x66E8, error_field=0x617C, kind=0x5C10, cls=0xBB4,
        format=0x6078, alternate=0xBA8, diagnostic=0x9ED,
        initializer=0xA0C46A, initializer_end=0xA0D7B0,
        table=0x1A4FE38, table_ram=(0x1A4F000, 0x4000), retained=9,
        dispatch=0x379C18, phase_count=8, last_phase=0xA0DD98,
        enqueue=0xA09B34, enqueue_boundary=0x407F1C,
        owner_pointer=0x1A45CA4, owner=0x1A3AAE0, adapter=0xA09B6E,
        queue=0x1A45C70, queue_entry=0x371FC8),
    'a1ii-4.00': dict(selector=0x3C0C58, error=0xAA59B0, logs=[0xAA67A6, 0xAA67F0],
        marker=0x68A8, error_field=0x633C, kind=0x5DA8, cls=0xBFC,
        format=0x6238, alternate=0xBF0, diagnostic=0xA30,
        initializer=0xAA049C, initializer_end=0xAA17D2,
        table=0x193509C, table_ram=(0x1934000, 0x5000), retained=10,
        dispatch=0x3C0F9C, phase_count=7, last_phase=0xAA1DD2,
        enqueue=0x3B8C60, enqueue_boundary=0xAD06D0,
        owner=0x192AECC, adapter=0x3B8CE0),
}


def word(v):
    return struct.pack('<I', v)


def audit(blob, spec):
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    pages = set()

    def page(address):
        at = address & ~4095
        if at not in pages:
            u.mem_map(at, 4096)
            if at < len(blob):
                u.mem_write(at, blob[at:at + 4096])
            pages.add(at)

    for at in [spec['selector'], spec['error'], spec['dispatch'], spec['last_phase'],
               spec['enqueue'], spec['enqueue_boundary'], spec['adapter'], *spec['logs']]:
        page(at)
    for at in range(spec['initializer'] & ~4095, spec['initializer_end'] + 1, 4096):
        page(at)
    for at, size in [spec['table_ram'], (MEM, 0x12000), (STACK, 0x4000), (STOP, 4096)]:
        u.mem_map(at, size)
    if spec.get('owner_pointer'):
        page(spec['owner_pointer'])
        u.mem_write(spec['owner_pointer'], word(spec['owner']))
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    constructor = list(md.disasm(blob[spec['initializer']:spec['initializer_end'] + 2], spec['initializer']))
    assert constructor[-1].mnemonic == 'bx' and constructor[-1].op_str == 'lr'
    assert {i.mnemonic for i in constructor} <= {'movw', 'movt', 'movs', 'str', 'str.w', 'strd', 'bx'}
    u.reg_write(UC_ARM_REG_LR, STOP | 1)
    u.emu_start(spec['initializer'] | 1, STOP, count=4000)
    assert u.reg_read(UC_ARM_REG_PC) == STOP
    descriptor = struct.unpack('<5I', u.mem_read(spec['table'] + 20 * spec['retained'], 20))
    assert (descriptor[2] & ~1) - 0x108000 == spec['dispatch']
    stops, observed = set(), []

    def stop(cpu, address, size, user):
        if address in stops:
            observed.append((address, [cpu.reg_read(r) for r in
                [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]]))
            cpu.emu_stop()

    u.hook_add(UC_HOOK_CODE, stop)

    def run(start, boundaries):
        nonlocal stops
        stops = set(boundaries)
        before = len(observed)
        u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
        u.reg_write(UC_ARM_REG_LR, STOP | 1)
        u.emu_start(start | 1, STOP, count=400)
        assert len(observed) == before + 1
        assert u.reg_read(UC_ARM_REG_PC) == observed[-1][0]
        return observed[-1]

    vectors = itertools.product([0, 1, 2, 3], range(6), [0, 1, 8], [0, 8, 10], [0, 1], [0, 3])
    results = []
    donor = spec['retained'] == 10
    for marker, cls, error, kind, fmt, alternate in vectors:
        frame = bytearray(0x6A00)
        for offset, value in [(spec['marker'], marker), (spec['cls'], cls),
                (spec['error_field'], error), (spec['kind'], kind),
                (spec['format'], fmt), (spec['alternate'], alternate)]:
            struct.pack_into('<I', frame, offset, value)
        u.mem_write(FRAME, bytes(frame))
        u.mem_write(HOLDER, word(FRAME))
        u.reg_write(UC_ARM_REG_R0, PIPE)
        u.reg_write(UC_ARM_REG_R1, HOLDER)
        _, regs = run(spec['selector'], spec['logs'])
        assert regs[:2] == [FRAME, 5]
        selected = regs[2]
        if marker == 3:
            expected = 1
        elif marker == 2 and error & 7:
            expected = 2 if donor else 1
        elif error & 7:
            expected = 11 if donor else 10
        elif kind:
            expected = 4 if donor else 3
        elif cls == 4:
            expected = spec['retained'] if marker == 2 else (9 if fmt else 8) if donor else (8 if fmt else 7)
        else:
            expected = (7 if donor else 6) if fmt else (6 if donor else 5) if alternate == 3 else (5 if donor else 4)
        assert selected == expected, (donor, marker, cls, error, kind, fmt, alternate, selected, expected)
        assert (selected == spec['retained']) == (marker == 2 and cls == 4 and kind == 0 and not error & 7)
        assert bytes(u.mem_read(FRAME, len(frame))) == bytes(frame)
        results.append({'marker': marker, 'class_raw': cls, 'error': error, 'kind_raw': kind,
            'format_raw': fmt, 'alternate_raw': alternate, 'descriptor': selected,
            'retention_path': selected == spec['retained']})
    # Real phase table and original dispatch execute; handler bodies do not.
    table = spec['dispatch'] + 12
    phases = []
    for phase in range(spec['phase_count']):
        target = table + 2 * blob[table + phase]
        ins = next(md.disasm(blob[target:target + 4], target))
        assert ins.mnemonic == 'b.w'
        body = int(ins.op_str.removeprefix('#'), 16)
        page(body)
        u.mem_write(PIPE, bytes(64))
        u.mem_write(PIPE + 0x27, bytes([phase]))
        u.reg_write(UC_ARM_REG_R0, PIPE)
        at, _ = run(spec['dispatch'], [body])
        phases.append({'phase': phase, 'handler_file': hex(at), 'executed': False})
    assert int(phases[-1]['handler_file'], 16) == spec['last_phase']
    # Separate original callback construction, not a fake completion of
    # sensor phases. Stop before OS delivery to the actual native owner.
    u.reg_write(UC_ARM_REG_R0, PIPE)
    _, regs = run(spec['enqueue'], [spec['enqueue_boundary']])
    assert regs[0] == spec['owner'] and regs[2] == PIPE
    callback = struct.unpack('<5I', u.mem_read(regs[1], 20))
    assert (callback[2] & ~1) - 0x108000 == spec['adapter']
    return {'native_decision_cases': len(results), 'cases': results,
        'retention_descriptor': spec['retained'], 'descriptor_callback': hex(spec['dispatch']),
        'phase_dispatch': phases, 'native_callback_boundary': hex(spec['enqueue_boundary']),
        'native_owner': hex(regs[0]), 'native_frame_argument_preserved': True,
        'native_callback_adapter_file': hex(spec['adapter']), 'OS_enqueue_executed': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--firmware-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--zig', type=Path, help='Also compile and compare the implemented admission guard')
    p.add_argument('--build-output', type=Path)
    a = p.parse_args()
    report = {'schema': 'OFFLINE_NATIVE_RETENTION_ENTRY/1', 'camera_io': False, 'models': {}}
    for model, spec in S.items():
        raw = (a.firmware_root / model / 'components/cpapp-b.bin').read_bytes()
        if hashlib.sha256(raw).hexdigest() != SPECS[model]['sha256']:
            raise ValueError('Unsupported exact original CP: ' + model)
        report['models'][model] = audit(raw, spec)
    if bool(a.zig) != bool(a.build_output):
        raise ValueError('--zig and --build-output must be supplied together')
    if a.zig:
        from support.build import compile_shared
        from support.elf import image_loader
        from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC
        a.build_output.mkdir(parents=True,exist_ok=False)
        compiled = {}
        for arch,triple in [('thumb','thumb-linux-gnueabi'),('aarch64','aarch64-linux-gnu')]:
            dest=a.build_output/(arch+'-retention-admission.elf')
            compile_shared(a.zig, arch, dest,
                [Path(__file__).with_name('frame_route.c')], optimization='-O2', debug=False)
            cpu,symbols=image_loader(dest,arch,('precapture_retention_entry_eligible',))
            from support.memory import STOP as return_address
            cpu.mem_map(MEM+0x1000,0x6000)
            r0,sp,lr,pc=((UC_ARM_REG_R0,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC) if arch=='thumb'
                else (UC_ARM64_REG_X0,UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC))
            count=0
            for model in report['models'].values():
                for case in model['cases']:
                    frame=bytearray(0x6a00)
                    for offset,value in [(0x66e8,case['marker']),(0xbb4,case['class_raw']),
                            (0x5c10,case['kind_raw']),(0x617c,case['error'])]:
                        struct.pack_into('<I',frame,offset,value)
                    cpu.mem_write(MEM,bytes(frame));cpu.reg_write(r0,MEM)
                    cpu.reg_write(sp,STACK+0x3000);cpu.reg_write(lr,return_address | (arch=='thumb'))
                    cpu.emu_start(symbols['precapture_retention_entry_eligible'],return_address,count=200)
                    assert cpu.reg_read(pc)==return_address
                    assert cpu.reg_read(r0)==int(case['retention_path'])
                    assert bytes(cpu.mem_read(MEM,len(frame)))==bytes(frame)
                    count+=1
            cpu.reg_write(r0,0);cpu.reg_write(sp,STACK+0x3000);cpu.reg_write(lr,return_address | (arch=='thumb'))
            cpu.emu_start(symbols['precapture_retention_entry_eligible'],return_address,count=200)
            assert cpu.reg_read(pc)==return_address and cpu.reg_read(r0)&0xffffffff==0xffffffea
            compiled[arch]={'native_comparisons':count,'null_frame_rejected':True,'frame_bytes_unchanged':True}
        report['compiled_guard_checks']=compiled
    report['limits'] = ['Raw class/kind/format fields are not user-facing shutter/drive names',
        'Frame marker2 alone does not establish entry into the retention task',
        'The actual failed frame class and CP runtime context were not captured',
        'No logging, image-processing phases, OS callback delivery or sensor operation execute',
        'This audit does not authorize installation or repeating the failed parameter']
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
        f.write('\n')
    print('Two original stage5 selectors, retention phase dispatches and native task callback boundaries verified. No camera I/O.')


if __name__ == '__main__':
    main()
