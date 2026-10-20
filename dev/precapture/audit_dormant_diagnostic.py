"""Audit a dormant source/mode observation fixture; emulator RAM ONLY.

No changed CP file, manifest, installer or host trigger is emitted. This is
not pre-capture. The logger's pure stack/copy prefix runs, but allocation and
send remain boundaries. Latency, delivery and real boot are unknown.
"""
import argparse
import hashlib
import itertools
import json
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR)
from support.cp_mapping import layout
from audit_bootstrap_memory import audit as bootstrap_audit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/looks'))
from looktool.hooks import assembler, HELPER
from looktool.six import retry_windows, read_tables
from looktool.sixbuild import helper, checker, CHECKER

SOURCE = '3d6656b933fc681282f920364e5f3b788117c4345a89ec6b9df9862c5563f8a1'
AP_SOURCE = '690b5f17f21cba5c7cd937e6feb0f6967ea2793c0b4ca6fc1fffdcaa1ed0d761'
BASE, STACK, MEM, STOP = 0x108000, 0x40000000, 0x30000000, 0x20000000
STUB, LOG_WRAP, LOG = BASE + 0x7d2a9c, BASE + 0xa18dc4, BASE + 0xa18cac
ALLOC = BASE + 0x45d204
ENTRY, BODY, RETURN = CHECKER + 0x9a, HELPER + 0x64, HELPER + 0xc2
MARKERS = {'status': 0xe1, 'nonce': 0x7ce1}
PRESERVED = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)


def words(*v):
    return struct.pack('<' + 'I' * len(v), *v)


def fixture(cp, kind):
    """Reconstruct the CURRENT helper, including the later retry overlays."""
    if hashlib.sha256(cp).hexdigest() != SOURCE:
        raise ValueError('Unsupported complete current CP source')
    asm = assembler()
    raw = bytearray(helper(asm))
    for at, value in retry_windows(asm):
        offset = BASE + at - HELPER
        if 0 <= offset < len(raw):
            raw[offset:offset + len(value)] = value
    if bytes(raw) != cp[HELPER - BASE:HELPER - BASE + 256]:
        raise ValueError('Current helper/retry reconstruction differs')
    check = checker(asm)
    assert len(check) == 92
    assert cp[CHECKER - BASE:CHECKER - BASE + len(check)] == check
    # Source-owned bounds, NOT a general zero-run storage search.
    gaps = [(HELPER + a, b - a) for a, b in
            ((0x64, 0x70), (0xc2, 0xc8), (0xfe, 0x100))]
    gaps += [(CHECKER + 0x5c, 4), (CHECKER + 0x9a, 6)]
    assert sum(n for at, n in gaps) == 30
    assert all(not any(cp[at-BASE:at-BASE+n]) for at, n in gaps)
    native = layout(cp)
    for at, n in gaps:
        assert native['text']['virtual'] <= at < at+n <= (
            native['text']['virtual'] + native['text']['length'])
    assert ENTRY + 6 == native['text']['virtual'] + native['text']['length']
    assert cp[STUB-BASE:STUB-BASE+4] == asm('movs r0,#1;bx lr', STUB)
    assert struct.unpack_from('<2I', cp, 0xff466c) == (0x4172, STUB | 1)
    assert struct.unpack_from('<2I', cp, 0xff4680) == (0x4173, (STUB + 4) | 1)
    # Separate alternatives, never installed together. No CP15/native-object
    # reads. Nonce reads only the command's existing context word.
    body = ('mrs r1,cpsr;movs r0,#0xe1' if kind == 'status' else
            'ldr r1,[r0,#4];movw r0,#0x7ce1')
    patches = [(ENTRY, asm(f'push {{r4,lr}};b.w {BODY:#x}', ENTRY)),
        (BODY, asm(f'{body};bl {LOG_WRAP:#x};b {RETURN:#x}', BODY)),
        (RETURN, asm('movs r0,#1;pop {r4,pc}', RETURN)),
        (STUB, asm(f'b.w {ENTRY:#x}', STUB))]
    assert [len(raw) for at, raw in patches] == [6, 12, 4, 4]
    for at, raw in patches[:-1]:
        assert any(a <= at and at + len(raw) <= a + n for a, n in gaps)
    # The exact inverse is checked in memory, but never exported as a job.
    target = bytearray(cp)
    inverse = []
    for at, raw in patches:
        inverse.append((at, cp[at-BASE:at-BASE+len(raw)]))
        target[at-BASE:at-BASE+len(raw)] = raw
    restored = bytearray(target)
    for at, raw in inverse:
        restored[at-BASE:at-BASE+len(raw)] = raw
    assert bytes(restored) == cp
    changed = {i for i, (a, b) in enumerate(zip(cp, target)) if a != b}
    allowed = {at-BASE+i for at, raw in patches for i in range(len(raw))}
    assert changed <= allowed
    assert read_tables(bytes(target)) == read_tables(cp)
    assert target[0x20124:0x20154] == cp[0x20124:0x20154]
    return patches, gaps, len(changed)


