# Original CP multicore and interrupt initialization

This page records the phase59 boundary. The subsequent
[timer and native-task experiment](VM-CP-TIMER.md) wires the timer outputs,
continues original initialization and identifies the next missing peripheral.

The staged stock2.01 CP now reaches `0x60d46c`, before its call to `0x5f6124`,
in a separate four-CPU QEMU profile. Original synchronization, memory setup,
init-array processing and interrupt/timer initialization execute. All four
native phase words reach5. **Task dispatch, timer interrupt delivery, AP/CP
communication, real exposures and saving remain unverified.** No camera was
connected or modified. The [boot-fixture limitations](VM-CP-BOOT.md) still apply.

## Native startup dependency

The one-CPU profile stopped inside the original synchronization routine.
Read-only inspection showed phase words `[1,0,0,0]`; its local guard had
already been released. Original code compares four signed phase words and
waits until every member reaches the requested phase. Missing participants
cannot be replaced by raising the words.

The new profile supplies four actual Cortex-A53 virtual CPUs. Their own MPIDR
reads give distinct IDs0–3. The primary runs the same staged loader fixture;
secondaries wait for fixture publication, execute the original architectural
handoff and enter CP at `0x108000`. The CP's own secondary path waits on
`0x108d94`, published by original primary startup, then enters its runtime.
No native phase counter, lock owner or CP waiting byte is written by the host.

| Observed boundary | Native evidence |
|---|---|
| One-CPU negative control | `[1,0,0,0]`, original wait, no absent-core progress |
| Four CPUs after memory initialization | `[1,2,2,2]`; primary reaches `0x60d38c` |
| Four CPUs before the following entry call | `[5,5,5,5]`; primary PC `0x60d46c`, each CPU has a separately qualified A32 register dump |

`audit_cp_smp_boot.py` checks269 original selector/start-cell/comparison cases.
It distinguishes the inter-core startup cell from AP peer/sensor readiness,
checks the four-member signed comparison and stops before ownership cleanup.
It does not establish a complete barrier or scheduling on its own. Separate
full-system execution supplies the native participant evidence above.

```text
python dev/precapture/audit_cp_smp_boot.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_REPORT.json
```

The function at `0x61ccbc` is recorded as runtime-library initialization;
returning from it is not taken as proof that every C++ constructor ran. The
actual init-array loop has a separate observed return at `0x60d3c0`.

## Interrupt-controller model

Without a controller, the original access to `0xf13a1008` produces a real
external abort. The new independent board instantiates QEMU's standard ARM
GICv2 distributor/CPU interface at `0xf13a1000` / `0xf13a2000` and connects
its architectural interrupt lines to the four CPUs. Four CPUs,512 interrupt
IDs and security extensions are explicit model inputs; physical chip details
are not inferred from the experiment. Unsupported peripherals still fault.

Before running Sony code, a firmware-free control verifies:

- Four real CPU participants close a shared-memory/WFE/SEV transaction.
- CPU0 sends SGI5 to CPU1 through the GIC distributor.
- CPU1 acknowledges token5, writes EOI and returns from its exception handler.
- The resumed CPU1 publishes completion; the other CPUs receive no interrupt.

With that controller, the unchanged CP passes the formerly faulting access,
reaches `0x60d408` after its interrupt/timer initializers, and then the
`0x60d46c` boundary. Original inputs are fully read back and hash-checked
before execution. Source-qualified RAM records the timer descriptor; its
interrupt field is30. **Generic-timer IRQ outputs are not yet wired to the
GIC**, and no native timer ISR or camera task dispatch is claimed.

## Tested source fixtures

The [SMP source folder](vm/cp_boot/smp/) contains byte-identical copies of the
actual successful build inputs. It uses the parent folder's ELF layout,
EL3 translation context and GPIO/alias model.

| Source | Role |
|---|---|
| [start.S](vm/cp_boot/smp/start.S), [fixture.c](vm/cp_boot/smp/fixture.c) | Primary setup and secondary actors using the original handoff/start paths |
| [qemu_none.c](vm/cp_boot/smp/qemu_none.c) | Four-CPU experimental board and standard GICv2 connections; GPL-2.0-or-later, [license](vm/cp_boot/COPYING.QEMU) |
| [control_smp.S](vm/cp_boot/smp/control_smp.S), [control_gic.S](vm/cp_boot/smp/control_gic.S) | Firmware-free CPU/event and SGI/acknowledge/EOI/return controls |

These are offline fixtures with no camera connector or installer. Private host
operators, compiled diagnostics, original inputs and raw reports stay private.

## Observation and acceptance limits

Secondary reset addresses are derived from the admitted ELF's `e_entry`;
section alignment moved this fixture's entry beyond its linker origin. A
wrong-entry probe is retained and excluded. Per-CPU HMP observations use
`cpu-index` in the same command; separate monitor-selection calls are excluded
as evidence of distinct CPU states.

Debugger reads of GIC MMIO can lack QEMU's required current-CPU context. A
firmware-free negative control reproduces the host failure, exit139, after
its SGI transaction succeeds. The accepted native continuation observes RAM
and guest-executed results, and exits normally at its declared boundary.
The faulty observer run is retained, without being counted as acceptance.

The earlier one-CPU, wrong-entry and missing-GIC guests were paused and kept
through source/trace review. Their qualified negative-control snapshots were
archived before explicit whole-guest disposal. An observation timeout alone
was never used as proof of completion or grounds for relaunch.

The profile still supplies a laboratory alias and initialized loader context,
uses stock CP rather than the current six-look camera image, and has no AP
Linux peer, working PCIe/DMA, sensor/ISP or recording backend. The next steps
are native timer routing and the initialization/dispatch path at `0x5f6124`.
Physical pre-capture and exact camera restoration remain open.

## 简体中文

单核对照实际停在原四核同步，阶段值为[1,0,0,0]。补齐三个虚拟CPU、让它们执行原次核
启动路径后，原代码自然推进到[1,2,2,2]，最终四核阶段均为5，主核到达60d46c调用点。
269项原指令检查只验证启动守卫与比较谓词；完整VM另外验证真实参与核，没有代写同步值。

缺失GIC时，原f13a1008访问真实触发总线异常。标准GICv2模型接回后，无固件程序验证
SGI5从CPU0到CPU1、实际应答／EOI／异常返回，随后原CP走过中断／计时初始化。中断数量
及拓扑是模型参数，尚未证明实机配置。原计时描述符指定中断30，但定时器IRQ线路仍未接通。

启动ELF入口与逐核观察均由实际元数据核对；调试器直接读GIC的崩溃已用无固件对照复现，
验收采用来宾执行结果与RAM现场。尚未执行后续5f6124路径、证明任务调度或原生定时中断；
没有AP／CP通信、真实曝光／写卡，也没有操作当前相机。预拍摄仍未完成。
