"""Synthetic original owner constructor; stops before property registration."""
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
from .memory import STACK, STOP

def original_owner_fixture(cp, root):
    """Native synthetic constructor/binding; property registration omitted."""
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    u.mem_map(0, (len(cp) + 4095) & ~4095)
    u.mem_write(0, cp)
    u.mem_map(root & ~4095, 0x2000)
    u.mem_map(STACK, 0x4000)
    u.mem_map(STOP, 4096)
    def stop(cpu, address, size, user):
        if address == 0x3AE744:
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, stop)
    for start, end in ((0xA17B7E, STOP), (0xA17D1C, 0x3AE744), (0xA17D32, STOP)):
        if start != 0xA17D32:
            u.reg_write(UC_ARM_REG_R0, root)
            u.reg_write(UC_ARM_REG_SP, STACK + 0x3000)
            u.reg_write(UC_ARM_REG_LR, STOP | 1)
        u.emu_start(start | 1, end, count=20000)
        if u.reg_read(UC_ARM_REG_PC) != end:
            raise AssertionError('Unresolved synthetic native constructor')
    return bytes(u.mem_read(root, 0x600))


