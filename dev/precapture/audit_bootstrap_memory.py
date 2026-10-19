"""Execute original CP bootstrap table construction on synthetic RAM.

Stops before boot polling, separates the pure post-poll slice, and executes
the original memcpy/page mapper. MMU/cache control and camera boot do not run.
Optional extra-page mapping is an emulator geometry experiment, not ownership
proof, executable storage approval, a firmware candidate or an installer.
"""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from verify_extension_layout import PINNED, layout

BASE, HEADER, STOP = 0x108000, 0x128000, 0x30000000


def word(v):
    return struct.pack('<I', v)


def translate(u, first, address):
    def get(at):
        return struct.unpack('<I', u.mem_read(at, 4))[0]
    l1 = get(first + (address >> 20) * 4)
    if l1 & 3 == 2:
        return dict(physical=(l1 & 0xFFF00000) + (address & 0xFFFFF),
            xn=bool(l1 & 16), entry_address=first + (address >> 20) * 4, descriptor=l1)
    if l1 & 3 != 1:
        raise AssertionError('Invalid native first-level descriptor')
    pte_at = (l1 & 0xFFFFFC00) + ((address >> 12) & 255) * 4
    l2 = get(pte_at)
    if l2 & 2 != 2:
        raise AssertionError('Invalid native small-page descriptor')
    return dict(physical=(l2 & 0xFFFFF000) + (address & 4095), xn=bool(l2 & 1),
                entry_address=pte_at, descriptor=l2)


def startup_clear(cp, state_bytes=48):
    """Original primary C-startup clear, with guards around proposed state."""
    regions = layout(cp)
    state_at = (regions['data']['virtual'] + regions['data']['length'] + 7) & ~7
    bss = regions['bss']['virtual']
    bss_end = bss + regions['bss']['length']
    arena_begin = state_at & ~4095
    arena_end = ((bss_end + 4095) & ~4095) + 4096
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    for at, size in ((0x60D000, 4096), (0x61E000, 4096),
                     (arena_begin, arena_end - arena_begin), (0x40000000, 4096)):
        u.mem_map(at, size)
        if at in (0x60D000, 0x61E000):
            u.mem_write(at, cp[at - BASE:at - BASE + size])
    before = bytearray([0xA5]) * (arena_end - arena_begin)
    assert 0 < state_bytes <= 256 and state_at + state_bytes <= bss
    state = bytes(range(state_bytes))
    before[state_at - arena_begin:state_at - arena_begin + len(state)] = state
    u.mem_write(arena_begin, bytes(before))
    stop_at = {0x61ED00}
    def stop(cpu, address, size, user):
        if address in stop_at:
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, stop)
    u.reg_write(UC_ARM_REG_SP, 0x40000F00)
    u.emu_start(0x60D334, 0xFFFFFFFF, count=100)
    assert u.reg_read(UC_ARM_REG_PC) == 0x61ED00
    begin, count = u.reg_read(UC_ARM_REG_R0), u.reg_read(UC_ARM_REG_R1)
    assert begin == bss + 0x418 and count == bss_end - begin
    stop_at.clear();stop_at.add(0x60D358)
    u.emu_start(0x61ED00, 0xFFFFFFFF, count=4000000)
    assert u.reg_read(UC_ARM_REG_PC) == 0x60D358
    expected = bytearray(before)
    expected[begin - arena_begin:bss_end - arena_begin] = bytes(count)
    assert bytes(u.mem_read(arena_begin, len(expected))) == bytes(expected)
    assert bytes(u.mem_read(state_at, len(state))) == state
    return dict(native_primary_entry_slice='0x60d334..0x60d358',
        clear_function='0x61ed00', native_clear_start=hex(begin), native_clear_bytes=count,
        proposed_state=hex(state_at), proposed_state_bytes_preserved=len(state),
        reserved_boot_info_prefix_preserved=0x418, entire_clear_and_boundary_guards_verified=True,
        native_boot_trace_before_slice_executed=False, state_initialization_implemented=False,
        actual_camera_boot=False)


