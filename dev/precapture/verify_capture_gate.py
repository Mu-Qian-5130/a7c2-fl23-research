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
import subprocess
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
)
from unicorn.arm64_const import (
    UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
    UC_ARM64_REG_X3, UC_ARM64_REG_X4,
    UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC,
)
from support.reference import SPECS
from support.elf import image_loader, codegen_flags
from support.memory import MEM, STACK, STOP


def word(value):
    return struct.pack("<I", value)


class Native:
    def __init__(self, blob, donor):
        self.u = u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        self.donor = donor
        self.gate = 0xAC4B0A if donor else 0xA2F0FA
        self.debug = 0x19386AC if donor else 0x1A533A4
        self.producer = (0xA9A37A, 0xA9A390) if donor else (0xA06126, 0xA06132)
        self.consumer = (0x3B4166, 0x3B4176) if donor else (0x36D8AE, 0x36D8BE)
        self.enabled_field = 0x160  # donor only; never assumed for target
        self.mode_field = 0x170 if donor else 0x160
        self.flag_field = 0xF47 if donor else 0xD97
        self.marker_field = 0x68A8 if donor else 0x66E8
        pages = set()
        for address in [self.gate, self.debug, *self.producer, *self.consumer]:
            page = address & ~4095
            if page not in pages:
                u.mem_map(page, 4096)
                if page < len(blob):
                    u.mem_write(page, blob[page:page + 4096])
                pages.add(page)
        for address, size in [(MEM, 0x20000), (STACK, 0x4000), (STOP, 0x1000)]:
            u.mem_map(address, size)

    def run(self, start, end):
        self.u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
        self.u.reg_write(UC_ARM_REG_LR, STOP | 1)
        self.u.emu_start(start | 1, end, count=100)
        if self.u.reg_read(UC_ARM_REG_PC) != end:
            raise AssertionError("Unresolved native execution is not success")

    def leaf(self, mode, enabled, flags, selection):
        u = self.u
        u.mem_write(self.debug + 0xF0, bytes([flags, selection]))
        u.reg_write(UC_ARM_REG_R0, mode)
        u.reg_write(UC_ARM_REG_R1, enabled)
        self.run(self.gate, STOP)
        return u.reg_read(UC_ARM_REG_R0)

    def propagate(self, context, mode, enabled, flags, selection, initial_marker):
        u = self.u
        u.mem_write(MEM, bytes(0x10000))
        u.mem_write(self.debug + 0xF0, bytes([flags, selection]))
        u.mem_write(MEM + 0x10, word(context))
        if self.donor:
            u.mem_write(MEM + self.enabled_field, word(enabled))
        u.mem_write(MEM + self.mode_field, word(mode))
        # Original producer context is the private base, not base+8.
        u.reg_write(UC_ARM_REG_R4, MEM)
        u.reg_write(UC_ARM_REG_R5, MEM)
        u.reg_write(UC_ARM_REG_R6, 0)
        self.run(*self.producer)
        flag = u.mem_read(MEM + self.flag_field, 1)[0]

        frame = MEM + 0x10000
        before = bytearray([0xA5] * 0x10000)
        before[self.marker_field:self.marker_field + 4] = word(initial_marker)
        u.mem_write(frame, bytes(before))
        u.reg_write(UC_ARM_REG_R4, frame)
        # The original parameter getter returns private base+8. Omitting
        # this adjustment misidentifies the flag offset by eight bytes.
        u.reg_write(UC_ARM_REG_R5, MEM + 8)
        u.reg_write(UC_ARM_REG_R2, initial_marker)
        self.run(*self.consumer)
        actual = bytes(u.mem_read(frame, 0x10000))
        wanted = 2 if flag else initial_marker
        before[self.marker_field:self.marker_field + 4] = word(wanted)
        if actual != before:
            raise AssertionError("Unexpected frame metadata write")
        return flag, wanted


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
        command = [str(args.zig), "cc", "-target", triple, "-O2", "-shared", "-fPIC",
                   "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables",
                   "-fno-asynchronous-unwind-tables", "-nostdlib", "-Wl,--no-undefined",
                   "-o", str(dest), str(source)]
        command[4:4] = codegen_flags(arch)
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
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
