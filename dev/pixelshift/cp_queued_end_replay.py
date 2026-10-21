"""Original CP clear handler -> native queue -> worker -> end/pool/event.

Build the empty-resource group BEFORE worker registration, preserve its paused
callee-saved roles, and enqueue the original 0x40ef handler's actual callable.
The worker invokes end; the harness never jumps to end or supplies an API result.
Actor stack boundaries and OS/pool/admission state remain synthetic. No AP/CP
hardware transport, real task switch, captured-resource release or centering
is established. Resource APIs still stop before execution.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_group_end_replay import profile as group_profile, construct_empty_group
from cp_pool_return_replay import profile as pool_profile, setup as setup_pool, observer as pool_observer
from cp_actor_delivery_replay import profile as delivery_profile, prepare as deliver
from cp_completion_replay import setup as setup_completion, observer as completion_observer
from cp_serial_replay import literals
from cp_sequence_replay import machine


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, group = group_profile(directory)
    _, pool = pool_profile(directory)
    _, delivery = delivery_profile(directory)
    c = delivery['completion']
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def code(at, size):
        return list(md.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def literal(at, size, register):
        values = [v for r, v in literals(code(at, size)) if r == register]
        if len(values) != 1:
            raise ValueError('Queued-end native binding is not unique')
        return values[0]

    def call(at, mnemonic='bl'):
        rows = code(at, 4)
        if len(rows) != 1 or rows[0].mnemonic != mnemonic:
            raise ValueError('Original queued-end call boundary changed')
        return int(rows[0].op_str.lstrip('#'), 0)

    handler = 0x359ed4 if group['end'] == 0x4757e8 else 0x35a034
    if call(handler + 0x2c) != c['sender'] or literal(handler + 0x1e, 12, 'r1') != group['end'] | 1:
        raise ValueError('Native clear handler no longer sends the original group-end callable')
    getter = call(handler + 6)
    if literal(getter, 12, 'r0') != c['manager']:
        raise ValueError('Clear handler does not use the registration actor manager')
    invoker = literal(handler + 0xa, 12, 'r2') & ~1
    if [(i.mnemonic, i.op_str) for i in code(invoker, 4)] != [('ldr', 'r0, [r0, #8]'), ('bx', 'r0')]:
        raise ValueError('Original queued-end invoker changed')
    destructor_thunk = literal(group['descriptor'] + 0x1e, 16, 'r1') & ~1
    fill = [int(i.op_str.lstrip('#'), 0) for i in code(group['constructor'], 0xb6) if i.mnemonic == 'blx']
    if len(fill) != 2:
        raise ValueError('Native empty-group constructor fill helpers changed')
    format_helper = call(group['cleanup'] + 0xe)
    resource_list = call(group['cleanup'] + 0x68)
    flag_getter = call(group['cleanup'] + 0xba)
    flag_clearer = call(group['cleanup'] + 0xc8, 'b.w')
    regions = delivery['regions'] + pool['regions'] + [
        (handler, handler + 0x4c), (getter, getter + 12), (invoker, invoker + 4),
        (group['descriptor'], group['descriptor'] + 0x3c),
        (group['factory'] + 0x3a, group['factory'] + 0xb4),
        (group['constructor'], group['constructor'] + 0xb6),
        (group['addref'], group['addref'] + 0x62), (group['release'], group['release'] + 0xb4),
        (group['cleanup'], group['cleanup'] + 0xd2), (group['end'], group['end'] + 0x5a),
        (destructor_thunk, destructor_thunk + 6), (min(fill), max(fill) + 0x150),
        (format_helper, format_helper + 0x228), (resource_list, resource_list + 0x62),
        (flag_getter, flag_getter + 0x14), (flag_clearer, flag_clearer + 0x24)]
    regions += [(at, at + (12 if index == len(group['reset_chain']) - 1 else 4))
                for index, at in enumerate(group['reset_chain'])]
    return data, dict(group=group, pool=pool, delivery=delivery, completion=c,
                      handler=handler, invoker=invoker, regions=regions)


def replay(directory, *, references=1, resource=False, start=0):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    g, c, q = p['group'], p['completion'], p['delivery']['queue']
    cpu = machine(data, [])
    cpu.mem_map(0x1700000, 0x440000)
    cpu.mem_map(g['mode'] & ~4095, 4096)
    body, stack, client_stack, finish = 0x30008000, 0x3001f000, 0x3001d000, 0x3001e000
    pool = setup_pool(cpu, directory, base=body, initialize_nodes=False)
    state = setup_completion(cpu, directory, kernel_state=pool['mutex'], initial_bits=0x204)
    cpu.mem_write(body - 4, b'\x6b' * 4 + bytes(0x5c20) + b'\x6b' * 4)
    cpu.mem_write(g['mode'], struct.pack('<I', 1))
    cpu.mem_write(g['cleanup_flag'], b'\1')
    pool_seen, observe_pool = pool_observer(cpu, p['pool'])
    completion_seen, observe_completion = completion_observer(cpu, c)
    phase, boundary, sent, received = 'descriptor', None, None, None
    send_status, sender_return, receive_status = None, None, None
    receive_destination, end_entries, worker_turns = None, 0, 0

    def hook(uc, at, size, unused):
        nonlocal boundary, sent, received, send_status, sender_return, receive_status, receive_destination, end_entries, worker_turns
        if observe_completion(at):
            return
        observe_pool(at)
        if completion_seen['boundary'] or pool_seen['boundary']:
            boundary = completion_seen['boundary'] or pool_seen['boundary']
            uc.emu_stop()
            return
        if at == g['resource']:
            boundary = 'resource_release'
            uc.emu_stop()
            return
        if phase == 'clear_handler' and at == q['send']:
            if uc.reg_read(arm.UC_ARM_REG_R0) != q['ident'] or uc.reg_read(arm.UC_ARM_REG_R2) != 28:
                raise ValueError('Native clear sender changed its queue/record length')
            sent = bytes(uc.mem_read(uc.reg_read(arm.UC_ARM_REG_R1), 28))
        if phase == 'clear_handler' and at == c['sender'] + 0x2e:
            send_status = uc.reg_read(arm.UC_ARM_REG_R0)
            if send_status != 0:
                raise ValueError('Native clear was not queued; the worker will not parse stale bytes')
        if phase == 'clear_handler' and at == p['handler'] + 0x30:
            sender_return = uc.reg_read(arm.UC_ARM_REG_R0)
        if phase == 'worker_clear' and at == q['receive']:
            receive_destination = uc.reg_read(arm.UC_ARM_REG_R1)
        if phase == 'worker_clear' and at == c['worker'] + 0x32:
            receive_status = uc.reg_read(arm.UC_ARM_REG_R0)
            if receive_status != 28 or receive_destination is None:
                raise ValueError('Native worker did not receive the queued clear callable')
            received = bytes(uc.mem_read(receive_destination, 28))
        if at == g['end']:
            end_entries += 1
            if phase != 'worker_clear' or uc.reg_read(arm.UC_ARM_REG_LR) & ~1 != c['worker'] + 0x76:
                raise ValueError('Group end was not invoked by the actual worker callable')
        if phase == 'worker_clear' and at == c['worker'] + 0x76 and received is not None:
            worker_turns += 1
            uc.emu_stop()
            return
        if not any(lo <= at and at + size <= hi for lo, hi in p['regions']):
            raise ValueError('Queued native end reached unmodeled code: ' + hex(at))

    def write_hook(uc, access, address, size, value, unused):
        allowed = pool['writes'] + state['writes'] + [
            (body, 0x5c20), (g['ordinal'], 1), (g['ended'], 1), (g['group'], 4), (g['cleanup_flag'], 1),
            (stack - 4096, 4096 + (64 if phase == 'descriptor' else 0)),
            (client_stack - 4096, 4096 + 0x140)]
        if 'queue_state' in state:
            allowed += state['queue_state']['writes'] + [(0x3100f000 - 4096, 4096 + 64)]
        if not any(lo <= address and address + size <= lo + length for lo, length in allowed):
            raise ValueError('Queued group-end changed unrelated state: ' + hex(address))

    def run_stage(stage, at, stop):
        nonlocal phase
        phase = stage
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        end = finish if stop is None else stop
        cpu.emu_start(at | 1, end, count=30000)
        if cpu.reg_read(arm.UC_ARM_REG_PC) != end:
            raise ValueError('Original group construction missed its boundary')

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        construct_empty_group(cpu, g, body, references, resource, run_stage)
        cpu.mem_write(g['group'], struct.pack('<I', body if references else 0))
        cpu.mem_write(g['ordinal'], b'\3')
        phase = 'registration'
        registration = deliver(cpu, directory, state, start=start)
        worker_sp = state['worker_frame_address']
        worker_before = state['worker_frame_snapshot']
        preserved = [getattr(arm, 'UC_ARM_REG_R' + str(i)) for i in range(4, 12)]
        callee_values = [cpu.reg_read(r) for r in preserved]
        phase = 'clear_handler'
        cpu.reg_write(arm.UC_ARM_REG_SP, client_stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(p['handler'] | 1, finish, count=30000)
        expected = struct.pack('<7I', p['invoker'] | 1, 0, g['end'] | 1, 0, 0, 0, 0)
        if (cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != client_stack
                or cpu.reg_read(arm.UC_ARM_REG_R0) != 1 or send_status != 0 or sender_return != 1 or sent != expected
                or [cpu.reg_read(r) for r in preserved] != callee_values
                or bytes(cpu.mem_read(worker_sp, len(worker_before))) != worker_before):
            raise ValueError('Native clear handler/callable queueing damaged the paused worker roles/frame')
        phase = 'worker_clear'
        # Explicit harness actor-stack boundary; no API return or GPR/FPU restore.
        cpu.reg_write(arm.UC_ARM_REG_SP, worker_sp)
        cpu.emu_start((c['worker'] + 0x76) | 1, 0, count=50000)
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    recycled = references == 1 and not resource
    reference_count = struct.unpack('<I', cpu.mem_read(body + 4, 4))[0] if references else None
    words = list(struct.unpack('<10I', cpu.mem_read(state['queue_state']['root'], 40)))
    expected_index = (start + 96) % 128
    if (received != sent or receive_status != 28 or end_entries != 1
            or reference_count != (references - 1 if references else None)
            or words[6:] != [128, expected_index, expected_index, 0]
            or worker_turns != int(not resource) or boundary != ('resource_release' if resource else None)
            or struct.unpack('<I', cpu.mem_read(g['group'], 4))[0] != (body if resource else 0)
            or struct.unpack('<I', cpu.mem_read(g['callback'], 4))[0] != (c['callbacks'][1] | 1 if resource else 0)
            or cpu.mem_read(g['ordinal'], 1)[0] != 0 or cpu.mem_read(g['ended'], 1)[0] != 1
            or struct.unpack('<I', cpu.mem_read(state['event'] + 12, 4))[0] != (0x204 if resource else 0x10204)
            or completion_seen['event_statuses'] != ([] if resource else [0])
            or pool_seen['pool_entry_executed'] != recycled
            or struct.unpack('<I', cpu.mem_read(p['pool']['root'] + 8, 4))[0] != int(recycled)
            or pool_seen['same_task_scheduler_entries'] != int(recycled)
            or bytes(cpu.mem_read(g['mode'], 4)) != struct.pack('<I', 1)
            or bytes(cpu.mem_read(body - 4, 4)) != b'\x6b' * 4 or bytes(cpu.mem_read(body + 0x5c20, 4)) != b'\x6b' * 4
            or bytes(cpu.mem_read(state['messages'], 56)) != state['raw_messages']):
        raise ValueError('Native queued clear/end/pool/event ownership differs')
    if (bytes(cpu.mem_read(pool['mutex']['lock']['object'], 12)) != bytes(12)
            or bytes(cpu.mem_read(pool['mutex']['core'] + 0x10, 4)) != bytes(4)
            or bytes(cpu.mem_read(pool['mutex']['entry'] + 12, 8)) != bytes(8)
            or bytes(cpu.mem_read(pool['mutex']['task'] + 0x54, 4)) != bytes(4)
            or bytes(cpu.mem_read(p['pool']['mutex']['guard'], 4)) != bytes(4)
            or struct.unpack('<I', cpu.mem_read(c['root'], 4))[0] != c['callbacks'][0] | 1):
        raise ValueError('Queued native end leaked lock ownership or changed the unrelated callback')
    if not resource and (cpu.reg_read(arm.UC_ARM_REG_PC) != c['worker'] + 0x76
                         or cpu.reg_read(arm.UC_ARM_REG_SP) != worker_sp
                         or bytes(cpu.mem_read(worker_sp + 32, len(worker_before) - 32)) != worker_before[32:]):
        raise ValueError('Queued end failed to unwind to the actual worker loop/callee-save frame')
    return dict(clear_send_status=send_status, complete_sender_return=sender_return, clear_handler_return=1,
                clear_receive_length=receive_status, native_worker_end_invocations=end_entries,
                clear_worker_message_completed=not resource, boundary=boundary or 'worker_loop_boundary',
                queued_clear_record_preserved=sent == received, native_registration=registration,
                queue_free_bytes=words[6], queue_messages=words[9], queue_index=words[7],
                object_recycled=recycled, reference_count=reference_count, group_pointer_retained=resource,
                event_bits=0x204 if resource else 0x10204, native_completion=completion_seen,
                worker_roles_preserved_by_native_callees=True, host_restored_gpr_or_fpu_values=False,
                harness_actor_stack_boundaries=True, direct_host_group_end_invocation=False,
                ap_to_cp_transport_executed=False, waiting_capture_task_woken=False,
                captured_resource_release_executed=False, synthetic_pool_task_and_queue_configuration=True)


def compare(c2, reference):
    inputs = [dict(references=n) for n in (0, 1, 2)] + [dict(resource=True), dict(start=52), dict(start=112)]
    rows = []
    for args in inputs:
        a, b = replay(c2, **args), replay(reference, **args)
        if a != b:
            raise ValueError('C2/A7CR queued native clear/end lifecycle differs')
        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-queued-end/1', paired_cases=len(rows), cases=rows,
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
