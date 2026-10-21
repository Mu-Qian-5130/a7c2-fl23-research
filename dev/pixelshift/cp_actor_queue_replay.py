"""Execute original CP actor message-buffer APIs on synthetic OS/queue data.

Native send/receive, ring headers/alignment/wrap and memcpy execute without
host transport or return substitution. Empty blocking receive and contention
stop before waiting. Configuration and task state remain synthetic; this is
not cross-task scheduling, hardware transport or a physical capture result.
"""
import argparse
from collections import deque
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_completion_replay import profile as completion_profile
from cp_native_mutex_replay import profile as kernel_profile, setup as setup_kernel
from cp_sequence_replay import machine
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_ARM
    data, completion = completion_profile(directory)
    _, kernel = kernel_profile(directory)
    thumb, arm = Cs(CS_ARCH_ARM, CS_MODE_THUMB), Cs(CS_ARCH_ARM, CS_MODE_ARM)

    def code(at, size, decoder=arm):
        return list(decoder.disasm(data[at - 0x108000:at - 0x108000 + size], at))

    def literal(at, size, register):
        values = [v for r, v in literals(code(at, size)) if r == register]
        if len(values) != 1:
            raise ValueError('Native actor-queue binding is not unique')
        return values[0]

    def call(at, decoder=arm):
        rows = code(at, 4, decoder)
        if len(rows) != 1 or rows[0].mnemonic not in ('bl', 'blx'):
            raise ValueError('Original actor-queue call changed')
        return int(rows[0].op_str.lstrip('#'), 0)

    send = completion['queue_send']
    receive = call(completion['worker'] + 0x2e, thumb)
    dequeue_helper = call(receive + 0x238)
    flush_helper = call(receive + 0x244)
    copy = call(dequeue_helper + 0x64)
    table = literal(send + 0x88, 12, 'r1')
    if table != literal(receive + 0xa0, 0x14, 'r1') or literal(receive + 0xa0, 0x14, 'r4') != kernel['guard']:
        raise ValueError('Native actor send/receive do not share the inspected table/guard')
    maximum = code(send + 0x64, 8)
    if [i.mnemonic for i in maximum] != ['movwge', 'movtge']:
        raise ValueError('Native actor-queue ID bound changed')
    lo, hi = [int(i.op_str.split('#')[1], 0) for i in maximum]
    maximum_id = struct.unpack_from('<I', data, (lo | hi << 16) - 0x108000)[0]
    initializer = code(completion['initialize'] + 0x14, 4, thumb)
    if initializer[0].mnemonic != 'movs' or initializer[1].op_str != 'r1, [r0, #0x18]':
        raise ValueError('Original actor queue ID initialization changed')
    ident = int(initializer[0].op_str.split('#')[1], 0)
    regions = [(send, send + 0x3f8), (receive, receive + 0x344),
               (dequeue_helper, dequeue_helper + 0x11c), (flush_helper, flush_helper + 0x190),
               (copy, copy + 0x300)]
    waits = [i.address for lo, end in regions for i in code(lo, end - lo) if i.mnemonic in ('wfe', 'wfi')]
    return data, dict(send=send, receive=receive, table=table, ident=ident, maximum_id=maximum_id,
                      guard=kernel['guard'], copy=copy, regions=regions, waits=waits,
                      receive_wait=receive + 0x1bc)


def setup(cpu, directory, *, kernel_state=None, capacity=128, start=0, context=0, masked=False,
          dispatch=True, kernel_busy=False):
    _, p = profile(directory)
    kernel = setup_kernel(cpu, directory, context=context, masked=masked, dispatch=dispatch) if kernel_state is None else kernel_state
    if not any(lo <= 0x31000000 <= hi for lo, hi, _ in cpu.mem_regions()):
        cpu.mem_map(0x31000000, 0x10000)
    root, attrs, ring = p['table'] + 40 * (p['ident'] - 1), 0x31001000, 0x31002000
    page = root & ~4095
    if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
        cpu.mem_map(page, 4096)
    cpu.mem_write(attrs, struct.pack('<3I', 0, 28, capacity))
    cpu.mem_write(root, struct.pack('<10I', root, root, attrs, root + 12, root + 12, ring, capacity, start, start, 0))
    cpu.mem_write(ring - 4, b'\x6b' * 4 + bytes(capacity) + b'\x6b' * 4)
    if kernel_busy:
        cpu.mem_write(p['guard'], struct.pack('<I', 1))
    return dict(kernel=kernel, root=root, attrs=attrs, ring=ring, capacity=capacity, start=start,
                source=0x31004000, destination=0x31003000,
                writes=[(root, 40), (ring, capacity), (p['guard'], 4)])


