"""Native callback/CAIF GPIO route with official configuration, offline only.

Original callback event API, action selector, SDK allocation/send/receive/free,
worker copy/dispatch slices and GPIO register accesses execute. Native SDK queue
bytes stay in one RAM image. Two diagnostic calls and BK reader mutex calls are
omitted explicitly; full backend initialization and worker profiling boundaries
do not execute. Endpoint/pool/OS, debug inputs and peripheral registers remain
fixtures. GPIO writes reach emulated cells, never a real camera or sensor.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_defaults_replay import _defaults_machine, profile as defaults_profile
from cp_sequence_replay import profile as sequence_profile
from cp_completion_replay import profile as event_profile, setup as setup_event
from cp_completion_consumer_replay import profile as consumer_profile
from cp_poweroff_request_replay import profile as sdk_profile
from cp_native_mutex_replay import setup as setup_kernel
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, defaults = defaults_profile(directory)
    _, sequence = sequence_profile(directory)
    _, events = event_profile(directory)
    _, consumer = consumer_profile(directory)
    _, sdk = sdk_profile(directory)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def call(at):
        rows = code(at, 4)
        if len(rows) != 1 or rows[0].mnemonic not in ('bl', 'blx', 'b.w'):
            raise ValueError('Native CAIF call boundary changed')
        return int(rows[0].op_str.lstrip('#'), 0)

    def literal(at, size, register):
        values = [v for r, v in literals(code(at, size)) if r == register]
        if len(values) != 1:
            raise ValueError('Native CAIF binding is not unique')
        return values[0]

    target = defaults['model'] == 'ILCE-7CM2'
    callback = literal(consumer['entry'] - 16, 12, 'r3') & ~1
    if callback != (0xb18e28 if target else 0xb18c86) or call(callback + 0x1a) != events['event_api']:
        raise ValueError('Native capture client does not register this event/action callback')
    trace, dispatch = call(callback + 0x10), call(callback + 0x32)
    table = dispatch + 0x22
    choice = table + 2 * data[table + 4 - 0x108000]
    selector = literal(choice, 8, 'r0')
    queued, direct = call(choice + 12), call(choice + 18)
    selector_init = sequence['first_getter'] + 12
    if literal(selector_init + 8, 12, 'r0') != selector:
        raise ValueError('Native backend selector initializer/reader differ')
    config = 0x742274 if target else 0x74248c
    config_stop = config + 0xe4
    if call(config + 0x10) != defaults['read32']:
        raise ValueError('CAIF configuration does not use the official parameter reader')
    config_rows = code(config, 0xe4)
    destinations = [(v, 1 if v > 0x1a00000 else 4) for r, v in literals(config_rows)
                    if r == 'r1' and 0x1700000 <= v < 0x2000000]
    if len(destinations) != 12:
        raise ValueError('Native CAIF parameter-prefix destinations changed')
    pin_a, port_a = literal(queued + 4, 8, 'r0'), literal(queued + 14, 8, 'r0')
    pin_b, port_b = literal(direct + 4, 8, 'r0'), literal(direct + 14, 8, 'r0')
    gpio_clear = call(direct + 0x18)
    gpio_leaf = call(gpio_clear + 6)
    gpio_read = gpio_clear + 12
    gpio_control, gpio_output, gpio_input = [call(gpio_read + n) for n in (0x10, 0x1e, 0x2e)]
    gpio_shadow = literal(gpio_leaf + 0x36, 10, 'r1')
    queued_builder = call(queued + 0x1a)
    allocator_wrapper = call(queued_builder + 0x1e)
    send = call(queued_builder + 0x5e)
    notify = call(send + 0x152)
    task = 0x236ae8 if target else 0x236b08
    receive, free, worker_dispatch = call(task + 0x64), call(task + 0x3e), call(task + 0x50)
    snapshot = literal(worker_dispatch + 0xe, 12, 'sb')
    worker_table = worker_dispatch + 0x34
    type12 = worker_table + 2 * data[worker_table + 0x12 - 0x108000]
    handler = call(type12 + 8)
    trace_snapshot, trace_recorder = call(worker_dispatch + 0x1c), call(worker_dispatch + 0x20)
    emitter = call(call(queued + 0x24))
    if call(handler + 0xc6) != emitter or call(handler + 0x9e) != gpio_clear:
        raise ValueError('Native CAIF type12 does not reach the inspected GPIO clear/trace path')
    regions = sdk['allocation']['regions'] + events['regions'] + [
        (callback, callback + 0x36), (dispatch, dispatch + 0x122),
        (queued, queued + 0x2c), (direct, direct + 0x28),
        (queued_builder, queued_builder + 0xaa), (allocator_wrapper, allocator_wrapper + 0x76),
        (send, send + 0x16a), (notify, notify + 0x48),
        (notify + 0x37a, notify + 0x38a), (receive, receive + 0x234),
        (task + 0xe, task + 0x2a), (task + 0x5c, task + 0x68),
        (task + 0x2c, task + 0x42), (task + 0x4e, task + 0x54),
        (free, free + 0x98), (sdk['allocation']['stop']['header'], sdk['allocation']['stop']['header'] + 6),
        (worker_dispatch, worker_dispatch + 0x190), (handler, handler + 0x14c),
        (trace_snapshot, trace_snapshot + 0xc0), (trace_recorder, trace_recorder + 0x50),
        (gpio_clear, gpio_clear + 12), (gpio_read, gpio_read + 0x32), (gpio_leaf, gpio_leaf + 0x44),
        (gpio_control, gpio_control + 0x14), (gpio_output, gpio_output + 0x1a),
        (gpio_input, gpio_input + 0x1a), (selector_init + 8, selector_init + 0x2a)]
    # Free implementation/pool coalescing are shared with the local request replay.
    regions += sdk['regions']
    return data, dict(defaults=defaults, events=events, sdk=sdk, callback=callback, trace=trace,
                      dispatch=dispatch, selector=selector, selector_init=selector_init,
                      selector_debug=literal(selector_init + 0x14, 8, 'r1') + 0x34,
                      skip=literal(callback + 0x1e, 8, 'r0') + 0x62,
                      queued=queued, direct=direct, config=config, config_stop=config_stop,
                      config_destinations=destinations, port_a=port_a, pin_a=pin_a, port_b=port_b, pin_b=pin_b,
                      gpio_shadow=gpio_shadow, gpio_leaf=gpio_leaf, send=send, receive=receive, free=free,
                      task=task, snapshot=snapshot, handler=handler, emitter=emitter, regions=regions)


def replay(directory, *, bank=0, debug=0, skip=0, peripheral=0):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, p = profile(directory)
    cpu, defaults, loaded = _defaults_machine(directory, bank)

    def mapping(at, size):
        for page in range(at & ~4095, (at + size + 4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)

    for at, _ in p['config_destinations']:
        mapping(at, 4)
    mapping(0x1700000, 0x440000)
    mapping(0x34000000, 0x5000)
    mapping(0x35000000, 0x10000)
    mapping(p['snapshot'], 32)
    mapping(0xf101d000, 0x15000)
    phase, omitted, reads, pending = 'config', 0, [], None
    request, received, event_before_action = None, None, None
    mmio_writes, boundary = [], None

    def hook(uc, at, size, unused):
        nonlocal omitted, pending, request, received, boundary, event_before_action
        if phase == 'config' and at == defaults['read32']:
            reads.append([uc.reg_read(arm.UC_ARM_REG_R0), None])
            pending = uc.reg_read(arm.UC_ARM_REG_LR) & ~1
        elif phase == 'config' and at == pending:
            reads[-1][1] = uc.reg_read(arm.UC_ARM_REG_R0)
            pending = None
        if phase == 'config' and at in defaults['locks']:
            omitted += 1
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR) | 1)
            return
        if phase == 'callback' and at == p['trace']:
            # Both diagnostic returns are unused by the following original code.
            if uc.reg_read(arm.UC_ARM_REG_LR) & ~1 not in (p['callback'] + 0x14, p['dispatch'] + 0x1a):
                raise ValueError('Only the two source-identified callback/action diagnostics may be omitted')
            omitted += 1
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR) | 1)
            return
        if phase == 'callback' and at == p['dispatch']:
            event_before_action = struct.unpack('<I', uc.mem_read(event['event'] + 12, 4))[0]
        if at == p['send']:
            request = bytes(uc.mem_read(uc.reg_read(arm.UC_ARM_REG_R1), 20))
        if phase == 'callback' and at in (p['queued'] + 0x24, p['direct'] + 0x22):
            boundary = 'before_sender_trace'
            uc.emu_stop()
            return
        if phase == 'worker_dispatch' and at == p['emitter']:
            if uc.reg_read(arm.UC_ARM_REG_R0) != 0x13a:
                raise ValueError('Native CAIF type12 reached a different trace-message boundary')
            boundary = 'before_worker_trace'
            uc.emu_stop()
            return
        allowed = (defaults['regions'] + [(p['config'], p['config_stop'])]) if phase == 'config' else p['regions']
        if not any(lo <= at and at + size <= hi for lo, hi in allowed):
            raise ValueError('Native CAIF GPIO replay reached an unexecuted dependency: ' + hex(at))

    def write_hook(uc, access, at, size, value, unused):
        if 0xf101d000 <= at < 0xf1032000:
            mmio_writes.append([at, size, value])
        allowed = (p['config_destinations'] if phase == 'config' else
                   [(record, 32), (lock, 4), (pool, 32), (block, 256),
                    (timer + 4, 4), (a['timer_depth'], 4), (a['timer_stamp'], 4),
                    (os['core'] + 12, 4), (os['core'] + 0x58, 4), (a['kernel']['guard'], 4),
                    (event['event'] + 12, 4), (p['selector'], 1), (p['snapshot'], 20),
                    (p['gpio_shadow'], 4), (0xf1028048, 4)])
        allowed += [(0x3001b000, 0x4000), (0x3500d000, 0x2080)]
        if not any(lo <= at and at + size <= lo + length for lo, length in allowed):
            raise ValueError('Native CAIF GPIO path changed unrelated state: ' + hex(at))

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.reg_write(arm.UC_ARM_REG_SP, 0x3001f000)
    cpu.emu_start(p['config'] | 1, p['config_stop'], count=30000)
    if cpu.reg_read(arm.UC_ARM_REG_PC) != p['config_stop'] or len(reads) != 12 or omitted != 24:
        raise ValueError('Original CAIF configuration prefix did not read all12 parameters')
    ports = [struct.unpack('<I', cpu.mem_read(p[key], 4))[0] for key in ('port_a', 'pin_a', 'port_b', 'pin_b')]
    if ports != [11, 26, 11, 25]:
        raise ValueError('Official CAIF GPIO defaults differ from the researched configuration')
    config_frame = bytes(cpu.mem_read(0x3001eff0, 16))
    os = setup_kernel(cpu, directory)
    event = setup_event(cpu, directory, kernel_state=os, initial_bits=0x204)
    a = p['sdk']['allocation']
    record, t1, t2, t3 = 0x34000100, 0x34000200, 0x34000240, 0x34000280
    timer, lock, pool, block = 0x34000300, 0x34000400, 0x34000500, 0x34001000
    ident = 0x2c7
    for at, value in [(a['table'] + 0x110 + 4 * ((ident >> 9) & 63), t1),
                      (t1 + 4 * ((ident >> 6) & 7), t2), (t2 + 4 * ((ident >> 3) & 7), t3),
                      (t3 + 4 * (ident & 7), record), (record + 0x18, pool), (record + 0x1c, lock),
                      (pool + 8, block), (pool + 0x10, 256), (pool + 0x18, 256), (pool + 0x1c, 256),
                      (block + 4, 256), (a['timer_root'] + 8, timer), (p['sdk']['task_base'], os['task'])]:
        cpu.mem_write(at, struct.pack('<I', value))
    for port in range(21):
        base = 0xf101d000 + port * 4096
        cpu.mem_write(base, struct.pack('<I', 0xffffffff))
        cpu.mem_write(base + 0x40, struct.pack('<I', peripheral))
    cpu.mem_write(p['selector_debug'], bytes([debug]))
    cpu.mem_write(p['skip'], bytes([skip]))
    phase = 'selector_postinit_slice'
    cpu.emu_start((p['selector_init'] + 8) | 1, p['selector_init'] + 0x2a, count=30)
    selector = cpu.mem_read(p['selector'], 1)[0]
    if selector != (debug >> 7 if debug & 2 else 1):
        raise ValueError('Native selector writer ignored its debug-input branch')
    phase = 'callback'
    cpu.reg_write(arm.UC_ARM_REG_SP, 0x3001d000)
    cpu.reg_write(arm.UC_ARM_REG_LR, 0x3001e001)
    cpu.emu_start(p['callback'] | 1, 0x3001e000, count=40000)
    if struct.unpack('<I', cpu.mem_read(event['event'] + 12, 4))[0] != 0x10204:
        raise ValueError('Original callback did not preserve/set its actual event')
    queued = not skip and selector != 0
    if skip:
        if cpu.reg_read(arm.UC_ARM_REG_PC) != 0x3001e000 or boundary is not None or request is not None:
            raise ValueError('Native callback skip-input branch did not return without action')
    elif event_before_action != 0x10204 or boundary != 'before_sender_trace':
        raise ValueError('Original callback/action did not reach its bounded trace boundary')
    before_delivery = list(mmio_writes)
    if queued:
        if (request is None or request[0] != 0x12 or struct.unpack_from('<II', request, 12) != (11, 26)
                or struct.unpack('<I', cpu.mem_read(record + 8, 4))[0] != block + 0xa8 or mmio_writes):
            raise ValueError('Native sender did not queue its actual type12 GPIO record before any GPIO write')
        paused_callback = bytes(cpu.mem_read(0x3001cc00, 0x400))
        cpu.reg_write(arm.UC_ARM_REG_SP, 0x3500f000)
        phase = 'worker_setup_slice'
        cpu.emu_start((p['task'] + 0xe) | 1, p['task'] + 0x2a, count=50)
        phase = 'worker_receive'
        cpu.emu_start((p['task'] + 0x5c) | 1, p['task'] + 0x68, count=30000)
        pointer = struct.unpack('<I', cpu.mem_read(0x3500f004, 4))[0]
        if cpu.reg_read(arm.UC_ARM_REG_R0) != 0 or pointer != block + 0xc0:
            raise ValueError('Native SDK receive did not return the original queued buffer')
        received = bytes(cpu.mem_read(pointer, 20))
        phase = 'worker_copy_free_slice'
        cpu.emu_start((p['task'] + 0x2c) | 1, p['task'] + 0x42, count=30000)
        if (bytes(cpu.mem_read(0x3500f008, 20)) != request or received != request
                or struct.unpack('<I', cpu.mem_read(pool + 0x18, 4))[0] != 256
                or bytes(cpu.mem_read(record + 2, 2)) != bytes(2)):
            raise ValueError('Original worker did not copy/free the actual received queue record')
        phase, boundary = 'worker_dispatch', None
        cpu.emu_start((p['task'] + 0x4e) | 1, 0x3001e000, count=30000)
        if (boundary != 'before_worker_trace' or bytes(cpu.mem_read(p['snapshot'], 20)) != request
                or bytes(cpu.mem_read(0x3001cc00, 0x400)) != paused_callback):
            raise ValueError('Original worker dispatch changed message/paused-callback ownership')
    expected_writes = [] if skip else [[0xf1028048, 4, 1 << (26 if queued else 25)]]
    if (mmio_writes != expected_writes or bytes(cpu.mem_read(0x3001eff0, 16)) != config_frame
            or struct.unpack('<I', cpu.mem_read(record + 8, 4))[0] != 0
            or struct.unpack('<I', cpu.mem_read(pool + 0x18, 4))[0] != 256
            or bytes(cpu.mem_read(record + 2, 2)) != bytes(2)
            or any(bytes(cpu.mem_read(at, 4)) != bytes(4) for at in (lock, pool, a['kernel']['guard'], a['timer_depth']))
            or struct.unpack('<I', cpu.mem_read(0xf1028040, 4))[0] != peripheral
            or not skip and struct.unpack('<I', cpu.mem_read(p['gpio_shadow'], 4))[0] != peripheral):
        raise ValueError('Native GPIO/pool/lock/peripheral observation differs')
    cpu.hook_del(ch)
    cpu.hook_del(wh)
    return dict(bank=bank, native_parameter_reads=reads, factory_gpio_pairs=[ports[:2], ports[2:]],
                backend_selector=selector, native_selector_postinit_slice_executed=True,
                native_backend_initialization_executed=False, callback_action_skipped=bool(skip),
                event_bits_before_action=event_before_action, event_bits_after=0x10204,
                mmio_writes_before_delivery=before_delivery, mmio_writes=mmio_writes,
                queued_record=None if request is None else request.hex(), native_received_record=None if received is None else received.hex(),
                native_sdk_receive_and_worker_copy_free_executed=queued,
                request_live_buffers_after=0, gpio_peripheral_input=peripheral,
                gpio_data_register_not_mirrored_from_command=True, host_assigned_api_return_or_copied_queue_data=False,
                omitted_mutex_calls=24 + loaded['mutex_calls_omitted'],
                omitted_diagnostic_calls=omitted - 24, callback_completed=bool(skip),
                boundary='callback_returned' if skip else boundary,
                harness_actor_and_worker_slice_boundaries=True, full_worker_loop_executed=False,
                sdk_endpoint_tree_pool_os_debug_and_mmio_are_fixtures=True,
                physical_gpio_or_sensor_verified=False, exposure_sync_verified=False)


def compare(c2, reference):
    inputs = [dict(bank=bank, **case) for bank in (0, 1) for case in
              (dict(peripheral=0), dict(peripheral=0xffffffff), dict(debug=2, peripheral=0x5a5a5a5a), dict(skip=1))]
    rows = []
    for args in inputs:
        a, b = replay(c2, **args), replay(reference, **args)
        if a != b:
            raise ValueError('C2/A7CR native callback/CAIF GPIO path differs')
        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-caif-gpio/1', paired_cases=len(rows), cases=rows,
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
