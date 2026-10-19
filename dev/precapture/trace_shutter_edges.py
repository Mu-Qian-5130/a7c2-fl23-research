"""Replay native target S1 decisions and record-reference callback construction.

Stops BEFORE original start/stop helpers or callback enqueue. Observed
requests are not delivered, sensor capture is not modeled, and no camera
or firmware is modified. Input button states and debug bytes are synthetic.
"""
import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R8,
    UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_SP,
)
from audit_control import SPECS

MEM, STACK, DEBUG = 0x30000000, 0x40000000, 0x1A533A4


def word(value):
    return struct.pack("<I", value)


class NativeEdges:
    def __init__(self, data):
        self.u = u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for address in [0x3AD000, 0xA1A000, 0xA05000, 0x407000]:
            u.mem_map(address, 0x1000)
            u.mem_write(address, data[address:address + 0x1000])
        for address, size in [(DEBUG & ~4095, 4096), (MEM, 0x4000), (STACK, 0x4000)]:
            u.mem_map(address, size)
        self.stop = {}
        self.result = None

        def trace(cpu, address, size, user):
            if address not in self.stop:
                return
            label = self.stop[address]
            item = {"boundary": hex(address), "request": label, "executed": False}
            if label == "enqueue-reference":
                callback = cpu.reg_read(UC_ARM_REG_R1)
                item.update({"owner_va": hex(cpu.reg_read(UC_ARM_REG_R0)),
                             "callback_va": hex(struct.unpack("<I", cpu.mem_read(callback + 8, 4))[0]),
                             "arg0": cpu.reg_read(UC_ARM_REG_R2),
                             "arg1": cpu.reg_read(UC_ARM_REG_R3)})
            self.result = item
            cpu.emu_stop()

        u.hook_add(UC_HOOK_CODE, trace)

    def reset(self, flags):
        u = self.u
        u.mem_write(MEM, bytes(0x4000))
        u.mem_write(DEBUG, bytes(0x100))
        u.mem_write(DEBUG + 0xF1, bytes([flags]))
        u.reg_write(UC_ARM_REG_R4, MEM + 0x100)
        u.reg_write(UC_ARM_REG_R5, MEM)
        u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
        self.result = None

    def run(self, address):
        self.u.emu_start(address | 1, 0xFFFFFFFF, count=150)
        if self.result is None:
            raise AssertionError("Unresolved execution is not a successful request")
        return self.result

    def edge(self, flags, old, pressed, index):
        self.reset(flags)
        u = self.u
        u.mem_write(MEM + 0x24, word(old))
        u.mem_write(MEM + 0x100 + 0xC, word(pressed) + word(index))
        u.reg_write(UC_ARM_REG_R9, 0x40002)  # loaded by original handler before dispatch
        self.stop = {0xA1AD9A: "start-helper", 0xA1ADB2: "stop-helper", 0x3AD5EE: "none"}
        item = self.run(0x3AD1BA)
        item["updated_mask"] = struct.unpack("<I", u.mem_read(MEM + 0x24, 4))[0]
        return item

    def reference(self, flags, active, pressed, subtype, sequence, timestamp):
        self.reset(flags)
        u = self.u
        u.mem_write(MEM + 0xC, word(MEM + 0x1000))
        u.mem_write(MEM + 0x1000 + 0x2D, bytes([active]))
        u.reg_write(UC_ARM_REG_R6, pressed)
        u.reg_write(UC_ARM_REG_R8, sequence)
        u.reg_write(UC_ARM_REG_R9, subtype)
        u.reg_write(UC_ARM_REG_R10, timestamp)
        self.stop = {0x407F1C: "enqueue-reference", 0x3AD576: "none"}
        return self.run(0x3AD54C)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cp", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = args.cp.read_bytes()
    if hashlib.sha256(data).hexdigest() != SPECS["a7c2-2.01"]["sha256"]:
        raise ValueError("Unsupported original target CP fingerprint")
    oracle = NativeEdges(data)
    edges, references = [], []
    # 0x11,0x21,0x41 select the original debug S1, AF-ON and combined paths.
    for flags, old, pressed, index in itertools.product([0, 0x11, 0x21, 0x41], [0, 2, 0x40000, 0x40002], [0, 1], [1, 18, 3]):
        item = oracle.edge(flags, old, pressed, index)
        expected_mask = old | (1 << index) if pressed else old & ~(1 << index)
        assert item["updated_mask"] == expected_mask
        wanted = "none"
        if flags == 0x11 and index == 1 or flags == 0x21 and index == 18:
            wanted = "start-helper" if pressed else "stop-helper"
        if flags == 0x41 and index in [1, 18]:
            if pressed:
                wanted = "start-helper"
            elif expected_mask & 0x40002 == 0:
                wanted = "stop-helper"
        assert item["request"] == wanted, (flags, old, pressed, index, item, wanted)
        edges.append({"debug_flags_f1": flags, "old_mask": old, "pressed": pressed,
                      "button_index": index, **item})
    for flags, active, pressed, subtype in itertools.product([0, 0x11], [0, 1], [0, 1], [1, 13]):
        sequence, timestamp = 0x12345678, 0x89ABCDEF
        item = oracle.reference(flags, active, pressed, subtype, sequence, timestamp)
        requested = flags != 0 and subtype != 13 and bool(pressed) != bool(active)
        assert (item["request"] == "enqueue-reference") == requested
        if requested:
            assert item["owner_va"] == "0x1a3aae0"
            assert item["callback_va"] == ("0x474fad" if pressed else "0x475015")
            assert item["arg0"] == sequence
            assert item["arg1"] == (timestamp if pressed else 0)
        references.append({"debug_flags_f1": flags, "active": active, "pressed": pressed,
                           "request_subtype": subtype, **item})
    report = {"mode": "OFFLINE_NATIVE_REQUEST_BOUNDARIES_ONLY", "camera_io": False,
              "firmware_modified": False, "edge_cases": edges, "reference_cases": references,
              "limits": ["Synthetic debug and button inputs", "Start/stop helpers are not executed",
                         "Reference enqueue is not executed; no OS/transport success is fabricated",
                         "No real physical-button timing, sensor readout or images tested"]}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(f"Native decision boundaries verified: {len(edges)} edge cases, {len(references)} reference cases; no requests delivered.")


if __name__ == "__main__":
    main()
