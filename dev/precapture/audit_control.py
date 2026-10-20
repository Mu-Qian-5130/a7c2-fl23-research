"""Read-only comparison of pinned donor/target CP control paths.

Produces private instruction evidence, not a patch, installer or hardware test.
Offsets below are file offsets. CP pointers use a separate 0x108000 VA bias.
"""

from support.reference import SPECS
import argparse
import hashlib
import json
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB


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
