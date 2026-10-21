"""Native PowerOffDetect local query: listener registration, reply and release.

Runs the original initialization prefix, listener allocation/registration,
PowerOffDetect request, synchronous local callback and buffer release. Optional
cache inputs pass through the original cache-copy slice; they are synthetic,
not hardware acknowledgements. Stops before diagnostics or the additional
message route selected by particular cached values. Endpoint-tree/pool/OS and
guard-timer setup remain fixtures; full boot, later callback and capture do not run.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_poweroff_allocate_replay import profile as allocation_profile
from cp_native_mutex_replay import setup as setup_kernel
from cp_sequence_replay import machine
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_ARM
    data, allocation = allocation_profile(directory)
    s = allocation['stop']
    target = s['entry'] == 0x475630
    md, arm = Cs(CS_ARCH_ARM, CS_MODE_THUMB), Cs(CS_ARCH_ARM, CS_MODE_ARM)

    def code(at, size, decoder=md):
        return list(decoder.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def call(at, decoder=md):
        rows = code(at, 4, decoder)
        if len(rows) != 1 or rows[0].mnemonic not in ('bl', 'blx', 'b.w'):
            raise ValueError('Native local-query call boundary changed')
        return int(rows[0].op_str.lstrip('#'), 0)

    def literal(at, size, register, decoder=md):
        values = [v for r, v in literals(code(at, size, decoder)) if r == register]
        if len(values) != 1:
            raise ValueError('Native local-query binding is not unique')
        return values[0]

    initialize = 0xc0dc50 if target else 0xc0daaa
    registrar = call(initialize + 0x2a)
    callback = literal(initialize + 0xa, 0x26, 'r2') & ~1
    output = literal(initialize + 0xa, 0x26, 'r1')
    endpoint = literal(initialize + 0xa, 0x26, 'r4') - 0xbb
    if endpoint != 0x92a20845 or callback != (0xc0dd1a if target else 0xc0db74):
        raise ValueError('Native initialization does not bind the actual845 query receiver')
    cache = literal(callback + 0x12, 8, 'r1') + 0xe8
    if literal(initialize + 0x2e, 0x10, 'r0') + 0xe8 != cache:
        raise ValueError('Native initializer/query receiver do not share the cache')
    small_alloc = call(registrar + 0x36)
    small_pool = literal(small_alloc + 0xa, 16, 'r6')
    live_listeners = literal(registrar + 0x46, 0x1c, 'r1') + 8
    wrapper = literal(registrar + 0x74, 8, 'r1') & ~1
    send_thunk = call(s['send_boundary'])
    send = call(send_thunk + 4)
    get_task = call(send + 0x162)
    task_base = literal(get_task + 0x58, 12, 'r2', arm)
    free = call(s['entry'] + 0xb6)
    free_impl = call(free + 0x8e)
    pool_free = call(free_impl + 0x58)
    producer = 0x596e30 if target else 0x597048
    if literal(producer + 4, 12, 'r1') + 0xe8 != cache:
        raise ValueError('Native cache-copy slice does not bind the queried cache')
    extra_message = call(s['entry'] + 0xd6)
    regions = allocation['regions'] + [
        (initialize, initialize + 0x48), (registrar, registrar + 0x10c),
        (small_alloc, small_alloc + 0x11c), (wrapper, wrapper + 0x2c),
        (send_thunk, send_thunk + 8), (send, send + 0x238), (get_task, get_task + 0x9c),
        (callback, callback + 0x28), (free, free + 0x98), (free_impl, free_impl + 0x60),
        (pool_free, pool_free + 0xf8), (producer, producer + 0x18),
        (s['entry'] + 0xb0, s['entry'] + 0xdc)]
    return data, dict(allocation=allocation, initialize=initialize, registrar=registrar,
                      output=output, endpoint=endpoint, callback=callback, cache=cache,
                      small_pool=small_pool, live_listeners=live_listeners,
                      wrapper=wrapper, send=send, get_task=get_task, task_base=task_base,
                      free=free, producer=producer, extra_message=extra_message, regions=regions)


def replay(directory, *, cache_words=None, descriptor_available=True):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    a, s = p['allocation'], p['allocation']['stop']
    cpu = machine(data, [])
    cpu.mem_map(0x1700000, 0x440000)
    cpu.mem_map(0x34000000, 0x5000)
    os = setup_kernel(cpu, directory)
    record, tree1, tree2, tree3 = 0x34000100, 0x34000200, 0x34000240, 0x34000280
    timer, lock, pool, listener_block, block = 0x34000300, 0x34000400, 0x34000500, 0x34000700, 0x34001000
    stack, client_stack, producer_input = 0x3001f000, 0x3001d000, 0x34003000
    endpoint = p['endpoint'] & 0x7fff
    bindings = [(a['table'] + 0x110 + 4 * ((endpoint >> 9) & 63), tree1),
                (tree1 + 4 * ((endpoint >> 6) & 7), tree2),
                (tree2 + 4 * ((endpoint >> 3) & 7), tree3), (tree3 + 4 * (endpoint & 7), record),
                (record + 0x18, pool), (record + 0x1c, lock),
                (pool + 8, block), (pool + 0x10, 256), (pool + 0x18, 256), (pool + 0x1c, 256),
                (block + 4, 256), (a['timer_root'] + 8, timer),
                (p['small_pool'] + 8, listener_block if descriptor_available else 0),
                (p['small_pool'] + 0x18, 64 if descriptor_available else 0),
                (p['small_pool'] + 0x1c, 64 if descriptor_available else 0),
                (p['task_base'], os['task'])]
    for at, value in bindings:
        cpu.mem_write(at, struct.pack('<I', value))
    cpu.mem_write(s['kind_state'], bytes(1))
    cpu.mem_write(s['end_marker'], b'\x6b')
    cpu.mem_write(block - 4, b'\x6b' * 4)
    cpu.mem_write(block + 256, b'\x6b' * 4)
    cpu.mem_write(listener_block - 4, b'\x6b' * 4)
    cpu.mem_write(listener_block + 64, b'\x6b' * 4)
    binding_snapshots = [(at, bytes(cpu.mem_read(at, 4))) for at, _ in bindings[:6]]
    phase, boundary, register_status = 'register', None, None
    send_status, free_status, request_pointer = None, None, None
    requests, replies, route_entries = [], [], []
    callback_calls, release_calls = 0, 0

    def hook(uc, at, size, unused):
        nonlocal boundary, register_status, send_status, free_status, request_pointer, callback_calls, release_calls
        if phase == 'register' and at == p['initialize'] + 0x2e:
            register_status = uc.reg_read(arm.UC_ARM_REG_R0)
        if phase == 'query' and at == s['send_boundary']:
            request_pointer = uc.reg_read(arm.UC_ARM_REG_R1)
            requests.append(bytes(uc.mem_read(request_pointer, 16)).hex())
        if phase == 'query' and at == p['send'] + 0x90:
            route_entries.append('native_local_endpoint')
        if at == p['callback']:
            callback_calls += 1
            if uc.reg_read(arm.UC_ARM_REG_R0) != request_pointer or uc.reg_read(arm.UC_ARM_REG_R1) != 0:
                raise ValueError('Native local-query wrapper changed payload or registered context')
        if phase == 'query' and at == s['send_boundary'] + 4:
            value = uc.reg_read(arm.UC_ARM_REG_R0)
            send_status = value if value < 0x80000000 else value - 0x100000000
            replies.append(bytes(uc.mem_read(request_pointer, 16)).hex())
        if at == p['free']:
            release_calls += 1
        if phase == 'query' and at in (s['entry'] + 0xb6 + 4, s['entry'] + 0x7e + 4):
            free_status = uc.reg_read(arm.UC_ARM_REG_R0)
        if phase == 'query' and at in (p['extra_message'], s['entry'] + 0x84):
            boundary = 'before_additional_poweroff_message' if at == p['extra_message'] else 'before_diagnostics'
            uc.emu_stop()
            return
        if not any(lo <= at and at + size <= hi for lo, hi in p['regions']):
            raise ValueError('Native local PowerOffDetect query reached an unexecuted dependency: ' + hex(at))

    def write_hook(uc, access, at, size, value, unused):
        allowed = [(stack - 4096, 4096), (client_stack - 4096, 4096), (s['flag'], 1),
                   (record, 32), (lock, 4), (pool, 32), (block, 256), (listener_block, 64),
                   (p['small_pool'], 32), (p['live_listeners'], 4), (p['output'], 4), (p['cache'], 16),
                   (timer + 4, 4), (a['timer_depth'], 4), (a['timer_stamp'], 4),
                   (os['core'] + 12, 4), (os['core'] + 0x58, 4), (a['kernel']['guard'], 4)]
        if not any(lo <= at and at + size <= lo + length for lo, length in allowed):
            raise ValueError('Native local-query path changed unrelated state: ' + hex(at))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.emu_start(p['initialize'] | 1, p['initialize'] + 0x48, count=20000)
    if cpu.reg_read(arm.UC_ARM_REG_PC) != p['initialize'] + 0x48 or bytes(cpu.mem_read(p['cache'], 16)) != bytes(16):
        raise ValueError('Original local-query initialization prefix did not finish/zero its cache')
    expected_register = 0 if descriptor_available else 0xfffffc01
    if register_status != expected_register:
        raise ValueError('Native listener registration returned an unexpected status')
    if descriptor_available and (
            struct.unpack('<I', cpu.mem_read(record + 0x14, 4))[0] != listener_block
            or struct.unpack('<I', cpu.mem_read(listener_block + 8, 4))[0] != p['wrapper'] | 1
            or struct.unpack('<II', cpu.mem_read(listener_block + 0x14, 8)) != (p['callback'] | 1, 0)):
        raise ValueError('Native initializer did not allocate/register its actual callback')
    paused_frame = bytes(cpu.mem_read(stack - 40, 40))
    if cache_words is not None:
        phase = 'cache_copy_slice'
        cpu.mem_write(producer_input, struct.pack('<5I', 0x6b6b6b6b, *cache_words))
        cpu.reg_write(arm.UC_ARM_REG_R8, producer_input)
        cpu.emu_start(p['producer'] | 1, p['producer'] + 0x18, count=30)
    cached = bytes(cpu.mem_read(p['cache'], 16))
    expected_cached = bytes(16) if cache_words is None else struct.pack('<4I', *cache_words)
    if cached != expected_cached:
        raise ValueError('Native cache producer did not preserve all16 input bytes')
    phase = 'query'
    cpu.reg_write(arm.UC_ARM_REG_SP, client_stack)
    cpu.reg_write(arm.UC_ARM_REG_LR, 0x3001e001)
    cpu.emu_start(s['entry'] | 1, 0x3001e000, count=40000)
    second = struct.unpack_from('<I', cached, 4)[0] if descriptor_available else 0
    extra = descriptor_available and second in (0x81, 0x84, 0x85, 0x94)
    expected_boundary = 'before_additional_poweroff_message' if extra else 'before_diagnostics'
    if (boundary != expected_boundary or requests != [struct.pack('<4I', 0x920162, 0, 0, 0).hex()]
            or route_entries != ['native_local_endpoint']
            or replies != [(cached if descriptor_available else bytes.fromhex(requests[0])).hex()]
            or send_status != (0 if descriptor_available else -1020)
            or free_status != 0 or callback_calls != int(descriptor_available) or release_calls != 1
            or struct.unpack('<I', cpu.mem_read(pool + 0x18, 4))[0] != 256
            or struct.unpack('<I', cpu.mem_read(pool + 8, 4))[0] != block
            or struct.unpack('<I', cpu.mem_read(block + 4, 4))[0] != 256
            or bytes(cpu.mem_read(record + 2, 2)) != bytes(2)
            or bytes(cpu.mem_read(lock, 4)) != bytes(4)
            or bytes(cpu.mem_read(pool, 4)) != bytes(4)
            or bytes(cpu.mem_read(p['small_pool'], 4)) != bytes(4)
            or bytes(cpu.mem_read(a['timer_depth'], 4)) != bytes(4)
            or bytes(cpu.mem_read(a['kernel']['guard'], 4)) != bytes(4)
            or bytes(cpu.mem_read(os['core'] + 0x58, 4)) != bytes(4)
            or cpu.reg_read(arm.UC_ARM_REG_CPSR) & 0x80
            or descriptor_available and (
                cpu.mem_read(listener_block + 12, 1)[0] != 0
                or cpu.mem_read(listener_block + 13, 1)[0] != 1
                or struct.unpack('<I', cpu.mem_read(listener_block + 16, 4))[0] != 1)
            or bytes(cpu.mem_read(p['cache'], 16)) != cached
            or bytes(cpu.mem_read(stack - 40, 40)) != paused_frame
            or any(bytes(cpu.mem_read(at, 4)) != before for at, before in binding_snapshots)
            or cpu.mem_read(s['end_marker'], 1)[0] != 0x6b
            or bytes(cpu.mem_read(block - 4, 4)) != b'\x6b' * 4
            or bytes(cpu.mem_read(block + 256, 4)) != b'\x6b' * 4
            or bytes(cpu.mem_read(listener_block - 4, 4)) != b'\x6b' * 4
            or bytes(cpu.mem_read(listener_block + 64, 4)) != b'\x6b' * 4):
        raise ValueError('Native local-query reply/release/ownership differs')
    return dict(boundary=boundary, listener_registration_status=0 if descriptor_available else -1023,
                native_listener_and_cache_receiver_executed=descriptor_available,
                native_request=requests[0], native_reply=replies[0], native_send_status=send_status,
                native_free_status=free_status, native_free_calls=release_calls,
                payload_pool_bytes_restored=256, payload_live_count=0,
                cache_words=list(struct.unpack('<4I', cached)), cache_copy_slice_executed=cache_words is not None,
                synchronous_local_query=True, host_supplied_callback_pointer_or_api_return=False,
                native_local_route_entries=len(route_entries), native_task_id=1 if descriptor_available else None,
                actual_endpoint_tree_boot_registration_executed=False,
                synthetic_pool_endpoint_os_timer_and_optional_cache=True,
                cached_off_factor=second, additional_poweroff_message_executed=False,
                later_completion_callback_executed=False,
                physical_completion_verified=False, full_poweroff_check_executed=False)


def compare(c2, reference):
    inputs = [dict()] + [dict(cache_words=[0x12345678, value, 0x87654321, 0xabcdef01])
                         for value in (0x80, 0x81, 0x82, 0x84, 0x85, 0x94, 0x95)]
    inputs.append(dict(descriptor_available=False))
    rows = []
    for args in inputs:
        a, b = replay(c2, **args), replay(reference, **args)
        if a != b:
            raise ValueError('C2/A7CR local PowerOffDetect query differs')
        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-poweroff-request/1', paired_cases=len(rows), cases=rows,
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
