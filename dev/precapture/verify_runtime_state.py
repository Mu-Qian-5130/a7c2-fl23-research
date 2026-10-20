"""Compile/init/check exact-source runtime state; never install firmware.

Explicit emulator RAM at the proposed data tail is not ownership approval.
Original full startup clear executes separately. No boot hook, task, hardware
or live publication runs. Source build tags are not live image verification.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from unicorn import UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP,
                               UC_ARM_REG_LR, UC_ARM_REG_PC)
from support.cp_mapping import PINNED, layout, emulator, invoke, translation, MAPPER
from support.build import compile_shared
from support.elf import image_loader
from support.memory import STACK, STOP
from audit_bootstrap_memory import startup_clear

MAGIC, BYTES = 0x31524350, 96
TAGS = {
    'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428': (0xf5a47758, 0x1208b80),
    '3d6656b933fc681282f920364e5f3b788117c4345a89ec6b9df9862c5563f8a1': (0x3d6656b9, 0x1209fa0),
}


def words(*v):
    return struct.pack('<' + 'I' * len(v), *v)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--zig', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cp = a.cp.read_bytes()
    digest = hashlib.sha256(cp).hexdigest()
    if digest not in TAGS or digest not in PINNED:
        raise ValueError('Unsupported complete runtime source')
    tag, region = TAGS[digest]
    native = layout(cp)
    assert region == (native['data']['virtual'] + native['data']['length'] + 7) & ~7
    assert region + BYTES <= native['bss']['virtual']
    file_at = region - 0x108000
    assert cp[file_at:file_at + BYTES] == bytes(BYTES)
    a.output.mkdir(parents=True, exist_ok=False)
    elf = a.output / 'thumb-runtime-state.elf'
    compile_shared(a.zig, 'thumb', elf,
        [Path(__file__).with_name('cp_runtime.c')])
    wanted = ('precapture_target_runtime_initialize', 'precapture_target_runtime_resolve')
    u, symbols = image_loader(elf, 'thumb', wanted)
    # The right sentinel crosses into BSS on the current image. Map that
    # explicit emulator guard page too; it is never runtime-state storage.
    u.mem_map(region & ~4095, 8192)
    guard_begin, guard_bytes = region - 32, BYTES + 64
    writes, reads, barriers, order = [], [], [], []
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    def memwrite(cpu, access, address, size, value, user):
        if region & ~4095 <= address < (region & ~4095) + 8192:
            writes.append((address, size, value))
            order.append(('write', address, size, value))
    def memread(cpu, access, address, size, value, user):
        # Exclude ELF code/literal-pool reads; retain alleged runtime/unknown
        # object reads. A truly unmapped dereference also fails execution.
        if ((region & ~4095) <= address < (region & ~4095) + 8192 or
                address >= 0x50000000):
            reads.append((address, size))
    def code(cpu, at, size, user):
        raw = bytes(cpu.mem_read(at, size))
        ins = next(md.disasm(raw, at), None)
        if ins and ins.mnemonic == 'dmb':
            barriers.append(at)
            order.append(('dmb', at))
    u.hook_add(UC_HOOK_MEM_WRITE, memwrite)
    u.hook_add(UC_HOOK_MEM_READ, memread)
    u.hook_add(UC_HOOK_CODE, code)
    def call(name, pointer=region, source_tag=tag):
        writes.clear();reads.clear();barriers.clear();order.clear()
        for reg, value in ((UC_ARM_REG_R0, pointer), (UC_ARM_REG_R1, source_tag),
                (UC_ARM_REG_SP, STACK + 0x3000), (UC_ARM_REG_LR, STOP | 1)):
            u.reg_write(reg, value)
        u.emu_start(symbols[name], STOP, count=4000)
        assert u.reg_read(UC_ARM_REG_PC) == STOP
        return u.reg_read(UC_ARM_REG_R0) & 0xffffffff
    initialize, resolve = wanted
    u.mem_write(guard_begin, bytes([0xa5]) * guard_bytes)
    u.mem_write(region, bytes(BYTES))
    assert call(resolve) == 0 and not writes
    assert call(initialize) == 0
    expected = words(MAGIC, 3, tag, BYTES,
        0, 1, 500, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0x4b3c49, 0x4b5fe5, 0xb1feaf, 0x8daa15, 0, 0, 0, 0)
    assert len(expected) == BYTES
    assert bytes(u.mem_read(region, BYTES)) == expected
    assert all(region <= at and at + size <= region + BYTES for at, size, value in writes)
    assert writes[-1] == (region, 4, MAGIC)
    publish = order.index(('write', region, 4, MAGIC))
    assert any(event[0] == 'dmb' for event in order[:publish])
    assert bytes(u.mem_read(guard_begin, 32)) == bytes([0xa5]) * 32
    assert bytes(u.mem_read(region + BYTES, 32)) == bytes([0xa5]) * 32
    assert call(resolve) == region and not writes and barriers
    # Reinitialization must not reset an active/pending/faulted transaction.
    active = bytearray(expected)
    active[16:64] = words(1, 3, 1000, 3, 1, 0x4173, 0x12345678, 0x90030001,
                          1, 42, 1, 1)
    active[80:96] = words(41, 1, 9, 500)
    u.mem_write(region, bytes(active))
    assert call(initialize) == 1 and not writes
    assert bytes(u.mem_read(region, BYTES)) == bytes(active)
    corruptions = []
    for offset in (0, 4, 8, 12, 64, 68, 72, 76):
        changed = bytearray(expected)
        changed[offset] ^= 1
        u.mem_write(region, bytes(changed))
        assert call(resolve) == 0 and not writes
        assert call(initialize) == (-16 & 0xffffffff) and not writes
        assert bytes(u.mem_read(region, BYTES)) == bytes(changed)
        corruptions.append(offset)
    # Partially initialized and stale data cannot be taken over even if its
    # publication word is still zero; startup must fail without any write.
    for offset in (4, 16, 48, 95):
        changed = bytearray(BYTES);changed[offset] = 1
        u.mem_write(region, bytes(changed))
        assert call(initialize) == (-16 & 0xffffffff) and not writes
    for old_abi, old_bytes in ((1, 80), (2, 96)):
        legacy = bytearray(expected)
        legacy[4:8] = words(old_abi)
        legacy[12:16] = words(old_bytes)
        u.mem_write(region, bytes(legacy))
        assert call(resolve) == 0 and not writes
        assert call(initialize) == (-16 & 0xffffffff) and not writes
        assert bytes(u.mem_read(region, BYTES)) == bytes(legacy)
    # Invalid pointers/tags reject before reading the alleged runtime storage.
    rejected = []
    for pointer, source_tag in ((0, tag), (0x50000000, tag), (region + 4, tag),
                                (region, 0), (region, tag ^ 1)):
        assert call(resolve, pointer, source_tag) == 0 and not reads and not writes
        assert call(initialize, pointer, source_tag) == (-95 & 0xffffffff) and not reads and not writes
        rejected.append(dict(pointer=hex(pointer), source_tag=hex(source_tag)))
    clear = startup_clear(cp, BYTES)
    assert int(clear['proposed_state'], 16) == region
    assert clear['proposed_state_bytes_preserved'] == BYTES
    # Extend only the declared data-copy extent inside existing padding. The
    # original mapper must leave every page-table descriptor unchanged.
    projected = {name: dict(segment) for name, segment in native.items()}
    projected['data']['length'] = region + BYTES - projected['data']['virtual']
    baseline, extended = emulator(cp), emulator(cp)
    for name in native:
        invoke(baseline, MAPPER, native[name])
        invoke(extended, MAPPER, projected[name])
    assert bytes(baseline.mem_read(0x30000000, 0x60000)) == bytes(extended.mem_read(0x30000000, 0x60000))
    for at in (region, region + BYTES - 1):
        assert translation(baseline, at) == translation(extended, at)
        assert translation(extended, at)['physical'] == at and translation(extended, at)['xn']
    report = dict(schema='OFFLINE_CP_RUNTIME_PUBLICATION/1', cp_sha256=digest,
        camera_io=False, firmware_candidate_written=False,
        source_tag_is_host_build_selection_not_live_verification=True,
        proposed_region=hex(region), bytes=BYTES,
        remaining_data_tail_bytes=native['bss']['virtual'] - region - BYTES,
        exact_native_operation_pointers_verified=True, disabled_initial_state_verified=True,
        retention_lease_initialized_bytes=16, legacy_ABI1_ABI2_refused_without_mutation=True,
        immutable_corruptions_rejected=corruptions, partial_initializations_rejected=4,
        invalid_pointer_or_tag_rejections=rejected,
        publication_last_with_release_barrier=True, resolver_has_acquire_barrier=True,
        reinitialization_preserves_live_transaction=True, original_startup_clear=clear,
        data_copy_extent_extension_bytes=projected['data']['length'] - native['data']['length'],
        original_mapper_all_descriptors_unchanged_by_data_extent_extension=True,
        limits=['No startup hook or native data-copy extension is installed',
            'Data-tail geometry and synthetic state do not prove runtime ownership',
            'Code mapping/loading, source freshness, task delivery and hardware remain unbound',
            'DMB instructions execute in the emulator; actual multicore cache behavior is not modeled',
            'No pre-trigger pixel retention, file save or restoration is tested'])
    (a.output / 'runtime-state.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('Runtime init/publication, immutable guards, no-reset reentry and native startup clear checked.')


if __name__ == '__main__':
    main()
