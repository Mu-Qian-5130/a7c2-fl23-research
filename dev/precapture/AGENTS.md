# Pre-capture research

Read README.md for current state and CONTROL-PATHS.txt for detailed evidence.
This directory is not a camera installer. Keep main/releases untouched when
working on the pre-capture feature branch.

At each phase boundary and before device preparation, refresh origin/main
and review its shared-runtime changes. Keep main as an ancestor of this
feature branch; retain main's product files outside this research directory.
Do not push unfinished research to main. A transport fix is not a pre-capture
implementation or permission to inherit its cleanup/recovery behavior.

At the same checkpoint, review imports and active callers for redundancy.
Consolidate repeated plumbing into support/; remove unused alternatives only
after checking source, docs and private evidence replay callers. Keep a small
compatibility export when a real replay still uses it. Refactors must preserve
original-source reports and model results, not just pass new replacement tests.

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
- SPECS ranges/calls in support/reference.py are FILE OFFSETS. The staged
  CP copy uses a separate +108000 fixture base. Record both coordinates and
  independently check encoded calls before qualifying named ranges. The old
  AT74 seventeen-range comparison mixed these coordinates and is invalid;
  AT78 repeats it correctly, preserving the original report. Neither admits
  whole current firmware, physical loaded addresses or RAM.
- CP parameter `00030072` half-press testing caused a crash and is retired.
  Do not recreate the removed forced-native-plan generator or retry that path.
- Current camera CP can belong to another native-photo calibration trial.
  An old pinned fixture is not a fresh camera identity. Do not restore or
  overwrite another trial as part of pre-capture diagnostics.
- The October23 file-only acquisition differs from October21: complete CP
  matches the factory reference, AP does not. Structural look classification
  and unchanged hook windows do not identify the entire AP or loaded RAM.
  Do not reinstall the archived six-look image or use that old runtime tag
  as the present body state. Preserve the fresh archive and current settings.
- Public files are offline source/evidence only. Keep firmware, body data,
  compiled diagnostics, private operators and deployment artifacts private.
- Device work needs current ownership of the camera. New parameter/ROM/AP or
  CP RAM patches require a concrete candidate and recovery review plus the
  owner's explicit approval. Temporary diagnostic execution must respect the
  separately reviewed scope; no replay of an unknown operation.
- Modern host transports must be independently pinned/reviewed, not imported
  from a changing sibling worktree. For existing-file-only sessions use the
  read-only wrapper: no upload/removal/arbitrary packets or auto-rescue after
  an unknown exchange. Main's probe cleanup and read-only reauthentication
  recovery do not become authorized simply by importing its Camera class.
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
- Stock2.01 TOMCO sets usrrtn_cfggrp=2. A fixture without it defaults to0
  and admits only TOPPERS_KERNEL. Do not infer transport initialization
  from that narrower callback walk or directly force the group word.
- Watchdog VM profiles use action=pause and retain expiry evidence. Do not
  silently reboot/replay or disable original watchdog settings to pass boot.
- The later I2C-stage boundary is a null table at 0x1a7e868, consumed at
  0xbe9a14 in UIN callback13. Reconstruct its original binding/input; do not
  install invented data or force the pointer to pass native initialization.
  Original BACKUP_INIT rejects the staged VM's zero input at 0x04000000
  and skips the secondary binder; this is not a physical-camera failure.
  The following factory-input stage binds exact original BK4 bytes at their
  declared base and reaches write f1388f4c/value101 at 595cfc. Its register
  meaning is unqualified. Factory fixtures are not current body backups.
- The DFS-stage block has endpoint-specific CP/AP register sequences, not
  generic SCU DATA/SET/CLR aliases. Its model roles remain inferred; absent
  backend must retain pending requests. No clock rate or IRQ route is modeled.
  Native DFS initialization returns with starts=0. The next boundary is
  clock-select SET f1388234/value0 at b716b8, followed by a scratch readback.
