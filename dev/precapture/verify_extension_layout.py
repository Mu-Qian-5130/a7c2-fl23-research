"""Offline CP extension mapping experiment; outputs no firmware candidate.

The six-look v4 fixture has only80 text-tail bytes. This experiment executes
the original ARM page mapper plus a small wrapper to test an alternative:
put a proposed payload in the final rodata-page padding and remove XN on
that one page, while keeping data/BSS mappings and existing contents intact.
Loader copy order, real MMU operation and camera boot remain unverified.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
)

BASE, MAPPER, STOP = 0x108000, 0x108768, 0x31000000
PINNED = {
    "f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428": "stock2.01",
    "90d1ed6d47df21c881936816647973b1562764458122eb72869e60b1a624900b": "six-look-v4-private-fixture",
    "3d6656b933fc681282f920364e5f3b788117c4345a89ec6b9df9862c5563f8a1": "six-look-current-readback-20261019",
}


def layout(image):
    result = {}
    for label, at, flags in [("text", 0x20124, 15), ("rodata", 0x20130, 13),
                             ("data", 0x2013C, 12), ("bss", 0x20148, 12)]:
        source, length, virtual = struct.unpack_from("<3I", image, at)
        assert virtual == source + 0x128000
        result[label] = {"source": source, "length": length, "virtual": virtual, "flags": flags}
    return result


def emulator(image):
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(BASE, 0x2000)
    cpu.mem_write(BASE, image[:0x2000])
    cpu.mem_map(0x30000000, 0x60000)
    cpu.mem_map(STOP, 4096)
    cpu.mem_write(0x30000000, struct.pack("<4096I", *[(i << 20) | 0x10412 for i in range(4096)]))
    for address, value in [(0x108F1C, 0x30000000), (0x108D98, 0x30010000), (0x108D9C, 0)]:
        cpu.mem_write(address, struct.pack("<I", value))
    return cpu


def invoke(cpu, address, segment):
    for reg, value in [(UC_ARM_REG_R0, segment["virtual"]), (UC_ARM_REG_R1, segment["length"]),
                       (UC_ARM_REG_R2, segment["source"] + 0x128000), (UC_ARM_REG_R3, segment["flags"]),
                       (UC_ARM_REG_SP, 0x3005F000), (UC_ARM_REG_LR, STOP)]:
        cpu.reg_write(reg, value)
    cpu.emu_start(address, STOP, count=1000000)
    assert cpu.reg_read(UC_ARM_REG_PC) == STOP


def translation(cpu, address):
    def get(at):
        return struct.unpack("<I", cpu.mem_read(at, 4))[0]
    first = get(0x30000000 + (address >> 20) * 4)
    if first & 3 == 2:
        return {"physical": (first & 0xFFF00000) + (address & 0xFFFFF),
                "xn": bool(first & 16), "descriptor": first, "kind": "section"}
    assert first & 3 == 1
    second = get((first & 0xFFFFFC00) + ((address >> 12) & 255) * 4)
    assert second & 2 == 2
    return {"physical": (second & 0xFFFFF000) + (address & 4095),
            "xn": bool(second & 1), "descriptor": second, "kind": "small-page"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cp", type=Path, required=True)
    parser.add_argument("--payload-bytes", type=int, required=True)
    parser.add_argument("--state-bytes", type=int, default=40)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    image = args.cp.read_bytes()
    digest = hashlib.sha256(image).hexdigest()
    if digest not in PINNED:
        raise ValueError("Unsupported private source fingerprint")
    assert args.payload_bytes > 0 and args.state_bytes > 0
    for at, value in [(0x4D0, 0xE3A0300F), (0x4EC, 0xE3A0300D),
                      (0x500, 0xE3A0300C), (0x518, 0xE3A0300C), (0x520, 0xEB000090)]:
        assert struct.unpack_from("<I", image, at)[0] == value
    original = layout(image)
    projected = {name: dict(segment) for name, segment in original.items()}
    stub_va = (original["text"]["virtual"] + original["text"]["length"] + 3) & ~3
    payload_va = (original["rodata"]["virtual"] + original["rodata"]["length"] + 3) & ~3
    state_va = (original["data"]["virtual"] + original["data"]["length"] + 3) & ~3
    page = payload_va & ~4095
    assert payload_va + args.payload_bytes <= original["data"]["virtual"]
    assert (payload_va + args.payload_bytes - 1) & ~4095 == page
    assert state_va + args.state_bytes <= original["bss"]["virtual"]
    assembly = ["push {r4,lr}", f"bl {MAPPER:#x}", f"movw r0, #{page & 65535}",
                f"movt r0, #{page >> 16}", "mov r1, #4096", "mov r2, r0",
                "mov r3, #15", f"bl {MAPPER:#x}", "pop {r4,pc}"]
    stub = bytes(Ks(KS_ARCH_ARM, KS_MODE_ARM).asm(";".join(assembly), addr=stub_va)[0])
    assert stub_va + len(stub) <= original["rodata"]["virtual"]
    projected["text"]["length"] = stub_va + len(stub) - original["text"]["virtual"]
    projected["rodata"]["length"] = payload_va + args.payload_bytes - original["rodata"]["virtual"]
    projected["data"]["length"] = state_va + args.state_bytes - original["data"]["virtual"]
    baseline, candidate = emulator(image), emulator(image)
    candidate.mem_map(stub_va & ~4095, 4096)
    candidate.mem_write(stub_va, stub)
    for name in original:
        invoke(baseline, MAPPER, original[name])
        invoke(candidate, stub_va if name == "bss" else MAPPER, projected[name])
    probes = {}
    for label, address in [("original-text", original["text"]["virtual"]),
                           ("bootstrap-wrapper", stub_va), ("original-rodata", original["rodata"]["virtual"]),
                           ("final-rodata-page-prefix", page), ("payload", payload_va),
                           ("payload-end", payload_va + args.payload_bytes - 1),
                           ("state", state_va), ("bss-start", original["bss"]["virtual"]),
                           ("bss-end", original["bss"]["virtual"] + original["bss"]["length"] - 1)]:
        before, after = translation(baseline, address), translation(candidate, address)
        assert before["physical"] == after["physical"] == address
        if address & ~4095 == page:
            assert before["xn"] and not after["xn"]
            assert before["kind"] == after["kind"] == "small-page"
            assert before["descriptor"] ^ after["descriptor"] == 1
        else:
            assert before == after
        probes[label] = {"virtual": hex(address), "before": before, "after": after}
    report = {"status": "OFFLINE_NATIVE_MAPPER_EXPERIMENT_ONLY", "source": PINNED[digest], "sha256": digest,
              "camera_io": False, "firmware_candidate_written": False,
              "original_text_tail_bytes": original["rodata"]["virtual"] - stub_va,
              "original_rodata_tail_bytes": original["data"]["virtual"] - payload_va,
              "original_data_tail_bytes": original["bss"]["virtual"] - state_va,
              "bootstrap_wrapper_bytes": len(stub), "payload_bytes": args.payload_bytes,
              "state_bytes": args.state_bytes, "probes": probes,
              "limits": ["No firmware candidate produced", "Original mapper and wrapper executed; MMU itself not enabled",
                         "Existing final-rodata-page prefix also becomes executable; all other tested descriptor bits unchanged",
                         "Copy order, caches, runtime ownership, new code execution and camera boot not established",
                         "Geometric padding is not approval to use storage or install this mapping"]}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k != "probes"}, indent=2))


if __name__ == "__main__":
    main()
