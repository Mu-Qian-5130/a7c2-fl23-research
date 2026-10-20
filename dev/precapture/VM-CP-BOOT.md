# Staged original CP startup

The original A7C II 2.01 CP now reaches its runtime entry in a separate QEMU
experiment. One follow-up reaches `0x60d358`, immediately after the original
primary BSS-clear call. This is partial startup under an explicit laboratory
context. Full cold boot, RTOS/peer initialization and physical pre-capture
remain unverified. No camera was connected or modified.

## Configuration recovered from actual inputs

Both pinned factory images, `CX89700_ALLLANG` and `CX89701_ALLLANG`, contain
the following selected records. Independent checksum-valid parsing of the
October17 historical body backup gives the same values for these records;
it does not establish the camera's current configuration or active bank.

| Factory segment | `fa0173` EXEC_MODE destination | `f909d5` / `f909d6` GPIO | `51005c` selector | `510050` secondary value |
|---|---|---|---|---|
| `0` | `0x403e42000` | port18 / bit9 | 2 | 0, one byte |
| `0xed000` | `0x803e42000` | port18 / bit3 | 2 | 0, one byte |

The original loader's initializer `0x4564` and reader `0x36dc` execute their
actual lookup, size, pointer and memcpy helpers against those unchanged input
bytes. Eighteen initializer/scalar contracts per factory image pass. Host
validation independently checks BK4 layout, checksum and bounds before native
execution; the native initializer itself checks the revision and sets pointers.
Selected values also match the independent PMCA parser. Seven corrupt/unsupported
input cases are rejected, including admitting a historical body file as factory
data. No setting is written.

```text
python dev/precapture/audit_loader_backup.py --loader PRIVATE_NOR_LOADER --backup PRIVATE_FACTORY_BACKUP --output NEW_PRIVATE_REPORT.json
```

## What the full-system experiment executes

A separate private QEMU binary uses a `none` machine with one Cortex-A53,
owned RAM and explicit GPIO-input/memory-alias actors. Original QEMU sources,
objects and other guests remain unchanged. Four firmware-free controls verify
both directions of the modeled RAM alias, preservation of the configured GPIO
input during direction writes, and real external aborts for unsupported MMIO.

The staged fixture then:

1. Runs the original BK4 initializer/reader on the selected factory segment.
2. Runs the original GPIO strap helper with that segment's actual port/bit
   configuration. The actor supplies an explicit launch-time input of0 or1.
3. Composes the boot-context byte using the separately audited source contract.
   The complete monolithic context-initialization caller is not executed.
4. Calls the original EXEC_MODE writer and its secondary-word producer. Their
   own backup reads and writes run; no successful service return is substituted.
5. Executes the original `SCR_EL3` / `SPSR_EL3` / `ELR_EL3` / `ERET` sequence.
6. Executes the unchanged CP from `0x108000` through its real polling/bootstrap
   instructions. Debug breakpoints only observe declared stage boundaries.

The fixture explicitly initializes the existing BK4-reader mode and logging
controller state, and supplies EL3 translation tables with Normal RAM and
Device MMIO attributes. These are laboratory preconditions, not a recovered
original cold-boot environment. In particular, packed BK4 records require
Normal-memory access semantics. Original loader, CP and factory bytes are
fully read back and hash-checked inside each paused guest before execution.

The [offline fixture sources](vm/cp_boot/) are byte-identical to the sources
used for the successful builds:

| Source | Responsibility |
|---|---|
| [fixture.c](vm/cp_boot/fixture.c) | Calls the original functions, explicitly composes the test context and records original writer output |
| [start.S](vm/cp_boot/start.S), [el3_context.c](vm/cp_boot/el3_context.c), [fixture.ld](vm/cp_boot/fixture.ld) | EL3 entry/exception observation and the explicit laboratory translation context |
| [qemu_bus.c](vm/cp_boot/qemu_bus.c) | Controlled GPIO input, modeled RAM alias and unsupported-MMIO fault policy |

The model replaces the existing experimental bus shim in an independent QEMU
build; that private build also allows this one device on the `none` machine.
Compiled diagnostics, original Sony inputs, private host operators and raw
reports remain private. These source fixtures have no camera connector or
installer and do not qualify an executable for camera use.

The QEMU bus model derives from the
[a7c2-re QEMU experiment](https://github.com/chocotan/a7c2-re) and is licensed
GPL-2.0-or-later; its [license text](vm/cp_boot/COPYING.QEMU) is included.

## Observed results

| Modeled alias bank | Configured strap | Original writer result | Original CP observation |
|---|---|---|---|
| `0x4` upper32 bits | 0 | mode word0 | A32 runtime entry `0x619ea0` |
| `0x4` upper32 bits | 1 | mode word`0x100` | original read/compare/back-branch; byte preserved |
| `0x8` upper32 bits | 0 | mode word0 | A32 runtime entry `0x619ea0` |
| `0x8` upper32 bits | 1 | mode word`0x100` | original read/compare/back-branch; byte preserved |

Trace/register evidence records the real EL3→AArch32 EL1 exception return,
the CP polling address `0x03e42001`, A32 register state and actual breakpoint
PCs. Both zero-input cases reach runtime entry. Another fresh `0x8`/zero guest
continues through native mode-stack setup and reaches the post-BSS-clear
boundary `0x60d358`. It stops before the subsequent flag store/global
constructors. All five successful probes end at declared boundaries and their
owned guests exit. Failed fixture runs and their exception records are retained.

## Remaining native connections

The alias is an explicit model input: the original mode writer's high-address
store and CP's low-address load share modeled RAM. That demonstrates this
software contract under the configured topology; the physical A7C II alias
and active boot bank still need qualification. The launch-time GPIO inputs
also do not prove a real board's strap or peer signal.

This profile runs one staged CPU, with no AP Linux/CP communication pair,
working PCIe/DMA, RTOS scheduling, sensor/ISP or recording writer. It uses stock
2.01 CP, and does not qualify the current camera's six-look program. The AP-side
GPIO17/bit4 startup condition remains a separate peer connection. No readiness
flag, CP wait byte or IRQ is forced to pass. Safe pixel retention, S2 saving,
terminal release, ordinary shooting and exact physical restoration remain open.

## 简体中文

已从两份原厂配置恢复模式字地址、端口18的9／3位、selector2及单字节次级配置；
历史机身备份的这些项相同。原加载器的真实初始化／读取函数在原始数据上执行，
两份配置各18项合同通过，另有独立解析与7种拒绝检查。没有查询当前相机。

隔离虚拟机现能执行原始备份读取、GPIO helper、模式字写入和EL3→A32切换，再运行
原CP启动字节。两个地址bank各做输入0／1对照：0进入运行时入口619ea0，1保留100并
继续原轮询。另一轮到达主核清BSS后的60d358，尚未执行后续标志写入／全局构造。

这里的内存别名、GPIO输入、已初始化的读取／日志状态和EL3映射属于显式实验条件，
并非完整冷启动或已证明的机身硬件拓扑。尚无AP／CP通信对、工作DMA、RTOS调度、
真实曝光与写卡，也未验证当前六款外观程序的集成。实机预拍摄仍未闭环。
