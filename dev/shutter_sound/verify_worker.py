"""Execute the compiled sound installer ELF with fault-injected syscalls.

The filesystem, mount and power environment is synthetic. This validates the
actual compiled transaction code, not camera boot safety or audible playback.
Firmware I/O is restricted to the proposed CP instruction windows.
"""
import argparse
import json
from pathlib import Path
import struct

from candidate import BEFORE, AFTER, OFFSET, WINDOWS

AP = '/usr/lib/appFw.so'
CP = '/cp/cpapp-b.bin'
REQUEST = '/tmp/jiritsu/a7c2.install.request'
RESULT = '/tmp/jiritsu/a7c2.install.result'
PLUGIN = '/tmp/jiritsu/libJit.so'


def load(worker):
    from elftools.elf.elffile import ELFFile
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    from unicorn.arm64_const import UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_CPACR_EL1
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    base, end = 0x10000000, 0x70000000
    with Path(worker).open('rb') as f:
        elf = ELFFile(f)
        segments = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
        size = max(s['p_vaddr'] + s['p_memsz'] for s in segments)
        cpu.mem_map(base, (size + 4095) & ~4095)
        for s in segments:
            cpu.mem_write(base + s['p_vaddr'], s.data())
        for section in elf.iter_sections():
            if section['sh_type'] == 'SHT_RELA':
                for r in section.iter_relocations():
                    if r['r_info_type'] != 1027 or r['r_info_sym'] != 0:
                        raise ValueError('Unexpected relocation')
                    cpu.mem_write(base + r['r_offset'], struct.pack('<Q', base + r['r_addend']))
        init = next(t.entry.d_val for t in elf.get_section_by_name('.dynamic').iter_tags() if t.entry.d_tag == 'DT_INIT')
    cpu.mem_map(0x60000000, 0x100000)
    cpu.mem_map(end, 4096)
    cpu.reg_write(UC_ARM64_REG_SP, 0x600f0000)
    cpu.reg_write(UC_ARM64_REG_LR, end)
    cpu.reg_write(UC_ARM64_REG_CPACR_EL1, 0x300000)
    return cpu, base + init, end


