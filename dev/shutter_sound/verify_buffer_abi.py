"""Offline execution of original sound-buffer allocation and completion code.

OSAL, allocator replies and futex wakes are explicitly simulated. This checks
argument/reply layouts and waiting behavior, NOT live ownership, DMA success,
codec rate, available memory or permission to install a custom sound.
"""
import argparse
import json
from pathlib import Path
import struct


ALLOC = 0x35521a0
WAIT = 0x31018f0
RAM, STACK, STOP = 0x10000000, 0x20000000, 0x40000000


def machine(ap, ranges):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    from unicorn.arm64_const import UC_ARM64_REG_SP, UC_ARM64_REG_X30
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    pages = set()
    for start, size in ranges:
        for page in range(start & ~4095, (start + size + 4095) & ~4095, 4096):
            if page not in pages:
                cpu.mem_map(page, 4096)
                pages.add(page)
        if start + size > len(ap):
            raise ValueError('Original AP block is truncated')
        cpu.mem_write(start, ap[start:start + size])
    for at, size in ((RAM, 0x10000), (STACK, 0x10000), (STOP, 4096)):
        cpu.mem_map(at, size)
    cpu.reg_write(UC_ARM64_REG_SP, STACK + 0xf000)
    cpu.reg_write(UC_ARM64_REG_X30, STOP)
    return cpu


def allocation_case(ap, space, *, reply_status=0, transport_status=0):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
        UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X30, UC_ARM64_REG_PC)
    # Stop before every external function; none of those functions execute.
    externals = (0x251db60, 0x34e4160, 0x1660060, 0x165d600,
                 0x165ead0, 0x165e940, 0x1660350, 0x36804c8)
    cpu = machine(ap, [(ALLOC, 0x210)] + [(x, 4) for x in externals])
    unit, sid, route = 0x70817, 0x1234, (0x9061003c if space == 1 else 0x61003c)
    message, response, output = RAM, RAM + 0x100, RAM + 0x200
    handle = 0x8123 if space == 1 else 0x123
    physical = 0x809900000 if space == 1 else 0x18000000
    reply = bytearray(40)
    struct.pack_into('<Hh', reply, 0, 0x20, reply_status)
    struct.pack_into('<I', reply, 12, handle)
    struct.pack_into('<QI', reply, 24, physical, 51200)
    cpu.mem_write(response, bytes(reply))
    for register, value in ((UC_ARM64_REG_X0, unit), (UC_ARM64_REG_X1, space),
                            (UC_ARM64_REG_X2, 1), (UC_ARM64_REG_X3, output)):
        cpu.reg_write(register, value)
    sent, freed, waits = [], [], []

    def hook(uc, at, size, _):
        x = lambda reg: uc.reg_read(reg)
        result = 0
        if at == STOP:
            uc.emu_stop()
            return
        if at not in externals:
            return
        if at == 0x251db60:
            if x(UC_ARM64_REG_X1) != 2:
                raise ValueError('Unexpected native queue mode')
            uc.mem_write(x(UC_ARM64_REG_X0), struct.pack('<I', sid))
        elif at == 0x1660060:
            if (x(UC_ARM64_REG_X0), x(UC_ARM64_REG_X2), x(UC_ARM64_REG_X3)) != (route, 40, 1):
                raise ValueError('Unexpected allocation message destination/size/options')
            uc.mem_write(x(UC_ARM64_REG_X1), struct.pack('<Q', message))
        elif at == 0x165d600:
            # The setter implementation is outside this ABI experiment.
            if (x(UC_ARM64_REG_X0), x(UC_ARM64_REG_X1)) != (message, sid):
                raise ValueError('Unexpected native message source setter arguments')
            uc.mem_write(message + 20, struct.pack('<H', sid))
        elif at == 0x165ead0:
            if (x(UC_ARM64_REG_X0), x(UC_ARM64_REG_X1)) != (route, message):
                raise ValueError('Unexpected allocation send arguments')
            sent.append(bytes(uc.mem_read(message, 40)))
            result = transport_status
        elif at == 0x165e940:
            waits.append(x(UC_ARM64_REG_X2) & 0xffffffff)
            if x(UC_ARM64_REG_X0) != sid:
                raise ValueError('Unexpected reply queue')
            uc.mem_write(x(UC_ARM64_REG_X1), struct.pack('<Q', response))
        elif at == 0x1660350:
            freed.append((x(UC_ARM64_REG_X0), x(UC_ARM64_REG_X1)))
        uc.reg_write(UC_ARM64_REG_X0, result)
        uc.reg_write(UC_ARM64_REG_PC, x(UC_ARM64_REG_X30))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(ALLOC, STOP + 4, count=3000)
    if cpu.reg_read(UC_ARM64_REG_PC) != STOP or len(sent) != 1:
        raise ValueError('Native allocation did not return through the inspected path')
    expected = bytearray(40)
    struct.pack_into('<HI', expected, 0, 0x20, 0)  # zeroed native header
    struct.pack_into('<I', expected, 4, unit)
    struct.pack_into('<i', expected, 12, -1)
    struct.pack_into('<HH', expected, 20, sid, 1)
    if sent[0] != expected:
        raise ValueError('Native allocation request layout differs')
    actual = bytes(cpu.mem_read(output, 24))
    if transport_status or reply_status < 0:
        want = struct.pack('<IIQII', unit, 0xffffffff, 0, 0, 0)
    else:
        want = struct.pack('<IIQII', unit, handle, physical, 51200, 0)
    if actual != want:
        raise ValueError('Native allocation result layout differs')
    if transport_status:
        if waits or freed != [(route, message)]:
            raise ValueError('Native failed-send cleanup differs')
    elif waits != [0xffffffff] or freed != [(sid, response)]:
        raise ValueError('Native reply wait/free path differs')
    return {'space': space, 'reply_status': reply_status,
            'transport_status': transport_status, 'waits': waits,
            'raw_return': cpu.reg_read(UC_ARM64_REG_X0) & 0xffffffff}


