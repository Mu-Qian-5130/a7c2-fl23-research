"""Analyze a private native abort log and replay original capture preconditions.

No camera access, patches or success callbacks. Reconstructs only the
captured frame-pointer chain, then tests the actual AP entry guard. Keep
logs and generated reports private; a matching abort is not a full trace.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
    UC_ARM64_REG_X2, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC)

TARGET_SHA = {'2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
              '690b5f17f21cba5c7cd937e6feb0f6967ea2793c0b4ca6fc1fffdcaa1ed0d761'}
DONOR_SHA = 'd04cc70b41382a147ef5c67d7e86ba706d66526aee17619767b07cbb416b77ca'
MEM, STACK = 0x30000000, 0x40000000


def original_guard(raw, donor=False):
    start, nonempty, diagnostic, line = ((0x3159148, 0x3159208, 0x338C490, 0x721)
        if donor else (0x34A60D8, 0x34A6198, 0x36E9310, 0x70A))
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for address in {start & ~4095, diagnostic & ~4095}:
        u.mem_map(address, 4096)
        u.mem_write(address, raw[address:address + 4096])
    u.mem_map(MEM, 0x4000)
    u.mem_map(STACK, 0x4000)
    stops = []

    def stop(cpu, address, size, user):
        if address in [nonempty, diagnostic]:
            stops.append(address)
            cpu.emu_stop()

    u.hook_add(UC_HOOK_CODE, stop)
    cases = []
    for begin, end in [(MEM + 0x2000, MEM + 0x2000),
                       (MEM + 0x2000, MEM + 0x2018),
                       (MEM + 0x2018, MEM + 0x2000),
                       (MEM + 0x2018, MEM + 0x2018)]:
        owner = bytearray(0x1000)
        struct.pack_into('<Q', owner, 0x330, begin)
        struct.pack_into('<Q', owner, 0x350, end)
        u.mem_write(MEM, bytes(owner))
        for reg, value in [(UC_ARM64_REG_X0, MEM), (UC_ARM64_REG_X1, MEM + 0x1000),
                           (UC_ARM64_REG_X2, 0), (UC_ARM64_REG_SP, STACK + 0x3000)]:
            u.reg_write(reg, value)
        before = len(stops)
        u.emu_start(start, 0xFFFFFFFF, count=80)
        expected = diagnostic if begin == end else nonempty
        assert len(stops) == before + 1 and stops[-1] == expected
        assert u.reg_read(UC_ARM64_REG_PC) == expected
        assert bytes(u.mem_read(MEM, 0x1000)) == bytes(owner)
        if begin == end:
            assert u.reg_read(UC_ARM64_REG_X2) == line
        cases.append({'begin_equals_end': begin == end,
            'boundary': hex(expected), 'assertion_diagnostic_selected': begin == end,
            'owner_unchanged': True, 'logging_or_frame_processing_executed': False})
    return cases


def original_pending_lifecycle(raw):
    """Original AP bookkeeping on explicit preallocated synthetic storage.

    This does not inject a capture request or fake an allocation on camera.
    The purpose is to check which native producer can satisfy the actual
    failing precondition, and that count/pop operations use the same queue.
    """
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for at in [0x34A1000, 0x34A2000, 0x34A6000, 0x36E9000]:
        u.mem_map(at, 4096)
        u.mem_write(at, raw[at:at + 4096])
    u.mem_map(MEM, 0x5000)
    u.mem_map(STACK, 0x4000)
    stop = 0x60000000
    u.mem_map(stop, 4096)
    observed, boundaries = [], set()

    def stop_at(cpu, at, size, user):
        if at in boundaries:
            observed.append(at)
            cpu.emu_stop()

    u.hook_add(UC_HOOK_CODE, stop_at)

    def call(start, args, stops):
        nonlocal boundaries
        boundaries = set(stops)
        old = len(observed)
        for reg, value in zip([UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2], args):
            u.reg_write(reg, value)
        u.reg_write(UC_ARM64_REG_SP, STACK + 0x3000)
        u.reg_write(UC_ARM64_REG_LR, stop)
        u.emu_start(start, stop, count=100)
        if stops:
            assert len(observed) == old + 1
            return observed[-1]
        assert u.reg_read(UC_ARM64_REG_PC) == stop

    cases = []
    for slot in [0, 1, 19]:
        begin, record, event = MEM + 0x3000 + 24 * slot, MEM + 0x2000, MEM + 0x1000
        owner = bytearray(0x1000)
        struct.pack_into('<Q', owner, 0x330, begin)
        struct.pack_into('<Q', owner, 0x350, begin)
        for at in [0x340, 0x360]:
            struct.pack_into('<Q', owner, at, MEM + 0x3000 + 504)
        u.mem_write(MEM, bytes(owner))
        u.mem_write(MEM + 0x2FF0, b'\xA5' * (504 + 32))
        pending = struct.pack('<IIQQ', 0, 0, 0, 0xFFFFFFFFFFFFFFFF)
        u.mem_write(record, pending)
        u.mem_write(event, bytes(64))
        call(0x34A144C, [MEM + 0x320, record], [])
        assert struct.unpack('<Q', u.mem_read(MEM + 0x350, 8))[0] == begin + 24
        assert bytes(u.mem_read(begin, 24)) == pending
        assert call(0x34A60D8, [MEM, event, 0], [0x34A6198, 0x36E9310]) == 0x34A6198
        # Stop before the rest of normal image handling. The actual native
        # next-entry load and per-group frame counter increment execute.
        boundaries = {0x34A61AC}
        previous = len(observed)
        u.emu_start(0x34A6198, stop, count=20)
        assert len(observed) == previous + 1 and observed[-1] == 0x34A61AC
        assert u.reg_read(UC_ARM64_REG_PC) == 0x34A61AC
        assert struct.unpack('<Q', u.mem_read(begin + 8, 8))[0] == 1
        call(0x34A2540, [MEM + 0x320], [])
        assert struct.unpack('<Q', u.mem_read(MEM + 0x330, 8))[0] == begin + 24
        assert call(0x34A60D8, [MEM, event, 0], [0x34A6198, 0x36E9310]) == 0x36E9310
        expected = bytearray(b'\xA5' * (504 + 32))
        expected[16 + 24 * slot:16 + 24 * slot + 24] = struct.pack('<IIQQ', 0, 0, 1, 0xFFFFFFFFFFFFFFFF)
        assert bytes(u.mem_read(MEM + 0x2FF0, len(expected))) == bytes(expected)
        cases.append({'initial_slot': slot, 'native_push_admits_entry': True,
            'native_frame_count': 1, 'native_pop_reestablishes_empty_guard': True,
            'bytes_outside_record_preserved': True, 'image_processing_executed': False})
    # Last-slot growth must not be pretended to succeed; stop before its
    # real allocation/reallocation path instead of manufacturing storage.
    u.mem_write(MEM + 0x350, struct.pack('<Q', MEM + 0x3000 + 480))
    assert call(0x34A144C, [MEM + 0x320, MEM + 0x2000], [0x34A1480]) == 0x34A1480
    return {'cases': cases, 'growth_path_stopped_before_execution': True,
        'native_start_producer_call': '0x34a7b44 ->0x34a144c',
        'actual_shutter_or_capture_start_notification_delivered': False}


def analyze(log, ap):
    rawlog = log.read_bytes()
    text = rawlog.decode('utf-8', errors='replace')
    begin = text.rfind('[register dump]')
    end = text.find('Booting Linux', begin)
    if begin < 0:
        raise ValueError('No native register dump in the supplied log')
    section = text[begin:end if end >= 0 else None]
    registers = {m[1]: int(m[2], 16) for m in
        re.finditer(r'\b(fp|lr|sp|pc):\s*0x([0-9a-fA-F]+)', section)}
    if set(registers) != {'fp', 'lr', 'sp', 'pc'}:
        raise ValueError('Incomplete register dump')
    memory = {}
    for m in re.finditer(r'0x([0-9a-fA-F]{16}):[| ]*(0x[0-9a-fA-F]{16})\s+(0x[0-9a-fA-F]{16})', section):
        address = int(m[1], 16)
        for delta, value in [(0, int(m[2], 16)), (8, int(m[3], 16))]:
            if address + delta in memory and memory[address + delta] != value:
                raise ValueError('Conflicting captured stack words')
            memory[address + delta] = value
    maps = []
    for m in re.finditer(r'^([0-9a-fA-F]{16})-([0-9a-fA-F]{16})[ \t]+([rwx-]{3})[ \t]+0x([0-9a-fA-F]+)[ \t]*([^\r\n]*)', section, re.M):
        maps.append((int(m[1], 16), int(m[2], 16), m[3], int(m[4], 16), m[5]))

    def locate(address):
        found = [{'module': name, 'file_offset': offset + address - start,
                  'permissions': permissions}
                 for start, stop, permissions, offset, name in maps if start <= address < stop]
        if len(found) != 1 or 'x' not in found[0]['permissions']:
            raise ValueError('Captured PC/LR is not uniquely executable: ' + hex(address))
        return found[0]

    fp = registers['fp']
    frames, visited = [], set()
    termination = 'stack_not_captured'
    for _ in range(128):
        if not fp:
            termination = 'null_frame_pointer'
            break
        if fp % 16 or fp in visited:
            raise ValueError('Unaligned/cyclic captured frame chain')
        if fp not in memory or fp + 8 not in memory:
            break
        visited.add(fp)
        nextfp, lr = memory[fp], memory[fp + 8]
        frames.append({'fp': hex(fp), 'next_fp': hex(nextfp), 'saved_lr': hex(lr), **locate(lr)})
        if nextfp and nextfp <= fp:
            raise ValueError('Non-monotonic captured frame chain')
        fp = nextfp
    else:
        raise ValueError('Frame chain exceeds analysis bound')
    apframes = [x['file_offset'] for x in frames if x['module'] == 'appFw.so']
    expected = [0x35AA4DC, 0x34A6198, 0x34A99E0, 0x34AE2B0, 0x3209E48, 0x36EC1B0]
    if apframes[:len(expected)] != expected:
        raise ValueError('Abort chain is not the audited capture-entry failure')
    raw = ap.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest not in TARGET_SHA:
        raise ValueError('Unsupported exact target AP')
    # Verify actual captured call sites, not arbitrary words resembling PCs.
    for return_address, callee in [(0x35AA4DC, 0x165FF80),
                                  (0x34A6198, 0x35AA4B4),
                                  (0x34A99E0, 0x34A60D8),
                                  (0x34AE2B0, 0x34A98F8)]:
        instruction = struct.unpack_from('<I', raw, return_address - 4)[0]
        immediate = instruction & 0x3FFFFFF
        if immediate & (1 << 25):
            immediate -= 1 << 26
        assert instruction & 0xFC000000 == 0x94000000
        assert return_address - 4 + immediate * 4 == callee
    from elftools.elf.elffile import ELFFile
    with ap.open('rb') as stream:
        elf = ELFFile(stream)
        relocations = elf.get_section_by_name('.rela.plt')
        symbols = elf.get_section(relocations['sh_link'])
        pc = 0x165FF80
        instruction, load = struct.unpack_from('<2I', raw, pc)
        assert instruction & 0x9F00001F == 0x90000010
        assert load & 0xFFC003FF == 0xF9400211
        immediate = (((instruction >> 5) & 0x7FFFF) << 2) | ((instruction >> 29) & 3)
        if immediate & (1 << 20):
            immediate -= 1 << 21
        got = (pc & ~4095) + (immediate << 12) + ((load >> 10) & 0xFFF) * 8
        resolved = [symbols.get_symbol(rel['r_info_sym']).name
                    for rel in relocations.iter_relocations() if rel['r_offset'] == got]
        assert resolved == ['__assert_fail']
    source_file = raw[0x4C5F4D1:].split(b'\0', 1)[0].decode()
    source_function = raw[0x4C5FBF0:].split(b'\0', 1)[0].decode()
    assert source_file == 'sequence/sequence_still_record.cpp'
    assert 'cap_data_entry_proc_normal' in source_function
    task = re.search(r'^program:\s*([^\r\n]+)', section, re.M)
    if not task or 'SeqQueueStillCa' not in task[1]:
        raise ValueError('Unexpected aborted task')
    prior_timestamp = re.findall(r'^\[\s*([\d.]+)\]', text[:begin], re.M)
    return {'schema': 'PRIVATE_CAPTURE_ABORT_ANALYSIS/1', 'camera_io': False,
        'log_sha256': hashlib.sha256(rawlog).hexdigest(), 'log_bytes': len(rawlog),
        'ap_sha256': digest, 'PC': locate(registers['pc']), 'LR': locate(registers['lr']),
        'task': task[1], 'captured_frames': frames, 'frame_chain_termination': termination,
        'source_file': source_file, 'source_line': 0x70A, 'source_function': source_function,
        'actual_assertion_PLT_symbol': resolved[0],
        'last_pre_dump_kernel_timestamp': prior_timestamp[-1] if prior_timestamp else None,
        'guard': 'AP owner+0x330 begin cursor equals owner+0x350 end cursor',
        'guard_interpretation': 'pending capture bookkeeping deque is empty; not a proven RAW-buffer-full condition',
        'target_native_guard_cases': original_guard(raw),
        'target_native_pending_lifecycle': original_pending_lifecycle(raw),
        'limits': ['Physical failure occurred, but this log has no absolute UTC crash timestamp',
            'Captured call chain localizes the abort; it does not explain why the pending deque was empty',
            'Missing AP capture request / early CP delivery is a hypothesis, not a proven complete root cause',
            'No captured CP stack, per-frame timeline or original queue contents are supplied',
            'Do not bypass the assertion: following code dereferences the pending entry',
            'Passing original-instruction cases does not establish camera safety or pre-capture']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--log', type=Path, required=True)
    p.add_argument('--ap', type=Path, required=True)
    p.add_argument('--donor-ap', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    report = analyze(a.log, a.ap)
    if a.donor_ap:
        donor = a.donor_ap.read_bytes()
        if hashlib.sha256(donor).hexdigest() != DONOR_SHA:
            raise ValueError('Unsupported exact donor AP')
        report['donor_native_guard_cases'] = original_guard(donor, True)
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print('Captured AP abort chain verified: sequence_still_record.cpp:1802, empty pending-capture deque. No camera I/O; do not bypass assertion.')


if __name__ == '__main__':
    main()
