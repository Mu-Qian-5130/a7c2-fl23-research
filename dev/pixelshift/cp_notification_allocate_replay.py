"""Native capture-stop notification allocation on synthetic registered pools.

Runs the original allocator, endpoint lookup, free-list split/removal, locks,
IRQ/dispatch guards and notification construction without supplying a buffer
pointer or API result. Stops BEFORE AP send, exhausted-pool backpressure or WFE.
Pool/endpoint/OS configuration and the guard's timer register are fixtures;
this does not execute boot registration, AP transport or physical capture.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_capture_stop_replay import profile as stop_profile
from cp_native_mutex_replay import profile as kernel_profile, setup as setup_kernel
from cp_sequence_replay import machine
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_ARM
    data, stop = stop_profile(directory)
    _, kernel = kernel_profile(directory)
    thumb, arm = Cs(CS_ARCH_ARM, CS_MODE_THUMB), Cs(CS_ARCH_ARM, CS_MODE_ARM)

    def code(at, size, decoder=thumb):
        return list(decoder.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def call(at, decoder=thumb):
        rows = code(at, 4, decoder)
        if len(rows) != 1 or rows[0].mnemonic not in ('bl', 'blx', 'b.w'):
            raise ValueError('Native notification-allocation call changed')
        return int(rows[0].op_str.lstrip('#'), 0)

    def literal(at, size, register, decoder=thumb):
        values = [v for r, v in literals(code(at, size, decoder)) if r == register]
        if len(values) != 1:
            raise ValueError('Native notification-allocation binding is not unique')
        return values[0]

    allocator = stop['allocator']
    impl = call(allocator + 0x38)
    lookup, pool = call(impl + 0x16), call(impl + 0xb4)
    lock, unlock = call(pool + 0x12), call(pool + 0x160)
    context, mask, dispatch = [call(lock + n) for n in (6, 0x12, 0x1e)]
    disable, irq_enter = call(lock + 0x2a), call(lock + 0x34)
    irq_leave, veneer = call(unlock + 0x14), call(unlock + 0x24)
    if code(veneer, 2)[0].op_str != 'pc':
        raise ValueError('Native dispatch-enable veneer changed')
    enable = struct.unpack_from('<I', data, veneer + 8 - 0x108000)[0]
    timer_get, timer_set = call(irq_enter + 0xa0, arm), call(irq_enter + 0xb4, arm)
    irq_disable = call(irq_enter + 0x34, arm)
    irq_enable = call(irq_enter + 0xec, arm)
    table = literal(lookup + 0xa6, 16, 'r0')
    timer_root = literal(timer_get, 16, 'r0', arm)
    timer_depth = literal(irq_enter + 0x84, 16, 'r5', arm)
    timer_stamp = literal(irq_enter + 0xa4, 8, 'r1', arm)
    if literal(disable, 0x14, 'ip', arm) != kernel['context_table']:
        raise ValueError('Native allocation/OS context tables differ')
    regions = [(stop['entry'], stop['entry'] + 0xb0), (stop['getter'], stop['getter'] + 10),
               (stop['kind'], stop['kind'] + 4), (stop['header'], stop['header'] + 6),
               (allocator, allocator + 0xcc), (impl, impl + 0x1a4),
               (lookup, lookup + 0x26), (lookup + 0xa6, lookup + 0xde),
               (lookup + 0x290, lookup + 0x29a), (pool, pool + 0x170),
               (lock, lock + 0x5c), (unlock, unlock + 0x28),
               (context, context + 0x34), (mask, mask + 12), (dispatch, dispatch + 0x48),
               (disable, disable + 0x144), (enable, enable + 0x188),
               (veneer, veneer + 8), (irq_enter, irq_enter + 0x140),
               (irq_leave, irq_leave + 0x138), (irq_disable, irq_disable + 0x54),
               (irq_enable, irq_enable + 0x6c), (timer_get, timer_get + 0x20),
               (timer_set, timer_set + 0x34)] + kernel['regions']
    return data, dict(stop=stop, kernel=kernel, impl=impl, pool=pool, lock=lock, unlock=unlock,
                      table=table, timer_root=timer_root, timer_depth=timer_depth,
                      timer_stamp=timer_stamp, retry_boundary=allocator + 0x70,
                      lock_wait=lock + 0x3a, regions=regions)


def replay(directory, *, block_size=256, busy=False):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    s, k = p['stop'], p['kernel']
    cpu = machine(data, [])
    cpu.mem_map(0x1700000, 0x440000)
    cpu.mem_map(0x34000000, 0x4000)
    os = setup_kernel(cpu, directory)
    record, tree1, tree2, tree3 = 0x34000100, 0x34000200, 0x34000240, 0x34000280
    timer, pool, block = 0x34000300, 0x34000500, 0x34001000
    endpoint, stack = 0x845, 0x3001f000
    # Already-registered endpoint and free-pool fixtures, not allocator returns.
    bindings = [(p['table'] + 0x110 + 4 * ((endpoint >> 9) & 63), tree1),
                (tree1 + 4 * ((endpoint >> 6) & 7), tree2),
                (tree2 + 4 * ((endpoint >> 3) & 7), tree3), (tree3 + 4 * (endpoint & 7), record),
                (record + 0x18, pool), (pool, 0x80000000 if busy else 0),
                (pool + 8, block if block_size else 0), (pool + 0x10, block_size),
                (pool + 0x18, block_size), (pool + 0x1c, block_size),
                (p['timer_root'] + 8, timer)]
    for at, value in bindings:
        cpu.mem_write(at, struct.pack('<I', value))
    cpu.mem_write(block - 4, b'\x6b' * 4 + bytes(block_size) + b'\x6b' * 4)
    if block_size:
        cpu.mem_write(block + 4, struct.pack('<I', block_size))
    cpu.mem_write(s['kind_state'], bytes(1))
    cpu.mem_write(s['end_marker'], b'\x6b')
    endpoints_before = [(at, bytes(cpu.mem_read(at, 4))) for at, _ in bindings[:5]]
    boundary, allocator_status, payload_pointer = None, None, None
    lock_entries, unlock_entries = 0, 0

    def hook(uc, at, size, unused):
        nonlocal boundary, allocator_status, payload_pointer, lock_entries, unlock_entries
        if at == p['lock']:
            lock_entries += 1
        if at == p['unlock']:
            unlock_entries += 1
        if at == s['allocation_boundary'] + 4:
            allocator_status = uc.reg_read(arm.UC_ARM_REG_R0)
            payload_pointer = struct.unpack('<I', cpu.mem_read(uc.reg_read(arm.UC_ARM_REG_SP) + 4, 4))[0]
        if at in (p['retry_boundary'], p['lock_wait']):
            boundary = 'allocation_backpressure' if at == p['retry_boundary'] else 'pool_lock_wait'
            uc.emu_stop()
            return
        if not any(lo <= at and at + size <= hi for lo, hi in p['regions']):
            raise ValueError('Native notification allocation reached an unexecuted dependency: ' + hex(at))

    def write_hook(uc, access, at, size, value, unused):
        allowed = [(stack - 4096, 4096), (s['flag'], 1), (record + 1, 3), (pool, 32),
                   (block, block_size), (timer + 4, 4), (p['timer_depth'], 4), (p['timer_stamp'], 4),
                   (os['core'] + 12, 4), (os['core'] + 0x58, 4), (k['guard'], 4)]
        if not any(lo <= at and at + size <= lo + length for lo, length in allowed):
            raise ValueError('Native notification allocation wrote unrelated state: ' + hex(at))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.emu_start(s['entry'] | 1, s['send_boundary'], count=20000)
    completed = not busy and block_size >= 128
    if boundary != (None if completed else 'pool_lock_wait' if busy else 'allocation_backpressure'):
        raise ValueError('Native allocator did not preserve its exhaustion/contention boundary')
    payload = None
    remaining = struct.unpack('<I', cpu.mem_read(pool + 0x18, 4))[0]
    head = struct.unpack('<I', cpu.mem_read(pool + 8, 4))[0]
    allocated_count = struct.unpack('<H', cpu.mem_read(record + 2, 2))[0]
    if completed:
        expected_pointer = block + block_size - 128 + 0x40
        payload = bytes(cpu.mem_read(payload_pointer, 16))
        if (cpu.reg_read(arm.UC_ARM_REG_PC) != s['send_boundary'] or allocator_status != 0
                or payload_pointer != expected_pointer or remaining != block_size - 128
                or head != (block if block_size > 128 else 0) or allocated_count != 1
                or payload != struct.pack('<4I', 0x920162, 0, 0, 0)
                or bytes(cpu.mem_read(payload_pointer - 12, 4)) != struct.pack('<I', 0x90030001)
                or bytes(cpu.mem_read(payload_pointer + 16, 4)) != struct.pack('<I', 0x77777777)
                or bytes(cpu.mem_read(pool, 4)) != bytes(4)
                or bytes(cpu.mem_read(p['timer_depth'], 4)) != bytes(4)
                or bytes(cpu.mem_read(k['guard'], 4)) != bytes(4)
                # Native enable clears +58, but with no pending +54 work it
                # leaves +0c zero; this is not a host-restored OS context.
                or bytes(cpu.mem_read(os['core'] + 12, 4)) != bytes(4)
                or bytes(cpu.mem_read(os['core'] + 0x58, 4)) != bytes(4)
                or cpu.reg_read(arm.UC_ARM_REG_CPSR) & 0x80
                or cpu.reg_read(arm.UC_ARM_REG_SP) != stack - 24
                or (lock_entries, unlock_entries) != (1, 1)):
            raise ValueError('Native allocator/payload/free-list ownership differs')
    elif allocated_count != 0 or remaining != block_size or payload_pointer is not None:
        raise ValueError('Uncompleted allocation produced a payload or consumed a block')
    if (bytes(cpu.mem_read(block - 4, 4)) != b'\x6b' * 4
            or bytes(cpu.mem_read(block + block_size, 4)) != b'\x6b' * 4
            or any(bytes(cpu.mem_read(at, 4)) != before for at, before in endpoints_before)
            or cpu.mem_read(s['flag'], 1)[0] != 1 or cpu.mem_read(s['end_marker'], 1)[0] != 0x6b):
        raise ValueError('Native allocation changed endpoint binding or unrelated state')
    return dict(boundary=boundary or 'before_ap_send', original_allocator_return=allocator_status,
                native_allocated_payload_offset=None if payload_pointer is None else payload_pointer - block,
                pool_remaining_bytes=remaining, pool_head_retained=bool(head), allocated_buffers=allocated_count,
                lock_entries=lock_entries, unlock_entries=unlock_entries,
                original_payload=None if payload is None else payload.hex(),
                allocation_api_executed=True, payload_constructed=completed,
                host_supplied_buffer_pointer_or_api_result=False,
                post_allocation_buffer_fixture_used=False,
                native_core_bookkeeping_word=struct.unpack('<I', cpu.mem_read(os['core'] + 12, 4))[0],
                native_dispatch_disable_word=struct.unpack('<I', cpu.mem_read(os['core'] + 0x58, 4))[0],
                synthetic_endpoint_pool_os_and_timer=True,
                endpoint_boot_registration_executed=False, ap_send_executed=False,
                completion_callback_executed=False, physical_ready_verified=False)


def compare(c2, reference):
    inputs = [dict(block_size=n) for n in (256, 128, 0)] + [dict(block_size=256, busy=True)]
    rows = []
    for args in inputs:
        a, b = replay(c2, **args), replay(reference, **args)
        if a != b:
            raise ValueError('C2/A7CR native notification allocation differs')
        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-notification-allocation/1', paired_cases=len(rows), cases=rows,
                camera_io=False, installable=False, physical_shift_verified=False)


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
    print(json.dumps({k: report[k] for k in ('paired_cases', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