def completion_case(ap, wakes_before_ready):
    """Run the original future wait with ready, delayed and never-ready states."""
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
        UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5,
        UC_ARM64_REG_X30, UC_ARM64_REG_PC)
    futex, vcall = 0x165ffc0, 0x40000100
    cpu = machine(ap, [(WAIT, 0x8c), (futex, 4)])
    state, vtable, value = RAM, RAM + 0x100, RAM + 0x300
    cpu.mem_write(state, struct.pack('<QQI', vtable, value,
                                    1 if wakes_before_ready == 0 else 0))
    cpu.mem_write(vtable + 16, struct.pack('<Q', vcall))
    cpu.reg_write(UC_ARM64_REG_X0, state)
    waits = []

    def hook(uc, at, size, _):
        if at == STOP:
            uc.emu_stop()
        elif at in (vcall, futex):
            if at == futex:
                if (uc.reg_read(UC_ARM64_REG_X0), uc.reg_read(UC_ARM64_REG_X1)) != (state + 16, state + 16):
                    raise ValueError('Unexpected future wait address')
                if any(uc.reg_read(reg) for reg in (UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5)):
                    raise ValueError('Original future no longer uses untimed wait')
                waits.append(at)
                if wakes_before_ready is not None and len(waits) >= wakes_before_ready:
                    uc.mem_write(state + 16, struct.pack('<I', 1))
                # Simulated wake; not proof of a real transfer completion.
                uc.reg_write(UC_ARM64_REG_X0, 1)
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_X30))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.emu_start(WAIT, STOP + 4, count=3000)
    returned = cpu.reg_read(UC_ARM64_REG_PC) == STOP
    if returned != (wakes_before_ready is not None):
        raise ValueError('Native future returned before ready or failed to return when ready')
    if returned and (cpu.reg_read(UC_ARM64_REG_X0) != value or len(waits) != wakes_before_ready):
        raise ValueError('Native completion pointer/wake count differs')
    return {'simulated_wakes_until_ready': wakes_before_ready,
            'returned': returned, 'wait_calls': len(waits),
            'never_ready_stopped_by_emulator_instruction_budget': not returned}


def verify(ap):
    allocations = [allocation_case(ap, space, reply_status=reply, transport_status=send)
                   for space in (0, 1)
                   for reply, send in ((0, 0), (1, 0), (-1, 0), (0, 5))]
    completion = [completion_case(ap, n) for n in (0, 1, 3, None)]
    return {'schema': 'a7c2-sound-buffer-abi/1', 'camera_io': False,
            'allocation_cases': allocations, 'completion_cases': completion,
            'external_osal_and_replies_simulated': True,
            'live_allocation_or_dma_verified': False,
            'native_allocation_wait_is_unbounded': True,
            'native_transfer_future_wait_is_unbounded': True,
            'installable_custom_audio': False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('ap', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args(argv)
    result = json.dumps(verify(a.ap.read_bytes()), indent=2) + '\n'
    if a.output:
        with a.output.open('x', encoding='utf-8') as f:
            f.write(result)
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
