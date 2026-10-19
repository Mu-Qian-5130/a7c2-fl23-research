"""Native UIPC/PCIe dispatch and enqueue slices on synthetic memory ONLY.

Only own-section ABS64 relocations are applied. Calls with ELF call/jump
relocations stop BEFORE execution, including locks/copy/cache/queue APIs.
Independent slices are explicit metadata inputs, not successful API mocks.
No real kernel loading, ioctl, CP command, worker or firmware output exists.
"""
import argparse
import hashlib
import io
import itertools
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
    UC_ARM64_REG_X3, UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X21,
    UC_ARM64_REG_X29, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC)

UIPC_SHA = 'f0eb3a32a9d339066600e012aa3e91de31419c173e3fe5c1cc44aa9188763095'
PCIE_SHA = '26f376a9025f0b56b5ede7ebabdbf5dd8a5235d6627abe2abfd1430e2af578bc'
MEM, STACK, STOP = 0x30000000, 0x40000000, 0x50000000


def q(v):
    return struct.pack('<Q', v)


def w(v):
    return struct.pack('<I', v)


class Module:
    def __init__(self, u, raw, digest, base):
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Unsupported original kernel module')
        self.u = u
        e = self.elf = ELFFile(io.BytesIO(raw))
        assert e['e_type'] == 'ET_REL' and e['e_machine'] == 'EM_AARCH64'
        symbols = e.get_section_by_name('.symtab')
        self.names, self.bases, self.calls, self.rel = {}, {}, {}, {}
        for i, sec in enumerate(e.iter_sections()):
            if not sec['sh_flags'] & 2 or not sec['sh_size']:
                continue
            address = base + len(self.bases)*0x100000
            assert sec['sh_size'] <= 0x100000
            self.names[sec.name] = address
            self.bases[i] = address
            u.mem_map(address, (sec['sh_size']+4095) & ~4095)
            if sec['sh_type'] != 'SHT_NOBITS':
                u.mem_write(address, sec.data())
        for sec in e.iter_sections():
            if sec['sh_type'] != 'SHT_RELA' or sec['sh_info'] not in self.bases:
                continue
            for r in sec.iter_relocations():
                sym = symbols.get_symbol(r['r_info_sym'])
                at = self.bases[sec['sh_info']] + r['r_offset']
                self.rel[at] = dict(type=r['r_info_type'], name=sym.name,
                    section=sym['st_shndx'], addend=r['r_addend'])
                if r['r_info_type'] == 257 and sym['st_shndx'] in self.bases:
                    u.mem_write(at, q(self.bases[sym['st_shndx']] + sym['st_value'] + r['r_addend']))
                elif r['r_info_type'] in (282, 283):
                    self.calls[at] = sym.name
        self.functions = {sym.name: (self.bases[sym['st_shndx']] + sym['st_value'], sym['st_size'])
            for sym in symbols.iter_symbols() if sym['st_info']['type'] == 'STT_FUNC'
            and sym['st_shndx'] in self.bases}

    def at(self, section, offset):
        return self.names[section] + offset


