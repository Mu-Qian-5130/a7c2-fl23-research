"""Regression checks for offline service boundaries; no firmware or device I/O."""

import struct
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm64_const as R
from support.boundaries import BoundaryRunner
from support.build import compile_shared

CODE, STACK, STOP = 0x10000000, 0x40000000, 0x50000000


class ServiceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        for address, size in ((CODE, 4096), (STACK, 65536), (STOP, 4096)):
            self.cpu.mem_map(address, size)
        # mov x0,#7; add x0,x0,#1; ret. A declared service boundary at the
        # ADD must stop before modifying x0, not simulate a successful call.
        self.cpu.mem_write(CODE, struct.pack("<3I", 0xD28000E0, 0x91000400, 0xD65F03C0))

    def runner(self, *maps):
        return BoundaryRunner(
            self.cpu, [SimpleNamespace(calls=m) for m in maps], stop=STOP, stack=STACK
        )

    def test_service_stops_before_instruction(self):
        runner = self.runner({CODE + 4: "unexecuted-native-service"})
        result = runner.call(CODE, ())
        self.assertEqual(
            result, dict(at=CODE + 4, call="unexecuted-native-service", args=[7, 0, 0, 0])
        )
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_X0), 7)

    def test_all_modules_contribute_boundaries(self):
        runner = self.runner({CODE + 4: "first"}, {CODE + 8: "second"})
        self.assertEqual(runner.call(CODE, ())["call"], "first")
        self.assertEqual(runner.run(CODE + 8)["call"], "second")

    def test_return_is_an_observed_boundary(self):
        result = self.runner().call(CODE, ())
        self.assertEqual((result["at"], result["call"], result["args"][0]), (STOP, None, 8))

    def test_instruction_cap_is_not_completion(self):
        self.cpu.mem_write(CODE, struct.pack("<I", 0x14000000))  # b .
        with self.assertRaises(AssertionError):
            self.runner().call(CODE, (), count=5)

    def test_targets_reset_without_reinitializing_registers(self):
        runner = self.runner()
        first = runner.call(CODE, (), targets=(CODE + 4,))
        self.assertEqual(first["args"][0], 7)
        second = runner.run(CODE + 4)
        self.assertEqual((second["at"], second["args"][0]), (STOP, 8))
        self.assertEqual(len(runner.seen), 1)

    def test_signed_synthetic_inputs_and_stack(self):
        result = self.runner({CODE: "entry"}).call(CODE, (-1, 2, 3, 4))
        self.assertEqual(result["args"], [(1 << 64) - 1, 2, 3, 4])
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_SP), STACK + 0x8000)
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_LR), STOP)

    def test_extra_arguments_fail_before_execution(self):
        with self.assertRaises(ValueError):
            self.runner().call(CODE, (1, 2, 3, 4, 5))
        self.assertEqual(self.cpu.reg_read(R.UC_ARM64_REG_PC), 0)


class BuildFailureTests(unittest.TestCase):
    def test_failed_compiler_is_not_a_valid_fixture(self):
        with patch("support.build.subprocess.run", return_value=SimpleNamespace(
                returncode=1, stderr="target compile failed")) as run:
            with self.assertRaisesRegex(RuntimeError, "target compile failed"):
                compile_shared('zig', 'thumb', 'unused.elf',
                    ['unused.c'])
        self.assertEqual(run.call_count, 1)

    def test_timeout_propagates_without_retry(self):
        with patch("support.build.subprocess.run", side_effect=subprocess.TimeoutExpired(
                "zig", 120)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                compile_shared('zig', 'aarch64', 'unused.elf',
                    ['unused.c'])
        self.assertEqual(run.call_count, 1)

    def test_unknown_target_never_launches_compiler(self):
        with patch("support.build.subprocess.run") as run:
            with self.assertRaises(KeyError):
                compile_shared('zig', 'x86', 'unused.elf',
                    ['unused.c'])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