def emulator(cp, patches=()):
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    u.mem_map(BASE, (len(cp)+4095) & ~4095)
    u.mem_write(BASE, cp)
    for at, raw in patches:
        u.mem_write(at, raw)
    for at, n in ((STACK, 0x10000), (MEM, 0x20000), (STOP, 4096)):
        u.mem_map(at, n)
    return u


def diagnostic_cases(cp, patches, kind):
    u = emulator(cp, patches)
    seen, writes = [], []
    boundary = {LOG, ALLOC, STOP}
    def trace(cpu, at, size, _):
        seen.append(at)
        if at in boundary:
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, trace)
    u.hook_add(UC_HOOK_MEM_WRITE, lambda cpu, access, at, n, value, _: writes.append((at, n)))
    cases = []
    contexts = (0, 0x12345678) if kind == 'status' else (0, 0x12345678, 0xffffffff)
    for mode, flags, opaque in itertools.product((0x10, 0x13, 0x1f), (0, 0xa8000000), contexts):
        # User mode has a separately banked SP: set mode BEFORE SP/LR.
        u.reg_write(UC_ARM_REG_CPSR, flags | mode | 0x20)
        for reg, value in zip(PRESERVED, range(0x10101010, 0x10101018)):
            u.reg_write(reg, value)
        preserved = [u.reg_read(r) for r in PRESERVED]
        u.mem_write(MEM, b'\xa5'*128)
        u.mem_write(MEM+4, words(opaque))
        input_packet = bytes(u.mem_read(MEM, 128))
        u.mem_write(STACK, b'\xa5'*0x10000)
        for reg, value in ((UC_ARM_REG_R0, MEM), (UC_ARM_REG_R1, MEM+64),
                (UC_ARM_REG_R2, opaque), (UC_ARM_REG_R3, opaque ^ 0xffffffff),
                (UC_ARM_REG_SP, STACK+0x8000), (UC_ARM_REG_LR, STOP|1)):
            u.reg_write(reg, value)
        # MRS status reads do not expose Thumb execution-state bit T. The
        # emulator's full CPSR debug accessor includes it; do not equate them.
        expected_cpsr = u.reg_read(UC_ARM_REG_CPSR) & ~0x20
        expected_value = expected_cpsr if kind == 'status' else opaque
        seen.clear();writes.clear()
        boundary.clear();boundary.update((LOG, STOP))
        u.emu_start(STUB | 1, 0xffffffff, count=100)
        assert u.reg_read(UC_ARM_REG_PC) == LOG
        assert u.reg_read(UC_ARM_REG_R0) == 4 and u.reg_read(UC_ARM_REG_R1) == 16
        packet = u.reg_read(UC_ARM_REG_R2)
        assert bytes(u.mem_read(packet, 16)) == words(MARKERS[kind], expected_value, opaque, opaque ^ 0xffffffff)
        assert all(STACK <= at < at+n <= STACK+0x10000 for at, n in writes)
        assert bytes(u.mem_read(MEM, 128)) == input_packet
        assert seen.count(LOG) == 1
        visited = list(seen)
        # Real logger stack prefix and real ARM memcpy, up to its FIRST
        # allocator. Zero is the actual fourth argument, not an assertion
        # about all locking, scheduling or logging latency.
        seen.clear();writes.clear()
        boundary.clear();boundary.update((ALLOC, STOP))
        u.emu_start(LOG | 1, 0xffffffff, count=500)
        assert u.reg_read(UC_ARM_REG_PC) == ALLOC
        assert [u.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R2, UC_ARM_REG_R3)] == [0x8f013a, 49, 0]
        log_stack = u.reg_read(UC_ARM_REG_SP)
        assert bytes(u.mem_read(log_stack, 17)) == b'\x04'+words(MARKERS[kind], expected_value, opaque, opaque ^ 0xffffffff)
        assert all(STACK <= at < at+n <= STACK+0x10000 for at, n in writes)
        allocation_prefix_instructions = len(seen)-1
        # A DISTINCT post-logger slice, with explicit caller-clobbered inputs.
        # It is not a fake successful return from the unexecuted logger.
        for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3):
            u.reg_write(reg, 0xdeaddead)
        seen.clear();writes.clear()
        # Unwind the REAL logger and wrapper stacks, not repaired SP/r7.
        # The allocator, queue send and all logger operations are omitted.
        u.emu_start((BASE+0xa18d6c) | 1, 0xffffffff, count=20)
        assert u.reg_read(UC_ARM_REG_PC) == STOP and u.reg_read(UC_ARM_REG_R0) == 1
        assert u.reg_read(UC_ARM_REG_SP) == STACK+0x8000
        assert [u.reg_read(r) for r in PRESERVED] == preserved
        assert not writes
        cases.append(dict(mode=hex(mode), flags=hex(flags), opaque=hex(opaque),
            observation=kind, frozen_value=hex(expected_value), observation_instructions=len(visited)-1,
            logger_allocation_prefix_instructions=allocation_prefix_instructions,
            original_logger_completed=False, original_allocator_executed=False,
            original_first_allocation_bytes=49, original_first_allocation_fourth_argument=0,
            independent_return_slice=True,
            return_value=1, preserved_registers_and_stack=True))
    return cases


