"""Link all target adapters and exercise state-bound native entry thunks.

The payload page exists ONLY in emulator RAM. No bootstrap hook, modified
firmware or camera installer is emitted. Original sends/posts/free/enqueues
remain stop boundaries; initialized state never implies physical capture.
"""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R8,
    UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R12, UC_ARM_REG_SP,
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR)
from audit_owner_binding import original_owner_fixture
from verify_entry_hooks import BASE, ROOT, MASTER, CONTROLLER, SEND, POST, REPLY, FREE, DISPATCH
from verify_offline import image_loader, codegen_flags, MEM, STACK, STOP
from verify_runtime_state import TAGS, BYTES

PAGE, MESSAGE, PARAMS = 0x10a000, MEM + 0x600, MEM + 0x1000
DEBUG, REFERENCE_END, ENQUEUE = 0x1a533a4, BASE + 0x3ad576, BASE + 0x407f1c
OS_ENQUEUE = BASE + 0x4e4b84


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
    if digest not in TAGS:
        raise ValueError('Unsupported complete CP source')
    tag, runtime = TAGS[digest]
    state = runtime + 16
    a.output.mkdir(parents=True, exist_ok=False)
    script = a.output / 'emulator-runtime-layout.ld'
    script.write_text('SECTIONS { . = 0x10000; .dynsym : { *(.dynsym) } '
        '.gnu.hash : { *(.gnu.hash) } .hash : { *(.hash) } .dynstr : { *(.dynstr) } '
        '.ARM.exidx : { *(.ARM.exidx*) } .dynamic : { *(.dynamic) } '
        '. = 0x10a000; .text : { *(.text*) } '
        '.rodata : { *(.rodata*) } precapture_payload_end = .; '
        '}\n', encoding='ascii')
    elf = a.output / 'thumb-runtime-entries.elf'
    source_names = ['cp_runtime.c', 'cp_runtime_entries.c', 'cp_entry_adapters.c',
        'cp_task_adapter.c', 'cp_owner_binding.c', 'cp_backend.c', 'cp_control_state.c',
        's1_trigger.c', 'capture_gate.c', 'cp_frame_gate_adapter.c', 'cp_bootstrap_mapping_guard.c',
        'cp_runtime_hooks.S', 'cp_retention_lease.c', 'cp_retention_callback.c']
    names = ('precapture_target_runtime_initialize', 'precapture_target_runtime_resolve',
        'precapture_hook_queue', 'precapture_hook_replay', 'precapture_hook_button',
        'precapture_hook_frame', 'precapture_hook_reference', 'precapture_runtime_retention')
    roots = (*names, 'precapture_target_low_unmap')
    command = [str(a.zig), 'cc', '-target', 'thumb-linux-gnueabi',
        *codegen_flags('thumb'), '-Oz', '-g', '-shared', '-fPIC', '-ffreestanding',
        '-flto', '-fvisibility=hidden', '-ffunction-sections', '-fdata-sections',
        '-Wl,--gc-sections,' + ','.join('-u,' + name for name in roots),
        '-fno-builtin', '-fno-stack-protector', '-fno-unwind-tables',
        '-fno-asynchronous-unwind-tables', '-nostdlib', '-Wl,--no-undefined,-Bsymbolic,-T,' + str(script),
        f'-DPRECAPTURE_RUNTIME_ADDRESS={runtime:#x}', f'-DPRECAPTURE_RUNTIME_SOURCE_TAG={tag:#x}',
        '-o', str(elf), *[str(Path(__file__).with_name(name)) for name in source_names]]
    built = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if built.returncode:
        raise RuntimeError(built.stderr[-3000:])
    with elf.open('rb') as stream:
        image = ELFFile(stream)
        payload_end = next(s['st_value'] for s in image.get_section_by_name('.symtab').iter_symbols()
                           if s.name == 'precapture_payload_end')
        assert payload_end <= PAGE + 4096, f'Full linked payload does not fit: {payload_end - PAGE} bytes'
        assert not any(s['sh_size'] for s in image.iter_sections() if s.name in ('.data', '.bss', '.got', '.got.plt'))
        sections = {s.name: s['sh_size'] for s in image.iter_sections() if s.name in ('.text', '.rodata')}
    u, symbols = image_loader(elf, 'thumb', names)
    # Do not overwrite the ELF's low page with the original CP prefix zeros.
    end = (BASE + len(cp) + 4095) & ~4095
    for start, stop in ((BASE, PAGE), (PAGE + 4096, end)):
        u.mem_map(start, stop - start)
        u.mem_write(start, cp[start - BASE:min(stop - BASE, len(cp))])
    u.mem_map(ROOT & ~4095, 0x2000)
    u.mem_map(MASTER & ~4095, 0x2000)
    u.mem_map(PARAMS, 0x2000)
    u.mem_map(0x1a44000, 0x2000)
    u.mem_map(0x1a3a000, 0x1000)
    fixture = original_owner_fixture(cp, ROOT)
    ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB)
    patch_sites = [(0x3ae6f4, 'bl', 'precapture_hook_queue', f'bl {DISPATCH:#x}'),
        (0xa18122, 'b.w', 'precapture_hook_replay', 'ldr.w r0,[r8]'),
        (0x3ad304, 'b.w', 'precapture_hook_button', 'ldrb.w r2,[r10,#0xf1]'),
        (0xa0612a, 'bl', 'precapture_hook_frame', f'bl {BASE + 0xa2f0fa:#x}'),
        (0x3ad55a, 'b.w', 'precapture_hook_reference', 'ldrb.w r0,[r0,#0xf1]')]
    for offset, opcode, symbol, original in patch_sites:
        at = BASE + offset
        assert cp[offset:offset + 4] == bytes(ks.asm(original, addr=at)[0])
        patch = bytes(ks.asm(f'{opcode} {symbols[symbol] & ~1:#x}', addr=at)[0])
        assert len(patch) == 4
        u.mem_write(at, patch)
    boundaries, stops = [], set()
    def trace(cpu, at, size, user):
        if at in stops:
            boundaries.append(dict(at=at, args=[cpu.reg_read(r) for r in
                (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)], executed=False))
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, trace)
    def run(start, boundaries_at, inputs=()):
        nonlocal stops
        stops = set(boundaries_at) | {STOP}
        boundaries.clear()
        for reg, value in inputs:
            u.reg_write(reg, value)
        u.emu_start(start, 0xffffffff, count=10000)
        assert len(boundaries) == 1 and u.reg_read(UC_ARM_REG_PC) == boundaries[0]['at']
        return boundaries[0]
    def setup(ready=True):
        u.mem_write(ROOT, fixture)
        u.mem_write(0x1a3aae0, owner_fixture)
        u.mem_write(0x1a45ca4, owner_binding)
        u.mem_write(MASTER, bytes(0xd64))
        u.mem_write(MASTER + 0x138, words(1))
        u.mem_write(MASTER + 0x700, words(1))
        u.mem_write(DEBUG, bytes(0x100))
        u.mem_write(runtime, bytes(BYTES))
        if ready:
            result = run(symbols[names[0]], (STOP,), [(UC_ARM_REG_R0, runtime),
                (UC_ARM_REG_R1, tag), (UC_ARM_REG_SP, STACK + 0x3000), (UC_ARM_REG_LR, STOP | 1)])
            assert result['args'][0] == 0
    # Original pure constructors supply the callback owner and actual queue
    # layout. They do not create an RTOS task or an image buffer in this test.
    run((BASE + 0xa05d8e) | 1, (), [(UC_ARM_REG_SP, STACK + 0x3000),
        (UC_ARM_REG_LR, STOP | 1)])
    run((BASE + 0xa09cce) | 1, (), [(UC_ARM_REG_SP, STACK + 0x3000),
        (UC_ARM_REG_LR, STOP | 1)])
    owner_fixture = bytes(u.mem_read(0x1a3aae0, 0x20))
    queue_fixture = bytes(u.mem_read(0x1a45c70, 0x34))
    # Original final binding stores the actual task pointer; stop before its
    # epilogue since the earlier clear is outside this explicit metadata slice.
    run((BASE + 0xa09ac2) | 1, (BASE + 0xa09acc,), [(UC_ARM_REG_R4, 0x1a3aae0)])
    owner_binding = bytes(u.mem_read(0x1a45ca4, 4))
    assert owner_binding == words(0x1a3aae0)
    def packet(raw, origin=0x90030001):
        u.mem_write(MESSAGE - 0x18, bytes([0xa5]) * (0x18 + 64))
        u.mem_write(MESSAGE - 12, words(origin, len(raw)))
        u.mem_write(MESSAGE, raw)
    def queue():
        sp = STACK + 0x2800
        u.mem_write(sp + 0x10, words(MESSAGE))
        return run((BASE + 0x3ae6ea) | 1, (FREE, DISPATCH, SEND, POST, REPLY, OS_ENQUEUE), [
            (UC_ARM_REG_R4, 0x900302d9), (UC_ARM_REG_R9, ROOT), (UC_ARM_REG_SP, sp)])
    cases = []
    for ready in (False, True):
        setup(ready)
        before = bytes(u.mem_read(runtime, BYTES))
        result = run(symbols['precapture_runtime_retention'], (BASE + 0x4e9f24,), [
            (UC_ARM_REG_R0, 1), (UC_ARM_REG_R1, 500),
            (UC_ARM_REG_SP, STACK + 0x3000), (UC_ARM_REG_LR, STOP | 1)])
        if ready:
            assert result['at'] == BASE + 0x4e9f24
            assert u.reg_read(UC_ARM_REG_R4) == 0x1a3aae0
        else:
            assert result['at'] == STOP and result['args'][0] == (-95 & 0xffffffff)
        assert bytes(u.mem_read(runtime, BYTES)) == before
        cases.append(dict(kind='retention-callback-native-task-query-boundary', ready=ready,
                          OS_task_query_executed=False, policy_or_ACK_executed=False))
    for offset in (0x14, 0x18):
        setup()
        u.mem_write(0x1a3aae0 + offset, words(0))
        before = bytes(u.mem_read(runtime, BYTES))
        result = run(symbols['precapture_runtime_retention'], (BASE + 0x4e9f24, POST), [
            (UC_ARM_REG_R0, 1), (UC_ARM_REG_R1, 500),
            (UC_ARM_REG_SP, STACK + 0x3000), (UC_ARM_REG_LR, STOP | 1)])
        assert result['at'] == STOP and result['args'][0] == (-95 & 0xffffffff)
        assert bytes(u.mem_read(runtime, BYTES)) == before
        cases.append(dict(kind='retention-callback-uninitialized-owner-refused', offset=offset,
                          OS_task_query_or_policy_or_ACK_executed=False))
    for current_id, mode, generation, duration, expected_status in (
            (0x87, 'configure', 1, 500, -1), (0x89, 'configure', 1, 500, -1),
            (0x88, 'configure', 1, 500, 0), (0x88, 'restore', 2, 0, 0),
            (0x88, 'busy', 1, 500, -16), (0x88, 'nonempty', 1, 500, -16),
            (0x88, 'lost-policy', 2, 0, -116), (0x88, 'stale', 1, 500, -116)):
        setup()
        u.mem_write(0x1a45c70, queue_fixture)
        if mode in ('restore', 'lost-policy'):
            u.mem_write(runtime + 80, words(1, 1, 7, 500))
            u.mem_write(0x1a45c70 + 20, words(0, 500 if mode == 'restore' else 999))
        elif mode == 'busy':
            u.mem_write(0x1a45c70 + 28, words(1))
        elif mode == 'nonempty':
            u.mem_write(0x1a45c70 + 12, words(1))
        elif mode == 'stale':
            u.mem_write(runtime + 80, words(2, 0, 0, 0))
        before = bytes(u.mem_read(runtime, BYTES))
        before_queue = bytes(u.mem_read(0x1a45c70, 0x34))
        result = run(symbols['precapture_runtime_retention'], (BASE + 0x4e9f24,), [
            (UC_ARM_REG_R0, generation), (UC_ARM_REG_R1, duration),
            (UC_ARM_REG_SP, STACK + 0x3000), (UC_ARM_REG_LR, STOP | 1)])
        assert result['at'] == BASE + 0x4e9f24
        observed_id = result['args'][0]
        assert u.reg_read(UC_ARM_REG_LR) == (BASE + 0xa3b60c) | 1
        # Explicit post-query slice with synthetic current-ID metadata, NOT
        # a mocked successful RTOS call or evidence of live owner admission.
        u.mem_write(observed_id, words(current_id))
        result = run((BASE + 0xa3b60c) | 1, (POST,))
        if current_id != 0x88:
            assert result['at'] == STOP and result['args'][0] == (-1 & 0xffffffff)
        else:
            assert result['at'] == POST
            owner, route, data, length = result['args']
            assert owner == 0x1a52b34 and route == 0x900302d9 and length == 32
            assert bytes(u.mem_read(data, length)) == words(0, 0x8240, generation,
                3, int(duration != 0), 0x50435231, expected_status & 0xffffffff, duration)
        assert bytes(u.mem_read(runtime, 80)) == before[:80]
        if expected_status < 0:
            assert bytes(u.mem_read(runtime, BYTES)) == before
            assert bytes(u.mem_read(0x1a45c70, 0x34)) == before_queue
        else:
            expected_queue = bytearray(before_queue)
            struct.pack_into('<2I', expected_queue, 20, *( (1, 7) if mode == 'restore' else (0, 500)))
            assert bytes(u.mem_read(0x1a45c70, 0x34)) == bytes(expected_queue)
            lease = words(2, 0, 0, 0) if mode == 'restore' else words(1, 0, 0, 500)
            assert bytes(u.mem_read(runtime + 80, 16)) == lease
        cases.append(dict(kind='retention-post-query-explicit-slice', task_id=current_id,
            mode=mode, status=expected_status, current_id_is_synthetic=True,
            OS_query_or_ACK_delivery_executed=False))
    for ready in (False, True):
        setup(ready)
        packet(words(1, 0x8205, 0, 0))
        assert queue()['at'] == DISPATCH
        cases.append(dict(kind='ordinary-native-dispatch', ready=ready))
        setup(ready)
        packet(words(0, 0x8240, 6, 1, 1, 0x50435231, 0, 0))
        assert queue()['at'] == FREE
        cases.append(dict(kind='missing-or-stale-private-event-consumed', ready=ready))
    setup(False)
    packet(bytes([5, 0, 0x73, 0x41]) + words(0x12345678, 1))
    assert queue()['at'] == FREE and bytes(u.mem_read(runtime, BYTES)) == bytes(BYTES)
    cases.append(dict(kind='unready-enable-rejected'))
    setup()
    packet(bytes([5, 0, 0x72, 0x41]) + words(0, 3, 250))
    assert queue()['at'] == FREE
    assert bytes(u.mem_read(state, 16)) == words(0, 3, 250, 0)
    cases.append(dict(kind='native-queue-setting-configured-disabled'))
    packet(bytes([5, 0, 0x73, 0x41]) + words(0x12345678, 1))
    result = queue()
    assert result['at'] == POST
    owner, route, data, length = result['args']
    assert owner == 0x1a52b34 and route == 0x900302d9 and length == 32
    assert bytes(u.mem_read(data, length)) == words(0, 0x8240, 1, 1, 1, 0x50435231, 0, 0)
    assert bytes(u.mem_read(state, 48)) == words(0, 3, 250, 1, 1, 0x4173, 0x12345678,
                                               0x90030001, 0, 1, 0, 0)
    cases.append(dict(kind='enable-reads-native-accessor-on-synthetic-prefix-before-post', executed=False))
    setup()
    u.mem_write(state, words(1))
    before = bytes(u.mem_read(runtime, BYTES))
    packet(bytes([5, 0, 0x72, 0x41]) + words(0, 3, 250))
    assert queue()['at'] == FREE and bytes(u.mem_read(runtime, BYTES)) == before
    cases.append(dict(kind='live-reconfigure-rejected'))
    setup()
    u.mem_write(state + 4, words(0, 0))
    before = bytes(u.mem_read(runtime, BYTES))
    packet(bytes([5, 0, 0x73, 0x41]) + words(0, 1))
    assert queue()['at'] == FREE and bytes(u.mem_read(runtime, BYTES)) == before
    cases.append(dict(kind='cannot-enable-routing-with-disabled-trigger'))
    for label, raw, origin in (
            ('invalid-private-flags', bytes([5, 1, 0x73, 0x41]) + words(0, 1), 0x90030001),
            ('invalid-private-length', bytes([5, 0, 0x73, 0x41]) + words(0), 0x90030001),
            ('invalid-enable-word', bytes([5, 0, 0x73, 0x41]) + words(0, 256), 0x90030001),
            ('invalid-setting-trigger', bytes([5, 0, 0x72, 0x41]) + words(0, 4, 500), 0x90030001),
            ('invalid-setting-duration', bytes([5, 0, 0x72, 0x41]) + words(0, 1, 1001), 0x90030001),
            ('filtered-reply-origin', bytes([5, 0, 0x73, 0x41]) + words(0, 1), 0x90bf0001)):
        setup()
        before = bytes(u.mem_read(runtime, BYTES))
        packet(raw, origin)
        assert queue()['at'] == FREE and bytes(u.mem_read(runtime, BYTES)) == before
        cases.append(dict(kind=label))
    setup()
    u.mem_write(runtime + 68, words(0))  # Corrupt immutable post pointer.
    before = bytes(u.mem_read(runtime, BYTES))
    packet(bytes([5, 0, 0x73, 0x41]) + words(0, 1))
    assert queue()['at'] == FREE and bytes(u.mem_read(runtime, BYTES)) == before
    cases.append(dict(kind='unrecognized-runtime-operation-rejected'))
    for phase, busy in ((1, 0), (2, 0), (2, 1), (4, 0), (4, 1)):
        setup()
        stage = {1: 1, 2: 4, 4: 6}[phase]
        u.mem_write(state, words(0, 1, 500, stage, 1, 0x4173, 0x12345678,
                                0x90030001, 0, 7, int(phase != 1), 0))
        u.mem_write(ROOT + 0x108 + 12, words(busy))
        event = words(0x8240, 7, phase, 1, 0x50435231, 0, 0)
        packet(words(0) + event)
        before = bytes(u.mem_read(runtime, BYTES))
        result = queue()
        if busy:
            assert result['at'] == FREE and bytes(u.mem_read(runtime, BYTES)) == before
            ring = ROOT + 0x398
            assert bytes(u.mem_read(ring + 4, 28)) == event
            assert bytes(u.mem_read(ring + 0x234, 8)) == words(0, 1)
        elif phase == 2:
            assert result['at'] == OS_ENQUEUE
            qid, data, length = result['args'][:3]
            assert qid == 0x38 and length == 28
            assert bytes(u.mem_read(data, length)) == words(0x805dcd, 0,
                symbols['precapture_runtime_retention'], 0, 0, 7, 500)
            expected = bytearray(before)
            struct.pack_into('<I', expected, 16 + 12, 5)
            assert bytes(u.mem_read(runtime, BYTES)) == bytes(expected)
        else:
            assert result['at'] == SEND
            data, length, route = result['args'][:3]
            assert length == 16 and route == 0x90040193
            assert bytes(u.mem_read(data, length)) == bytes([5, 0, 0x3d, 0x40]) + words(0, 4, int(phase == 1))
            if phase == 1:
                assert bytes(u.mem_read(runtime, BYTES)) == before
            else:
                assert bytes(u.mem_read(state, 16)) == words(1, 1, 500, 2)
                assert bytes(u.mem_read(runtime + 64, 16)) == before[64:80]
        cases.append(dict(kind='runtime-native-control-event', phase=phase, busy=busy,
                          native_send_executed=False))
    def waiting_owner_job():
        setup()
        u.mem_write(0x1a45c70, queue_fixture)
        u.mem_write(state, words(0, 1, 500, 4, 1, 0x4173, 0x12345678,
                                0x90030001, 0, 7, 1, 0))
        packet(words(0, 0x8240, 7, 2, 1, 0x50435231, 0, 0))

    waiting_owner_job()
    u.mem_write(ROOT + 0x108 + 12, words(1))
    assert queue()['at'] == FREE
    ring = ROOT + 0x398
    retained = words(0x8240, 7, 2, 1, 0x50435231, 0, 0)
    assert bytes(u.mem_read(ring + 4, 28)) == retained
    u.mem_write(ROOT + 0x108 + 12, words(0))
    result = run((BASE + 0xa180fc) | 1, (OS_ENQUEUE, FREE), [
        (UC_ARM_REG_R0, CONTROLLER), (UC_ARM_REG_SP, STACK + 0x3000),
        (UC_ARM_REG_LR, STOP | 1)])
    assert result['at'] == OS_ENQUEUE
    assert bytes(u.mem_read(ring + 0x234, 8)) == words(1, 1)
    assert bytes(u.mem_read(state, 16)) == words(0, 1, 500, 5)
    assert bytes(u.mem_read(result['args'][1], 28)) == words(0x805dcd, 0,
        symbols['precapture_runtime_retention'], 0, 0, 7, 500)
    cases.append(dict(kind='native-deferred-phase2-replay-requests-owner-job',
        IPC_stack_copy_not_freed=True, OS_enqueue_executed=False))

    for label, generation, desired, duration, phase, stage in (
            ('old-generation', 6, 1, 500, 3, 5), ('wrong-desired', 7, 0, 500, 3, 5),
            ('wrong-duration', 7, 1, 499, 3, 5), ('ready-before-owner', 7, 1, 0, 4, 5),
            ('duplicate-owner-ACK', 7, 1, 500, 3, 6)):
        waiting_owner_job()
        u.mem_write(state + 12, words(stage))
        packet(words(0, 0x8240, generation, phase, desired, 0x50435231, 0, duration))
        before = bytes(u.mem_read(runtime, BYTES))
        assert queue()['at'] == FREE and bytes(u.mem_read(runtime, BYTES)) == before
        cases.append(dict(kind='runtime-owner-ACK-mismatch-consumed', reason=label,
                          release_or_ACK_sent=False))
    for status in (-16, -22, -116, -5):
        waiting_owner_job()
        u.mem_write(state + 12, words(5))
        packet(words(0, 0x8240, 7, 3, 1, 0x50435231, status & 0xffffffff, 500))
        before = bytearray(u.mem_read(runtime, BYTES))
        assert queue()['at'] == FREE
        struct.pack_into('<I', before, 16 + 12, 3)
        struct.pack_into('<I', before, 16 + 44, 1)
        assert bytes(u.mem_read(runtime, BYTES)) == bytes(before)
        cases.append(dict(kind='runtime-owner-error-retains-cancellation', status=status,
                          release_or_success_ACK_sent=False))

    for label, address in [('owner-binding', 0x1a45ca4),
                           ('owner-task-id', 0x1a3aae0 + 0x14),
                           ('owner-queue-id', 0x1a3aae0 + 0x18)]:
        waiting_owner_job()
        u.mem_write(address, words(0))
        before = bytearray(u.mem_read(runtime, BYTES))
        assert queue()['at'] == FREE
        struct.pack_into('<I', before, 16 + 12, 3)
        struct.pack_into('<I', before, 16 + 44, 1)
        assert bytes(u.mem_read(runtime, BYTES)) == bytes(before)
        cases.append(dict(kind='retention-enqueue-owner-guard-fault', guard=label,
                          OS_enqueue_or_release_or_ACK_executed=False))
    waiting_owner_job()
    assert queue()['at'] == OS_ENQUEUE
    before = bytearray(u.mem_read(runtime, BYTES))
    # Explicit original failure-return epilogue. No OS send, logging or
    # successful result is manufactured; follow actual C failure cleanup.
    result = run((BASE + 0x407faa) | 1, (FREE,))
    assert result['at'] == FREE
    struct.pack_into('<I', before, 16 + 12, 3)
    struct.pack_into('<I', before, 16 + 44, 1)
    assert bytes(u.mem_read(runtime, BYTES)) == bytes(before)
    cases.append(dict(kind='retention-native-enqueue-failure-return-slice',
                      OS_enqueue_executed=False, cancellation_retained=True))

    # Linked phase2 -> real native28-byte job -> original post-receive thunk
    # -> callback -> original post-query comparison -> encoded phase3 -> S1
    # phase4 -> release boundary. All transport/query operations remain stops;
    # outputs become explicit inputs to separate slices, not fake OS success.
    waiting_owner_job()
    result = queue()
    assert result['at'] == OS_ENQUEUE
    job = bytes(u.mem_read(result['args'][1], 28))
    before_main = bytes(u.mem_read(state, 48))
    sp = STACK + 0x3000
    u.mem_write(sp + 4, job)
    result = run((BASE + 0x40807c) | 1, (BASE + 0x4e9f24,), [
        (UC_ARM_REG_R5, sp + 4), (UC_ARM_REG_R4, 0x1a3aae0),
        (UC_ARM_REG_SP, sp), (UC_ARM_REG_LR, STOP | 1)])
    assert result['at'] == BASE + 0x4e9f24
    assert bytes(u.mem_read(state, 48)) == before_main
    u.mem_write(result['args'][0], words(0x88))
    result = run((BASE + 0xa3b60c) | 1, (POST,))
    assert result['at'] == POST
    ack = bytes(u.mem_read(result['args'][2], 32))
    assert ack == words(0, 0x8240, 7, 3, 1, 0x50435231, 0, 500)
    assert bytes(u.mem_read(state, 48)) == before_main
    assert bytes(u.mem_read(runtime + 80, 16)) == words(7, 0, 0, 500)
    packet(ack)
    result = queue()
    assert result['at'] == POST
    ready = bytes(u.mem_read(result['args'][2], 32))
    assert ready == words(0, 0x8240, 7, 4, 1, 0x50435231, 0, 0)
    assert bytes(u.mem_read(state, 16)) == words(0, 1, 500, 6)
    assert bytes(u.mem_read(state + 40, 8)) == words(1, 0)
    packet(ready)
    result = queue()
    assert result['at'] == SEND
    data, length, route = result['args'][:3]
    assert bytes(u.mem_read(data, length)) == bytes([5, 0, 0x3d, 0x40]) + words(0, 4, 0)
    assert bytes(u.mem_read(state, 16)) == words(1, 1, 500, 2)
    assert bytes(u.mem_read(state + 40, 8)) == words(1, 0)
    cases.append(dict(kind='native-owner-job-and-matched-ACK-explicit-slices',
        OS_send_receive_query_release_executed=False, sensor_or_pixels_executed=False))
    for desired, requested, pressed, command in ((1, 1, 0, 0x4039),
            (1, 0, 1, 0x4038), (0, 1, 1, 0x4039)):
        setup()
        u.mem_write(state, words(0, 1, 500, 6, desired, 0x4173, 0x12345678,
                                0x90030001, requested, 7, 1, 0))
        u.mem_write(CONTROLLER + 0x24, words(2 if pressed else 0))
        packet(words(0, 0x8240, 7, 4, desired, 0x50435231, 0, 0))
        before = bytes(u.mem_read(runtime, BYTES))
        result = queue()
        assert result['at'] == SEND
        data, length, route = result['args'][:3]
        assert length == 16 and route == 0x90040193
        assert bytes(u.mem_read(data, length)) == bytes([5, 0]) + struct.pack('<H', command) + words(0, 13, 0)
        assert bytes(u.mem_read(runtime, BYTES)) == before
        cases.append(dict(kind='runtime-pending-button-reconciliation', command=command))
    for requested, desired in ((0, 0), (0, 1), (1, 0), (1, 1)):
        setup()
        u.mem_write(state, words(0, 1, 500, 1, desired, 0x4173, 0x12345678,
                                0x90030001, requested, 7, 1, 0))
        packet(words(0, 0x8240, 7, 99, desired, 0x50435231, 0, 0))
        before = bytearray(u.mem_read(runtime, BYTES))
        result = queue()
        assert result['at'] == FREE  # original free is a boundary, not executed
        struct.pack_into('<I', before, 16 + 12, 3)
        struct.pack_into('<I', before, 16 + 44, 1)
        assert bytes(u.mem_read(runtime, BYTES)) == bytes(before)
        cases.append(dict(kind='runtime-fault-retains-cancellation', requested=requested,
                          desired=desired, release_or_ACK_sent=False))
    for ready, event, expected in ((False, 0x8240, BASE + 0xa1814e),
                                   (True, 0x8205, BASE + 0xa18126)):
        setup(ready)
        u.mem_write(MESSAGE, words(event, 6, 1, 1, 0x50435231, 0, 0))
        flags = 0xa8000030
        result = run(symbols['precapture_hook_replay'], (expected,), [(UC_ARM_REG_R8, CONTROLLER),
            (UC_ARM_REG_R1, MESSAGE), (UC_ARM_REG_SP, STACK + 0x3000),
            (UC_ARM_REG_LR, STOP | 1),
            (UC_ARM_REG_CPSR, (u.reg_read(UC_ARM_REG_CPSR) & ~0xf8000000) | (flags & 0xf8000000))])
        assert result['at'] == expected and u.reg_read(UC_ARM_REG_CPSR) & 0xf8000000 == flags & 0xf8000000
        cases.append(dict(kind='runtime-replay', ready=ready, event=hex(event)))
    for ready, enabled, requested, pressed, expected_command in (
            (False, 0, 0, 1, None), (True, 0, 0, 1, None),
            (True, 1, 0, 1, 0x4038), (True, 1, 1, 0, 0x4039)):
        setup(ready)
        if ready:
            u.mem_write(state, words(enabled))
            u.mem_write(state + 32, words(requested))
        u.mem_write(CONTROLLER + 0x24, words(0 if pressed else 2))
        u.mem_write(MESSAGE, words(0x8205, 0, 0, pressed, 1, 0, 0))
        result = run((BASE + 0x3ad1ba) | 1, (SEND, BASE + 0x3ad5ee), [
            (UC_ARM_REG_R4, MESSAGE), (UC_ARM_REG_R5, CONTROLLER),
            (UC_ARM_REG_R9, 0x40002), (UC_ARM_REG_SP, STACK + 0x3000)])
        assert result['at'] == (SEND if expected_command else BASE + 0x3ad5ee)
        if expected_command:
            data, length, route = result['args'][:3]
            assert length == 16 and route == 0x90040193
            assert bytes(u.mem_read(data, length)) == bytes([5, 0]) + struct.pack('<H', expected_command) + words(0, 13, 0)
        cases.append(dict(kind='runtime-native-button', ready=ready, command=expected_command))
    for ready, enabled, generation, subtype, expected_flag in (
            (False, 0, 0, 13, 0), (True, 0, 0, 13, 0),
            (True, 1, 0, 1, 0), (True, 1, 0, 13, 1),
            (True, 0, 7, 13, 1), (True, 0, 7, 1, 0)):
        setup(ready)
        if ready:
            u.mem_write(state, words(enabled))
            u.mem_write(state + 36, words(generation))
        u.mem_write(PARAMS, bytes(0x1000))
        u.mem_write(PARAMS + 0x160, words(1))
        u.mem_write(PARAMS + 0xd9c, bytes([subtype]))
        result = run((BASE + 0xa06126) | 1, (BASE + 0xa06132,), [
            (UC_ARM_REG_R4, PARAMS), (UC_ARM_REG_SP, STACK + 0x3000)])
        assert u.mem_read(PARAMS + 0xd97, 1)[0] == expected_flag
        cases.append(dict(kind='runtime-native-frame-producer', ready=ready, subtype=subtype,
                          generation=generation, flag=expected_flag))
    reference_cases = [(False, 0, 0, 0, 0, 1, False), (True, 0, 0, 0, 0, 1, False),
        (True, 1, 0, 0, 0, 1, True), (True, 1, 0, 0, 1, 1, False),
        (True, 1, 1, 0, 1, 0, True), (True, 1, 1, 0, 0, 1, False)]
    for stage in (1, 4, 5, 6):
        reference_cases.extend([(True, 1, 0, stage, 0, 1, False),
                                (True, 1, 0, stage, 1, 0, True)])
    for ready, enabled, fault, stage, active, pressed, enqueue in reference_cases:
        setup(ready)
        if ready:
            u.mem_write(state, words(enabled))
            u.mem_write(state + 44, words(fault))
            u.mem_write(state + 12, words(stage))
        u.mem_write(ROOT + 0x108 + 0x2d, bytes([active]))
        result = run((BASE + 0x3ad54c) | 1, (ENQUEUE, REFERENCE_END), [
            (UC_ARM_REG_R5, CONTROLLER), (UC_ARM_REG_R6, pressed),
            (UC_ARM_REG_R8, 0x12345678), (UC_ARM_REG_R9, 1),
            (UC_ARM_REG_R10, 0x89abcdef), (UC_ARM_REG_SP, STACK + 0x3000)])
        assert result['at'] == (ENQUEUE if enqueue else REFERENCE_END)
        if enqueue:
            descriptor = result['args'][1]
            assert struct.unpack('<I', u.mem_read(descriptor + 8, 4))[0] == (0x474fad if pressed else 0x475015)
        cases.append(dict(kind='runtime-native-recording-reference', ready=ready,
                          fault=fault, stage=stage, pressed=pressed, enqueue_boundary=enqueue))
    report = dict(schema='OFFLINE_LINKED_RUNTIME_ENTRIES/1', cp_sha256=digest,
        camera_io=False, firmware_candidate_written=False, runtime=hex(runtime), state=hex(state),
        payload_page=hex(PAGE), payload_bytes=payload_end - PAGE, payload_sections=sections,
        LTO=True, explicit_retained_roots=roots,
        cases=cases, native_OS_operations_executed=False,
        limits=['The full code page is supplied by the emulator, not a verified camera loader',
            'No bootstrap hook, executable mapping, source readiness or real startup initialization exists',
            'Native send/post/free/enqueue stop before execution; no successful transport is mocked',
            'Settings are accepted only while fully disabled; enable requires an active configured trigger',
            'Live RAM, sensor acquisition, bounded RAW retention, saving and restoration remain untested'])
    (a.output / 'runtime-entries.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'All target entry modules linked: {payload_end - PAGE} bytes; {len(cases)} native boundary cases passed.')


if __name__ == '__main__':
    main()
