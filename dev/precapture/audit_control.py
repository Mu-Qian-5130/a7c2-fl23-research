"""Read-only comparison of pinned donor/target CP control paths.

Produces private instruction evidence, not a patch, installer or hardware test.
Offsets below are file offsets. CP pointers use a separate 0x108000 VA bias.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB


SPECS = {
    "a1ii-4.00": {
        "sha256": "96b41427958c1b412b3e15c5bd9b51e34657ae1e1246344438b8368031ca4859",
        "ranges": {
            "s1_predicate_use": (0x3F6E02, 0x70),
            "s1_predicate": (0xAAD012, 0xD0),
            "enable_filter": (0xAC4B0A, 0x34),
            "start_wrapper": (0xAAF626, 0x18),
            "stop_wrapper": (0xAAF63E, 0x18),
            "start_message": (0xA6E18E, 0x4A),
            "stop_message": (0xA6E1E6, 0x4A),
            "request_receiver": (0x395FBC, 0x2FC),
            "request_selector": (0xA6C62C, 0x3E),
            "capture_arbitration": (0x396D90, 0x280),
            "capture_message": (0xA6F1FC, 0x62),
            "retention_task_start": (0xA9DAB2, 0x42),
            "retention_task_construct": (0xA9DCE4, 0x2E),
            "retention_config_enqueue": (0x3B8C00, 0x36),
            "retention_event_enqueue": (0x3B8C60, 0x36),
            "task_entry_trampoline": (0xAD079C, 0x3A),
            "task_queue_loop": (0x4585E8, 0x78),
        },
        "calls": [
            (0x3F6E18, 0xAAD012), (0x3F6E6C, 0xAAF626),
            (0xAAF636, 0xA6E18E), (0xAAF64E, 0xA6E1E6),
            (0x39635C, 0x395FBC), (0x397002, 0xA6F1FC),
        ],
        "instructions": [
            (0xA6E1AC, "movs", "r1, #5"),
            (0xA6E1AE, "movs", "r2, #0xd"),
            (0xA6E1B2, "movw", "r1, #0x4038"),
            (0xA6E208, "movw", "r1, #0x4039"),
            (0xA6C65A, "adds", "r4, #0x14"),
            (0xA6C65E, "cmp", "r6, #0xf"),
            (0xA6F228, "movw", "r1, #0x300c"),
            (0x396F60, "cmp", "r6, #0xd"),
            (0xA9DCE8, "movs", "r2, #0xae"),
            (0xA9DCEE, "str", "r2, [r0, #0x14]"),
            (0xA9DCF0, "movs", "r2, #0x51"),
            (0xA9DCF2, "str", "r2, [r0, #0x18]"),
        ],
        "priority_table": 0x395BE8,
        "priority_count": 15,
        "priority_values": [0, 6, 6, 11, 3, 2, 1, 8, 9, 12, 5, 4, 10, 13, 7],
        "selector_stride": 20,
        "task_names": 0xE6B3E8,
        "task_count": 293,
        "task_index": 173,
        "task_name": "CAP_PRECAP_CTL",
        "task_entry": 0xBD879D,
    },
    "a7c2-2.01": {
        "sha256": "f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428",
        "ranges": {
            "s1_start_call": (0x3AD538, 0x10),
            "s1_other_start_call": (0x3AD5A4, 0x12),
            "start_wrapper": (0xA1AD9A, 0x18),
            "stop_wrapper": (0xA1ADB2, 0x18),
            "start_message": (0x9DAC1E, 0x4A),
            "stop_message": (0x9DAC76, 0x48),
            "request_receiver": (0x3508D4, 0x2D8),
            "request_selector": (0x9D917C, 0x3E),
            "capture_arbitration": (0x9DA2C0, 0x18A),
            "capture_message": (0x9DBBFA, 0x62),
            "reference_notification": (0x9DBCCA, 0x58),
            "retention_owner_bind": (0xA09A8E, 0x40),
            "retention_owner_source": (0xA0589E, 0x18),
            "retention_owner_construct": (0xA05D8E, 0x32),
            "retention_config_enqueue": (0xA09AEE, 0x3A),
            "retention_event_enqueue": (0xA09B34, 0x3A),
            "callback_enqueue": (0x407F1C, 0x30),
        },
        "calls": [
            (0x3AD540, 0xA1AD9A), (0x3AD5AE, 0xA1AD9A),
            (0x3AD4C6, 0xA1ADB2), (0x3AD5EA, 0xA1ADB2),
            (0xA1ADAA, 0x9DAC1E), (0xA1ADC2, 0x9DAC76),
            (0x350C4A, 0x3508D4), (0x9DA3CA, 0x9DBBFA),
            (0x350AC4, 0x9DBCCA),
            (0xA058A8, 0xA3B5DC),
            (0xA09B20, 0x407F1C), (0xA09B66, 0x407F1C),
        ],
        "instructions": [
            (0x9DAC3C, "movs", "r1, #5"),
            (0x9DAC3E, "movs", "r2, #0xd"),
            (0x9DAC42, "movw", "r1, #0x4038"),
            (0x9DAC98, "movw", "r1, #0x4039"),
            (0x9D91AA, "adds", "r4, #0x10"),
            (0x9D91AE, "cmp", "r6, #0xe"),
            (0x9DBC26, "movw", "r1, #0x300c"),
            (0x350AA8, "movs", "r1, #0xd"),
            (0x9DBCF8, "movw", "r1, #0x3026"),
            (0xA0589E, "movw", "r4, #0xaae0"),
            (0xA058A2, "movt", "r4, #0x1a3"),
            (0xA09ACA, "str", "r4, [r0]"),
            (0xA05D92, "movs", "r1, #0x88"),
            (0xA05DA0, "str", "r1, [r0, #0x14]"),
            (0xA05DA2, "movs", "r1, #0x38"),
            (0xA05DA4, "str", "r1, [r0, #0x18]"),
        ],
        "priority_table": 0x350564,
        "priority_count": 14,
        "priority_values": [0, 6, 6, 10, 3, 2, 1, 7, 8, 11, 5, 4, 9, 12],
        "selector_stride": 16,
        "task_names": 0xDAD0EC,
        "task_count": 279,
        "task_index": 135,
        "task_name": "CAM_CAP_MGR",
        "task_entry": 0xB435A3,
    },
}


def audit(root):
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    result = {"mode": "offline-read-only", "models": {}}
    for model, spec in SPECS.items():
        data = (root / model / "components" / "cpapp-b.bin").read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != spec["sha256"]:
            raise ValueError(f"Unsupported {model} CP fingerprint: {digest}")

        def one(at):
            return next(md.disasm(data[at:at + 4], at, count=1))

        for at, dest in spec["calls"]:
            ins = one(at)
            if ins.mnemonic != "bl" or ins.op_str != f"#{dest:#x}":
                raise ValueError(f"Unexpected call at {model}:{at:#x}")
        for at, mnemonic, operands in spec["instructions"]:
            ins = one(at)
            if (ins.mnemonic, ins.op_str) != (mnemonic, operands):
                raise ValueError(f"Unexpected instruction at {model}:{at:#x}")
        # These are TBB branch tables, not arrays of priority integers.
        table = spec["priority_table"]
        priorities = []
        for index in range(spec["priority_count"]):
            target = table + 2 * data[table + index]
            ins = one(target)
            if index == 0:
                if ins.mnemonic != "uxtb" or ins.op_str != "r0, r0":
                    raise ValueError("Unexpected zero-priority return")
                value = 0  # The function initializes r0=0 before dispatch.
            else:
                if ins.mnemonic != "movs" or not ins.op_str.startswith("r0, #"):
                    raise ValueError("Unexpected priority branch")
                value = int(ins.op_str.split("#")[1], 0)
            priorities.append({"request": index, "branch_file": hex(target), "priority": value})
        if [p["priority"] for p in priorities] != spec["priority_values"]:
            raise ValueError("Unexpected priority mapping")
        ranges = {}
        for label, (start, length) in spec["ranges"].items():
            ranges[label] = [
                {"file": hex(i.address), "instruction": f"{i.mnemonic} {i.op_str}"}
                for i in md.disasm(data[start:start + length], start)
            ]
        names = spec["task_names"]
        count = spec["task_count"]
        # The task ID array is immediately before names; each descriptor is
        # 40 bytes. Validate all IDs and the boundary count before indexing.
        ids_start = names - count * 4
        if struct.unpack_from("<I", data, ids_start - 4)[0] != count:
            raise ValueError("Unexpected task count")
        if struct.unpack_from(f"<{count}I", data, ids_start) != tuple(range(1, count + 1)):
            raise ValueError("Unexpected task ID array")
        descriptors = ids_start - 4 - count * 40
        index = spec["task_index"]
        pointer = struct.unpack_from("<I", data, names + index * 4)[0] - 0x108000
        name = data[pointer:data.index(b"\0", pointer)].decode("ascii")
        descriptor = struct.unpack_from("<10I", data, descriptors + index * 40)
        if name != spec["task_name"] or descriptor[2] != spec["task_entry"] or descriptor[4] != 0x2000:
            raise ValueError("Unexpected native task descriptor")
        result["models"][model] = {
            "sha256": digest, "selector_stride": spec["selector_stride"],
            "priorities": priorities, "ranges": ranges,
            "verified_direct_calls": [{"file": hex(a), "target_file": hex(b)} for a, b in spec["calls"]],
            "task": {"id": index + 1, "name": name, "descriptor_table_file": hex(descriptors),
                     "descriptor_file": hex(descriptors + index * 40),
                     "entry_va": hex(descriptor[2]), "initial_priority_raw": descriptor[3],
                     "stack_bytes": descriptor[4], "stack_va": hex(descriptor[5])},
        }
    result["limits"] = [
        "Request subtype 13 is present in both control paths; identical meaning at every receiver is not established.",
        "A7C II has original start/stop helpers and a 0x300c capture-message path, not proof of pre-S2 sensor acquisition.",
        "Donor arbitration has special subtype-13 priority/switch logic absent from the compared target routine.",
        "Native retention task descriptors and target owner binding are identified; this does not bind the missing 0x4173 enable event.",
        "Capture-message receiver delivery, pixel buffers and sensor timing remain unverified.",
        "No firmware mutation or camera connection is performed.",
    ]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New private JSON path")
    args = parser.parse_args()
    result = audit(args.firmware_root)
    # Never overwrite an earlier report or an input file.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print("Pinned control-path comparison passed; private evidence written.")
    print("No camera operation or working pre-capture claim.")
