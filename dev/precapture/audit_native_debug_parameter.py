"""Audit existing CP debug parameter0x30072; no device writes or ROM patch.

With an optional private256-byte backup, emits an OFFLINE candidate and
exact inverse in the private report. It does not connect to a camera or
establish safe sensor operation. This is not an installation command.

The exact candidate FAILED a physical half-press test (stall/crash/restart).
Keep this audit for failure analysis only. Do not install or repeat it.
"""
import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from audit_control import SPECS
from verify_capture_gate import Native
from trace_shutter_edges import NativeEdges
from verify_retention import TargetOracle
from verify_offline import MEM, STACK, STOP

DEBUG = 0x1A533A4


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--debug-unit', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cp = a.cp.read_bytes()
    if hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original target CP')
    pointer = struct.unpack_from('<I', cp, 0x110FC88 - 0x108000)[0]
    keys = [struct.unpack_from('<I', cp, va - 0x108000)[0] for va in [0x110FCD0, 0x110FD10]]
    size = struct.unpack_from('<I', cp, 0x110FD50 - 0x108000)[0]
    assert pointer == DEBUG and keys == [0x30072] * 2 and size == 256
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    checks = [
        (0x3B09BC, 'bl', '#0xae1d98'),
        (0x3B0B96, 'bl', '#0x408800'),
        (0x3B10BC, 'bl', '#0x408728'),
        (0xA1D92C, 'blx', '#0x51660c'),
        (0xA2F104, 'ldrb.w', 'r0, [r2, #0xf0]'),
        (0xA2F11E, 'ldrb.w', 'r1, [r2, #0xf1]'),
        (0x3AD304, 'ldrb.w', 'r2, [sl, #0xf1]'),
        (0x3AD55A, 'ldrb.w', 'r0, [r0, #0xf1]'),
        (0xA09D54, 'ldrb.w', 'r2, [r1, #0xf2]'),
        (0xA09D70, 'ldrb.w', 'r1, [r1, #0xf3]'),
    ]
    for at, mnemonic, operands in checks:
        ins = next(md.disasm(cp[at:at + 4], at))
        assert (ins.mnemonic, ins.op_str) == (mnemonic, operands)
    original = a.debug_unit.read_bytes() if a.debug_unit else bytes(256)
    if len(original) != 256 or original[0xF0:0xF4] != bytes(4):
        raise ValueError('Expected a256-byte backup with unmodified pre-capture debug bytes; preserve unknown state')
    candidate = bytearray(original)
    candidate[0xF0:0xF4] = bytes([0x10, 0x11, 0, 2])
    edits = [{'offset': i, 'before': x, 'after': y} for i, (x, y) in enumerate(zip(original, candidate)) if x != y]
    assert [e['offset'] for e in edits] == [0xF0, 0xF1, 0xF3]
    inverse = bytearray(candidate)
    for e in edits:
        inverse[e['offset']] = e['before']
    assert inverse == original and candidate[:0xF0] == original[:0xF0] and candidate[0xF4:] == original[0xF4:]
    gate = Native(cp, False)
    n = gate.u
    for at, length in [(0xA1D000, 4096), (0x516000, 0x4000)]:
        n.mem_map(at, length);n.mem_write(at, cp[at:at + length])
    # Execute the original registered update callback's actual copy. Stop
    # before diagnostics; no property write or notification is synthesized.
    n.mem_write(MEM + 0x18000, bytes(candidate))
    n.mem_write(DEBUG - 16, b'\xA5' * (256 + 32))
    for reg, value in [(UC_ARM_REG_R0, 0x30072), (UC_ARM_REG_R1, 256),
                       (UC_ARM_REG_R2, MEM + 0x18000), (UC_ARM_REG_R3, DEBUG),
                       (UC_ARM_REG_SP, STACK + 0x3000), (UC_ARM_REG_LR, STOP | 1)]:
        n.reg_write(reg, value)
    n.emu_start(0xA1D91B, 0xA1D930, count=1000)
    assert n.reg_read(UC_ARM_REG_PC) == 0xA1D930
    assert bytes(n.mem_read(DEBUG - 16, 288)) == b'\xA5' * 16 + bytes(candidate) + b'\xA5' * 16
    gate_cases = []
    for mode in [0, 1, 0x1A, 0x21, 2, 0xFFFFFFFF]:
        before = gate.leaf(mode, 0, original[0xF0], original[0xF1])
        after = gate.leaf(mode, 0, candidate[0xF0], candidate[0xF1])
        assert before == 0 and after == int(mode in [1, 0x1A, 0x21])
        flag, marker = gate.propagate(0, mode, 0, candidate[0xF0], candidate[0xF1], 1)
        assert flag == after and marker == (2 if after else 1)
        gate_cases.append({'mode_raw': mode, 'before': before, 'after': after, 'frame_marker': marker})
    edges = NativeEdges(cp)
    edge_cases = []
    for old, pressed, button in itertools.product([0, 2, 0x40000, 0x40002], [0, 1], [1, 18]):
        item = edges.edge(candidate[0xF1], old, pressed, button)
        want = ('start-helper' if pressed else 'stop-helper') if button == 1 else 'none'
        assert item['request'] == want
        edge_cases.append({'old': old, 'pressed': pressed, 'button': button, **item})
    queue = TargetOracle(cp).u
    queue.mem_write(MEM, bytes(64))
    queue.mem_write(DEBUG + 0xF2, bytes(candidate[0xF2:0xF4]))
    queue.reg_write(UC_ARM_REG_R0, MEM)
    queue.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
    queue.reg_write(UC_ARM_REG_LR, STOP | 1)
    queue.emu_start(0xA09D33, STOP, count=100)
    assert queue.reg_read(UC_ARM_REG_PC) == STOP
    wanted = bytearray(64)
    struct.pack_into('<2I', wanted, 0x14, 1, 2)
    assert bytes(queue.mem_read(MEM, 64)) == bytes(wanted)
    report = {'schema': 'OFFLINE_NATIVE_DEBUG_PARAMETER_CANDIDATE', 'camera_io': False,
              'physical_candidate_status': 'FAILED_HALF_PRESS_STALL_CRASH_AUTOMATIC_RESTART',
              'candidate_must_not_be_installed_or_repeated': True,
              'ROM_modified': False, 'parameter_write_authorized': False,
              'property': {'chip': 1, 'key': '0x00030072', 'bytes': size, 'native_destination': hex(DEBUG)},
              'candidate': {'source_is_supplied_private_backup': bool(a.debug_unit),
                            'before_sha256': hashlib.sha256(original).hexdigest(),
                            'after_sha256': hashlib.sha256(candidate).hexdigest(),
                            'changes': edits, 'exact_inverse_verified': True,
                            'before_hex_private': original.hex(), 'after_hex_private': bytes(candidate).hex()},
              'native_update_copy_verified': True, 'native_gate_cases': gate_cases,
              'native_edges': edge_cases, 'native_empty_queue_policy': {'policy': 1, 'references': 2},
              'limits': ['This is a native debug path, not a normal menu-enabled port',
                         'Property write/save/persistence and notification delivery are not executed here',
                         'This candidate caused a physical half-press stall/crash/restart; do not repeat',
                         'The failing sensor/task/buffer operation has not been localized',
                         'Suitable RAW capacity, physical pre-trigger images and full recovery are not established',
                         'Running this offline audit never authorizes a camera parameter write']}
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2);f.write('\n')
    print('Offline copy/gate/S1/count checks only. This candidate FAILED the physical half-press test; do not install or repeat. No device I/O.')


if __name__ == '__main__':
    main()
