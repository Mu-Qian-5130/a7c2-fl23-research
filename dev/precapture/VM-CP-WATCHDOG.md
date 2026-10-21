# Reset-mode watchdog and entry into PCIDMA initialization

With the exact original TOMCO configuration retained, stock2.01 CP now
passes watchdog reset/setup/enable/feed and enters `PCIDMA_INIT`. The next
unsupported access is a PCIe sideband interrupt-enable register. It is
**not a link-ready poll**. No camera was accessed, no watchdog option was
removed and no PCIe readiness value was supplied.

This remains an experimental VM profile. AP/CP receipt, working DMA,
sensor exposure, retained RAW pixels, pre-trigger saving/cancel and
physical restoration are unverified.

## Independent source evidence and limits

Sony's [official2.01 kernel package](https://oss.sony.net/Products/Linux/DI/ILCE-7CM2_Ver201.html)
contains `drivers/misc/wdt.c`, `include/linux/wdt.h` and the SCU definitions.
The original CP uses the same watchdog control/range/count/restart/status
offsets. The driver supplies nominal4MHz and restart value`0x76`.

The reset control is at`0xf1388340`, SET/CLR at+4/+8, with native bit18.
The watchdog registers are at`0xf1052000`; the reset-output control is
at`0xf13883a0`. These are separate regions. Other SCU bits/registers still
fault; the model does not turn the SCU page into permissive RAM.

[state.h](vm/cp_boot/watchdog/state.h) implements a reset-mode DW-style
contract: count/deadline, initial and reload TOP values, valid restart,
expiry and sticky enable until block reset. The same source package's
`drivers/watchdog/dw_wdt.c` describes separate TOPINIT on cores supporting
that capability. The physical Sony capability and reset routing/pulse
timing remain unqualified. Native CP restarts immediately after enabling;
these tests do not establish its long-running feeder-task lifetime.

The CP's coarse millisecond table differs from exact4MHz periods. Its
entries are below those nominal periods; it is not a frequency measurement.
The model uses the vendor driver's4MHz value explicitly. Interrupt mode,
an active disconnected reset route and unsupported accesses are rejected.

## Controls that actually expire

The firmware-free [control.S](vm/cp_boot/watchdog/control.S) uses CPU0;
the other CPUs are parked. It asserts/releases the modeled reset, connects
the output and programs a65.536ms interval. Its waits use the separately
admitted2MHz architectural counter. The four cases run in fresh guests:

| Case | Observed result |
|---|---|
| Correct `0x76` feed after25ms | Guest reaches75ms, beyond the initial deadline; counter remains positive and block reset stops it |
| No feed | Real QEMU watchdog event, action`pause`, before guest completion |
| Incorrect `0x75` feed | Same real expiry; the invalid value does not postpone it |
| Unsupported reset bit | Actual data abort with FAR`0xf1388344` |

The host never injects a watchdog event or completion marker. The board uses
QEMU virtual time and `watchdog_perform_action()`. All runs explicitly use
`-watchdog-action pause`: an expiry is recorded and retained rather than
silently rebooting a guest. The small control interval is a firmware-free
test parameter; the original CP run keeps its original TOMCO value7.

The host state test covers reset/release, decreasing count, initial/reload
TOP, correct/incorrect feed, expiry, sticky enable and access rejection:

```text
python dev/precapture/verify_cp_watchdog.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

This command runs a host C model only, with no VM or camera connector.
The GPT and watchdog commands share `support/host_test.py`; the GPT
refactor preserves its source hashes, tested contracts and limits. A real
host test returning7 is rejected without a success report. The19 support
regressions still pass. Source fixtures are under
[watchdog/](vm/cp_boot/watchdog/); GPL-2.0-or-later,
[license](vm/cp_boot/COPYING.QEMU). The none-machine source also includes
the unchanged GPT fixture. Compiled programs and private operators are omitted.

## Original CP reaches the next device

The fresh native run uses the original741-byte TOMCO, original loader,
stock CP, factory image and existing SMP fixture, with input/source hashes
and complete initial readbacks checked. The parser again produces group2.
The trace records reset assertion/release, output connection, range7,
enable and`0x76` restart writes from original CP instructions.

Execution reaches the next unsupported read at`0xf11e0274`. An independent
same-source guest sets a read watchpoint before execution and stops **before**
that access: CPU0 PC`0x56d46c`, R0=`0xf11c0000`, R1=`0x20274`.
The original instruction is `ldr r2,[r0,r1]`; the following instructions
OR in`0xffff` and write it back. This lies in the initializer whose UIN
table entry is `PCIDMA_INIT` at`0x56d391`.

The official PCIe header defines sideband base`0x20000`,
`INTERRUPT0_ENABLE_OFF=base+0x274` and `EDMA_INT=0xffff`.
Its platform header gives `PCIE_PHY_I=0xf11c0000`. Both the effective
address and the original read/modify/write mask match independently.
This is DMA-interrupt configuration, not evidence of a trained link,
message receipt or DMA completion. UIPC/PCIEIF initialization remains open.

The faulting guest was paused through source and watchpoint qualification,
then its archive was hash verified before explicit disposal. The watchpoint
guest exits normally at its declared boundary. An observation timeout was
not used to authorize replay or cleanup. No native PC, group, ready flag,
service result or hardware-status value was forced.

The next step is the PCIe sideband/controller interrupt and DMA behavior,
with absent-peer and incomplete-transfer cases preserved. This does not
yet provide a pre-capture installer or a camera-safe candidate.

## 简体中文

保留原厂TOMCO及看门狗设置后，原CP已通过复位、配置、启用和喂狗，实际进入PCIDMA_INIT。
看门狗模型通过四组来宾对照：正确喂狗能跨原截止点；不喂或错误喂狗会实际产生WATCHDOG／
pause事件；非法复位位实际异常。没有关闭原厂看门狗、注入事件或伪造完成标志。

下一处是56d46c读取f11e0274，原指令随后OR入ffff再写回，独立watchpoint在访问前确认。
官方头文件将其定义为PCIe边带INTERRUPT0_ENABLE和EDMA中断位，不能误说成link-ready轮询。
尚无对端通信、DMA完成、曝光、RAW保留或预拍摄存盘证明；物理看门狗能力／路由也未验收。
