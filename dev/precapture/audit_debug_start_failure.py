"""Analyze the FAILED native debug candidate without camera I/O.

Replay original target debug edges and donor predicate/idempotence slices.
Trace the original target start wrapper only to its first real allocation.
All mode/button/object inputs are synthetic. No allocator, OS or sensor
success is fabricated, and no installable candidate is generated.
"""
import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R8, UC_ARM_REG_SP,
    UC_ARM_REG_LR, UC_ARM_REG_PC)
from support.reference import SPECS
from trace_shutter_edges import NativeEdges
from verify_capture_gate import Native
from support.memory import MEM, STACK, STOP


def word(v):
    return struct.pack('<I', v)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--firmware-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    blobs = {}
    for model, spec in SPECS.items():
        raw = (a.firmware_root / model / 'components/cpapp-b.bin').read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec['sha256']:
            raise ValueError('Unsupported private original: ' + model)
        blobs[model] = raw
    target, donor = blobs['a7c2-2.01'], blobs['a1ii-4.00']
    edges = NativeEdges(target)
    target_gate = Native(target, False)
    dn = Native(donor, True)
    n = dn.u
    for at in [0xAAD000, 0x3F6000, 0x3F7000, 0xAAF000]:
        n.mem_map(at, 4096)
        n.mem_write(at, donor[at:at + 4096])
    boundaries = []

    def stop_donor(cpu, address, size, user):
        if address in [0xAAF626, 0xAAF63E, 0x3F7236]:
            boundaries.append(address)
            cpu.emu_stop()

    n.hook_add(UC_HOOK_CODE, stop_donor)
    cases = []
    for mode, old_mask in itertools.product([0, 1, 0x1A, 0x21, 2, 0xFFFFFFFF], [0, 2]):
        # Exact failed debug bytes. This is an offline input, not a proposal.
        gate = target_gate.leaf(mode, 0, 0x10, 0x11)
        edge = edges.edge(0x11, old_mask, 1, 1)
        assert edge['request'] == 'start-helper'
        n.mem_write(MEM, bytes(4096))
        n.mem_write(MEM + 0x148, word(mode))
        n.mem_write(dn.debug + 0xF0, bytes([0x10, 0x11]))
        for reg, value in [(UC_ARM_REG_R0, 0), (UC_ARM_REG_R1, MEM),
                           (UC_ARM_REG_R2, 2), (UC_ARM_REG_SP, STACK + 0x3000),
                           (UC_ARM_REG_LR, STOP | 1)]:
            n.reg_write(reg, value)
        n.emu_start(0xAAD013, STOP, count=150)
        assert n.reg_read(UC_ARM_REG_PC) == STOP
        desired = n.reg_read(UC_ARM_REG_R0)
        assert desired == gate
        for active in [0, 1]:
            n.mem_write(MEM + 0x2C, bytes([active]))
            n.reg_write(UC_ARM_REG_R5, MEM)
            n.reg_write(UC_ARM_REG_R8, desired)
            before = len(boundaries)
            n.emu_start(0x3F6E59, 0xFFFFFFFF, count=30)
            assert len(boundaries) == before + 1
            expected = 0x3F7236 if active == desired else (0xAAF626 if desired else 0xAAF63E)
            assert boundaries[-1] == expected
            cases.append({'mode_raw': mode, 'old_target_button_mask': old_mask,
                'target_gate': gate, 'target_debug_edge': edge['request'],
                'donor_desired_active': desired, 'donor_stored_active': active,
                'donor_decision_boundary': hex(expected),
                'target_edge_requests_start_while_gate_false': not bool(gate),
                'duplicate_target_press_input': old_mask == 2})

    # Expand the previously unexecuted start-helper boundary. The wrapper
    # logs event7 before it constructs command0x4038. Stop at the actual
    # first log allocation; never fake its success to reach the next call.
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for at, size in [(0xA1A000, 4096), (0xA18000, 4096),
                     (0x516000, 0x4000), (0x45D000, 4096)]:
        u.mem_map(at, size)
        u.mem_write(at, target[at:at + size])
    u.mem_map(STACK, 0x4000)
    allocs = []

    def stop_allocator(cpu, address, size, user):
        if address == 0x45D204:
            values = [cpu.reg_read(reg) for reg in [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]]
            allocs.append(values)
            cpu.emu_stop()

    u.hook_add(UC_HOOK_CODE, stop_allocator)
    u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
    u.reg_write(UC_ARM_REG_LR, STOP | 1)
    u.emu_start(0xA1AD9B, 0xFFFFFFFF, count=1000)
    assert u.reg_read(UC_ARM_REG_PC) == 0x45D204 and len(allocs) == 1
    route, output_pointer, size, flags = allocs[0]
    assert route == 0x8F013A and size == 37 and flags == 0
    # Original memcpy copied event7 into the log buffer after its type byte5.
    log_sp = u.reg_read(UC_ARM_REG_SP)
    assert bytes(u.mem_read(log_sp, 5)) == bytes([5, 7, 0, 0, 0])
    # A property/global update is not proof that previously derived capture
    # context was rebuilt. Replay the old producer, an explicit synthetic
    # global update, the consumer, then a fresh producer. No camera context
    # or parameter-notification delivery is claimed by this experiment.
    stale = Native(target, False)
    assert stale.propagate(0, 1, 0, 0, 0, 1) == (0, 1)
    stale.u.mem_write(stale.debug + 0xF0, bytes([0x10, 0x11]))
    old_marker = None
    for refresh in [False, True]:
        if refresh:
            stale.u.reg_write(UC_ARM_REG_R4, MEM)
            stale.run(*stale.producer)
        stale.u.reg_write(UC_ARM_REG_R4, MEM + 0x10000)
        stale.u.reg_write(UC_ARM_REG_R5, MEM + 8)
        stale.u.reg_write(UC_ARM_REG_R2, 1)
        stale.run(*stale.consumer)
        flag = stale.u.mem_read(MEM + stale.flag_field, 1)[0]
        marker = struct.unpack('<I', stale.u.mem_read(MEM + 0x10000 + stale.marker_field, 4))[0]
        assert (flag, marker) == ((1, 2) if refresh else (0, 1))
        if not refresh:
            old_marker = marker
    report = {'mode': 'OFFLINE_FAILED_DEBUG_START_ANALYSIS', 'camera_io': False,
        'physical_candidate_status': 'FAILED_HALF_PRESS_STALL_CRASH_AUTOMATIC_RESTART',
        'do_not_repeat_candidate': True, 'cases': cases,
        'first_original_start_boundary': {'file': '0x45d204', 'route': hex(route),
            'allocation_bytes': size, 'flags': flags, 'log_payload_hex': '0507000000',
            'allocator_executed': False, 'command4038_reached': False},
        'synthetic_stale_context': {'global_debug_bytes_f0_f1': '1011',
            'marker_without_reexecuting_producer': old_marker,
            'marker_after_reexecuting_producer': marker,
            'actual_failed_camera_context_observed': False},
        'findings': [
            'Target debug pressed/index decision can request start while its separate mode gate is false',
            'Target debug decision repeats start for an already-set synthetic half-press bit',
            'Donor normal decision compares desired activity with stored activity before start/stop',
            'The actual start wrapper enters log allocation before capture-message construction',
            'Updating debug globals alone does not rewrite an already-derived capture-context flag'],
        'limits': [
            'These are potential integration hazards, not a localized physical crash cause',
            'Synthetic duplicate button inputs are not evidence of actual duplicated physical events',
            'No physical raw capture mode or crash stack was collected during the failure',
            'Logging allocation is not shown to have failed; no return value is fabricated',
            'The stale-context scenario is synthetic, not a captured CP trace or established crash cause',
            'Native sensor, message delivery and pixel ownership remain unverified']}
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
        f.write('\n')
    print(f'{len(cases)} original decision cases and first real log-allocation boundary checked. Failed candidate remains prohibited; crash cause unknown.')


if __name__ == '__main__':
    main()