def replay(directory, case):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    data, p = profile(directory)
    cpu = machine(data, [])
    state = setup(cpu, directory, **{k: case[k] for k in ('capacity', 'start', 'context', 'masked', 'dispatch', 'kernel_busy') if k in case})
    root, ring, stack, finish = state['root'], state['ring'], 0x3001f000, 0x3001e000
    pending, rows, copies, boundary = deque(), [], [], None
    sent_cost, received_cost = 0, 0

    def hook(uc, at, size, unused):
        nonlocal boundary
        if at == p['receive_wait'] or at in p['waits']:
            boundary = 'receive_wait_transition' if at == p['receive_wait'] else 'wait_for_event'
            uc.emu_stop()
            return
        if at == p['copy']:
            copies.append(uc.reg_read(arm.UC_ARM_REG_R2))
        if not any(lo <= at and at + size <= hi for lo, hi in p['regions']):
            raise ValueError('Native queue reached an unmodeled task/waiter helper: ' + hex(at))

    def write_hook(uc, access, address, size, value, unused):
        allowed = state['writes'] + [(state['destination'], 64), (stack - 2048, 2048)]
        if not any(lo <= address and address + size <= lo + length for lo, length in allowed):
            raise ValueError('Native actor queue wrote unrelated state: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    for op in case['ops']:
        before = bytes(cpu.mem_read(root, 40)), bytes(cpu.mem_read(ring, state['capacity']))
        raw = bytes.fromhex(op.get('payload', ''))
        cpu.mem_write(state['source'], raw)
        cpu.mem_write(state['destination'], b'\x6b' * 64)
        send = op['call'] == 'send'
        cpu.reg_write(arm.UC_ARM_REG_R0, op.get('ident', p['ident']))
        cpu.reg_write(arm.UC_ARM_REG_R1, state['source'] if send else state['destination'])
        cpu.reg_write(arm.UC_ARM_REG_R2, len(raw) if send else op.get('timeout', 0) & 0xffffffff)
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(p[op['call']], finish, count=10000)
        value = cpu.reg_read(arm.UC_ARM_REG_R0)
        status = None if boundary else value if value < 0x80000000 else value - 0x100000000
        if status != op['status'] or boundary != op.get('boundary'):
            raise ValueError('Native actor-queue status/wait boundary differs')
        if boundary is None and (cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack):
            raise ValueError('Original actor-queue API did not restore its own stack')
        if status is not None and status >= 0:
            if send:
                pending.append(raw)
                sent_cost += 4 + (len(raw) + 3) // 4 * 4
                if bytes(cpu.mem_read(state['source'], len(raw))) != raw:
                    raise ValueError('Native send changed its input payload')
            else:
                expected = pending.popleft()
                if status != len(expected) or bytes(cpu.mem_read(state['destination'], 64)) != expected + b'\x6b' * (64 - len(expected)):
                    raise ValueError('Native receive did not preserve FIFO payload/length/bounds')
                received_cost += 4 + (len(expected) + 3) // 4 * 4
        elif before != (bytes(cpu.mem_read(root, 40)), bytes(cpu.mem_read(ring, state['capacity']))):
            raise ValueError('Rejected/waiting queue operation changed ring/metadata')
        if not send and (status is None or status < 0) and bytes(cpu.mem_read(state['destination'], 64)) != b'\x6b' * 64:
            raise ValueError('Rejected receive copied unaccepted message bytes')
        words = list(struct.unpack('<10I', cpu.mem_read(root, 40)))
        expected_words = [root, root, state['attrs'], root + 12, root + 12, ring,
                          state['capacity'] - sent_cost + received_cost,
                          (state['start'] + received_cost) % state['capacity'],
                          (state['start'] + sent_cost) % state['capacity'], len(pending)]
        if (words != expected_words or bytes(cpu.mem_read(ring - 4, 4)) != b'\x6b' * 4
                or bytes(cpu.mem_read(ring + state['capacity'], 4)) != b'\x6b' * 4):
            raise ValueError('Native actor-queue ring indices/count/alignment/bounds differ')
        rows.append(dict(call=op['call'], status=status, boundary=boundary, queued_messages=words[9],
                         free_bytes=words[6], read_index=words[7], write_index=words[8]))
        if boundary:
            break
    return dict(operations=rows, original_memcpy_lengths=copies,
                host_copied_payload_into_receiver=False, host_assigned_api_return=False,
                synthetic_queue_and_os_configuration=True, waiter_enqueue_or_wakeup_executed=False,
                task_switch_to_different_task_executed=False)


def cases(maximum):
    a, b = bytes(range(28)).hex(), bytes(range(100, 128)).hex()
    send = lambda payload, status=0, **kw: dict(call='send', payload=payload, status=status, **kw)
    receive = lambda status, **kw: dict(call='receive', status=status, **kw)
    return [dict(ops=[send(a), send(b), receive(28, timeout=-1), receive(28), receive(-50)]),
            dict(capacity=64, start=52, ops=[send(a), send(b), receive(28), receive(28)]),
            dict(start=124, ops=[send('ab'), send('0102030405'), send(bytes(range(13)).hex()), receive(1), receive(5), receive(13)]),
            dict(capacity=32, ops=[send(a), send(b, -50), receive(28), receive(-50)]),
            dict(ops=[send('', -17), send(bytes(29).hex(), -17), send(a, -18, ident=0), send(a, -18, ident=maximum + 1)]),
            dict(ops=[receive(-18, ident=0), receive(-18, ident=maximum + 1), receive(-17, timeout=-2)]),
            dict(context=1, ops=[receive(-25)]), dict(masked=True, ops=[receive(-25)]),
            dict(dispatch=False, ops=[receive(-25)]),
            dict(ops=[receive(None, timeout=-1, boundary='receive_wait_transition')]),
            dict(kernel_busy=True, ops=[send(a, None, boundary='wait_for_event')]),
            dict(context=1, ops=[send(a)])]


def compare(c2, reference):
    _, p = profile(c2)
    _, r = profile(reference)
    if p['maximum_id'] != r['maximum_id'] or p['ident'] != r['ident']:
        raise ValueError('C2/A7CR queue ID/bounds differ')
    rows = []
    for args in cases(p['maximum_id']):
        a, b = replay(c2, args), replay(reference, args)
        if a != b:
            raise ValueError('C2/A7CR native actor-queue behavior differs')
        rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-actor-queue/1', paired_cases=len(rows), cases=rows,
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