def look_cases(cp, patches):
    """Compare actual current helper/checksum/preview fragments, before/after."""
    baseline, modified = emulator(cp), emulator(cp, patches)
    rows = []
    root, env, state, output, work, owner = [MEM+n for n in (0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0)]
    for u in (baseline, modified):
        u.mem_write(owner, words(root, env))
        u.mem_write(output+12, words(work))
    for marker, flag, direct, available in itertools.product(
            (0, 248, 249, 250, 251, 252, 253, 254, 255), (0, 1, 2), (0, 1, 2), (0, 1)):
        observations = []
        for u in (baseline, modified):
            u.mem_write(root+1, bytes([flag]));u.mem_write(root+0x2e, bytes([marker]))
            u.mem_write(env+6, bytes([direct]));u.mem_write(work+0x6b0, words(MEM+0x9000 if available else 0))
            u.mem_write(state+0x180, b'\xa5'*16)
            for reg, value in ((UC_ARM_REG_R0, 7), (UC_ARM_REG_R1, 9), (UC_ARM_REG_R2, MEM+0xb000),
                    (UC_ARM_REG_R5, state), (UC_ARM_REG_R8, output), (UC_ARM_REG_R9, owner),
                    (UC_ARM_REG_R10, root), (UC_ARM_REG_SP, STACK+0x8000), (UC_ARM_REG_LR, STOP|1)):
                u.reg_write(reg, value)
            u.emu_start(HELPER|1, STOP, count=15000)
            assert u.reg_read(UC_ARM_REG_PC) == STOP and u.reg_read(UC_ARM_REG_SP) == STACK+0x8000
            observations.append(bytes(u.mem_read(state+0x180, 16)))
        assert observations[0] == observations[1]
        ptr, kind, transform = struct.unpack_from('<IBB', observations[1], 4)
        selected = 249 <= marker <= 254 and ((flag == 1 and direct <= 1) or
            (flag == 0 and (direct == 1 or (direct == 0 and available))))
        assert (ptr, kind, transform) == ((0x110020+(marker-249)*1215, 1, 2) if selected else (MEM+0xb000, 9, 7))
        rows.append(dict(marker=marker, flag=flag, direct=direct, available=available, identical=True))
    return rows


