"""Verify AP marshalling through the exact native-sender call boundary.

The sender is never executed or replaced with a successful return. No CP
reply is synthesized. These checks do not establish message delivery.
"""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from unicorn import UC_HOOK_CODE
from unicorn.arm64_const import (
    UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
    UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5,
    UC_ARM64_REG_SP, UC_ARM64_REG_LR,
)
from support.elf import image_loader, codegen_flags
from support.memory import MEM, STACK, STOP
from verify_offline import oracle

SEND = 0x21000000
AP_HASHES = {
    "a7c2-2.01": "2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b",
    "a1ii-4.00": "d04cc70b41382a147ef5c67d7e86ba706d66526aee17619767b07cbb416b77ca",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware-root", type=Path, required=True)
    parser.add_argument("--zig", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    images = {}
    for model, digest in AP_HASHES.items():
        data = (args.firmware_root / model / "components/appFw.so").read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Unsupported original AP fingerprint")
        images[model] = data
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    for model, at, mnemonic, operands in [
        ("a7c2-2.01", 0x35358B8, "stp", "x29, x30, [sp, #-0xa0]!"),
        ("a7c2-2.01", 0x3535BCC, "bl", "#0x35358b8"),
        ("a7c2-2.01", 0x3535BC4, "mov", "x2, #0xc"),
        ("a1ii-4.00", 0x31E3574, "bl", "#0x31e0f8c"),
        ("a1ii-4.00", 0x31E357C, "cmp", "w0, #0xf, lsl #12"),
        ("a1ii-4.00", 0x31E3580, "cset", "w0, ne"),
    ]:
        ins = next(md.disasm(images[model][at:at + 4], at))
        assert (ins.mnemonic, ins.op_str) == (mnemonic, operands)
    args.output.mkdir(parents=True, exist_ok=False)
    dest = args.output / "aarch64-ap-transport.elf"
    sources = [Path(__file__).with_name(name) for name in ["ap_transport.c", "offline_codec.c"]]
    command = [str(args.zig), "cc", "-target", "aarch64-linux-gnu", "-O2", "-shared", "-fPIC",
               "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables",
               "-fno-asynchronous-unwind-tables", "-nostdlib", "-Wl,--no-undefined,-Bsymbolic",
               "-o", str(dest), *map(str, sources)]
    command[4:4] = codegen_flags('aarch64')
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    u, symbols = image_loader(dest, "aarch64", ("precapture_ap_setting", "precapture_ap_shooting"))
    u.mem_map(SEND, 4096)
    captured = []

    def boundary(cpu, address, size, user):
        if address != SEND:
            return
        route, pointer, length, reply_command, reply, reply_size = [cpu.reg_read(r) for r in
            [UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5]]
        captured.append({"route": route, "packet_hex": bytes(cpu.mem_read(pointer, length)).hex(),
                         "request_size": length, "reply_command": reply_command,
                         "reply_size": reply_size,
                         "reply_initial_hex": bytes(cpu.mem_read(reply, reply_size)).hex() if reply_size else "",
                         "reply_pointer_is_null": reply == 0})
        cpu.emu_stop()

    u.hook_add(UC_HOOK_CODE, boundary)

    def run(kind, request, domain=0):
        before = len(captured)
        u.mem_write(MEM, struct.pack("<3I", *request))
        u.mem_write(MEM + 0x100, bytes([0xA5]) * 32)
        for reg, value in [(UC_ARM64_REG_X0, MEM), (UC_ARM64_REG_X1, MEM + 0x100),
                           (UC_ARM64_REG_X2, domain if kind == "setting" else SEND),
                           (UC_ARM64_REG_X3, SEND), (UC_ARM64_REG_SP, STACK + 0x3000),
                           (UC_ARM64_REG_LR, STOP)]:
            u.reg_write(reg, value)
        u.emu_start(symbols["precapture_ap_" + kind], STOP, count=1000)
        assert len(captured) == before + 1
        assert bytes(u.mem_read(MEM + 0x100, 32)) == bytes([0xA5]) * 32
        return captured[-1]

    for duration in [0, 10, 19]:
        for trigger in [0, 1, 2]:
            for domain in [0, 1]:
                context = 0x12345678
                item = run("setting", [context, duration, trigger], domain)
                expected = struct.pack("<BBHI", 5, 0, 0x4172, context) + oracle(images["a1ii-4.00"], "setting", [duration, trigger, domain])
                assert item["route"] == 0x90030001 and bytes.fromhex(item["packet_hex"]) == expected
                assert item["reply_command"] == 0 and item["reply_size"] == 0 and item["reply_pointer_is_null"]
    for setting in [0, 1]:
        for prohibited in [0, 1]:
            context = 0x12345678
            item = run("shooting", [context, setting, prohibited])
            expected = struct.pack("<BBHI", 5, 0, 0x4173, context) + oracle(images["a1ii-4.00"], "shooting", [setting, prohibited])
            assert item["route"] == 0x90030001 and bytes.fromhex(item["packet_hex"]) == expected
            assert item["reply_command"] == 0x4173 and item["reply_size"] == 12
            assert item["reply_initial_hex"] == "00" * 12
    report = {"mode": "OFFLINE_AP_SENDER_BOUNDARY_ONLY", "camera_io": False, "firmware_modified": False,
              "target_sender_file_va": "0x35358b8", "sender_executed": False,
              "CP_reply_synthesized": False, "boundaries": captured,
              "limits": ["Target load bias and code placement unbound", "Target domain dependency unbound",
                         "Sender results and CP completion were not tested; no reply was fabricated"]}
    (args.output / "ap-transport.private.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"AP marshalling boundaries verified: {len(captured)}; native sender and CP replies not executed.")


if __name__ == "__main__":
    main()
