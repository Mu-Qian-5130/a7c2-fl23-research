"""Original enable/marker slices on synthetic memory, never physical capture."""
import struct
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from .memory import MEM, STACK, STOP

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


