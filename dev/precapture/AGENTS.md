# Pre-capture research

Read README.md for current state and CONTROL-PATHS.txt for detailed evidence.
This directory is not a camera installer. Keep main/releases untouched when
working on the pre-capture feature branch.

- Put shared emulator/build/source fixtures in `support/`. Do not make a new
  verifier depend on another verifier for general ELF or boundary utilities.
  Use shared original-instruction fixtures directly from support/; retain old
  exports when private evidence replay paths depend on them. Use build.py for
  ordinary component builds; keep specialized linker/LTO settings explicit.
- Boundary execution stops BEFORE original external services. Never insert a
  fake successful native call to make an audit pass. Instruction exhaustion
  without the expected boundary is a test failure.
- Use `ap_linux_aarch64.h` for Linux open flags and independently check them
  with `support/aarch64_abi.py`. Do not copy host/x86 flag literals into ARM64
  code or use those same literals as the verifier's only expected values.
- Keep explicit target FP/NEON exclusions in `support/elf.py`. Zig0.13 can
  append target features after `-mgeneral-regs-only`; that switch alone does
  not prevent vector aggregate copies. Never bypass the generated ISA check.
- Preserve source fingerprints, ownership UNKNOWN states, one-shot fences,
  inverse evidence and original/known-working backups. A source drift needs
  independent reconstruction, not a masked or relaxed hash check.
- CP parameter `00030072` half-press testing caused a crash and is retired.
  Do not recreate the removed forced-native-plan generator or retry that path.
- Current camera CP can belong to another native-photo calibration trial.
  An old pinned fixture is not a fresh camera identity. Do not restore or
  overwrite another trial as part of pre-capture diagnostics.
- Public files are offline source/evidence only. Keep firmware, body data,
  compiled diagnostics, private operators and deployment artifacts private.
- Device work needs current ownership of the camera. New parameter/ROM/AP or
  CP RAM patches require a concrete candidate and recovery review plus the
  owner's explicit approval. Temporary diagnostic execution must respect the
  separately reviewed scope; no replay of an unknown operation.
- For refactors, compare original-source audit reports and existing component
  models before/after; validate the service-stop helpers' failure paths.
  Model success is not physical pre-capture, boot safety or camera recovery.
- Derive VM CPU reset entries from the admitted ELF header and executable
  segments. Section alignment/build notes can move `_start` beyond the linker
  origin; do not hardcode that origin for secondary CPUs.
- Use `cpu-index` on each HMP/QMP per-CPU observation. A standalone `cpu N`
  command does not persist its selection across separate QMP HMP calls.
- Do not read banked GIC MMIO through debugger `memsave`: QEMU's callback can
  require `current_cpu`, absent in that observer context. Use actual guest
  instructions or source-qualified RAM state; retain failed observer evidence.
- In stock2.01 CP, the `0x63476c` workers wait on flag0x56/bit1 before the
  UFI finalization path. Do not force that event or treat its `0x634e80`
  return as a required normal initialization boundary.

No Claude or additional agents without explicit user authorization.
