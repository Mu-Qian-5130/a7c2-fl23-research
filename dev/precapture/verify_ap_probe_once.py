"""AP one-shot component UNIT MODELS; never a live/native IPC success claim.

The header fixture is built by original kernel constructor instructions on
synthetic memory, stopping at the pool API and resuming an independent slice.
Controller tests then deliberately model ioctl outcomes, including success,
failure and buffers disappearing during handoff/free. No real API executes.
"""

import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import UC_HOOK_CODE, UC_HOOK_INTR
from unicorn import arm64_const as reg
from support.kernel import UIPC_SHA
from support.uipc import library, original_header
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM, STACK, STOP

SHARED, SIZE, IOCTL = 0x60000000, 0x200000, 0x21000000
BLOCK, MESSAGE = SHARED+0x1000, SHARED+0x1040
BIND, STATE = MEM+0x200, MEM
WANTED = ('precapture_probe_once', 'precapture_probe_native_ioctl')


def q(v):
    return struct.pack('<Q', v)


def controller_case(elf, header, sourced_header, case):
    u, sym = image_loader(elf, 'aarch64', WANTED)
    u.mem_map(SHARED, SIZE);u.mem_map(IOCTL, 4096)
    u.mem_write(BLOCK, header)
    binding = [77, 0, SHARED, SIZE]
    for index, value in case.get('binding', {}).items():
        binding[index] = value
    u.mem_write(BIND, struct.pack('<iIQQ', *binding))
    u.mem_write(STATE, bytes(72))
    if case.get('used'):
        u.mem_write(STATE+68, b'\x01')
    original_state = bytes(u.mem_read(STATE, 72))
    calls, mapped = [], True
    nonce, mode = case.get('nonce', 0x7ce11234), case.get('mode', 1)
    def finish_callback(cpu, result):
        for i in range(1, 18):
            cpu.reg_write(getattr(reg, f'UC_ARM64_REG_X{i}'), 0xde000000+i)
        cpu.reg_write(reg.UC_ARM64_REG_X0, result & ((1 << 64)-1))
        cpu.reg_write(reg.UC_ARM64_REG_PC, cpu.reg_read(reg.UC_ARM64_REG_LR))
    def invoke(cpu, at, size, _):
        nonlocal mapped
        if at != IOCTL:
            return
        fd, command, ptr = [cpu.reg_read(r) for r in
            (reg.UC_ARM64_REG_X0, reg.UC_ARM64_REG_X1, reg.UC_ARM64_REG_X2)]
        assert fd == 77
        route, reserved, argument = struct.unpack('<IIQ', bytes(cpu.mem_read(ptr, 16)))
        assert (route, reserved) == (0x90030001, 0)
        calls.append(command)
        current = struct.unpack('<10I3qQ', bytes(cpu.mem_read(STATE, 72)))
        if command == 0x8000000a:
            assert calls == [command] and current[2] == 1 and current[6] == 1
            out, count, wait = struct.unpack('<QII', bytes(cpu.mem_read(argument, 16)))
            assert count == 16 and wait == 0 and bytes(cpu.mem_read(out, 8)) == bytes(8)
            result = case.get('allocation_status', 0)
            pointer = case.get('message', MESSAGE if not result else 0)
            cpu.mem_write(out, q(pointer))
            if case.get('bad_header'):
                cpu.mem_write(MESSAGE-8, struct.pack('<I', 24))
            finish_callback(cpu, result)
        elif command == 0x80000004:
            assert calls == [0x8000000a, command] and argument == MESSAGE
            assert current[2] == 3 and current[3] == 1 and current[7] == 1
            expected = struct.pack('<BBHIII', 5, 0, 0x4172, nonce, 0, 0)
            assert bytes(cpu.mem_read(MESSAGE, 16)) == expected
            modified = bytes(cpu.mem_read(BLOCK, 128))
            expected_block = bytearray(sourced_header)
            expected_block[64:80] = expected
            assert modified == bytes(expected_block)
            # Accepted or ambiguous sends MAY have consumed/freed the buffer
            # before returning. Any later read/free by the controller fails.
            cpu.mem_unmap(SHARED, SIZE);mapped = False
            finish_callback(cpu, case.get('send_status', 0))
        elif command == 0x8000000b:
            assert mode == 0 and calls == [0x8000000a, command] and argument == MESSAGE
            assert current[2] == 5 and current[8] == 1
            assert bytes(cpu.mem_read(BLOCK, 128)) == header
            cpu.mem_unmap(SHARED, SIZE);mapped = False
            finish_callback(cpu, case.get('release_status', 0))
        else:
            raise AssertionError('Unplanned ioctl')
    u.hook_add(UC_HOOK_CODE, invoke)
    def run():
        for r, value in ((reg.UC_ARM64_REG_X0, 0 if case.get('null_binding') else BIND),
                (reg.UC_ARM64_REG_X1, STATE), (reg.UC_ARM64_REG_X2, nonce),
                (reg.UC_ARM64_REG_X3, mode),
                (reg.UC_ARM64_REG_X4, 0 if case.get('null_callback') else IOCTL),
                (reg.UC_ARM64_REG_SP, STACK+0x3000), (reg.UC_ARM64_REG_LR, STOP)):
            u.reg_write(r, value & ((1 << 64)-1))
        u.emu_start(sym[WANTED[0]], STOP, count=5000)
        assert u.reg_read(reg.UC_ARM64_REG_PC) == STOP
        return u.reg_read(reg.UC_ARM64_REG_X0) & 0xffffffff
    got = run()
    assert got == case.get('return', -5) & 0xffffffff, (case, hex(got))
    data = bytes(u.mem_read(STATE, 72))
    state = struct.unpack('<10I3qQ', data)
    assert calls == case['calls'], case
    if not calls:
        assert data == original_state
    else:
        assert state[0:2] == (0x31514f50, 1)
        assert (state[2], state[3]) == case['terminal']
        assert state[6:9] == (1, int(0x80000004 in calls), int(0x8000000b in calls))
        # A consumed handle cannot allocate/send/free a second time, even
        # after the shared mapping disappears in an ambiguous outcome.
        old_calls = list(calls)
        assert run() == (-16 & 0xffffffff)
        assert calls == old_calls and bytes(u.mem_read(STATE, 72)) == data
    return dict(case=case['name'], model_calls=[hex(c) for c in calls],
        terminal_phase=state[2], terminal_ownership=state[3],
        native_operations_executed=False, buffer_disappeared_during_model_call=not mapped)