def runtime_cleanup_probe(u, cp, first, coarse, mapped_page, guard_elf=None):
    """Original low-region unmap, using a synthetic runtime MMU manager."""
    for at in (0x610000, 0x61A000):
        u.mem_map(at, 4096)
        u.mem_write(at, cp[at - BASE:at - BASE + 4096])
    u.mem_map(0x30001000, 0x4000)
    context = bytearray(0x430)
    struct.pack_into('<3I', context, 0, first, coarse, 32)
    context[12:12 + 512] = bytes([0xFF]) * 512
    used = struct.unpack('<I', u.mem_read(0x108D9C, 4))[0]
    assert 0 < used <= 32
    for index in range(used, 32):
        context[12 + index // 8] &= ~(1 << (index & 7))
    struct.pack_into('<II', context, 0x20C, first, coarse)
    u.mem_write(0x30001000, bytes(context))
    tables_before = bytes(u.mem_read(first, 0xC000))
    for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3),
                          (0x30001000, 0, HEADER, 0)):
        u.reg_write(reg, value)
    u.reg_write(UC_ARM_REG_SP, 0x30004F00)
    u.mem_write(0x30004F00, word(0xFFFFFFFF))
    u.reg_write(UC_ARM_REG_LR, STOP)
    # Existing bootstrap hook already stops at STOP after the mapper probe.
    u.emu_start(0x61A1F4, 0xFFFFFFFF, count=100000)
    assert u.reg_read(UC_ARM_REG_PC) == STOP and u.reg_read(UC_ARM_REG_R0) == 0
    actual = struct.unpack('<I', u.mem_read(mapped_page['entry_address'], 4))[0]
    assert actual == 0
    assert translate(u, first, HEADER)['physical'] in (HEADER, 0xD0220000)
    result = dict(original_unmap='0x61a1f4', startup_call='0x61a014',
        native_unmap_range=['0x0', hex(HEADER)], flag=0, table_selector=-1,
        proposed_page_descriptor_after=actual, proposed_page_removed=True,
        native_context_synthetic=True, hardware_TLB_or_MMU_effect_not_emulated=True,
        conclusion='Early extra-page mapping alone does not survive runtime initialization')
    if guard_elf:
        from elftools.elf.elffile import ELFFile
        from verify_offline import image_loader
        _, symbols = image_loader(guard_elf, 'thumb', ('precapture_target_low_unmap',))
        entry = symbols['precapture_target_low_unmap']
        assert entry & 1 and (entry & ~4095) == 0x10A000
        mapped = set()
        with guard_elf.open('rb') as stream:
            elf = ELFFile(stream)
            for segment in elf.iter_segments():
                if segment['p_type'] != 'PT_LOAD' or not segment['p_memsz']:
                    continue
                start = segment['p_vaddr'] & ~4095
                end = (segment['p_vaddr'] + segment['p_memsz'] + 4095) & ~4095
                for page in range(start, end, 4096):
                    if page not in mapped:
                        u.mem_map(page, 4096);mapped.add(page)
                u.mem_write(segment['p_vaddr'], segment.data())
        baseline_tables = bytes(u.mem_read(first, 0xC000))
        baseline_context = bytes(u.mem_read(0x30001000, len(context)))
        native_calls, code_steps = [], []
        def guard_trace(cpu, address, size, user):
            if 0x10A000 <= address < 0x10B000:
                translation = translate(cpu, first, address)
                assert translation['physical'] == address and not translation['xn']
                code_steps.append(address)
            if address == 0x61A1F4:
                native_calls.append([cpu.reg_read(r) for r in
                    (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)] +
                    [struct.unpack('<I', cpu.mem_read(cpu.reg_read(UC_ARM_REG_SP), 4))[0]])
        u.hook_add(UC_HOOK_CODE, guard_trace)
        checked = []
        for label, manager, address, length, flags, selector, corrupt, expected_status in [
            ('native-low-region', 0x30001000, 0, HEADER, 0, -1, None, 0),
            ('null-manager', 0, 0, HEADER, 0, -1, None, -22),
            ('unaligned-manager', 0x30001001, 0, HEADER, 0, -1, None, -22),
            ('unexpected-address', 0x30001000, 4, HEADER, 0, -1, None, -22),
            ('unexpected-length', 0x30001000, 0, HEADER - 4096, 0, -1, None, -22),
            ('unexpected-flags', 0x30001000, 0, HEADER, 1, -1, None, -22),
            ('unexpected-selector', 0x30001000, 0, HEADER, 0, 0, None, -22),
            ('wrong-table', 0x30001000, 0, HEADER, 0, -1, (0, 0), -95),
            ('wrong-pool-size', 0x30001000, 0, HEADER, 0, -1, (8, 31), -95),
        ]:
            u.mem_write(first, tables_before)
            candidate_context = bytearray(context)
            if corrupt:
                struct.pack_into('<I', candidate_context, *corrupt)
            u.mem_write(0x30001000, bytes(candidate_context))
            native_calls.clear();code_steps.clear()
            for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3),
                                  (manager, address, length, flags)):
                u.reg_write(reg, value)
            u.reg_write(UC_ARM_REG_SP, 0x30004F00)
            u.mem_write(0x30004F00, word(selector & 0xFFFFFFFF))
            u.reg_write(UC_ARM_REG_LR, STOP)
            u.emu_start(entry, 0xFFFFFFFF, count=100000)
            assert u.reg_read(UC_ARM_REG_PC) == STOP
            assert u.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF == expected_status & 0xFFFFFFFF
            assert code_steps
            if expected_status == 0:
                assert native_calls == [[manager, 0, 0x10A000, 0, 0xFFFFFFFF],
                    [manager, 0x10B000, HEADER - 0x10B000, 0, 0xFFFFFFFF]]
                after = bytes(u.mem_read(first, 0xC000))
                changes = [i for i in range(0, len(after), 4) if after[i:i + 4] != baseline_tables[i:i + 4]]
                assert changes == [mapped_page['entry_address'] - first]
                assert translate(u, first, 0x10A000) == mapped_page
                assert bytes(u.mem_read(0x30001000, len(context))) == baseline_context
            else:
                assert not native_calls
                assert bytes(u.mem_read(first, 0xC000)) == tables_before
                assert bytes(u.mem_read(0x30001000, len(context))) == bytes(candidate_context)
            checked.append(dict(label=label, returned_status=expected_status,
                original_unmap_calls=len(native_calls), executing_code_page_remained_mapped=True))
        result['compiled_preserve_page_guard'] = dict(cases=checked, entry_va=hex(entry),
            only_difference_from_native_cleanup='One retained code-page PTE',
            runtime_ownership_and_boot_version_guard_implemented=False,
            hardware_MMU_not_enabled=True, camera_installation=False)
    return result


