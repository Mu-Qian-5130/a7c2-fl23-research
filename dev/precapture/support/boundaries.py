"""Execute synthetic AArch64 slices, stopping BEFORE every known service call.

No automatic return stubs or successful native-operation mocks are supplied.
Instruction exhaustion without reaching one declared boundary is a failure.
Caller register/memory state persists between explicitly separate slices.
"""

from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as R

ARGUMENTS = (R.UC_ARM64_REG_X0, R.UC_ARM64_REG_X1, R.UC_ARM64_REG_X2, R.UC_ARM64_REG_X3)


class BoundaryRunner:
    def __init__(self, cpu, modules, *, stop, stack, count=2000):
        self.cpu = cpu
        self.stop = stop
        self.stack = stack
        self.count = count
        self.calls = {at: name for module in modules for at, name in module.calls.items()}
        self.targets = set()
        self.seen = []
        self.hook = cpu.hook_add(UC_HOOK_CODE, self._trace)

    def _trace(self, cpu, address, size, user):
        if address in self.calls or address in self.targets:
            self.seen.append(
                dict(
                    at=address,
                    call=self.calls.get(address),
                    args=[cpu.reg_read(r) for r in ARGUMENTS],
                )
            )
            cpu.emu_stop()

    def run(self, entry, targets=(), inputs=(), count=None):
        self.targets.clear()
        self.targets.update((self.stop, *targets))
        self.seen.clear()
        for register, value in inputs:
            self.cpu.reg_write(register, value & ((1 << 64) - 1))
        self.cpu.emu_start(entry, 0xFFFFFFFFFFFFFFFF, count=self.count if count is None else count)
        assert (
            len(self.seen) == 1 and self.cpu.reg_read(R.UC_ARM64_REG_PC) == self.seen[0]["at"]
        ), "Slice did not reach exactly one declared service/return boundary"
        return self.seen[0]

    def call(self, entry, args, targets=(), count=None):
        if len(args) > len(ARGUMENTS):
            raise ValueError("At most four explicit slice arguments are supported")
        return self.run(
            entry,
            targets,
            [
                *zip(ARGUMENTS, args),
                (R.UC_ARM64_REG_SP, self.stack + 0x8000),
                (R.UC_ARM64_REG_LR, self.stop),
            ],
            count=count,
        )