def native_syscall_cases(elf):
    cases = []
    for result in (0, -1021):
        u, sym = image_loader(elf, 'aarch64', WANTED)
        seen = []
        def trap(cpu, interrupt, _):
            assert interrupt == 2 and cpu.reg_read(reg.UC_ARM64_REG_X8) == 29
            args = [cpu.reg_read(r) for r in
                (reg.UC_ARM64_REG_X0, reg.UC_ARM64_REG_X1, reg.UC_ARM64_REG_X2)]
            assert args == [77, 0x80000004, MEM+0x100]
            seen.append(args)
            cpu.reg_write(reg.UC_ARM64_REG_X0, result & ((1 << 64)-1))
        u.hook_add(UC_HOOK_INTR, trap)
        for r, value in ((reg.UC_ARM64_REG_X0, 77), (reg.UC_ARM64_REG_X1, 0x80000004),
                (reg.UC_ARM64_REG_X2, MEM+0x100), (reg.UC_ARM64_REG_SP, STACK+0x3000),
                (reg.UC_ARM64_REG_LR, STOP)):
            u.reg_write(r, value)
        u.emu_start(sym[WANTED[1]], STOP, count=30)
        assert len(seen) == 1 and u.reg_read(reg.UC_ARM64_REG_PC) == STOP
        assert u.reg_read(reg.UC_ARM64_REG_X0) == result & ((1 << 64)-1)
        cases.append(dict(explicit_syscall_model_result=result, SVC_count=1, real_syscall=False))
    return cases