def execute(worker, sizes, mode=1, fault='none', byte_windows=None):
    from unicorn import UC_HOOK_INTR
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X8, UC_ARM64_REG_PC
    cpu, start, end = load(worker)
    spans = byte_windows or [(CP, OFFSET, BEFORE, AFTER)]
    contents = [bytearray(new if mode == 2 else old) for path, at, old, new in spans]
    originals = [bytes(value) for value in contents]
    if fault == 'conflict': contents[0][0] ^= 1
    actual_sizes = list(sizes)
    if fault == 'size': actual_sizes[1] -= 1
    files = {REQUEST: bytearray(struct.pack('<8sII', b'A7INS001', mode, 0)), PLUGIN: bytearray(b'owned')}
    if fault == 'request': files[REQUEST][0] ^= 1
    handles, writes, mounts, injected = {}, [], [], []
    ro = [True]
    def string(at):
        out = bytearray()
        for i in range(1024):
            v = bytes(cpu.mem_read(at + i, 1))
            if v == b'\0': return out.decode('ascii')
            out += v
        raise AssertionError('Unterminated syscall path')
    def syscall(uc, number, user):
        no = uc.reg_read(UC_ARM64_REG_X8)
        a = [uc.reg_read(r) for r in (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4)]
        result = 0
        if no in (172, 175): result = 47 if no == 172 else (1000 if fault == 'nonroot' else 0)
        elif no == 56:
            path = string(a[1]); flags = a[2]
            assert path in (AP, CP, REQUEST, RESULT, '/proc/mounts')
            if path == RESULT:
                assert flags == 0x241; files[path] = bytearray()
            if path == '/proc/mounts':
                text = '/dev/nflasha15 /usr ext2 ' + ('ro' if ro[0] else 'rw') + ',sync 0 0\n'
                if fault == 'mount_readback' and not ro[0] and not injected:
                    text = 'wrong mount\n'; injected.append(fault)
                files[path] = bytearray(text.encode())
            if path == CP and fault == 'missing': result = -2
            else:
                result = 10 + len(handles)
                handles[result] = [path, 0, False, flags]
        elif no == 35:
            assert string(a[1]) == PLUGIN; files.pop(PLUGIN, None)
        elif no == 80:
            path = handles[a[0]][0]; assert path in (AP, CP)
            stat = bytearray(128); index = int(path == CP)
            struct.pack_into('<QQI', stat, 0, 15, 100 + index, 0o100644)
            struct.pack_into('<q', stat, 48, actual_sizes[index]); uc.mem_write(a[1], bytes(stat))
        elif no in (63, 67):
            path, pos, closed, flags = handles[a[0]]; assert not closed
            at, count = (pos if no == 63 else a[3]), a[2]
            if path in (AP, CP):
                matches = [i for i, (p, off, old, new) in enumerate(spans)
                           if p == path and off <= at and at + count <= off + len(old)]
                assert len(matches) == 1
                index = matches[0]; offset = spans[index][1]
                if fault == 'read': result = -5
                else:
                    if fault == 'short': count = min(count, 1)
                    data = bytes(contents[index][at - offset:at - offset + count])
                    uc.mem_write(a[1], data); result = len(data)
            else:
                data = bytes(files[path][at:at + count]); uc.mem_write(a[1], data); result = len(data)
            if no == 63: handles[a[0]][1] += max(result, 0)
        elif no in (64, 68):
            path, pos, closed, flags = handles[a[0]]; assert not closed
            at, count = (pos if no == 64 else a[3]), a[2]
            if path in (AP, CP):
                assert no == 68 and flags == 2
                matches = [i for i, (p, off, old, new) in enumerate(spans)
                           if p == path and off <= at and at + count <= off + len(old)]
                assert len(matches) == 1
                index = matches[0]; offset = spans[index][1]
                if fault == 'write' and not injected:
                    injected.append(fault); result = -5
                elif fault in ('partial_write', 'rollback_write') and len(writes) == 1 and not injected:
                    injected.append(fault); result = -5
                elif fault == 'rollback_write' and injected:
                    result = -5
                else:
                    if fault in ('short', 'partial_write', 'rollback_write') and not injected: count = min(count, 1)
                    data = bytes(uc.mem_read(a[1], count))
                    contents[index][at - offset:at - offset + count] = data
                    writes.append((at, count)); result = count
            else:
                assert path == RESULT and no == 64
                data = bytes(uc.mem_read(a[1], count)); files[path].extend(data)
                handles[a[0]][1] += count; result = count
        elif no == 40:
            assert a[0] == 0 and string(a[1]) == '/usr' and a[2] == 0 and a[4] == 0
            assert a[3] in (0xc30, 0xc31)
            wanted = a[3] == 0xc31; mounts.append(wanted)
            if fault == 'mount' and not wanted: result = -1
            elif fault == 'readonly' and wanted: result = -1
            else: ro[0] = wanted
        elif no == 82:
            path = handles[a[0]][0]
            if writes and path in (AP, CP) and not injected:
                if fault == 'fsync': injected.append(fault); result = -5
                elif fault == 'readback': injected.append(fault); contents[0][0] ^= 255
        elif no == 57: handles[a[0]][2] = True
        else: raise AssertionError('Forbidden syscall: ' + str(no))
        uc.reg_write(UC_ARM64_REG_X0, result & ((1 << 64) - 1))
    cpu.hook_add(UC_HOOK_INTR, syscall)
    cpu.emu_start(start, end, count=2000000)
    assert cpu.reg_read(UC_ARM64_REG_PC) == end
    raw = bytes(files[RESULT]); assert len(raw) == 240
    values = struct.unpack_from('<8sIIII7q4Q', raw)
    assert values[:2] == (b'A7IRP001', 1)
    if fault != 'request': assert values[2] == mode
    assert raw[112:] == bytes(128), 'Byte-only worker must not scan firmware hashes'
    if fault in ('none', 'short'):
        assert values[3] == 9 and not any(values[i] for i in range(5, 11))
        assert all(bytes(value) == (old if mode in (0, 2) else new)
                   for value, (_, _, old, new) in zip(contents, spans))
        if not mode: assert not writes and not mounts
    else:
        assert values[5] < 0
        if fault in ('write', 'partial_write', 'fsync', 'readback'):
            assert values[6] == 0 and all(bytes(a) == b for a, b in zip(contents, originals))
        elif fault == 'rollback_write': assert values[6] < 0
        elif fault == 'readonly': assert values[8] < 0
        else: assert not writes
    if fault != 'readonly': assert ro[0]
    assert all(h[2] for h in handles.values())
    return dict(mode=mode, fault=fault, phase=values[3], status=values[5], rollback=values[6],
                pwrite_calls=len(writes), pwrite_offsets=[at for at, count in writes])


def verify(worker, sizes, byte_windows=None):
    spans=byte_windows or [(CP,at,old,new) for at,old,new in WINDOWS]
    rows = [execute(worker, sizes, mode,byte_windows=spans) for mode in (0, 1, 2)]
    rows += [execute(worker, sizes, 1, fault,byte_windows=spans) for fault in
             ('short', 'conflict', 'size', 'missing', 'request', 'nonroot', 'read',
              'write', 'partial_write', 'rollback_write', 'fsync', 'readback', 'mount', 'mount_readback', 'readonly')]
    return {'compiled_worker_cases': len(rows), 'camera_io': False,
            'firmware_io_limited_to_sound_cp_windows': True,
            'camera_boot_or_playback_tested': False, 'cases': rows}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    document = json.loads(a.plan.read_text(encoding='utf-8'))
    plan = document['native_program']
    spans=([(CP,w['offset'],bytes.fromhex(w['before_hex']),bytes.fromhex(w['after_hex']))
            for w in document['windows']] if 'windows' in document else [(CP,OFFSET,BEFORE,AFTER)])
    result = verify(plan['path'], plan['sizes'],spans)
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2); f.write('\n')
    print('Compiled native worker:', result['compiled_worker_cases'], 'offline cases passed')


if __name__ == '__main__': main()