def audit(cp, alternate_text, probe, guard_elf=None):
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    for at, size in ((BASE, 0x2000), (HEADER, 4096), (0x1B80000, 0x20000),
                     (0x3E42000, 4096), (STOP, 4096)):
        u.mem_map(at, size)
    u.mem_write(BASE, cp[:0x2000])
    u.mem_write(HEADER, cp[0x20000:0x21000])
    u.mem_write(0x3E42000, bytes([alternate_text]))
    stop_at = set()
    def stop(cpu, address, size, user):
        if address in stop_at:
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, stop)
    def run(start, end, count=1000000):
        stop_at.clear();stop_at.add(end)
        u.emu_start(start, 0xFFFFFFFF, count=count)
        if u.reg_read(UC_ARM_REG_PC) != end:
            raise AssertionError(f'Unresolved native bootstrap execution at {u.reg_read(UC_ARM_REG_PC):#x}')
    initial_sp = struct.unpack_from('<I', cp, 0x384)[0]
    assert initial_sp == 0x109F20
    u.reg_write(UC_ARM_REG_SP, initial_sp)
    run(0x108398, 0x108974)
    # The poll is not executed and has no supplied success result. Its
    # return value is unused by the subsequent pure header-copy slice.
    run(0x1083A4, 0x108768)
    first = struct.unpack('<I', u.mem_read(0x108F1C, 4))[0]
    coarse = struct.unpack('<I', u.mem_read(0x108D98, 4))[0]
    assert (first, coarse) == (0x1B88000, 0x1B8C000)
    original_default = [(i << 20) | 0x10C12 for i in range(4096)]
    assert bytes(u.mem_read(first, 0x4000)) == struct.pack('<4096I', *original_default)
    assert bytes(u.mem_read(0x108DA0, 0x17C)) == cp[0x20000:0x2017C]
    args = [u.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
    assert args == [BASE, 4096, BASE, 2]
    run(0x108768, 0x1084BC)
    # Four original text/rodata/data/BSS mapper calls now execute.
    run(0x1084BC, 0x108524)
    regions = layout(cp)
    samples = dict(bootstrap=BASE, boot_stack=initial_sp - 16,
        proposed_page=0x10A000, text=regions['text']['virtual'],
        rodata=regions['rodata']['virtual'], data=regions['data']['virtual'],
        data_tail=regions['data']['virtual'] + regions['data']['length'],
        bss=regions['bss']['virtual'])
    maps = {label: translate(u, first, at) for label, at in samples.items()}
    assert not maps['bootstrap']['xn'] and maps['boot_stack']['xn'] and maps['proposed_page']['xn']
    assert maps['bootstrap']['physical'] == BASE
    assert maps['text']['physical'] == (0xD0220000 if alternate_text else HEADER)
    for name in ('rodata', 'data', 'bss'):
        assert maps[name]['physical'] == samples[name]
    assert not maps['text']['xn'] and all(maps[name]['xn'] for name in ('rodata', 'data', 'data_tail', 'bss'))
    state_at = (samples['data_tail'] + 7) & ~7
    state_bytes = samples['bss'] - state_at
    prefix = cp[0x2000:0x3000]
    assert len(prefix) == 4096 and not any(prefix)
    result = dict(alternate_text_source_byte=alternate_text, initial_sp=hex(initial_sp),
        native_first_level_table=hex(first), native_coarse_pool=hex(coarse),
        native_default_section_descriptor='0x10c12', samples=maps,
        data_tail_geometry=dict(proposed_state=hex(state_at), bytes_before_bss=state_bytes),
        proposed_prefix_file_offset='0x2000', proposed_prefix_rom_zero_bytes=len(prefix),
        boot_poll_executed=False, MMU_enabled=False, cache_or_TLB_operation_executed=False)
    if probe:
        before = bytes(u.mem_read(first, 0xC000))
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3),
                              (0x10A000, 4096, 0x10A000, 15)):
            u.reg_write(reg, value)
        u.reg_write(UC_ARM_REG_LR, STOP)
        run(0x108768, STOP)
        after = bytes(u.mem_read(first, 0xC000))
        changed_words = [i for i in range(0, len(before), 4) if before[i:i + 4] != after[i:i + 4]]
        assert changed_words == [maps['proposed_page']['entry_address'] - first]
        mapped = translate(u, first, 0x10A000)
        assert not mapped['xn'] and mapped['physical'] == 0x10A000
        for label, at in samples.items():
            if label != 'proposed_page':
                assert translate(u, first, at) == maps[label]
        result['emulator_extra_page'] = dict(mapping=mapped,
            changed_table_words=len(changed_words), existing_sample_mappings_preserved=True,
            ownership_proven=False, payload_loaded_or_executed=False)
        result['native_runtime_cleanup'] = runtime_cleanup_probe(u, cp, first, coarse, mapped, guard_elf)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp', type=Path, required=True)
    parser.add_argument('--probe-extra-page', action='store_true')
    parser.add_argument('--zig', type=Path)
    parser.add_argument('--guard-build', type=Path)
    parser.add_argument('--guard-elf', type=Path,
        help='Existing offline full-payload ELF with its unmap guard in the proposed page')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cp = args.cp.read_bytes()
    digest = hashlib.sha256(cp).hexdigest()
    if digest not in PINNED:
        raise ValueError('Unsupported complete target CP fingerprint')
    guard_elf = args.guard_elf
    if guard_elf and (not args.probe_extra_page or args.zig or args.guard_build):
        raise ValueError('Existing guard ELF requires --probe-extra-page without guard build arguments')
    if args.zig or args.guard_build:
        if not (args.zig and args.guard_build and args.probe_extra_page):
            raise ValueError('Guard build needs --zig, --guard-build and --probe-extra-page')
        from verify_offline import codegen_flags
        args.guard_build.mkdir(parents=True, exist_ok=False)
        script = args.guard_build / 'guard-layout.ld'
        script.write_text('SECTIONS { . = 0x10000; .dynsym : { *(.dynsym) } '
            '.gnu.hash : { *(.gnu.hash) } .hash : { *(.hash) } .dynstr : { *(.dynstr) } '
            '.ARM.exidx : { *(.ARM.exidx*) } . = 0x10a000; .text : { *(.text*) } '
            '.dynamic : { *(.dynamic) } }\n', encoding='ascii')
        guard_elf = args.guard_build / 'thumb-low-unmap.elf'
        command = [str(args.zig), 'cc', '-target', 'thumb-linux-gnueabi',
            *codegen_flags('thumb'), '-Oz', '-g', '-shared', '-fPIC', '-ffreestanding',
            '-fno-builtin', '-fno-stack-protector', '-fno-unwind-tables',
            '-fno-asynchronous-unwind-tables', '-nostdlib',
            '-Wl,--no-undefined,-Bsymbolic,-T,' + str(script), '-o', str(guard_elf),
            str(Path(__file__).with_name('cp_bootstrap_mapping_guard.c'))]
        build = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if build.returncode:
            raise RuntimeError(build.stderr[-2500:])
    cases = [audit(cp, alternate, args.probe_extra_page, guard_elf) for alternate in (0, 1)]
    report = dict(schema='OFFLINE_ORIGINAL_CP_BOOTSTRAP_TABLES/1', camera_io=False,
        cp_sha256=digest, cases=cases, primary_startup_clear=startup_clear(cp),
        firmware_candidate_written=False,
        limits=['Boot polling is omitted explicitly, not mocked successful',
            'Source-selection byte is synthetic and has not been read from the current camera',
            'Native table construction executes; hardware MMU/caches/TLB are not activated',
            'A zero prefix and a viable page mapping do not prove unowned executable storage',
            'Actual NOR/AP transfer freshness, byte swapping, all boot-stack users, state initialization and loader ownership remain unresolved',
            'No camera-boot or pre-capture acceptance is established'])
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print('Two original bootstrap mapping paths checked; no polling/MMU/cache or camera execution.')


if __name__ == '__main__':
    main()
