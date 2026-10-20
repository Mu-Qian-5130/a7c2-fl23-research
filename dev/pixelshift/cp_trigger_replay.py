"""Replay native trigger arbitration and selected internal-message routing.

Registries, previous triggers and actor state are synthetic. Original rank
callbacks come from the native initializer. Sender bodies, transports and the
actor scheduler are omitted; a host byte bridge supplies already allocated
packets to the original normalizer. Capture routing stops BEFORE its handler.
No positioning, exposure, saved setting or hardware success is emulated.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_metadata_replay import program
from cp_sequence_replay import machine


@lru_cache(maxsize=2)
def profile(directory):
    data, model, _, _ = program(directory)
    target = model == 'ILCE-7CM2'
    # Each region is independently matched in these two original programs.
    return data, dict(
        initializer=0xae14be if target else 0xae131c,
        rank_setters=0xae106a if target else 0xae0ec8,
        arbitration=0xae213c if target else 0xae1f9a,
        select=0xae1076 if target else 0xae0ed4,
        capture_id=0xae10d8 if target else 0xae0f36,
        clear_flag=0xae1100 if target else 0xae0f5e,
        bit_setter=0xae1470 if target else 0xae12ce,
        rank_callbacks=[0x4593c8, 0x459470, 0x4594dc] if target else
                       [0x4595e0, 0x459688, 0x4596f4],
        senders={0xae3b50 if target else 0xae39ae: 0x3021,
                 0xae3ba6 if target else 0xae3a04: 0x3022,
                 0xae3902 if target else 0xae3760: 0x300e,
                 0xae396e if target else 0xae37cc: 0x3010,
                 0xae3ae4 if target else 0xae3942: 0x300f,
                 0xae3d8a if target else 0xae3be8: 0x302e,
                 0xae3de0 if target else 0xae3c3e: 0x302f},
        normalize=0x4b6064 if target else 0x4b6280,
        zero=0x61ed00 if target else 0x61ef18,
        handle=0xb1fe10 if target else 0xb1fc6e,
        send=0x4b5fe4 if target else 0x4b6200,
        router=0x4b4cf0 if target else 0x4b4f0c,
        capture_handler=0xb206ba if target else 0xb20518,
        af_prepare=0xb22d4e if target else 0xb22bac,
        awb_setter=0x4b6904 if target else 0x4b6b20,
        getter=0x8db1b8 if target else 0x8db3d0,
        parameter=0x165a720 if target else 0x1659720,
        trace=0xb20e08 if target else 0xb20c66,
        post_handler=0x4b56e4 if target else 0x4b5900)


def arbitrate(directory, *, active, previous=(0, 0, 0), af_enabled=1):
    """Run the original three rank passes; observe, but do not execute, senders."""
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4,
                                   UC_ARM_REG_PC, UC_ARM_REG_LR)
    data, p = profile(directory)
    cpu = machine(data, [])
    context, finish = 0x30000000, 0x3001e000
    cpu.reg_write(UC_ARM_REG_R4, context)
    init_regions = [(p['initializer'], p['initializer'] + 42),
                    (p['rank_setters'], p['rank_setters'] + 12)]

    def init_hook(uc, address, size, unused):
        if not any(start <= address < end for start, end in init_regions):
            raise ValueError('Rank initializer left its native slice: ' + hex(address))

    token = cpu.hook_add(UC_HOOK_CODE, init_hook)
    cpu.emu_start(p['initializer'] | 1, p['initializer'] + 42, count=100)
    cpu.hook_del(token)
    callbacks = struct.unpack('<3I', cpu.mem_read(context + 4, 12))
    if callbacks != tuple(at | 1 for at in p['rank_callbacks']):
        raise ValueError('Unexpected native rank callback initialization')
    for trigger in active:
        if not 0 <= trigger < 23:
            raise ValueError('Native trigger registry has 23 slots')
        cpu.mem_write(context + 0x40 + trigger * 12, b'\1')
        cpu.mem_write(context + 0x44 + trigger * 12, struct.pack('<I', 0x12340000 + trigger))
    af, ae, awb = previous
    cpu.mem_write(context + 0x260, struct.pack('<6I', context, context + 0x298,
                                             af, ae, awb, af_enabled))
    cpu.reg_write(UC_ARM_REG_R0, context + 0x260)
    cpu.reg_write(UC_ARM_REG_LR, finish | 1)
    result = dict(requests=[], sender_bodies_executed=False,
                  registry_and_previous_state_synthetic=True,
                  transport_executed=False, capture_executed=False,
                  physical_shift_verified=False)
    regions = [(p['arbitration'], p['arbitration'] + 0x154),
               (p['select'], p['select'] + 0x48),
               (p['capture_id'], p['capture_id'] + 12),
               (p['clear_flag'], p['clear_flag'] + 6),
               (p['bit_setter'], p['bit_setter'] + 4)]
    regions += [(at, at + size) for at, size in zip(p['rank_callbacks'], (0x7c, 0x40, 0x40))]

    def hook(uc, address, size, unused):
        if address in p['senders']:
            command = p['senders'][address]
            trigger, ident = uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1)
            # The native off senders write capture ID zero, not their unused r1.
            if command in (0x3010, 0x3022):
                ident = 0
            result['requests'].append(dict(command=hex(command), trigger=trigger, capture_id=ident))
            # Void request boundary only: no success result or transport reply.
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
        elif not any(start <= address < end for start, end in regions):
            raise ValueError('Arbitration reached unhandled native code: ' + hex(address))

    def write_hook(uc, access, address, size, value, unused):
        if context <= address and address + size <= context + 0x300:
            return
        if 0x30018000 <= address and address + size <= 0x3001f000:
            return
        raise ValueError('Arbitration changed unrelated state: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.emu_start(p['arbitration'] | 1, finish, count=20000)
    if cpu.reg_read(UC_ARM_REG_PC) != finish:
        raise ValueError('Native trigger arbitration did not finish')
    result['selected'] = list(struct.unpack('<3I', cpu.mem_read(context + 0x268, 12)))
    return result


def normalize(directory, *, command, capture_id=0x12345678, trigger=20):
    """Original 24-byte LiRo packet -> original 32-byte actor message(s)."""
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                   UC_ARM_REG_R3, UC_ARM_REG_PC, UC_ARM_REG_LR)
    if command not in (0x300c, 0x300e, 0x300f, 0x3010, 0x3021, 0x3022, 0x302e, 0x302f):
        raise ValueError('This replay only covers the inspected trigger messages')
    data, p = profile(directory)
    cpu = machine(data, [])
    packet, finish = 0x30000000, 0x3001e000
    raw = struct.pack('<BBHIII8x', 2 if command == 0x300c else 0, 0,
                      command, capture_id, trigger, 0x87654321)
    cpu.mem_write(packet, raw)
    cpu.reg_write(UC_ARM_REG_R0, packet)
    cpu.reg_write(UC_ARM_REG_R1, 0x90040193)
    cpu.reg_write(UC_ARM_REG_LR, finish | 1)
    result = dict(messages=[], preallocated_input=True, native_zero_executed=False,
                  sender_and_allocator_executed=False, transport_executed=False,
                  physical_shift_verified=False)
    regions = [(p['normalize'], p['normalize'] + 0x2ec),
               (p['zero'], p['zero'] + 0x130), (p['handle'], p['handle'] + 10)]

    def hook(uc, address, size, unused):
        if address == p['send']:
            if (uc.reg_read(UC_ARM_REG_R1), uc.reg_read(UC_ARM_REG_R3)) != (0x900302d9, 32):
                raise ValueError('Unexpected native actor destination or message size')
            result['messages'].append(bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R2), 32)).hex())
            # The caller ignores this return register. No send/allocator succeeds here.
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
        elif not any(start <= address < end for start, end in regions):
            raise ValueError('Normalizer reached unhandled native code: ' + hex(address))
        if address == p['zero']:
            result['native_zero_executed'] = True

    def write_hook(uc, access, address, size, value, unused):
        if not 0x30018000 <= address or address + size > 0x3001f000:
            raise ValueError('Normalizer wrote outside its stack: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.emu_start(p['normalize'] | 1, finish, count=3000)
    if (cpu.reg_read(UC_ARM_REG_PC) != finish or not result['native_zero_executed']
            or bytes(cpu.mem_read(packet, 24)) != raw or not result['messages']):
        raise ValueError('Native trigger normalization failed')
    return result


def route(directory, message):
    """Direct actor-handler replay; the queue, permissions and scheduler are absent."""
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_PC)
    data, p = profile(directory)
    raw = bytes.fromhex(message)
    if len(raw) != 32 or struct.unpack_from('<I', raw, 4)[0] not in (0x100, 0x102, 0x8307, 0x8308):
        raise ValueError('Only capture-start, AF preparation and AWBL actor routes are covered')
    cpu = machine(data, [p['parameter'] & ~4095])
    actor, packet = 0x30000000, 0x30001000
    cpu.mem_write(actor + 0xc, struct.pack('<I', 0x30002000))
    cpu.mem_write(packet, raw[4:] + b'\0' * 4)
    cpu.mem_write(p['parameter'] + 0x242, b'\xa5')
    cpu.reg_write(UC_ARM_REG_R0, actor)
    cpu.reg_write(UC_ARM_REG_R1, packet)
    result = dict(synthetic_actor=True, queue_and_scheduler_executed=False,
                  capture_handler_executed=False, capture_executed=False,
                  diagnostic_calls_omitted=0, physical_shift_verified=False)
    regions = [(p['router'], p['router'] + 0x7cc),
               (p['awb_setter'], p['awb_setter'] + 0x26), (p['getter'], p['getter'] + 10)]

    def hook(uc, address, size, unused):
        if address == p['capture_handler']:
            if (uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1)) != (actor, packet):
                raise ValueError('Native capture handler arguments changed')
            result['boundary'] = 'capture-start-handler'
            result['capture_id'] = struct.unpack_from('<I', raw, 8)[0]
            result['trigger'] = struct.unpack_from('<I', raw, 16)[0]
            uc.emu_stop()
        elif address == p['af_prepare']:
            result['boundary'] = 'af-prepare-helper'
            uc.emu_stop()
        elif address == p['post_handler']:
            result['boundary'] = 'post-handler'
            uc.emu_stop()
        elif address == p['trace']:
            from unicorn.arm_const import UC_ARM_REG_LR
            result['diagnostic_calls_omitted'] += 1
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
        elif not any(start <= address < end for start, end in regions):
            raise ValueError('Actor router reached unhandled native code: ' + hex(address))

    def write_hook(uc, access, address, size, value, unused):
        if address == p['parameter'] + 0x242 and size == 1:
            return
        if 0x30018000 <= address and address + size <= 0x3001f000:
            return
        raise ValueError('Actor route changed unrelated state: ' + hex(address))

    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    cpu.emu_start(p['router'] | 1, 0x3001e000, count=2000)
    if 'boundary' not in result or bytes(cpu.mem_read(packet, 28)) != raw[4:]:
        raise ValueError('Actor routing did not reach its inspected boundary')
    result['awbl_flag'] = bytes(cpu.mem_read(p['parameter'] + 0x242, 1))[0]
    return result


def compare(c2, reference):
    cases = []
    active_sets = [[], [20], [2], [0, 20], [1, 20], [3, 20],
                   [20, 21], [20, 22], [1, 2, 20], [2, 3, 20], [19, 20], [18, 20]]
    for active in active_sets:
        for previous in ((0, 0, 0), (20, 20, 20)):
            for af_enabled in (0, 1):
                args = dict(active=active, previous=previous, af_enabled=af_enabled)
                a, b = arbitrate(c2, **args), arbitrate(reference, **args)
                if a != b:
                    raise ValueError('C2/A7CR original trigger arbitration differs')
                cases.append(dict(stage='arbitration', input=args, target=a, reference=b))
    for command in (0x300c, 0x300e, 0x300f, 0x3010, 0x3021, 0x3022, 0x302e, 0x302f):
        for ident in (0, 0x12345678, 0xffffffff):
            args = dict(command=command, capture_id=ident)
            a, b = normalize(c2, **args), normalize(reference, **args)
            if a != b:
                raise ValueError('C2/A7CR original trigger normalization differs')
            if command in (0x300c, 0x300e, 0x302e, 0x302f):
                # Capture start first emits 0x8202, then the 0x100 message.
                index = 1 if command == 0x300c else 0
                a['route'], b['route'] = route(c2, a['messages'][index]), route(reference, b['messages'][index])
                if a != b:
                    raise ValueError('C2/A7CR original trigger actor routing differs')
            cases.append(dict(stage='normalization', input=args, target=a, reference=b))
    return dict(schema='a7c2-pixelshift-cp-trigger/1', camera_io=False, installable=False,
                physical_shift_verified=False, paired_cases=len(cases), cases=cases)


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
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'installable')}))


if __name__ == '__main__':
    main()