def preview_cases(cp, patches):
    baseline, modified = emulator(cp), emulator(cp, patches)
    boundaries = {BASE+n for n in (0x138832, 0x1354e8, 0x135516,
        0x13553e, 0x13556c, 0x1358cc, 0x135b98)} | {STOP}
    for u in (baseline, modified):
        def stop(cpu, at, size, _):
            if at in boundaries:
                cpu.emu_stop()
        u.hook_add(UC_HOOK_CODE, stop)
    root, env, state, output, work, owner = [MEM+n for n in (0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0)]
    records = []
    samples = [('gamma', HELPER+0x70, dict(marker=m)) for m in (0, 248, 249, 254, 255, 0xffffffff)]
    samples += [('preview-build', HELPER+0x90, dict(marker=m, r4=r, direct=d, available=a))
        for m, r, d, a in itertools.product((0, 249, 254, 255), (0, 1), (0, 1, 2), (0, 1))]
    samples += [('preview-retry', HELPER+0x7e, dict(r4=r, kind=k, available=a))
        for r, k, a in itertools.product((0, 1), (0, 0x101, 0x201, 0x202), (0, 1))]
    samples += [('switch-bridge', CHECKER+0x60, dict(marker=m, flag=f, kind=k))
        for m, f, k in itertools.product((0, 249, 254, 255), (0, 1), (0, 0x201))]
    samples += [('ordinary-4173', STUB+4, dict(mode=m)) for m in (0x10, 0x13, 0x1f)]
    regs = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, *PRESERVED,
            UC_ARM_REG_SP, UC_ARM_REG_CPSR)
    for kind, entry, config in samples:
        observed = []
        for u in (baseline, modified):
            u.reg_write(UC_ARM_REG_CPSR, config.get('mode', 0x13) | 0x20)
            u.mem_write(MEM, bytes(0x10000))
            u.mem_write(owner, words(root, env));u.mem_write(output+12, words(work))
            u.mem_write(root+1, bytes([config.get('flag', 0)]))
            u.mem_write(root+0x2e, bytes([config.get('marker', 0) & 255]))
            u.mem_write(env+6, bytes([config.get('direct', 0)]))
            u.mem_write(work+0x6b0, words(MEM+0x9000 if config.get('available') else 0))
            u.mem_write(state+0x188, struct.pack('<H', config.get('kind', 0)))
            u.mem_write(STACK+0x8038, words(MEM+0x6000))
            u.mem_write(MEM+0x6008, words(state))
            for reg, value in ((UC_ARM_REG_R0, config.get('marker', 0)), (UC_ARM_REG_R1, 0),
                    (UC_ARM_REG_R2, 0), (UC_ARM_REG_R3, 0), (UC_ARM_REG_R4, config.get('r4', 0)),
                    (UC_ARM_REG_R5, state), (UC_ARM_REG_R8, owner if kind == 'switch-bridge' else output),
                    (UC_ARM_REG_R9, owner), (UC_ARM_REG_R10, root),
                    (UC_ARM_REG_SP, STACK+0x8000), (UC_ARM_REG_LR, STOP|1)):
                u.reg_write(reg, value)
            u.emu_start(entry|1, 0xffffffff, count=100)
            pc = u.reg_read(UC_ARM_REG_PC)
            assert pc in boundaries
            observed.append((pc, [u.reg_read(r) for r in regs], bytes(u.mem_read(MEM, 0x10000))))
        assert observed[0] == observed[1], (kind, config)
        records.append(dict(kind=kind, input=config, native_continuation=hex(observed[0][0]), identical=True))
    return records


