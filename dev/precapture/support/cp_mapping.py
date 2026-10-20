"""Pinned CP layout and synthetic page-mapper fixtures; no firmware output."""
import struct
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)

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
    # Original bootstrap0x108438/0x108448/0x108450 initializes0x10c12,
    # independently executed by audit_bootstrap_memory.py.
    cpu.mem_write(0x30000000, struct.pack("<4096I", *[(i << 20) | 0x10C12 for i in range(4096)]))
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


