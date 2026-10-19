"""Prepare a NON-INSTALLABLE plan for the original target debug path.

No full image, installer manifest, USB operation or flash command is emitted.
Seven non-flag-setting MOV instructions replace seven original byte loads.
Original native mode checks, request helpers, queues and RAW services remain
in use. This is an experiment plan, not the normal configurable port.
"""
import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from trace_shutter_edges import NativeEdges
from verify_capture_gate import Native
from verify_retention import TargetOracle
from verify_offline import MEM, STACK, STOP
from verify_extension_layout import PINNED


PATCHES = [
    ("frame-gate-path", 0xA2F104, "ldrb.w r0, [r2, #0xf0]", "mov.w r0, #16"),
    ("frame-gate-selection", 0xA2F11E, "ldrb.w r1, [r2, #0xf1]", "mov.w r1, #17"),
    ("s1-recompute-selection", 0x3AD1D8, "ldrb.w r0, [r6, #0xf1]", "mov.w r0, #17"),
    ("s1-edge-selection", 0x3AD304, "ldrb.w r2, [sl, #0xf1]", "mov.w r2, #17"),
    ("record-reference-selection", 0x3AD55A, "ldrb.w r0, [r0, #0xf1]", "mov.w r0, #17"),
    ("queue-count-policy", 0xA09D54, "ldrb.w r2, [r1, #0xf2]", "mov.w r2, #0"),
    ("queue-two-frames", 0xA09D70, "ldrb.w r1, [r1, #0xf3]", "mov.w r1, #2"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cp", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New private JSON plan path")
    args = parser.parse_args()
    source = args.cp.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    if digest not in PINNED:
        raise ValueError("Unsupported source; do not substitute a camera backup without review")
    ks, md = Ks(KS_ARCH_ARM, KS_MODE_THUMB), Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    modified = bytearray(source)
    changes = []
    allowed = set()
    for label, at, old_asm, new_asm in PATCHES:
        old = bytes(ks.asm(old_asm, addr=at + 0x108000)[0])
        new = bytes(ks.asm(new_asm, addr=at + 0x108000)[0])
        assert len(old) == len(new) == 4
        assert source[at:at + 4] == old, (label, hex(at))
        ins = next(md.disasm(new, at))
        assert ins.mnemonic == "mov.w", "Do not replace LDR with flag-changing MOVS"
        modified[at:at + 4] = new
        allowed.update(range(at, at + 4))
        changes.append({"label": label, "file_offset": hex(at), "before_hex": old.hex(),
                        "after_hex": new.hex(), "before_instruction": old_asm,
                        "after_instruction": new_asm, "reverse_is_exact_before_bytes": True})
    assert len(modified) == len(source)
    assert all(i in allowed for i, (a, b) in enumerate(zip(source, modified)) if a != b)
    assert modified[:0x20200] == source[:0x20200]
    restored = bytearray(modified)
    for change in changes:
        at = int(change["file_offset"], 16)
        restored[at:at + 4] = bytes.fromhex(change["before_hex"])
    assert restored == source

    # Actual patched leaf and producer/consumer instructions execute in RAM
    # only. No full modified image is saved to disk.
    replay_image = bytes(modified)
    gate = Native(replay_image, False)
    marker_cases = []
    for mode in [0, 1, 0x1A, 0x21, 2, 0xFFFFFFFF]:
        wanted = int(mode in [1, 0x1A, 0x21])
        assert gate.leaf(mode, 0, 0, 0) == wanted
        flag, marker = gate.propagate(0, mode, 0, 0, 0, 1)
        assert flag == wanted and marker == (2 if wanted else 1)
        marker_cases.append({"mode_raw": mode, "flag": flag, "frame_marker": marker})
    edges = NativeEdges(replay_image)
    edge_cases = []
    for old, pressed, button in itertools.product([0, 2, 0x40000, 0x40002], [0, 1], [1, 18]):
        item = edges.edge(0, old, pressed, button)
        wanted = ("start-helper" if pressed else "stop-helper") if button == 1 else "none"
        assert item["request"] == wanted
        edge_cases.append({"old_mask": old, "pressed": pressed, "button": button, **item})
    reference_cases = []
    for active, pressed, subtype in itertools.product([0, 1], [0, 1], [1, 13]):
        item = edges.reference(0, active, pressed, subtype, 0x12345678, 0x89ABCDEF)
        wanted = subtype != 13 and bool(active) != bool(pressed)
        assert (item["request"] == "enqueue-reference") == wanted
        reference_cases.append({"active": active, "pressed": pressed, "subtype": subtype, **item})
    config = TargetOracle(replay_image).u
    initial = struct.pack("<16I", *([0] * 16))
    config.mem_write(MEM, initial)
    config.reg_write(UC_ARM_REG_R0, MEM)
    config.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
    config.reg_write(UC_ARM_REG_LR, STOP | 1)
    config.emu_start(0xA09D33, STOP, count=100)
    assert config.reg_read(UC_ARM_REG_PC) == STOP
    after = bytearray(initial)
    struct.pack_into("<2I", after, 0x14, 1, 2)
    assert bytes(config.mem_read(MEM, len(after))) == after
    # Native count policy: third metadata reference asks to discard the
    # oldest; no actual dequeue/allocation/free is allowed to execute.
    policy = TargetOracle(replay_image)
    assert not policy.check((1, 2, 100000, 0, 2))
    assert policy.check((1, 2, 100000, 0, 3))
    report = {
        "schema": "NON_INSTALLABLE_NATIVE_PRECAPTURE_PROBE_PLAN",
        "installable": False, "source_sha256": digest, "source_label": PINNED[digest],
        "camera_io": False, "firmware_candidate_written": False,
        "changes": changes, "exact_inverse_verified": True,
        "boot_header_unchanged": True, "all_bytes_outside_list_unchanged": True,
        "intent": {"trigger": "original target S1 path", "metadata_retention": "count policy, two references",
                   "eligible_modes": "original raw enum1/0x1a/0x21 only; meanings not fully recovered"},
        "native_gate_cases": marker_cases, "native_edge_cases": edge_cases,
        "native_reference_cases": reference_cases,
        "count_policy_third_reference_prunes": True,
        "unverified_required_before_device_work": [
            "Fresh exact installed source and redundant working/original backups",
            "Physical electronic-shutter restriction and actual raw mode binding",
            "At least three suitable pixel buffers with correct ownership, not three metadata nodes",
            "Sensor acquisition before full press, complete save/discard/cancel flow",
            "All post and sender boundaries remain unexecuted in these tests",
            "Physical viewfinder/shooting/RAW and existing looks acceptance",
        ],
        "warning": "Diagnostic forced debug-path plan only. No normal enable control, firmware image or installation command is provided.",
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print("Non-installable seven-site plan verified offline; no firmware image or device operation produced.")


if __name__ == "__main__":
    main()