def mapping_cases(cp, patches):
    """Original mapper, unchanged headers; no real CP source or MMU access."""
    samples = {}
    for i, (at, raw) in enumerate(patches):
        samples[f'fragment-{i}-first'] = at
        samples[f'fragment-{i}-last'] = at+len(raw)-1
    native = layout(cp)
    cases = []
    for alternate in (0, 1):
        got = bootstrap_audit(cp, alternate, False, extra_samples=samples)
        maps = {name: got['samples'][name] for name in samples}
        for name, mapping in maps.items():
            expected = samples[name]
            if alternate:
                expected += 0xd0220000-native['text']['virtual']
            assert mapping['physical'] == expected and not mapping['xn']
        cases.append(dict(synthetic_alternate_text_source=alternate, mappings=maps,
            original_headers=True, MMU_activated=False, actual_source_bytes_read=False))
    return cases


def dispatcher_cases(cp, patches, kind):
    """Actual350-entry lookup and argument forwarding, not an assigned call."""
    baseline, modified = emulator(cp), emulator(cp, patches)
    control_pages = (0x186f000, 0x1a53000, 0x1b16000)
    boundary = {LOG, STOP}
    for u in (baseline, modified):
        for page in control_pages:
            u.mem_map(page, 4096)
        def stop(cpu, at, n, _):
            if at in boundary:
                cpu.emu_stop()
        u.hook_add(UC_HOOK_CODE, stop)
    cases = []
    for command, origin, context in itertools.product((0x4172, 0x4173),
            (0x80020002, 0x90030001), (0, 0x12345678, 0xffffffff)):
        snapshots = []
        packet = struct.pack('<BBHIII', 5, 0, command, context, 0, 0)
        frozen = None
        for index, u in enumerate((baseline, modified)):
            for page in control_pages:
                u.mem_write(page, bytes(4096))
            u.mem_write(MEM, packet)
            u.reg_write(UC_ARM_REG_CPSR, 0x33)
            for reg, value in ((UC_ARM_REG_R0, MEM), (UC_ARM_REG_R1, origin),
                    (UC_ARM_REG_SP, STACK+0x8000), (UC_ARM_REG_LR, STOP|1)):
                u.reg_write(reg, value)
            u.emu_start((BASE+0x254f70)|1, 0xffffffff, count=10000)
            if index and command == 0x4172:
                assert u.reg_read(UC_ARM_REG_PC) == LOG
                ptr = u.reg_read(UC_ARM_REG_R2)
                frozen = struct.unpack('<4I', bytes(u.mem_read(ptr, 16)))
                assert frozen[0] == MARKERS[kind]
                if kind == 'nonce':
                    assert frozen[1] == context
                assert frozen[2:] == (0x8db6a1 if origin == 0x80020002 else origin, 344)
                # Independent original logger epilogue, no allocation/send
                # result supplied. At this boundary its own frame is absent.
                u.emu_start((LOG_WRAP+0x10)|1, 0xffffffff, count=100)
            assert u.reg_read(UC_ARM_REG_PC) == STOP
            assert u.reg_read(UC_ARM_REG_R0) == 1
            assert u.reg_read(UC_ARM_REG_SP) == STACK+0x8000
            assert bytes(u.mem_read(MEM, len(packet))) == packet
            snapshots.append([bytes(u.mem_read(page, 4096)) for page in control_pages])
        assert snapshots[0] == snapshots[1]
        cases.append(dict(command=hex(command), synthetic_origin=hex(origin), context=hex(context),
            table_entries_searched=345 if command == 0x4172 else 346,
            frozen_words=[hex(v) for v in frozen] if frozen else None,
            original_dispatcher_bookkeeping_identical=True,
            logger_completed=False, independent_post_logger_slice=bool(frozen)))
    return cases


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--ap', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cp = a.cp.read_bytes()
    ap = a.ap.read_bytes()
    if hashlib.sha256(ap).hexdigest() != AP_SOURCE:
        raise ValueError('Unsupported complete current AP source')
    for at in (0x352d564, 0x352d56c):
        assert ap[at:at+8] == bytes.fromhex('3f0000b9c0035fd6')
    prototypes = []
    mappings = None
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    shape = None
    for kind in ('status', 'nonce'):
        patches, gaps, changed = fixture(cp, kind)
        diagnostic = diagnostic_cases(cp, patches, kind)
        looks = look_cases(cp, patches)
        previews = preview_cases(cp, patches)
        dispatcher = dispatcher_cases(cp, patches, kind)
        current_shape = [(at, len(raw)) for at, raw in patches]
        if mappings is None:
            mappings = mapping_cases(cp, patches)
            shape = current_shape
        else:
            assert current_shape == shape  # Same original mapper geometry.
        decoded = [i for at, raw in patches for i in md.disasm(raw, at)]
        assert sum(i.size for i in decoded) == sum(len(raw) for at, raw in patches)
        assert not any(i.mnemonic.startswith(('mrc', 'mcr', 'msr', 'v')) for i in decoded)
        prototypes.append(dict(kind=kind, marker=hex(MARKERS[kind]), changed_bytes=changed,
            diagnostic_cases=diagnostic, original_look_helper_comparisons=looks,
            original_preview_and_ordinary_dispatch_comparisons=previews,
            original_command_dispatcher_cases=dispatcher))
    report = dict(schema='OFFLINE_DORMANT_CP_DIAGNOSTIC/1', camera_io=False,
        cp_sha256=SOURCE, ap_sha256=AP_SOURCE, AP_setting_and_shooting_endpoints_still_stubs=True,
        current_helper_reconstructed_with_retry=True,
        helper_gaps_bytes=20, checker_gaps_bytes=10,
        gaps=[dict(virtual=hex(at), bytes=n) for at, n in gaps],
        stale_helper_only_padding_estimate_bytes=60,
        touched_envelope_bytes=sum(len(raw) for at, raw in patches),
        new_code_inside_existing_declared_text=True, segment_headers_unchanged=True,
        all_six_color_tables_identical=True, in_memory_inverse_exact=True,
        mutually_exclusive_emulator_prototypes=prototypes,
        original_mapper_cases=mappings,
        dormant_handler='4172', unmodified_shooting_handler='4173',
        firmware_candidate_written=False, install_manifest_written=False,
        limits=['Only exact current CP source is accepted; no stock first-install path',
            'Source-owned gaps are a fixture, not approval to modify ROM or generic zero-run ownership',
            'Status observes CPSR; nonce observes the synthetic command context; neither reads CP15/TTBR0/PTE/source pages',
            'Original logger stack/copy prefix executes, but allocation/send never execute; duration and delivery remain unverified',
            'Markers are not globally unique; nonce is synthetic, not proof of a real fresh reply',
            'Nonce assumes a complete context word; upstream rejection of short native commands is not audited',
            'No AP trigger, ROM/RAM installation, camera boot or hardware pre-capture test exists',
            'Two-page code ownership, startup, terminal-frame fence and actual capture remain unresolved'])
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2);f.write('\n')
    print('Dormant alternatives: '+', '.join(f"{r['kind']} {len(r['diagnostic_cases'])} boundary/return slices" for r in prototypes)+
        f'; each {len(looks)} helper / {len(previews)} preview+ordinary / {len(dispatcher)} dispatcher comparisons; 2 native mappings; no camera I/O or firmware output.')


if __name__ == '__main__':
    main()
