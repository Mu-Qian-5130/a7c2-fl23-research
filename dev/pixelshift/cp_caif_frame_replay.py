"""Native CAIF frame queue/ring and first header-transfer boundary, offline.

Starts from the original default mode writer, retaining an explicit unexecuted
backend-init boundary. Original action2 copies its 34-byte synthetic frame,
builds/queues type2, and original SDK/worker slices consume it into the ring.
Independent GPIO input drives original state transitions: the low input stays
on the bulk branch; the high input reaches an eight-byte header-read descriptor.
Stops BEFORE the bus driver; no header response, payload transfer or exposure
acknowledgement is supplied. Full boot/worker scheduling remains unexecuted.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_caif_gpio_replay import profile as gpio_profile
from cp_defaults_replay import _defaults_machine
from cp_native_mutex_replay import setup as setup_kernel
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, gpio = gpio_profile(directory)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, length):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + length], at))

    def call(at):
        rows = code(at, 4)
        if len(rows) != 1 or rows[0].mnemonic not in ('bl', 'blx', 'b.w'):
            raise ValueError('Native CAIF frame call changed')
        return int(rows[0].op_str.lstrip('#'), 0)

    def literal(at, length, reg):
        values = [v for r, v in literals(code(at, length)) if r == reg]
        if len(values) != 1:
            raise ValueError('Native CAIF frame binding is not unique')
        return values[0]

    action_table = gpio['dispatch'] + 0x22
    branch = action_table + 2 * data[action_table + 2 - 0x108000]
    copy_frame = call(branch + 6)
    wrapper = call(copy_frame + 0x1c)
    builder, lookup = call(wrapper + 0x12), call(call(wrapper + 0x12) + 0x32)
    frame_buffer = literal(copy_frame + 4, 14, 'r4')
    task = gpio['task']
    dispatch = call(task + 0x50)
    initialize = call(task + 0xa)
    state = literal(initialize + 0x4e, 12, 'r0')
    table = literal(dispatch + 0x66, 16, 'r3')

    def target(mode, substate, event):
        base = struct.unpack_from('<I', data, table + 4 * mode - 0x108000)[0]
        return struct.unpack_from('<I', data, base + 4 * (5 * substate + event) - 0x108000)[0] & ~1

    enqueue_wrapper, transition, header = target(4, 1, 2), target(4, 1, 0), target(1, 0, 0)
    enqueue = call(enqueue_wrapper + 4)
    count = literal(enqueue + 0xa, 8, 'r4')
    write_index = literal(enqueue + 0x4c, 8, 'ip')
    ring = literal(enqueue + 0x5c, 12, 'r4')
    sio_send = call(header + 0x112)
    descriptors = literal(header + 0xce, 16, 'r1')
    dummy = literal(header + 0xe2, 8, 'r0')
    rx_header = literal(header + 0xec, 8, 'r0')
    callback = literal(header + 0xfe, 8, 'r1')
    handshake = literal(header + 0xa, 24, 'r0')
    tracing = call(header + 0x10a)
    zero = call(header + 0xba)
    config_bytes = min(at for at, length in gpio['config_destinations'] if length == 1) - 1
    config_ranges = [(gpio['port_a'] - 0x18, 0x48), (config_bytes, 4)]
    if target(1, 0, 2) != enqueue_wrapper or target(4, 3, 2) != enqueue_wrapper:
        raise ValueError('Native ordinary CAIF states no longer share the inspected queue/ring path')
    regions = gpio['regions'] + [(gpio['defaults']['copy'], gpio['defaults']['copy'] + 0x300),
        (copy_frame, copy_frame + 0x20), (wrapper, wrapper + 0x1c),
        (builder, builder + 0x110), (lookup, lookup + 0x28),
        (initialize + 0x4e, initialize + 0x5e),
        (enqueue_wrapper, enqueue_wrapper + 12), (enqueue, enqueue + 0x98),
        (transition, transition + 0x40), (header, header + 0x174),
        (tracing - 0x66, tracing), (tracing, tracing + 0x66), (zero, zero + 0x150)]
    return data, dict(gpio=gpio, copy_frame=copy_frame, wrapper=wrapper, builder=builder,
                      frame_buffer=frame_buffer, dispatch=dispatch, initialize=initialize,
                      state=state, count=count, write_index=write_index, read_index=write_index + 1,
                      ring=ring, sio_send=sio_send, descriptors=descriptors, dummy=dummy,
                      rx_header=rx_header, callback=callback, handshake=handshake,
                      config_ranges=config_ranges, regions=regions)


def replay(directory, *, bank=0, start=0, peer_high=False, seed=0x5a):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, p = profile(directory)
    g = p['gpio']
    cpu, defaults, loaded = _defaults_machine(directory, bank)

    def mapping(at, length):
        for page in range(at & ~4095, (at + length + 4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)

    for at, length in [(0x1700000, 0x440000), (0x34000000, 0x5000), (0x35000000, 0x10000),
                       (0x36000000, 0x2000), (0x37000000, 0x3000), (0xf101d000, 0x15000),
                       (p['frame_buffer'], 0x100), (p['dummy'], 16), (g['snapshot'], 32)]:
        mapping(at, length)
    sdk, a = g['sdk'], g['sdk']['allocation']
    # Both SDK endpoints are fixtures. Native code allocates their payloads.
    record, lock, pool, block = 0x34000100, 0x34000400, 0x34000500, 0x34001000
    sio_record, sio_pool, sio_block = 0x37000100, 0x37000500, 0x37001000
    timer, worker_stack, client_stack = 0x34000300, 0x3500f000, 0x3001d000
    phase, omitted, config_reads, pending, boundary = 'config', 0, [], None, None
    queued, received, descriptor = None, None, None

    def hook(uc, at, size, unused):
        nonlocal omitted, pending, boundary, queued, descriptor
        if phase == 'config' and at == defaults['read32']:
            config_reads.append([uc.reg_read(arm.UC_ARM_REG_R0), None])
            pending = uc.reg_read(arm.UC_ARM_REG_LR) & ~1
        elif phase == 'config' and at == pending:
            config_reads[-1][1] = uc.reg_read(arm.UC_ARM_REG_R0)
            pending = None
        if phase == 'config' and at in defaults['locks']:
            omitted += 1
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR) | 1)
            return
        if phase == 'frame_request' and at == g['trace']:
            if uc.reg_read(arm.UC_ARM_REG_LR) & ~1 != g['dispatch'] + 0x1a:
                raise ValueError('Only the source action2 diagnostic may be omitted')
            omitted += 1
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR) | 1)
            return
        if phase == 'frame_request' and at == g['send']:
            if uc.reg_read(arm.UC_ARM_REG_R0) != 0x901502c7:
                raise ValueError('Native frame builder changed its queue endpoint')
            queued = bytes(uc.mem_read(uc.reg_read(arm.UC_ARM_REG_R1), 20))
        if phase == 'frame_request' and at == p['wrapper'] + 0x1c:
            boundary = 'before_frame_trace'
            uc.emu_stop()
            return
        if phase == 'event0' and at == p['sio_send']:
            if uc.reg_read(arm.UC_ARM_REG_R0) != 0x740017:
                raise ValueError('Native header stage changed its SIO endpoint')
            descriptor = bytes(uc.mem_read(uc.reg_read(arm.UC_ARM_REG_R1), 64))
            boundary = 'before_bus_driver'
            uc.emu_stop()
            return
        allowed = defaults['regions'] + [(g['config'], g['config'] + 0x188)] if phase == 'config' else p['regions']
        if not any(lo <= at and at + size <= hi for lo, hi in allowed):
            raise ValueError('Native CAIF frame reached an unexecuted dependency: ' + hex(at))

    def write_hook(uc, access, at, size, value, unused):
        allowed = p['config_ranges'] if phase == 'config' else [
            (record, 32), (lock, 4), (pool, 32), (block, 256),
            (sio_record, 32), (sio_record + 0x80, 4), (sio_pool, 32), (sio_block, 256),
            (timer + 4, 4), (a['timer_depth'], 4), (a['timer_stamp'], 4),
            (os['core'] + 12, 4), (os['core'] + 0x58, 4), (a['kernel']['guard'], 4),
            (p['frame_buffer'], 34), (g['snapshot'], 20), (p['ring'], 200),
            (p['count'], 3), (p['state'] + 14, 2), (p['handshake'], 1), (p['descriptors'], 16),
            (0x36001000, 20)]
        allowed += [(0x3001b000, 0x4000), (worker_stack - 0x2000, 0x2080)]
        if not any(lo <= at and at + size <= lo + length for lo, length in allowed):
            raise ValueError('Native CAIF frame changed unrelated state: ' + hex(at))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.reg_write(arm.UC_ARM_REG_SP, 0x3001f000)
    cpu.emu_start(g['config'] | 1, g['config'] + 0x188, count=30000)
    if cpu.reg_read(arm.UC_ARM_REG_PC) != g['config'] + 0x188 or len(config_reads) != 17 or omitted != 34:
        raise ValueError('Native CAIF configuration prefix did not load all17 actual parameters')
    os = setup_kernel(cpu, directory)
    for at, value in [(a['table'] + 0x114, 0x34000200), (0x3400020c, 0x34000240),
                      (0x34000240, 0x34000280), (0x3400029c, record),
                      (record + 0x18, pool), (record + 0x1c, lock),
                      (pool + 8, block), (pool + 0x10, 256), (pool + 0x18, 256), (pool + 0x1c, 256),
                      (block + 4, 256), (a['timer_root'] + 8, timer), (sdk['task_base'], os['task']),
                      (a['table'] + 8 + 4 * 0x17, sio_record),
                      (sio_record + 0x18, sio_pool), (sio_record + 0x1c, sio_record + 0x80),
                      (sio_pool + 8, sio_block), (sio_pool + 0x10, 256),
                      (sio_pool + 0x18, 256), (sio_pool + 0x1c, 256), (sio_block + 4, 256)]:
        cpu.mem_write(at, struct.pack('<I', value))
    for port in range(21):
        base = 0xf101d000 + 4096 * port
        cpu.mem_write(base, struct.pack('<I', 0xffffffff))
        cpu.mem_write(base + 0x40, struct.pack('<I', 1 << 5 if peer_high and port == 5 else 0))
    source, event_input = 0x36000000, 0x36001000
    payload = bytes((seed + n) & 255 for n in range(34))
    cpu.mem_write(source + 0x3b, b'\x6b' + payload + b'\x6b')
    cpu.mem_write(event_input, bytes(20))
    cpu.mem_write(p['ring'] - 4, b'\x6b' * 4 + b'\x7c' * 200 + b'\x6b' * 4)
    cpu.mem_write(p['count'], bytes([0, start, start]))
    phase = 'default_mode_writer'
    cpu.emu_start((p['initialize'] + 0x4e) | 1, p['initialize'] + 0x5e, count=12)
    if bytes(cpu.mem_read(p['state'] + 14, 2)) != b'\4\1':
        raise ValueError('Original initialization writer did not select mode4/substate1')
    phase = 'frame_request'
    cpu.reg_write(arm.UC_ARM_REG_SP, client_stack)
    cpu.reg_write(arm.UC_ARM_REG_LR, 0x3001e001)
    cpu.reg_write(arm.UC_ARM_REG_R0, 2)
    cpu.reg_write(arm.UC_ARM_REG_R1, source)
    cpu.emu_start(g['dispatch'] | 1, 0x3001e000, count=40000)
    if (boundary != 'before_frame_trace' or queued is None or queued[0] != 2
            or queued[4:10] != bytes.fromhex('f00301002200')
            or struct.unpack_from('<I', queued, 12)[0] != p['frame_buffer']
            or bytes(cpu.mem_read(p['frame_buffer'], 34)) != payload):
        raise ValueError('Native action2 did not retain the frame/header in its actual queued record')
    paused_client = bytes(cpu.mem_read(client_stack - 0x400, 0x400))
    cpu.reg_write(arm.UC_ARM_REG_SP, worker_stack)
    phase = 'worker_setup'
    cpu.emu_start((g['task'] + 0xe) | 1, g['task'] + 0x2a, count=50)
    phase = 'worker_receive'
    cpu.emu_start((g['task'] + 0x5c) | 1, g['task'] + 0x68, count=30000)
    pointer = struct.unpack('<I', cpu.mem_read(worker_stack + 4, 4))[0]
    if cpu.reg_read(arm.UC_ARM_REG_R0) != 0 or pointer != block + 0xc0:
        raise ValueError('Original SDK receiver did not obtain the actual frame request buffer')
    received = bytes(cpu.mem_read(pointer, 20))
    phase = 'worker_copy_free'
    cpu.emu_start((g['task'] + 0x2c) | 1, g['task'] + 0x42, count=30000)
    phase = 'worker_type2'
    cpu.emu_start((g['task'] + 0x4e) | 1, g['task'] + 0x54, count=30000)
    slot = p['ring'] + start * 20
    if (received != queued or bytes(cpu.mem_read(slot, 20)) != queued
            or cpu.mem_read(p['count'], 1)[0] != 1
            or cpu.mem_read(p['write_index'], 1)[0] != (start + 1) % 10
            or struct.unpack('<I', cpu.mem_read(pool + 0x18, 4))[0] != 256):
        raise ValueError('Native SDK worker did not preserve/enqueue/release its actual frame record')
    states = [[4, 1]]
    phase, boundary = 'event0', None

    def event0():
        cpu.reg_write(arm.UC_ARM_REG_SP, worker_stack - 0x1000)
        cpu.reg_write(arm.UC_ARM_REG_LR, 0x3001e001)
        cpu.reg_write(arm.UC_ARM_REG_R0, event_input)
        cpu.emu_start(p['dispatch'] | 1, 0x3001e000, count=30000)
        states.append(list(cpu.mem_read(p['state'] + 14, 2)))

    event0()
    if states[-1] != ([1, 0] if peer_high else [4, 3]):
        raise ValueError('Original mode4 event0 did not retain its independent GPIO-input branch')
    if peer_high:
        event0()
        if boundary != 'before_bus_driver' or states[-1] != [3, 1] or descriptor is None:
            raise ValueError('Native high-GPIO transition did not reach the header-request driver boundary')
        segments = struct.unpack('<4I', cpu.mem_read(p['descriptors'], 16))
        if (descriptor[:4] != bytes([5, 0, 4, 30]) or descriptor[4] != 1
                or struct.unpack_from('<H', descriptor, 8)[0] != 6
                or struct.unpack_from('<I', descriptor, 0x2c)[0] != 3
                or struct.unpack_from('<I', descriptor, 0x38)[0] != p['descriptors']
                or struct.unpack_from('<I', descriptor, 0x3c)[0] != p['callback']
                or segments != (p['dummy'], p['rx_header'], 0, 8)
                or struct.unpack('<H', cpu.mem_read(sio_record + 2, 2))[0] != 1):
            raise ValueError('Native first SIO request is not the source-defined eight-byte header read')
    if (bytes(cpu.mem_read(slot, 20)) != queued or bytes(cpu.mem_read(p['frame_buffer'], 34)) != payload
            or bytes(cpu.mem_read(source + 0x3b, 36)) != b'\x6b' + payload + b'\x6b'
            or bytes(cpu.mem_read(client_stack - 0x400, 0x400)) != paused_client
            or bytes(cpu.mem_read(p['ring'] - 4, 4)) != b'\x6b' * 4
            or bytes(cpu.mem_read(p['ring'] + 200, 4)) != b'\x6b' * 4
            or cpu.mem_read(p['count'], 1)[0] != 1
            or bytes(cpu.mem_read(record + 2, 2)) != bytes(2)):
        raise ValueError('Native state transitions consumed/corrupted a still-pending payload')
    return dict(bank=bank, ring_start=start, native_config_reads=config_reads,
                native_frame=payload.hex(), native_queue_header=queued[4:10].hex(),
                native_queue_worker_ring_bytes_preserved=True, state_history=states,
                ring_pending_count=1, ring_write_index=(start + 1) % 10,
                control_request_live_buffers=0, sio_descriptor_live_buffers=int(peer_high),
                sio_header_request_built=bool(peer_high), sio_segment_bytes=8 if peer_high else None,
                sio_segment_source_and_destination_verified=bool(peer_high),
                sio_descriptor_mode=3 if peer_high else None,
                boundary=boundary or 'bulk_branch_selected', native_parameter_mutex_calls_omitted=39,
                action_diagnostic_calls_omitted=omitted - 34,
                original_default_mode_writer_executed=True, full_backend_initialization_executed=False,
                hardware_event_and_gpio_inputs_are_fixtures=True,
                host_assigned_api_return_or_copied_queue_bytes=False,
                bus_driver_executed=False, header_response_supplied=False, payload_transmitted=False,
                framing_or_darwin_direction_equivalence_verified=False,
                full_worker_loop_executed=False, sensor_or_exposure_sync_verified=False)


def compare(c2, reference):
    inputs = [dict(bank=bank, **case) for bank in (0, 1) for case in
              (dict(start=0, peer_high=False, seed=0), dict(start=9, peer_high=True, seed=0xa5),
               dict(start=0, peer_high=True, seed=0x5a), dict(start=9, peer_high=False, seed=0xff))]
    rows = []
    for args in inputs:
        a, b = replay(c2, **args), replay(reference, **args)
        if a != b:
            raise ValueError('C2/A7CR native frame-ring/header-stage behavior differs')
        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-caif-frame/1', paired_cases=len(rows), cases=rows,
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
