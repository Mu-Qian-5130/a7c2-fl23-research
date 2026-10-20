"""Synthetic AP component calls with explicitly modeled service outcomes.

Use only in generated-component unit models. Original firmware audits must
use BoundaryRunner and stop before native services instead of returning here.
No service hook, operation result, retry or ownership policy is implicit.
"""

from unicorn import arm64_const as R

from .memory import STACK, STOP


def call_component(cpu, entry, args, *, count=50000):
    """Call an AArch64 component; require its return, not budget exhaustion."""
    if len(args) > 8:
        raise ValueError("At most eight register arguments are supported")
    for index, value in enumerate(args):
        cpu.reg_write(getattr(R, f"UC_ARM64_REG_X{index}"), value & ((1 << 64) - 1))
    cpu.reg_write(R.UC_ARM64_REG_SP, STACK + 0x3000)
    cpu.reg_write(R.UC_ARM64_REG_LR, STOP)
    cpu.emu_start(entry, STOP, count=count)
    assert cpu.reg_read(R.UC_ARM64_REG_PC) == STOP, "Component did not return"
    return cpu.reg_read(R.UC_ARM64_REG_X0) & 0xffffffff


def return_modeled_service(cpu, status):
    """Return an explicitly supplied unit-test status; poison scratch regs."""
    for index in range(1, 18):
        cpu.reg_write(getattr(R, f"UC_ARM64_REG_X{index}"), 0xde000000 + index)
    cpu.reg_write(R.UC_ARM64_REG_X0, status & ((1 << 64) - 1))
    cpu.reg_write(R.UC_ARM64_REG_PC, cpu.reg_read(R.UC_ARM64_REG_LR))