- SPI selector masks total 0x30777. Its alias-readback words are explicit
  unknown-value fixtures; local readback independence does not establish
  hardware values or independence in other paths. No clock rate/ready signal
  is supplied. Two native profiles reach PLL SET f1388204/cc10 at b716b8;
  do not generalize SPI storage into an unqualified whole-SCU RAM mapping.
- PLL programming uses original ROM tables; generated reports containing
  those tables stay private. Control/response roles remain inferred. Guest
  bit24 writes must not produce LOCK; absent backend retains the original
  b74b02/b74b04/b74b08 poll. Native observations cover three retained cycles,
  not a clock transition or full UIN return. Gate storage admits only the
  audited masks documented in VM-CP-CLOCK-GATES.md, not entire SCU banks or
  a physical clock tree. Logic-bank bit24 is not the separate PLL LOCK bit.
- The optional PLL source-fixture is an explicit conditional experiment.
  Its private source tuples and guest-ROM comparison do not prove analog
  validity, clock rates, real LOCK or boot safety. Keep the absent-backend
  negative control intact. Packaged cxd clock-source presence does not admit
  its fixed rates/layout as the current CP hardware. Original helper/startup
  audits qualify the gate masks; conditional execution reaches f54005d4. That
  subsequent source-policy stage admits paired software request words only;
  hardware clock/reset completion remains unqualified. Its next f5408038
  read is unsupported without the later explicit single-word experiment;
  do not return a guessed ready/configuration value.
- The isolated config_rmw helper fixture maps register addresses as ordinary
  test RAM. It is not a peripheral model or native-boot continuation. Never
  reuse that broad RAM mapping to pass an unsupported startup access. Its
  current-file span comparison is not loaded-RAM or whole-firmware admission.
- The optional config-word model admits only bit14 at f5408038 under an
  explicit zero/ones initial input and per-I/O original-code checks. Initial
  words are not hardware reset values or ready signals. Absent input retains
  the fault. Conditional continuation reaches f5411000 read at b9b5a2;
  its role/value remain unqualified. Never expand this into whole-bank RAM.
- Original diagnostic display identifies f5411000 as MTG_REG_SEL. Target
  and donor selector/getter bytes match, but this is not physical timing or
  reset-value qualification. Original log calls remain boundaries; do not
  make the following independent store slice a successful logger return.
- The MTG selector experiment stores only bits0..1 at f5411000; explicit
  initial inputs, source/caller/name pins and every-I/O checks remain. It
  provides no MTG edge, frame IRQ, clock rate or sensor. Conditional original
  execution next writes f5411010 at b9b69e/value1b7e47; role/timing remain
  unqualified. Do not create a permissive timing bank to pass it.
- The period-word experiment admits only f5411010/1014/1018, with an explicit
  write-first profile. Unwritten words stay undefined and fail reads; only
  full-word writes may define them. No period unit, rate, edge or completion
  is modeled. Conditional execution next reads f5410004 at b9b146, still
  unqualified. Do not substitute a reset value for that different word.
- A64 source-drift controls must use naturally aligned reference DATA access,
  and verify the actual mutation plus the expected device fault address and
  syndrome. Loader-order failures or alignment exceptions are not successful
  source-guard controls. Retain and qualify those failed observer artifacts.
- Sparse command policy files and original execution reports stay private.
  Admit only canonical policy/code pins, bounded words and source masks.
  Requested-bit latches are experimental state, not confirmed hardware or
  native peer readiness. Original zero software returns do not prove success.
- A debugger step reply alone is not instruction progress. Verify the target
  CPU/PC and observed value; preserve repeated-PC failures. Current poll
  controls explicitly select the GDB CPU and journal their step packets.
- Upstream DesignWare CLR_TX_ABRT releases the IRQ but retains its source
  syndrome until reset. Treat this as a model limitation, not silicon proof.

No Claude or additional agents without explicit user authorization.
