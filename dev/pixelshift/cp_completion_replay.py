"""Native completion registration and event production, offline only.

Original client records, sender prefix and post-dequeue dispatcher execute.
The default does NOT execute queue send/receive: exact sender bytes cross an
explicit fixture boundary. Native callbacks set a synthetic empty-waiter event
object through original RTOS code. No waiting capture task, hardware-ready
response, physical completion or host-supplied API return is provided.
An optional helper mode delegates to native actor delivery without that gap.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_group_end_replay import profile as group_profile
from cp_native_mutex_replay import profile as mutex_profile, setup as setup_kernel
from cp_sequence_replay import machine
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_ARM
    data, group = group_profile(directory)
    _, kernel = mutex_profile(directory)
    target = group['end'] == 0x4757e8
    thumb, arm = Cs(CS_ARCH_ARM, CS_MODE_THUMB), Cs(CS_ARCH_ARM, CS_MODE_ARM)

    def code(at, size, decoder=thumb):
        return list(decoder.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def literal(at, size, register, decoder=thumb):
        values = [v for r, v in literals(code(at, size, decoder)) if r == register]
        if len(values) != 1:
            raise ValueError('Native completion binding is not unique')
        return values[0]

    def call(at, mnemonic='bl', decoder=thumb):
        rows = code(at, 4, decoder)
        if len(rows) != 1 or rows[0].mnemonic != mnemonic:
            raise ValueError('Original completion call boundary changed')
        return int(rows[0].op_str.lstrip('#'), 0)

    client, initialize = (0x490220, 0xb0dd8e) if target else (0x49043c, 0xb0dbec)
    getter = call(client)
    manager = literal(getter, 12, 'r0')
    if literal(initialize, 0x18, 'r0') != manager:
        raise ValueError('Original actor initializer does not bind the client manager')
    setter = literal(client + 4, 0x16, 'r6') & ~1
    invoker = literal(client + 4, 0x16, 'sl') & ~1
    callbacks = [literal(client + offset, 12, 'r3') & ~1 for offset in (0x20, 0x40)]
    sender = call(client + 0x2c)
    if call(client + 0x4c) != sender:
        raise ValueError('Native completion client uses different sender prefixes')
    worker = literal(initialize, 0x18, 'r2') & ~1
    root = literal(setter + 0x64, 8, 'r0')
    if root + 8 != group['callback']:
        raise ValueError('Native setter does not supply TrinityShotEnd callback storage')
    veneer = call(callbacks[1] + 0x1e, 'b.w')
    if call(callbacks[0] + 0x1e, 'b.w') != veneer or code(veneer, 2)[0].op_str != 'pc':
        raise ValueError('Native completion callbacks no longer share the interworking veneer')
    api = struct.unpack_from('<I', data, veneer + 8 - 0x108000)[0]
    table = literal(api + 0x68, 16, 'r1', arm)
    guard = literal(api + 0x68, 16, 'sl', arm)
    if guard != kernel['guard']:
        raise ValueError('Native event and mutex kernel guard bindings differ')
    pairs = [code(at + 0x14, 6) for at in callbacks]
    ids = [int(rows[0].op_str.split('#')[1], 0) for rows in pairs]
    masks = [int(rows[1].op_str.split('#')[1], 0) for rows in pairs]
    if ids[0] != ids[1]:
        raise ValueError('Native completion callbacks use different event IDs')
    trace = call(callbacks[1] + 0x10)
    regions = [(initialize, initialize + 0x32), (getter, getter + 12),
               (client, client + 0x2c), (client + 0x30, client + 0x4c),
               (sender, sender + 0x2e), (worker + 0x5c, worker + 0x76),
               (invoker, invoker + 8), (setter, setter + 0x72),
               (veneer, veneer + 8), (api, api + 0x248)]
    regions += [(at, at + 0x22) for at in callbacks]
    waits = [i.address for i in code(api, 0x248, arm) if i.mnemonic == 'wfe']
    return data, dict(initialize=initialize, client=client, manager=manager, sender=sender,
                      queue_send=call(sender + 0x2a, 'blx'), worker=worker,
                      invoker=invoker, setter=setter, root=root,
                      completed=literal(setter + 0x12, 12, 'r0'), callbacks=callbacks,
                      trace=trace, event_api=api, event_id=ids[0], masks=masks, table=table,
                      guard=guard, waits=waits, regions=regions)


def setup(cpu, directory, *, kernel_state=None, context=0, masked=False, kernel_busy=False,
          initial_bits=0, already_complete=False):
    _, p = profile(directory)
    kernel = setup_kernel(cpu, directory, context=context, masked=masked) if kernel_state is None else kernel_state
    event, attrs, messages = 0x30015000, 0x30003400, 0x30016000
    slot = p['table'] + 4 * (p['event_id'] - 1)
    for address in (slot, p['manager'], p['root'], p['completed']):
        page = address & ~4095
        if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
            cpu.mem_map(page, 4096)
    cpu.mem_write(slot, struct.pack('<I', event))
    cpu.mem_write(event - 4, b'\x6b' * 4 + struct.pack('<4I', event, event, attrs, initial_bits) + b'\x6b' * 4)
    cpu.mem_write(attrs, bytes(8))
    cpu.mem_write(p['completed'], bytes([int(already_complete)]))
    if kernel_busy:
        cpu.mem_write(p['guard'], struct.pack('<I', 1))
    return dict(kernel=kernel, event=event, attrs=attrs, messages=messages, initial_bits=initial_bits,
                already_complete=already_complete,
                writes=[(p['manager'], 32), (p['root'], 12), (event + 12, 4), (p['guard'], 4)])


def observer(cpu, p):
    import unicorn.arm_const as arm
    seen = dict(callbacks=[], event_arguments=[], event_statuses=[], diagnostic_calls_omitted=0, boundary=None)

    def observe(at):
        if at in p['callbacks']:
            seen['callbacks'].append(p['callbacks'].index(at))
        if at == p['trace']:
            # Both selected callbacks overwrite diagnostic R0 before using it.
            if cpu.reg_read(arm.UC_ARM_REG_LR) & ~1 not in [at + 0x14 for at in p['callbacks']]:
                raise ValueError('Only the selected completion callbacks diagnostic call may be omitted')
            seen['diagnostic_calls_omitted'] += 1
            cpu.reg_write(arm.UC_ARM_REG_PC, cpu.reg_read(arm.UC_ARM_REG_LR) | 1)
            return 'diagnostic_omitted'
        if at == p['event_api']:
            seen['event_arguments'].append([cpu.reg_read(arm.UC_ARM_REG_R0), cpu.reg_read(arm.UC_ARM_REG_R1)])
        if at == p['event_api'] + 0x244:
            value = cpu.reg_read(arm.UC_ARM_REG_R0)
            seen['event_statuses'].append(value if value < 0x80000000 else value - 0x100000000)
        if at in p['waits']:
            seen['boundary'] = 'wait_for_event'
            cpu.emu_stop()
    return seen, observe


def prepare(cpu, directory, state, *, native_queue=False):
    """Run the explicit-boundary model, or delegate to actual native queue delivery."""
    if native_queue:
        from cp_actor_delivery_replay import prepare as deliver
        return deliver(cpu, directory, state)
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    seen, observe = observer(cpu, p)
    client_stack, stack, finish = 0x3001d000, 0x3001f000, 0x3001e000
    phase, messages, jobs = 'initialize', [], []
    registers = [arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3]

    def hook(uc, at, size, unused):
        if phase == 'sender' and at == p['queue_send']:
            length = uc.reg_read(arm.UC_ARM_REG_R2)
            if length != 28:
                raise ValueError('Original actor sender did not produce its 28-byte record')
            messages.append(bytes(uc.mem_read(uc.reg_read(arm.UC_ARM_REG_R1), length)))
            uc.emu_stop()
            return
        action = observe(at)
        if action or seen['boundary']:
            return
        if not any(lo <= at and at + size <= hi for lo, hi in p['regions']):
            raise ValueError('Native completion replay reached omitted code: ' + hex(at))

    def write_hook(uc, access, address, size, value, unused):
        allowed = state['writes'] + [(client_stack, 0x140), (stack - 4096, 4096 + 64)]
        if not any(lo <= address and address + size <= lo + length for lo, length in allowed):
            raise ValueError('Native completion replay changed unrelated state: ' + hex(address))

    def run(at, stop=finish, sp=stack):
        cpu.reg_write(arm.UC_ARM_REG_SP, sp)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(at | 1, stop, count=10000)
        if phase != 'sender' and seen['boundary'] is None and cpu.reg_read(arm.UC_ARM_REG_PC) != stop:
            raise ValueError('Native completion stage missed its boundary')

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        run(p['initialize'])
        for start, stop in ((p['client'], p['client'] + 0x2c), (p['client'] + 0x30, p['client'] + 0x4c)):
            phase = 'client'
            run(start, stop, client_stack)
            jobs.append([cpu.reg_read(register) for register in registers])
        for args in jobs:
            phase = 'sender'
            for register, value in zip(registers, args):
                cpu.reg_write(register, value)
            run(p['sender'], 0)
        if len(messages) != 2:
            raise ValueError('Original client/sender did not produce two native messages')
        for index, raw in enumerate(messages):
            if raw[:20] != bytes(cpu.mem_read(jobs[index][1], 20)) or struct.unpack_from('<2I', raw, 20) != tuple(jobs[index][2:]):
                raise ValueError('Native sender record differs from actual client callable/arguments')
            cpu.mem_write(state['messages'] + 28 * index, raw)
        completed = 0
        for raw in messages:
            # Explicit synthetic post-dequeue frame; bytes remain unmodified.
            cpu.mem_write(stack + 4, raw)
            cpu.reg_write(arm.UC_ARM_REG_R5, stack + 4)
            phase = 'post_dequeue'
            run(p['worker'] + 0x5c, p['worker'] + 0x76)
            if seen['boundary']:
                break
            if cpu.reg_read(arm.UC_ARM_REG_SP) != stack:
                raise ValueError('Original post-dequeue invocation did not restore its frame stack')
            completed += 1
        if bytes(cpu.mem_read(state['messages'], 56)) != b''.join(messages):
            raise ValueError('Native invocation changed sender-produced fixture records')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    state['raw_messages'] = b''.join(messages)
    return dict(**seen, native_client_categories=[args[2] for args in jobs], worker_messages_completed=completed,
                sender_bytes_preserved=True, actor_queue_transport_executed=False,
                complete_sender_function_executed=False, client_branch_admission_synthetic=True,
                host_assigned_callback_or_api_return=False)


def replay(directory, case):
    data, p = profile(directory)
    cpu = machine(data, [])
    cpu.mem_map(0x1700000, 0x440000)
    state = setup(cpu, directory, **case)
    result = prepare(cpu, directory, state)
    immediate = case.get('already_complete', False)
    busy = case.get('kernel_busy', False)
    error = case.get('context', 0) != 0 or case.get('masked', False)
    expected_bits = case.get('initial_bits', 0) | (p['masks'][1] if immediate and not error and not busy else 0)
    pending = struct.unpack('<3I', cpu.mem_read(p['root'], 12))
    if (result['native_client_categories'] != [0, 2]
            or pending[0] != p['callbacks'][0] | 1
            or pending[2] != (0 if immediate else p['callbacks'][1] | 1)
            or struct.unpack('<I', cpu.mem_read(state['event'] + 12, 4))[0] != expected_bits
            or result['event_statuses'] != ([] if not immediate or busy else [-25] if error else [0])
            or result['callbacks'] != ([1] if immediate else [])
            or result['worker_messages_completed'] != (1 if busy else 2)
            or bytes(cpu.mem_read(state['event'] - 4, 4)) != b'\x6b' * 4
            or bytes(cpu.mem_read(state['event'] + 16, 4)) != b'\x6b' * 4):
        raise ValueError('Native completion registration/event behavior differs')
    return dict(**result, completion_pending=bool(pending[2]), unrelated_start_callback_preserved=True,
                event_bits=expected_bits, event_id=p['event_id'], event_mask=p['masks'][1],
                synthetic_os_event_and_completion_state=True, waiting_capture_task_woken=False)


def compare(c2, reference):
    inputs = [dict(already_complete=done, initial_bits=bits) for done in (False, True) for bits in (0, 0x204)]
    inputs += [dict(already_complete=True, masked=True), dict(already_complete=True, context=1),
               dict(already_complete=True, kernel_busy=True)]
    rows = []
    for args in inputs:
        a, b = replay(c2, args), replay(reference, args)
        if a != b:
            raise ValueError('C2/A7CR native completion registration/event paths differ')
        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-completion/1', paired_cases=len(rows), cases=rows,
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
