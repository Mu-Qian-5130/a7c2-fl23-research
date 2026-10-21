# CP timer routing and first native task dispatch

The stock2.01 CP now runs beyond the [phase5 boundary](VM-CP-SMP.md),
activates its secondary CPUs and enters its original task trampoline and
task `0x634780` in the isolated four-CPU laboratory. Continuing that task
reaches an unsupported peripheral write. **AP/CP communication, camera
tasks, real exposures, retained RAW pixels and saving remain unverified.**
No physical camera was accessed. This is not an installer.

## Timer channel and frequency

The native descriptor initializer at `0x6314d0` writes frequency2,000,000
and IRQ30. QEMU's default Cortex-A53 counter runs at62.5MHz, so the tested
profile explicitly uses `-cpu cortex-a53,cntfrq=2000000`. Setting the CPU
property selects the actual counter period; merely writing CNTFRQ would
change its reported value without changing QEMU's counter frequency.

The earlier inference that secure A32 execution must select GTIMER_SEC
was wrong. The firmware-free probe actually receives IRQ30 on all four
CPUs with standard wiring. QEMU's `target/arm/tcg/hflags.c` function
`access_secure_reg()` also requires **A32 EL3** to select the secure A32
register bank. This fixture enters secure A32 EL1 from **A64 EL3**. Its
CNTP accesses select GTIMER_PHYS despite the secure execution state.

| Explicit laboratory route | Four independently observed CPU results |
|---|---|
| `standard`: PHYS→PPI30, SEC→PPI29 | Timer expires; IRQ30 acknowledged once, timer disabled, EOI and exception return complete |
| `phys-only`: PHYS→PPI30 | Same successful transaction |
| `secure-only`: SEC→PPI30 | Counter advances beyond four programmed periods; ISTATUS set, no interrupt |
| `none` | Same expiry without interrupt delivery |

All cores read CNTFRQ2,000,000 and program1953 ticks. The controls execute
the same A32 CP15 instruction encodings as the native timer code. They
use real generic timers and GIC state, without host IRQ injection or
overwritten status/counter results. These are model-routing controls,
not measurements of physical Sony wiring or native timer-ISR completion.
Native IRQ traces alone do not distinguish timer interrupts from SGIs.

## Native continuation

The unchanged loader, CP and factory inputs are fully read back and hash
checked before execution. This profile keeps the prior explicit GPIO,
memory-alias and staged-loader assumptions. Unsupported MMIO faults.
No native phase, ready flag, task entry or successful service return is
supplied by the host.

| Observed native boundary | Evidence and limit |
|---|---|
| `0x5f6124` and primary `0x5f6244` | Original initialization proceeds beyond `0x60d46c` |
| Returns after six original subsystem calls | Before secondary activation at `0x5f62a0` |
| Three `0x6147ac` activation calls | Original calls for cores1–3 return; original IRQ handlers resume secondary execution |
| `0x5f5830` scheduler, `0x5f590c` trampoline | Actual runtime reaches scheduler and task setup, separately from source-slice checks |
| `0x5f5920` branch and `0x634780` task | Original fields supply the task pointer; actual native task entry is observed on secondary CPUs and CPU0 |
| Write to `0xf1042000` | First unsupported peripheral operation, not a successful device configuration |

This establishes entry into a native bootstrap task. It does not establish
general scheduling correctness, camera-service startup or pre-capture.

## First missing peripheral

The first fault is a four-byte write to `0xf1042000`. Error reporting then
reads `0xf1000018` and produces nested aborts. The latter is secondary;
adding a UART alone would leave the original failure unresolved.

A fresh same-source control stops at a hardware write watchpoint **before**
the first access. CPU0 has PC`0x5ffc78`, R0=0, R1=0, R2=`0xf1042000`.
The original instruction is `str r0,[r2,r1,lsl #12]!`. Its function accepts
bank IDs0–8, using a4KiB stride. Independent slices stop before MMIO for
each valid bank and confirm that invalid IDs return1 without an access.
The register bank's full device semantics remain unresolved; it has not
been replaced by RAM or a constant ready value.

The faulting guest was paused and retained through source qualification.
Its evidence was archived and hash checked before explicit disposal of
the isolated guest. Observation timeout alone did not authorize cleanup.
The watchpoint control and earlier successful boundary runs terminate
normally. Private raw reports, host operators and binaries stay private.

## Tested sources and checks

The [timer fixture folder](vm/cp_boot/timer/) contains exact copies of
the successful build inputs:

- `entry.S`: A64 architectural handoff to the admitted A32 ELF entry.
- `a32.S`, `a32.ld`: four-CPU firmware-free timer/IRQ/EOI/return controls.
- `qemu_none.c`: explicit GIC/timer connections; GPL-2.0-or-later,
  [license](vm/cp_boot/COPYING.QEMU). This is a replacement laboratory
  none-machine source for the retained QEMU tree, not a standalone build.

The A64 probe uses the parent `fixture.ld`; the native continuation uses
the existing SMP fixture. Generic reset entries come from ELF `e_entry`
inside initialized executable PT_LOAD bytes, never the linker origin.
The shared validator rejects wrong architecture/type/endianness,
misaligned or uninitialized entry, ambiguous executable coverage,
truncated segments, address overflow and nonidentity physical placement.
This metadata check does not replace source fingerprints or ISA checks.

```text
python dev/precapture/verify_support.py
python dev/precapture/audit_cp_timer_boot.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_REPORT.json
```

The first command passes19 support tests. The second passes15 original
descriptor/task-argument/peripheral-admission cases, stopping before
timer enable, task branch or MMIO. Neither is physical camera acceptance.
A mutated CP fingerprint is rejected. The earlier invalid A32 ELF with
entry0 and the incorrect IRQ29 expectation remain excluded failures.

## 简体中文

本轮补齐虚拟机2MHz计时器与标准中断接线。四核正反对照确认：本测试上下文虽是安全
A32执行，但EL3为A64，实际选择PHYS通道；不能只凭“安全模式”推断SEC通道。
原CP已越过60d46c，执行次核激活、原调度器和634780任务。首次外设失败是5ffc78向
f1042000写零，之后f1000018是错误输出的二次异常；另一次原源码watchpoint在首次
写入前确认寄存器和指令。尚未实现该设备模型，不能填“就绪”绕过。

19项共用检查、15项原指令检查与四核计时正反对照通过。以上只证明这些离线范围，
不代表相机服务已启动、曝光／RAW保留／全按存盘已完成，也没有操作相机。
