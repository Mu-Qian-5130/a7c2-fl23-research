# General-purpose timer and native initialization callbacks

The staged stock2.01 CP now passes the formerly faulting `0xf1042000`
access, initializes four general-purpose timers, walks its1111-entry
initialization callback list and returns to the original caller. This
uses an **experimental counter/compare model**, with declared assumptions.
It is not proof of physical timer fidelity, AP/CP communication, camera
service readiness, exposures, retained pixels or saved pre-trigger photos.
No camera was accessed.

## Independent register evidence

Sony's [official ILCE-7CM2 Ver2.01 source distribution](https://oss.sony.net/Products/Linux/DI/ILCE-7CM2_Ver201.html)
provides `linux-kernel.tar.gz`. Its `include/linux/cxd_timer.h` and
`drivers/udif/mach-cxd900xx/include/mach/platform.h` define the same timer
base,4KiB stride and register offsets used by the original CP:

| Offset | Source-defined role |
|---|---|
| `0x00` | Control; start bit`0x1000`, interrupt bit`0x100`, divider in low bits |
| `0x04` | Clear count bit`0x10`, clear interrupt bit`1` |
| `0x08` | Compare value |
| `0x0c` | Current count |
| `0x10` | Counter load |
| `0x14` | Capture; deliberately unsupported by this model |

The source base is `0xf1042000 + bank*0x1000`. This independently identifies
the first [phase60 fault](VM-CP-TIMER.md) as a timer access. It does **not**
make every legacy platform definition applicable to the current CP.

The CP programs mode2 and registers interrupts413–416. The official AP
header names free-running mode3 and has different interrupt assignments.
The model therefore makes these assumptions explicit: CP mode2 behaves as
a free-running counter; its input clock is4MHz, so divider4 gives1MHz;
the CP GIC routes are413–416. Actual silicon mode2, clock selection,
compare/clear edge behavior and physical routing remain unqualified.

## Implemented model and controls

[counter.h](vm/cp_boot/gptimer/counter.h) implements elapsed-time counting,
stopping, divider changes,32-bit wrap, compare deadlines and a pending
interrupt. [qemu_counter.c](vm/cp_boot/gptimer/qemu_counter.c) uses QEMU's
virtual clock and connects the interrupt through the real GIC model.
It never supplies a successful native function return or patches a flag,
task pointer or original instruction. Unsupported accesses and running
periodic/one-shot modes fault instead of reporting completion.

The firmware-free [control.S](vm/cp_boot/gptimer/control.S) runs on four
actual virtual CPUs. Each programs its own bank, observes counter progress,
then acknowledges its interrupt, clears/disables it, writes EOI and returns.

| Profile | Observed result on CPUs0–3 |
|---|---|
| `cp-inferred` | IDs413,414,415,416, each delivered once; clear/EOI/return complete |
| `wrong-route` | Counter advances beyond four programmed periods; no interrupt reaches the enabled IDs |

There is no host IRQ injection. The marker's1MHz value is explicitly model
configuration, not a value read from a hardware frequency register. These
controls validate model behavior and wiring, not physical Sony behavior.
Native CP timer initialization succeeds, but its general-purpose timer ISR
has not separately been qualified as executing.

The portable host test covers elapsed and stopped counts, comparison before
and at the deadline, pending-interrupt clearing, wrap, actual divider rate
and rejection of unsupported operations:

```text
python dev/precapture/verify_cp_gptimer.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

This command compiles and runs a host test only. It has no camera connector
and does not launch QEMU. The source folder also contains the exact tested
none-machine replacement and guest control; they are offline fixtures,
not a standalone emulator build or a camera installer. QEMU-derived/model
sources use GPL-2.0-or-later; [license](vm/cp_boot/COPYING.QEMU).

## Original CP continuation

Fresh guests use the same pinned loader, stock CP, factory image and SMP
fixture. Original inputs are completely read back before execution. The
model's source/binary fingerprints are checked. Its experimental alias,
GPIO, GIC topology and staged-loader limitations still apply.

The original `0x5feff0` routine resets and starts banks0–3 with control
`0x1022`, then returns to `0x601c5c`. Subsequent original initialization
calls return, and `0x60d220` walks the callback list at `0xffe444`.
The first callback boundary, loop return at `0x60d24c`, return to caller
`0x634d7c` and outer initialization return at `0x634824` are observed.

The list has1111 nonzero entries followed by its terminator. Its entire
4448 bytes match the original before and after execution. The returned
R4=`0x00fff5a4` matches the native iterator's terminator traversal. No
callback/table entry, native service result, wait flag or PC is forced.
This establishes that initialization path, not universal startup correctness.

## Finalization wait is a separate path

A subsequent observer incorrectly waited for `0x634e80` as another startup
boundary. Its deadline paused and retained the guest. Read-only inspection
then found all CPUs in the original idle/WFI path, and four tasks with
entry`0x63476c` queued on flag`0x56`, mask1; the flag pattern was0.

Original `0x634660` waits on that flag before entering the `UFI` callback
path. The two Thumb callers of its signal wrapper`0x60647c` are adjacent
to `upm_cp:Task Finalize` logging. This is finalization work, not another
normal initialization return. No flag was set to make the observer pass.
The missed boundary is excluded from acceptance. Its paused evidence was
source-qualified, archived and verified before explicit whole-guest disposal.

The current result is native initialization followed by idle/waiting tasks
in this laboratory. Producing AP requests, qualifying transport/DMA,
entering camera services and generating real pre-trigger exposures remain
separate unresolved work. No physical installation or restoration is tested.

## 简体中文

原来f1042000的故障已由实验计时器模型接住。官方源码独立确认基址、寄存器和控制位，
但CP模式2、4MHz输入时钟及413–416中断映射仍是明确标注的模型推断，不能声称硬件完全
复现。四核正反对照通过：正确路线实际计数、比较、中断、清除与返回；错误路线只有计数。

原CP通过四路计时器初始化、1111项原初始化回调及调用者返回；完整回调表前后未变。
后面的634e80属于结束／清理路径，四个任务等flag56的bit1，UPM Task Finalize才触发。
没有强置事件去“完成启动”，错误观察点不计验收。尚无AP／CP通信、传感器曝光、RAW保留
和预拍摄存盘的闭环，本轮也没有相机操作。
