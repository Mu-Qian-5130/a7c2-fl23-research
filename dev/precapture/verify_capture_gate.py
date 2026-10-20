"""Offline replay of native enable gates and frame-marker propagation.

No allocator, OS service, transport or sensor callback is replaced with a
success result. Only leaf instructions and bounded producer/consumer slices
execute. Synthetic frame metadata is not an acquired image.
"""
import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC
from support.native_gate import word, Native  # compatibility exports
from support.reference import SPECS
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM, STACK, STOP


def compiled(u, symbol, arch, values):
    if arch == "aarch64":
        regs = [UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
                UC_ARM64_REG_X3, UC_ARM64_REG_X4]
        sp, lr, pc = UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC
    else:
        regs = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]
        sp, lr, pc = UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
    u.reg_write(sp, STACK + 0x3000)
    for reg, value in zip(regs, values):
        u.reg_write(reg, value)
    if len(values) > len(regs):
        u.mem_write(STACK + 0x3000, word(values[4]))
    u.reg_write(lr, STOP if arch == "aarch64" else STOP | 1)
    u.emu_start(symbol, STOP, count=100)
    if u.reg_read(pc) != STOP:
        raise AssertionError("Compiled gate did not return")
    return u.reg_read(regs[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware-root", type=Path, required=True)
    parser.add_argument("--zig", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Preserve prior runs and never overwrite a firmware input directory.
    args.output.mkdir(parents=True, exist_ok=False)
    engines = {}
    for model in SPECS:
        blob = (args.firmware_root / model / "components/cpapp-b.bin").read_bytes()
        if hashlib.sha256(blob).hexdigest() != SPECS[model]["sha256"]:
            raise ValueError("Unsupported original CP fingerprint")
        engines[model] = Native(blob, model == "a1ii-4.00")
    donor, target = engines["a1ii-4.00"], engines["a7c2-2.01"]
    vectors = list(itertools.product([0, 1, 0x1A, 0x21, 2], [0, 1, 2], [0, 0x10], [0, 0xFF]))
    cases = []
    for mode, enabled, flags, selection in vectors:
        normal = int(enabled == 1)
        override = int(mode in (1, 0x1A, 0x21) and selection != 0xFF)
        expected = override if flags & 0x10 else normal
        native = donor.leaf(mode, enabled, flags, selection)
        stock = target.leaf(mode, enabled, flags, selection)
        assert native == expected
        assert stock == (override if flags & 0x10 else 0)
        for context, marker in itertools.product([0, 1], [0, 1]):
            donor_flag, donor_marker = donor.propagate(context, mode, enabled, flags, selection, marker)
            target_flag, target_marker = target.propagate(context, mode, enabled, flags, selection, marker)
            assert donor_flag == (native if context == 0 else 0)
            assert target_flag == stock
            cases.append({"mode_raw": mode, "enabled": enabled, "debug_flags": flags,
                          "debug_selection": selection, "context_word_10": context,
                          "initial_marker": marker, "donor_flag": donor_flag,
                          "stock_target_flag": target_flag,
                          "donor_marker": donor_marker, "stock_target_marker": target_marker})
    source = Path(__file__).with_name("capture_gate.c")
    compared = 0
    for arch, triple in [("aarch64", "aarch64-linux-gnu"), ("thumb", "thumb-linux-gnueabi")]:
        dest = args.output / (arch + "-capture-gate.elf")
        compile_shared(args.zig, arch, dest,
            [source], optimization='-O2', debug=False, symbolic=False)
        u, symbols = image_loader(dest, arch, ("precapture_enable_gate", "precapture_frame_gate"))
        for values in vectors:
            want = donor.leaf(*values)
            assert compiled(u, symbols["precapture_enable_gate"], arch, values) == want
            compared += 1
            for context in [0, 1]:
                flag, _ = donor.propagate(context, *values, 0)
                assert compiled(u, symbols["precapture_frame_gate"], arch, [context, *values]) == flag
                compared += 1
    report = {"status": "OFFLINE_GATE_AND_METADATA_ONLY", "camera_io": False,
              "firmware_modified": False, "native_propagation_cases": len(cases),
              "compiled_native_comparisons": compared, "cases": cases,
              "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "limits": ["No image acquired or retained", "Target enabled state and code placement remain unbound",
                         "No debug flags are changed on a camera", "Native slices contain no mocked external calls"]}
    (args.output / "capture-gate.private.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))


if __name__ == "__main__":
    main()
