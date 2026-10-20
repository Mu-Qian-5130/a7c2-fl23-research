"""Read-only evidence for CP message/layout differences and RAW allocation.

Accepts pinned private firmware only. Outputs instruction evidence, never a
firmware candidate. Identifying a transport or allocator does not execute it.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from support.reference import SPECS


PATHS = {
    "a1ii-4.00": {
        "bridge_table": 0x3F7DE4,
        "bridge_entries": {0x300C: 0x3F7E9A, 0x3026: 0x3F800A, 0x3031: 0x3F8070},
        "s1_table": 0x3F6A16,
        "s1_entries": {0x8202: 0x3F6D70, 0x8203: 0x3F6D7A,
                       0x8205: 0x3F6E02, 0x8206: 0x3F6E72},
        "checks": [
            (0x277422, "str.w", "r1, [r3, #0x13c]"),
            (0x277434, "str.w", "r2, [r3, #0x140]"),
            (0x2774BA, "bl", "#0xb7aee0"),
            (0x2774EA, "bl", "#0xaad30e"),
            (0x3F6EEE, "bl", "#0xaae7ec"),
            (0x3F6EF8, "bl", "#0xaac5ee"),
            (0x3F6F3A, "str.w", "r6, [r0, #0x138]"),
            (0x3F6F56, "bl", "#0xaaf58a"),
            (0x3F6F5A, "bl", "#0x843ac2"),
            (0x843B04, "bl", "#0x8432c4"),
            (0xA948CC, "b.w", "#0xa94544"),
            (0xA948DC, "b.w", "#0xa94546"),
            (0xA94544, "bx", "lr"),
            (0xA94546, "bx", "lr"),
            (0x3F7EA8, "movw", "r0, #0x8202"),
            (0x3F7EC0, "mov.w", "r0, #0x100"),
            (0x3F800A, "movw", "r0, #0x8203"),
            (0x3F8070, "movw", "r0, #0x8205"),
            (0x3F6E02, "ldr", "r6, [r4, #0xc]"),
            (0x3F6E18, "bl", "#0xaad012"),
            (0x843658, "movw", "r0, #0x2ec8"),
            (0x84365C, "movt", "r0, #0x150"),
            (0xA9A37E, "ldr.w", "r1, [r5, #0x160]"),
            (0xA9A382, "ldr.w", "r0, [r5, #0x170]"),
            (0xA9A386, "bl", "#0xac4b0a"),
            (0xA9A38C, "strb.w", "r6, [r5, #0xf47]"),
            (0x3B4166, "ldrb.w", "r0, [r5, #0xf3f]"),
            (0x3B4170, "it", "ne"),
            (0x3B4172, "movs", "r2, #2"),
            (0x3B4174, "str", "r2, [r4, r0]"),
            (0x3B75FA, "bl", "#0x458eb8"),
            (0xA98F28, "bl", "#0x3b6d88"),
        ],
        "ranges": {
            "setting_native_store": (0x277418, 0x20),
            "pending_request_store": (0x2774B4, 0x38),
            "deferred_apply_and_completion": (0x3F6EEC, 0x72),
            "completion_packet_builder": (0x843AC2, 0x4A),
            "allocation_extra_hooks_are_noops": (0xA94544, 4),
            "capture_request_bridge": (0x3F7E9A, 0x36),
            "s1_edge_bridge": (0x3F800A, 0x18),
            "s1_info_bridge": (0x3F8070, 0xC),
            "s1_full_info_handler": (0x3F6E02, 0x70),
            "enable_event_handler": (0x3F6E72, 0x7A),
            "frame_gate_source": (0xA9A37A, 0x16),
            "frame_marker_consumer": (0x3B4166, 0x10),
            "raw_frame_allocation": (0xA98EB6, 0xC8),
            "raw_service_allocation": (0x458EB8, 0x4A),
        },
    },
    "a7c2-2.01": {
        "bridge_table": 0x3AE090,
        "bridge_entries": {0x300C: 0x3AE144, 0x3026: 0x3AE2AA, 0x3031: 0x3AE316},
        "s1_table": 0x3ACDD2,
        "s1_entries": {0x8202: 0x3AD12E, 0x8203: 0x3AD138,
                       0x8205: 0x3AD1BA, 0x8206: 0x3AD1D0},
        "checks": [
            (0xAE402A, "ldr", "r0, [r0, #-0xc]"),
            (0xAE402E, "bx", "lr"),
            (0xA1A030, "ldr", "r0, [r0, #0xc]"),
            (0x7D2A38, "bl", "#0xa18bce"),
            (0x7D2A4A, "b.w", "#0x3abc48"),
            (0xA1AD10, "bl", "#0x9da63a"),
            (0x3AE152, "movw", "r0, #0x8202"),
            (0x3AE16A, "mov.w", "r0, #0x100"),
            (0x3AE2AA, "movw", "r0, #0x8203"),
            (0x3AE316, "movw", "r0, #0x8205"),
            (0x3AD1BA, "ldrd", "r6, r8, [r4, #0xc]"),
            (0x3AD1BE, "movs", "r0, #1"),
            (0x3AD1D8, "ldrb.w", "r0, [r6, #0xf1]"),
            (0x7D31B8, "movw", "r0, #0xa720"),
            (0x7D31BC, "movt", "r0, #0x165"),
            (0xA060B2, "movw", "r2, #0xd64"),
            (0xA060B6, "blx", "#0x51660c"),
            (0xA06126, "ldr.w", "r0, [r4, #0x160]"),
            (0xA0612A, "bl", "#0xa2f0fa"),
            (0xA0612E, "strb.w", "r0, [r4, #0xd97]"),
            (0xA2F10C, "movs", "r0, #0"),
            (0x36D8AE, "ldrb.w", "r0, [r5, #0xd8f]"),
            (0x36D8B8, "it", "ne"),
            (0x36D8BA, "movs", "r2, #2"),
            (0x36D8BC, "str", "r2, [r4, r0]"),
            (0xA061D2, "add.w", "r0, r4, #8"),
            (0x3709EE, "bl", "#0x408870"),
            (0x4088CC, "movs", "r0, #0x20"),
            (0x4088DA, "movs", "r0, #0x55"),
            (0x4089DC, "movw", "r0, #0x8020"),
            (0x408A08, "movs", "r2, #0xd8"),
            (0xA04F34, "movw", "r8, #0x5ad8"),
            (0xA04F98, "bl", "#0x37019c"),
            (0xA04FE6, "push", "{r4, r5, r7, lr}"),
            (0xA04FFA, "bl", "#0xa13a60"),
            (0xA13A7E, "bl", "#0x408fdc"),
            (0x409032, "movs", "r0, #0x23"),
            (0x392E92, "bl", "#0xa04f28"),
            (0xA0DDAC, "bl", "#0xa09b34"),
        ],
        "ranges": {
            "native_origin_accessor": (0xAE402A, 6),
            "native_busy_predicate": (0xA1A030, 10),
            "native_reply_sender": (0x7D2A14, 0x3A),
            "native_release_helper": (0xA1ACFE, 0x1A),
            "capture_request_bridge": (0x3AE144, 0x2C),
            "s1_edge_bridge": (0x3AE2AA, 0x18),
            "s1_info_bridge": (0x3AE316, 0x10),
            "s1_info_handler": (0x3AD1BA, 0x16),
            "event_8206_handler": (0x3AD1D0, 0x46),
            "frame_gate_source": (0xA06126, 0xC),
            "normal_gate_disabled": (0xA2F0FA, 0x30),
            "frame_marker_consumer": (0x36D8AE, 0x10),
            "raw_prefetch_request": (0x3709D4, 0x20),
            "raw_service_request": (0x4088C8, 0x24),
            "raw_service_reply": (0x4089B4, 0x7C),
            "raw_frame_allocation": (0xA04F28, 0xBE),
            "raw_frame_release": (0xA04FE6, 0x3E),
            "raw_release_service_request": (0x40902C, 0x1A),
            "retention_stage_enqueue": (0xA0DD98, 0x24),
        },
    },
}


def audit(root):
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    result = {"mode": "offline-read-only", "models": {}}
    for model, spec in PATHS.items():
        data = (root / model / "components/cpapp-b.bin").read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != SPECS[model]["sha256"]:
            raise ValueError(f"Unsupported {model} fingerprint")
        for at, mnemonic, operands in spec["checks"]:
            ins = next(md.disasm(data[at:at + 4], at, count=1))
            if (ins.mnemonic, ins.op_str) != (mnemonic, operands):
                raise ValueError(f"Unexpected instruction at {model}:{at:#x}")
        tables = {}
        for kind, base, first in [("bridge", spec["bridge_table"], 0x3000),
                                  ("s1", spec["s1_table"], 0x8201)]:
            entries = {}
            for command, want in spec[kind + "_entries"].items():
                target = base + 2 * struct.unpack_from("<H", data, base + 2 * (command - first))[0]
                if target != want:
                    raise ValueError("Unexpected TBH destination")
                entries[hex(command)] = hex(target)
            tables[kind] = entries
        result["models"][model] = {"sha256": digest, "decoded_tables": tables,
            "ranges": {label: [{"file": hex(i.address), "instruction": f"{i.mnemonic} {i.op_str}"}
                               for i in md.disasm(data[a:a + n], a)]
                       for label, (a, n) in spec["ranges"].items()}}
    result["binding_hazards"] = [
        "Donor extra allocation/release hooks end in BX LR no-ops; they are not extra reference-count evidence.",
        "Donor commits enable only after native busy clears, then calls release before constructing its completion reply.",
        "0x8205 is a full S1 bitfield in donor handling but a two-word edge update in target handling.",
        "Target 0x8206 already has a different handler; do not inject donor enable messages unchanged.",
        "Donor master+0x138 enable flag overlaps the target mode source; do not copy donor field writes.",
        "Getter returns private parameter base+8: target producer+0xd97 matches consumer+0xd8f.",
    ]
    result["limits"] = ["No service allocation/free or camera operation is executed",
                        "RAW allocation path identification does not prove pre-S2 frame acquisition",
                        "Pixel pool capacity, allocation ownership across retention, sensor start and cancellation remain unverified"]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.firmware_root)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print("Pinned capture/control/RAW-path instruction audit passed; no camera I/O.")