def audit(uipc_raw, pcie_raw):
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    a = Module(u, uipc_raw, UIPC_SHA, 0x10000000)
    b = Module(u, pcie_raw, PCIE_SHA, 0x18000000)
    for at, size in ((MEM, 0x40000), (STACK, 0x10000), (STOP, 4096)):
        u.mem_map(at, size)
    A, B = lambda x: a.at('.text', x), lambda x: b.at('.text', x)
    calls = dict(a.calls)
    calls.update(b.calls)
    boundaries, seen = {STOP}, []
    def hook(cpu, at, size, _):
        if at in calls or at in boundaries:
            seen.append(dict(at=at, call=calls.get(at), args=[cpu.reg_read(r) for r in
                (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3)]))
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, hook)
    def run(entry, targets=(), inputs=()):
        boundaries.clear();boundaries.update((STOP, *targets));seen.clear()
        for reg, value in inputs:
            u.reg_write(reg, value & ((1 << 64)-1))
        u.emu_start(entry, 0xffffffffffffffff, count=2000)
        assert len(seen) == 1 and u.reg_read(UC_ARM64_REG_PC) == seen[0]['at']
        return seen[0]
    def call(entry, args, targets=()):
        return run(entry, targets, [*zip((UC_ARM64_REG_X0, UC_ARM64_REG_X1,
            UC_ARM64_REG_X2, UC_ARM64_REG_X3), args),
            (UC_ARM64_REG_SP, STACK+0x8000), (UC_ARM64_REG_LR, STOP)])
    def readq(at):
        return struct.unpack('<Q', bytes(u.mem_read(at, 8)))[0]
    def readw(at):
        return struct.unpack('<I', bytes(u.mem_read(at, 4)))[0]

    # Relocations bind descriptor -> ops -> ioctl-like entry and its dispatch
    # table. Do NOT identify the unrelated18d0 read path as an ioctl.
    assert a.rel[a.at('.data', 0x1b0)]['addend'] == 0x600
    assert readq(a.at('.data', 0x610)) == A(0x4d8)
    assert readq(a.at('.rodata', 0x3c0)) == A(0x13c0)
    assert a.calls[A(0x530)] == '__arch_copy_from_user'
    assert a.calls[A(0x13f4)] == 'osal_snd_msg'
    owner, task, user_base, native_base = MEM+0x1000, MEM+0x3000, 0x60000000, MEM+0x20000
    checks = []
    for command, mapped in itertools.product((0, 4, 16, 17, 0x40000004), (0, 1)):
        u.mem_write(owner+0x30, q(user_base if mapped else 0))
        got = run(A(0x538), (A(0x510), A(0x554)), [
            (UC_ARM64_REG_X19, command | 0x80000000), (UC_ARM64_REG_X20, owner)])
        valid = command <= 16 and (mapped or command == 16)
        assert got['at'] == A(0x554 if valid else 0x510)
        checks.append(dict(kind='post-user-copy-command-map-check', command=command,
            synthetic_map=bool(mapped), reaches_owner_check=bool(valid), copy_executed=False))
    for matched in (False, True):
        u.mem_write(owner+0x28, q(0x11223344))
        u.mem_write(task+0x2d8, q(0x11223344 if matched else 0x55667788))
        u.mem_write(STACK+0x8020, w(0x90030001) + bytes(4) + q(user_base+0x100))
        got = run(A(0x558), (A(0x590), A(0x13c0)), [
            (UC_ARM64_REG_X0, task), (UC_ARM64_REG_X20, owner),
            (UC_ARM64_REG_X19, 4), (UC_ARM64_REG_X29, STACK+0x8000)])
        assert got['at'] == A(0x13c0 if matched else 0x590)
        if matched:
            assert got['args'][:3] == [0x90030001, user_base+0x100, owner]
        checks.append(dict(kind='post-current-task-read-owner-check', matched=matched,
            task_field='0x2d8 opaque owner identity', native_MRS_executed=False))
    mapped_literal = readq(A(0x1400))
    u.mem_write(mapped_literal+0x40, q(native_base))
    for delta in (-1, 0, 0x100, 0x1fffff, 0x200000):
        u.mem_write(owner+0x30, q(user_base))
        got = call(A(0x13c0), (0x90030001, user_base+delta, owner))
        valid = 0 <= delta <= 0x1fffff
        if valid:
            assert got['at'] == A(0x13f4)
            assert got['args'][:2] == [0x90030001, native_base+delta]
        else:
            assert got['at'] == STOP and got['args'][0] & 0xffffffff == 0xfffffc00
        checks.append(dict(kind='native-shared-pointer-range', synthetic_offset=delta,
            accepted=valid, kernel_send_executed=False,
            entire_message_extent_validated=False))

    # Actual PCIe registration output, then an independent pure UIPC binding.
    assert b.calls[B(0x3c94)] == 'osal_reg_public'
    got = call(B(0x3c88), ())
    assert got['at'] == B(0x3c94)
    public = got['args'][0]
    assert public == b.at('.data', 0xb8) and readq(public) == B(0x3c70)
    public_root = readq(A(0x3bd8))
    slot = public_root+0x458
    binding = []
    for existing, request, expected in ((0, 0, -1024), (0, public, 0), (public, public, -1018)):
        u.mem_write(slot, q(existing))
        got = call(A(0x3ba8), (request,))
        assert got['at'] == STOP and got['args'][0] & 0xffffffff == expected & 0xffffffff
        assert readq(slot) == (public if expected == 0 else existing)
        binding.append(dict(existing=bool(existing), request=bool(request), result=expected))
    got = call(A(0x3bf8), (0x90030001, MEM+0x100), (B(0x3c70),))
    assert got['at'] == B(0x3c70) and got['args'][:2] == [0x90030001, MEM+0x100]
    got = run(B(0x3c70))
    assert got['at'] == B(0x34f8) and got['call'] == 'pcieif_debug_measure_start'
    assert u.reg_read(UC_ARM64_REG_X20) == 0
    callback = dict(actual_registration_output=hex(public), native_UIPC_slot=hex(slot),
        callback_text_offset='0x3c70', native_async_argument=0,
        reaches_common_sender='0x34c0', debug_measure_or_sender_services_executed=False,
        registration_cases=binding)

    # Name check: wait_done sets/wakes. It is NOT a transfer-completion wait.
    assert b.functions['pcieif_wait_done'] == (B(0x4b90), 68)
    wake_calls = {at-B(0): name for at, name in b.calls.items() if B(0x4b90) <= at < B(0x4bd4)}
    assert wake_calls == {0x4ba8: '_raw_spin_lock_irqsave', 0x4bb8: 'wake_up_process',
        0x4bc4: '_raw_spin_unlock_irqrestore'}
    wake = MEM+0x5000
    wake_cases = []
    for task_pointer in (0, MEM+0x8000):
        u.mem_write(wake, bytes(32));u.mem_write(wake+8, q(task_pointer))
        got = call(B(0x4b90), (wake,))
        assert got['at'] == B(0x4ba8) and readw(wake+16) == 1
        got = run(B(0x4bac), inputs=[(UC_ARM64_REG_X0, 0xa5)])
        assert got['at'] == B(0x4bb8 if task_pointer else 0x4bc4)
        if task_pointer:
            assert got['args'][0] == task_pointer
            got = run(B(0x4bbc))
            assert got['at'] == B(0x4bc4)
        assert got['args'][:2] == [wake, 0xa5]
        wake_cases.append(dict(synthetic_task_present=bool(task_pointer), flag_set_before_lock=True,
            wake_and_locks_executed=False, scheduler_wait_executed=False))

    # Separate sender slices. Neither a cache result nor queue acceptance is
    # supplied. Post-void-call register inputs are retained native callee-saved
    # metadata, and queue threshold values are explicitly synthetic states.
    queue_cases = []
    metadata = MEM+0x10000
    for channel, synchronous in itertools.product((0, 1), (0, 1)):
        u.mem_write(metadata, b'\xa5'*64);u.mem_write(metadata+8, w(16))
        context = MEM+0x9000 if synchronous else 0
        got = call(B(0x2c38), (channel, context, metadata))
        assert got['at'] == B(0x2c9c) and got['call'] == '__udif_cache_ctrl'
        assert got['args'][:3] == [metadata, 80, 1]
        assert readq(metadata+24) == context
        got = run(B(0x2ca0))
        assert got['at'] == B(0x2cb0) and got['call'] == 'pcieif_add_node'
        owner_base = u.reg_read(UC_ARM64_REG_X19)
        assert got['args'][:2] == [owner_base+0x50, metadata]
        # The sender's original frame survives in this emulator. Each return
        # slice gets that explicit frame, not a fabricated add_node success.
        frame_sp = u.reg_read(UC_ARM64_REG_SP)
        frame = bytes(u.mem_read(frame_sp, 64))
        for threshold in (0, 60, 61):
            u.mem_write(frame_sp, frame)
            u.reg_write(UC_ARM64_REG_SP, frame_sp)
            u.reg_write(UC_ARM64_REG_X19, owner_base)
            u.reg_write(UC_ARM64_REG_X20, 0)
            u.mem_write(owner_base+0x40, w(threshold))
            got = run(B(0x2cb4))
            notified = threshold <= 60
            assert got['at'] == (B(0x2ce0) if notified else STOP)
            if notified:
                assert got['call'] == 'pcieif_wait_done'
            else:
                assert got['args'][0] == 0
            queue_cases.append(dict(channel=channel, synthetic_sync_pointer=bool(synchronous),
                synthetic_owner_field40=threshold, reaches_wake_helper=notified,
                cache_queue_or_wake_executed=False))
    got = call(B(0x2c38), (0, 0, 0))
    assert got['at'] == STOP and got['args'][0] == 2

    # Actual first-attempt allocator geometry. Its pool API stays a boundary.
    # Negative remote routes reserve64 bytes before the returned payload.
    queue_table = readq(A(0x3518))
    queue = MEM+0x7000
    out = MEM+0x6000
    block = native_base+0x2000
    allocations = []
    for wait_flag in (0, 1):
        u.mem_write(queue, bytes(64));u.mem_write(queue_table+0x18, q(queue))
        u.mem_write(out, b'\xa5'*16)
        got = call(A(0x3248), (0x90030001, out, 16, wait_flag))
        assert got['at'] == A(0x32e8) and got['call'] == 'vpool_alloc'
        assert got['args'][1:3] == [128, wait_flag]
        assert readw(got['args'][3]) == 0
        # DISTINCT post-pool slice, using an explicit synthetic block. This
        # does not supply a successful result to a mocked vpool_alloc.
        u.mem_write(block-32, b'\xa5'*192)
        run_result = run(A(0x32f0), inputs=[(UC_ARM64_REG_X0, block)])
        assert run_result['at'] == STOP and run_result['args'][0] == 0
        assert readq(out) == block+64
        assert bytes(u.mem_read(out+8, 8)) == b'\xa5'*8
        assert bytes(u.mem_read(block-32, 32)) == b'\xa5'*32
        assert bytes(u.mem_read(block+128, 32)) == b'\xa5'*32
        assert bytes(u.mem_read(block+64, 16)) == b'\xa5'*16
        assert readw(block+56) == 16 and readw(block+80) == 0x77777777
        assert bytes(u.mem_read(block+48, 4)) == bytes.fromhex('02410100')
        assert struct.unpack('<H', bytes(u.mem_read(queue+2, 2)))[0] == 1
        allocations.append(dict(remote_route='0x90030001', payload_bytes=16,
            pool_bytes=128, reserved_prefix_bytes=64, pool_wait_flag=wait_flag,
            real_pool_allocation=False, independent_header_construction=True,
            guard_bytes_unchanged=True))

    # The pool's wait flag is BOOLEAN, not milliseconds. With no fitting
    # block, any nonzero value enters wait-node construction/current-task
    # handling and can later schedule; zero goes straight to unlock/return.
    pool = MEM+0xa000
    wait_cases = []
    assert a.calls[A(0x6aa4)] == 'schedule'
    for wait_flag in (0, 1, 2, 0xffffffff):
        u.mem_write(pool, bytes(0x40));u.mem_write(pool+0x20, w(4096))
        got = call(A(0x6998), (pool, 128, wait_flag, 0))
        assert got['at'] == A(0x69c4) and got['call'] == 'osal_lock'
        got = run(A(0x69c8), (A(0x6a58),))
        assert got['at'] == (A(0x6a58) if wait_flag else A(0x6b64))
        if wait_flag:
            assert readq(pool+0x28) != 0
        else:
            assert got['call'] == 'osal_unlock' and readq(pool+0x28) == 0
        wait_cases.append(dict(explicit_wait_flag=wait_flag, synthetic_no_fitting_block=True,
            enters_native_wait_node=bool(wait_flag), waits_or_kernel_MRS_executed=False))

    # Public allocator first tries0, then only a nonzero caller flag enables
    # another allocation attempt with waiting. The OOM wakeup/API is omitted;
    # this is a distinct original post-OOM branch with retained arguments.
    allocator_wrapper = []
    for flag in (0, 1, 2):
        got = call(A(0x44c0), (0x90030001, out, 16, flag), (A(0x3248),))
        assert got['at'] == A(0x3248) and got['args'] == [0x90030001, out, 16, 0]
        got = run(A(0x4598), (A(0x459c), A(0x3248)))
        assert got['at'] == (A(0x3248) if flag else A(0x459c))
        if flag:
            assert got['args'] == [0x90030001, out, 16, flag]
        allocator_wrapper.append(dict(caller_wait_flag=flag, first_try_wait_flag=0,
            post_OOM_retry_wait_flag=flag if flag else None,
            original_allocation_OOM_or_current_task_read_executed=False))

    # Native receive-completion processing separates asynchronous free from
    # waking a synchronous caller. This is not proof of any CP operation or
    # real completion arrival. Translation/dequeue/free/wake never execute.
    completions = []
    assert b.calls[B(0x23e8)] == 'osal_free_msg'
    assert b.calls[B(0x2290)] == 'pcieif_sleep_wakeup'
    for sync, status in itertools.product((False, True), (0, 5)):
        payload = metadata+64
        header = bytearray(b'\xa5'*64)
        struct.pack_into('<2I', header, 0xc, 0x90030001, 0x80020002)
        struct.pack_into('<Q', header, 0x18, MEM+0x9000 if sync else 0)
        u.mem_write(metadata, bytes(header));u.mem_write(STACK+0x8074, w(status))
        got = run(B(0x2268), inputs=[(UC_ARM64_REG_X0, payload),
            (UC_ARM64_REG_X29, STACK+0x8000)])
        assert got['at'] == B(0x2290 if sync else 0x23e8)
        if sync:
            assert got['args'][0] == MEM+0x9000
        else:
            assert got['args'][:2] == [0x90030001, payload]
        struct.pack_into('<I', header, 0x14, status)
        assert bytes(u.mem_read(metadata, 64)) == bytes(header)
        completions.append(dict(synthetic_sync_context=sync, synthetic_completion_status=status,
            boundary=got['call'], native_message_freed=False, CP_completion_observed=False))
    return dict(ioctl_and_pointer_cases=checks, callback=callback, wake_cases=wake_cases,
        enqueue_slices=queue_cases, null_metadata_returns=2,
        remote_message_allocation_slices=allocations, boolean_pool_wait_cases=wait_cases,
        allocator_wrapper_slices=allocator_wrapper, independent_completion_slices=completions)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uipc-kernel', type=Path, required=True)
    p.add_argument('--pcie', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = audit(a.uipc_kernel.read_bytes(), a.pcie.read_bytes())
    report = dict(schema='OFFLINE_NATIVE_MESSAGE_ROUTE/1', camera_io=False,
        uipc_kernel_sha256=UIPC_SHA, pcie_sha256=PCIE_SHA, **result,
        limits=['Only own-section ABS64 relocations are applied; this is not a general kernel loader',
            'Current-task fields, mappings, origins, queues and metadata are synthetic inputs',
            'Access checks and pointer conversion do not allocate a valid native message or prove full extent',
            'No kernel MRS/current-task read, user copy, spin lock, cache, queue, wake, ioctl or transfer executes',
            'Independent post-void-call slices do not imply actual cache/queue success',
            'wait_done wakes a worker; it is neither a blocking completion wait nor proof of remote delivery',
            'Allocation geometry and independent completion slices are not real pool/transport ownership proof',
            'Pool wait flag is boolean, not a millisecond timeout; nonzero can enter schedule with no timer here',
            'Locks, allocation failure/retry ownership and safe live AP triggering remain unresolved',
            'No worker, CP command, firmware patch or physical pre-capture acceptance is provided'])
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2);f.write('\n')
    print(f"Native message route: {len(result['ioctl_and_pointer_cases'])} ioctl/pointer cases, 3 registration, 2 wake, 12 enqueue, 2 allocation, 4 boolean-wait, 3 allocator-wrapper, 4 completion slices. No kernel/camera operations.")


if __name__ == '__main__':
    main()
