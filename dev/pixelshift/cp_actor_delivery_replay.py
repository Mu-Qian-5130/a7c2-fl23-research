"""Native client -> complete sender -> message buffer -> bounded worker loop.

Queue configuration and OS/task state are synthetic. Both original senders and
two original receive/dispatch iterations execute; the host never copies a
payload into the receiver. The worker pauses before a third receive and does
not return. Actor boundaries are invoked by the harness, not a real task switch.
No waiting capture task, physical completion or hardware transport is implied.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_actor_queue_replay import profile as queue_profile, setup as setup_queue
from cp_completion_replay import profile as completion_profile, setup as setup_completion, observer
from cp_sequence_replay import machine


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_ARM
    data, completion = completion_profile(directory)
    _, queue = queue_profile(directory)
    thumb, arm = Cs(CS_ARCH_ARM, CS_MODE_THUMB), Cs(CS_ARCH_ARM, CS_MODE_ARM)

    def code(at, size, decoder):
        return list(decoder.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    call = code(completion['worker'] + 0x38, 4, thumb)
    if len(call) != 1 or call[0].mnemonic != 'blx':
        raise ValueError('Native worker profiling-guard call changed')
    profiling = int(call[0].op_str.lstrip('#'), 0)
    flag = code(profiling + 12, 8, arm)
    if [i.mnemonic for i in flag] != ['movwne', 'movtne']:
        raise ValueError('Original profiling-enable guard changed')
    lo, hi = [int(i.op_str.split('#')[1], 0) for i in flag]
    exit_branch = code(profiling + 0x1c, 4, arm)[0]
    if exit_branch.mnemonic != 'beq':
        raise ValueError('Native disabled-profiling exit changed')
    profiling_exit = int(exit_branch.op_str.lstrip('#'), 0)
    regions = completion['regions'] + queue['regions'] + [
        (completion['client'], completion['client'] + 0x50),
        (completion['sender'], completion['sender'] + 0x98),
        (completion['worker'], completion['worker'] + 0x78),
        (profiling, profiling + 0x20), (profiling_exit, profiling_exit + 4)]
    return data, dict(completion=completion, queue=queue, profiling=profiling,
                      profiling_flag=lo | hi << 16, regions=regions)


def prepare(cpu, directory, state, *, start=0):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    c, q = p['completion'], p['queue']
    queue = setup_queue(cpu, directory, kernel_state=state['kernel'], start=start)
    state['queue_state'] = queue
    if bytes(cpu.mem_read(p['profiling_flag'], 4)) != bytes(4):
        raise ValueError('This bounded worker fixture requires profiling disabled by its input state')
    seen, observe = observer(cpu, c)
    client_stack, worker_stack, finish = 0x3001d000, 0x3100f000, 0x3001e000
    phase, sent, received, send_statuses, receive_statuses, sender_returns = 'initialize', [], [], [], [], []
    turns, profiling_calls, receive_destination = 0, 0, None

    def signed(value):
        return value if value < 0x80000000 else value - 0x100000000

    def hook(uc, at, size, unused):
        nonlocal turns, profiling_calls, receive_destination
        action = observe(at)
        if action or seen['boundary']:
            return
        if at in q['waits'] or at == q['receive_wait']:
            raise ValueError('Queued positive actor fixture unexpectedly reached a wait')
        if at == q['send']:
            if uc.reg_read(arm.UC_ARM_REG_R0) != q['ident'] or uc.reg_read(arm.UC_ARM_REG_R2) != 28:
                raise ValueError('Original sender did not use its configured native queue/record length')
            sent.append(bytes(uc.mem_read(uc.reg_read(arm.UC_ARM_REG_R1), 28)))
        if at == c['sender'] + 0x2e:
            status = signed(uc.reg_read(arm.UC_ARM_REG_R0))
            send_statuses.append(status)
            if status != 0:
                raise ValueError('Actor sender failed; unqueued records will not be dispatched')
        if at == c['client'] + 0x30:
            sender_returns.append(uc.reg_read(arm.UC_ARM_REG_R0))
        if at == q['receive']:
            receive_destination = uc.reg_read(arm.UC_ARM_REG_R1)
        if at == c['worker'] + 0x32:
            status = signed(uc.reg_read(arm.UC_ARM_REG_R0))
            receive_statuses.append(status)
            if status != 28 or receive_destination is None:
                raise ValueError('Worker receive failed; stale frame data will not be invoked')
            received.append(bytes(uc.mem_read(receive_destination, status)))
        if at == p['profiling']:
            profiling_calls += 1
        if phase == 'worker' and at == c['worker'] + 0x76:
            turns += 1
            if turns == 2:
                uc.emu_stop()
                return
        if not any(lo <= at and at + size <= hi for lo, hi in p['regions']):
            raise ValueError('Native actor delivery reached an unmodeled helper: ' + hex(at))

    def write_hook(uc, access, address, size, value, unused):
        allowed = state['writes'] + queue['writes'] + [
            (client_stack - 4096, 4096 + 0x140), (worker_stack - 4096, 4096 + 64)]
        if not any(lo <= address and address + size <= lo + length for lo, length in allowed):
            raise ValueError('Native actor delivery changed unrelated state: ' + hex(address))

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        cpu.reg_write(arm.UC_ARM_REG_SP, client_stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(c['initialize'] | 1, finish, count=1000)
        if cpu.reg_read(arm.UC_ARM_REG_PC) != finish:
            raise ValueError('Original actor initializer did not return')
        phase = 'client'
        cpu.emu_start(c['client'] | 1, c['client'] + 0x50, count=20000)
        sender_returns.append(cpu.reg_read(arm.UC_ARM_REG_R0))
        if (cpu.reg_read(arm.UC_ARM_REG_PC) != c['client'] + 0x50
                or cpu.reg_read(arm.UC_ARM_REG_SP) != client_stack
                or send_statuses != [0, 0] or sender_returns != [1, 1] or len(sent) != 2):
            raise ValueError('Original client/complete sender did not enqueue both records')
        phase = 'worker'
        cpu.reg_write(arm.UC_ARM_REG_R0, c['manager'])
        cpu.reg_write(arm.UC_ARM_REG_SP, worker_stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(c['worker'] | 1, 0, count=30000)
        if (turns != 2 or cpu.reg_read(arm.UC_ARM_REG_PC) != c['worker'] + 0x76
                or sent != received or receive_statuses != [28, 28] or profiling_calls != 2):
            raise ValueError('Original queue/worker did not consume those exact two records')
        words = list(struct.unpack('<10I', cpu.mem_read(queue['root'], 40)))
        if words[6:] != [128, (start + 64) % 128, (start + 64) % 128, 0]:
            raise ValueError('Original actor queue did not restore count/capacity/indices after delivery')
        if (bytes(cpu.mem_read(queue['ring'] - 4, 4)) != b'\x6b' * 4
                or bytes(cpu.mem_read(queue['ring'] + 128, 4)) != b'\x6b' * 4):
            raise ValueError('Native actor queue overran its ring')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    state['raw_messages'] = b''.join(received)
    # Observation snapshots AFTER native receive/dispatch, never receiver input.
    cpu.mem_write(state['messages'], state['raw_messages'])
    state['worker_frame_address'] = cpu.reg_read(arm.UC_ARM_REG_SP)
    state['worker_frame_snapshot'] = bytes(cpu.mem_read(state['worker_frame_address'], worker_stack - state['worker_frame_address']))
    return dict(**seen, native_client_categories=[struct.unpack_from('<I', raw, 20)[0] for raw in sent],
                worker_messages_completed=turns, sender_bytes_preserved=sent == received,
                actor_queue_transport_executed=True, complete_sender_function_executed=True,
                native_send_statuses=send_statuses, native_receive_statuses=receive_statuses,
                native_sender_returns=sender_returns, native_worker_loop_iterations=turns,
                complete_worker_function_returned=False, profiling_guard_calls=profiling_calls,
                profiling_enabled_in_fixture=False, queue_free_bytes=words[6], queue_messages=words[9],
                queue_read_index=words[7], queue_write_index=words[8],
                host_copied_payload_into_receiver=False, host_assigned_callback_or_api_return=False,
                client_branch_admission_synthetic=True, cross_task_scheduling_executed=False)


def replay(directory, case):
    data, p = profile(directory)
    cpu = machine(data, [])
    cpu.mem_map(0x1700000, 0x440000)
    state = setup_completion(cpu, directory, initial_bits=case['initial_bits'], already_complete=case['already_complete'])
    result = prepare(cpu, directory, state, start=case['start'])
    c = p['completion']
    pending = struct.unpack('<3I', cpu.mem_read(c['root'], 12))
    expected_bits = case['initial_bits'] | (c['masks'][1] if case['already_complete'] else 0)
    if (result['native_client_categories'] != [0, 2]
            or pending[0] != c['callbacks'][0] | 1
            or pending[2] != (0 if case['already_complete'] else c['callbacks'][1] | 1)
            or result['event_statuses'] != ([0] if case['already_complete'] else [])
            or struct.unpack('<I', cpu.mem_read(state['event'] + 12, 4))[0] != expected_bits):
        raise ValueError('Queued native actor invocation produced different completion state')
    return dict(**result, completion_pending=bool(pending[2]), event_bits=expected_bits,
                waiting_capture_task_woken=False, synthetic_queue_os_and_completion_state=True)


def compare(c2, reference):
    inputs = [dict(start=start, initial_bits=bits, already_complete=False) for start in (0, 112) for bits in (0, 0x204)]
    inputs += [dict(start=start, initial_bits=0x204, already_complete=True) for start in (0, 112)]
    rows = []
    for args in inputs:
        a, b = replay(c2, args), replay(reference, args)
        if a != b:
            raise ValueError('C2/A7CR native actor delivery differs')
        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-actor-delivery/1', paired_cases=len(rows), cases=rows,
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