def native_wire_cases(path):
    result = []
    for entry, command in ((0x3e98, 0x8000000a), (0x3a10, 0x80000004), (0x3f28, 0x8000000b)):
        u, entries = library(path)
        observed = []
        def stop(cpu, at, n, _):
            if at == entries['ioctl']:
                observed.append(at);cpu.emu_stop()
        u.hook_add(UC_HOOK_CODE, stop)
        for r, value in ((reg.UC_ARM64_REG_X0, 0x90030001),
                (reg.UC_ARM64_REG_X1, MEM+0x100 if entry == 0x3e98 else MESSAGE),
                (reg.UC_ARM64_REG_X2, 16), (reg.UC_ARM64_REG_X3, 0),
                (reg.UC_ARM64_REG_SP, STACK+0x8000), (reg.UC_ARM64_REG_LR, STOP)):
            u.reg_write(r, value)
        u.emu_start(entry, 0xffffffffffffffff, count=100)
        assert observed == [entries['ioctl']]
        assert u.reg_read(reg.UC_ARM64_REG_X0) == 77
        assert u.reg_read(reg.UC_ARM64_REG_X1) & 0xffffffff == command
        packet = u.reg_read(reg.UC_ARM64_REG_X2)
        route, argument = struct.unpack('<I4xQ', bytes(u.mem_read(packet, 16)))
        assert route == 0x90030001
        if entry == 0x3e98:
            assert struct.unpack('<QII', bytes(u.mem_read(argument, 16))) == (MEM+0x100, 16, 0)
        else:
            assert argument == MESSAGE
        result.append(dict(native_library_entry=hex(entry), command=hex(command),
            ioctl_executed=False, fourth_allocation_argument=0 if entry == 0x3e98 else None))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uipc-kernel', type=Path, required=True)
    p.add_argument('--uipc', type=Path, required=True)
    p.add_argument('--zig', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raw = a.uipc_kernel.read_bytes()
    header, sourced_header = original_header(raw, a.uipc.read_bytes())
    wires = native_wire_cases(a.uipc)
    a.output.mkdir(parents=True, exist_ok=False)
    elf = a.output/'NOT-INSTALLABLE-ap-probe-once.elf'
    compile_shared(a.zig, 'aarch64', elf,
        [Path(__file__).with_name('ap_probe_once.c')])
    A, S, F = 0x8000000a, 0x80000004, 0x8000000b
    scenarios = [dict(name='cancel', mode=0, calls=[A,F], terminal=(6,0), **{'return':0}),
        dict(name='cancel-free-unknown', mode=0, release_status=-5, calls=[A,F], terminal=(8,3)),
        dict(name='send-handoff', calls=[A,S], terminal=(4,2), **{'return':0}),
        dict(name='header-mismatch', bad_header=True, calls=[A], terminal=(8,3)),
        dict(name='allocated-null', message=0, calls=[A], terminal=(8,3)),
        dict(name='allocated-unaligned', message=MESSAGE+1, calls=[A], terminal=(8,3)),
        dict(name='allocated-outside', message=0x70000000, calls=[A], terminal=(8,3)),
        dict(name='allocated-prefix', message=SHARED, calls=[A], terminal=(8,3)),
        dict(name='allocated-tail', message=SHARED+SIZE-64+0x40, calls=[A], terminal=(8,3)),
        dict(name='failed-with-pointer', allocation_status=-1023, message=MESSAGE, calls=[A], terminal=(8,3))]
    for value in (-22, -1021, -1023, -1024):
        scenarios.append(dict(name=f'allocation-rejected-{value}', allocation_status=value, calls=[A], terminal=(7,0)))
    for value in (-4, -5, 1):
        scenarios.append(dict(name=f'allocation-unknown-{value}', allocation_status=value, calls=[A], terminal=(8,3)))
    for value in (-22, -1024, 2, -4, -5, -1021, -1023):
        scenarios.append(dict(name=f'send-unknown-{value}', send_status=value, calls=[A,S], terminal=(8,3)))
    for name, fields in [('bad-fd', {'binding':{0:-1}}), ('bad-reserved', {'binding':{1:1}}),
            ('bad-alignment', {'binding':{2:SHARED+1}}), ('bad-size', {'binding':{3:4096}}),
            ('wrapped-binding', {'binding':{2:0xfffffffffffff000}}), ('zero-base', {'binding':{2:0}}),
            ('bad-mode', {'mode':2}), ('zero-nonce', {'nonce':0}), ('null-binding', {'null_binding':True}),
            ('null-callback', {'null_callback':True})]:
        scenarios.append(dict(name=name, calls=[], **fields, **{'return':-22}))
    scenarios.append(dict(name='used-state', used=True, calls=[], **{'return':-16}))
    results = [controller_case(elf, header, sourced_header, s) for s in scenarios]
    native = native_syscall_cases(elf)
    report = dict(schema='OFFLINE_AP_PROBE_ONCE_UNIT_MODELS/1', camera_io=False,
        kernel_header_fixture_sha256=hashlib.sha256(header).hexdigest(),
        header_source_sha256=UIPC_SHA, compiler_source_sha256=hashlib.sha256(
            Path(__file__).with_name('ap_probe_once.c').read_bytes()).hexdigest(),
        ELF_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(), cases=results, syscall_ABI_models=native,
        native_wire_boundaries=wires, native_source_set_get_matches=True,
        native_source_displacement=-12,
        limits=['ioctl success/failure outcomes are explicit unit models, not successful native service observations',
            'The original header constructor runs only an independent post-pool slice on synthetic memory',
            'Binding validation is structural only; no live source/fd/map adapter or persistent host job fencing exists',
            'Only serialized single-thread calls are tested; local state does not deduplicate concurrent/independent jobs',
            'Call counts are bounded but kernel-call duration is NOT proven',
            'Header/unknown send/free outcomes intentionally remain unresolved; do not automatically reclaim or retry',
            'Unresolved ownership is a live-install blocker, not a successful cancellation/recovery result',
            'There is no worker init, USB command, ROM candidate, CP response or physical pre-capture acceptance'])
    (a.output/'unit-models.private.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(f'AP prototype: {len(results)} ioctl decision models +{len(native)} SVC ABI models /3 native wire boundaries /original source setter+getter. No live binding, kernel call or camera operation.')


if __name__ == '__main__':
    main()
