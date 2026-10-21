# eDMA byte movement and native UIPC initialization

The [GPIO follow-up](VM-CP-GPIO.md) now passes this page's direction read
and observes PCIEIF returning while its other-chip trigger byte remains0.

The experimental CP-view eDMA model now moves actual bytes between distinct
local and fixture-peer RAM views. It retains RUN without a peer and records
only the copied prefix on an error. Original group2 CP completes PCIDMA
initialization, initializes its UIPC memory arena and enters PCIEIF before
the next unsupported GPIO-direction read.

The fixture peer is **not an AP Linux peer**. These results do not prove
AP/CP message receipt, original native DMA-IRQ handling, link training,
sensor exposure, retained RAW, pre-trigger saving/cancel or physical recovery.
No camera was accessed.

## Source-bound controller view

The original CP data descriptor and actual native readback agree:

| Field | CP2.01 value |
|---|---|
| DMA register base | `0xf6780000` |
| PHY/sideband base | `0xf11c0000` |
| Expected GIC interrupt |403 |
| EDMA interrupt-enable address | `0xf11e0274` |

The official2.01 `drivers/misc/pciedma/regs.h` independently defines engine
enable, doorbell, status/mask/clear, power, channel and64-bit address fields.
The CP view is deliberately kept separate from AP platform IRQ/base names;
these are not measurements of physical aliases, topology or interrupt routing.

[state.h](vm/cp_boot/edma/state.h) separates configuration, active progress,
completion and abort. Enabling an engine does not complete anything. A
bounded copy callback reports the actual moved prefix; only the full
successful length sets DONE. Missing peer leaves RUN and remaining length
unchanged. Partial error sets ABORT/HALT without DONE. Active configuration
cannot be overwritten to manufacture cancellation.

[qemu_edma.c](vm/cp_boot/edma/qemu_edma.c) connects this state to actual RAM
copies, QEMU virtual time and the standard GIC. `absent` creates no peer.
`fixture` creates separate1MiB peer RAM, with an explicit64-bit remote
namespace and a CPU inspection alias. It is a test actor, not an injected
native AP-ready flag. Unexpected backend errors retain/pause the guest;
they do not invent a completed byte count.

The profile covers non-LL read/write, interrupt masks and W1C acknowledgement.
LL descriptors, STOP/cancellation, detailed abort syndromes, ATU, link state
and realistic timing remain unimplemented. Unsupported accesses fault.
Error registers report0 only without a pending abort; an unsupported abort
syndrome is not hidden by a zero result. Directional summary-bit mapping,
reset defaults and physical routing remain model assumptions.

## Independent controls

The firmware-free [control.S](vm/cp_boot/edma/control.S) uses CPU0 to program
the controller and handle real GIC403; other CPUs are parked. Each accepted
case uses a fresh guest. Guest byte comparisons and independent host RAM
readbacks agree:

| Case | Observed result |
|---|---|
| Local→fixture peer |512 bytes match; DONE and one IRQ403; status clear and exception return complete |
| Fixture peer→local |Same512-byte verification in the opposite namespace |
| No peer |No copy/IRQ/DONE; RUN and512 remaining after a measured wait |
| Destination ends after8 of16 bytes |Actual8-byte prefix,8 remaining, ABORT/HALT and one IRQ; no DONE |
| Completion interrupt masked |512 bytes and status latch without IRQ; unmask delivers one IRQ, then clear/EOI |

The bounded no-peer control ends its observation with an active virtual
transfer. It is not a quiescence/teardown admission for a camera sender.
The fixture's data and interrupts are not source-camera pixels or receipts.

```text
python dev/precapture/verify_cp_edma.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

This command runs only host C contracts for actual bytes, separate address
spaces, missing peer, partial abort, masks/clear and rejection. It has no
camera or VM connector. Tested VM source fixtures are under
[edma/](vm/cp_boot/edma/), GPL-2.0-or-later,
[license](vm/cp_boot/COPYING.QEMU); the none-machine source includes the
unchanged GPT/watchdog profiles. Host operators and compiled inputs stay private.

## Excluded failures and the control wait fix

The first model failed during fixture-RAM creation before guest execution:
the migrating RAM initializer expected a device owner. The tested profile
uses the matching nonmigrating RAM API; initial source/binary/logs remain.
A subsequent incorrect API name failed linking and never ran.

An earlier control then reproduced a lost wake: the IRQ had delivered403,
acknowledged ABORT and cleared status, but arrived between an unmasked
count check and WFI. The control slept with stale register0 while its RAM
IRQ count was1. Its actual8-byte prefix and remaining8 were preserved.
The corrected control masks IRQ around the check/WFI and reenables it,
matching the architectural masked-WFI pattern used by the native idle path.
All five fresh controls pass with that source. The old case is excluded;
it was retained, source-qualified and archived before explicit disposal.
Timeout alone did not authorize restart, an injected wake or cleanup.

## Native initialization evidence and next boundary

Fresh native guests keep original loader/stock CP/factory/SMP/TOMCO inputs,
group2 and enabled watchdog. They use `absent`, never the fixture peer.
The original PCIDMA register writes execute and its initializer reaches
`0x56d4a2`, then returns to its original caller at`0x634d7c`.

The original UIPC initializer at`0x563510` subsequently returns. Readback
shows its arena pointer`0x01c20000`, size`0x200000` and pool field`0x80000`.
Header byte+`0x15` reads1; this is an observed byte, not an admitted role or
ownership identifier. These memory-initialization facts do not establish
an asynchronous peer, callback lifetime or successful send/receive.

PCIEIF entry`0x56a920` is observed, but its return is not. The next external
abort is a read of`0xf102f000`. An independent before-read watchpoint gives
PC`0xbf7376`, R2=`0xf101d000`, R0=`0x12000`, R1=3: the original GPIO direction
getter for port18/bit3. The official `GPIO_DIR=0` definition agrees. The
earlier strap-only actor supports the input sample and selected writes;
it lacks this direction read. No GPIO ready/input bit is forced to proceed.

The native fault was retained through source and watchpoint qualification,
then its private archive was hash verified before explicit whole-guest
disposal. The successful checkpoints exit normally. The next work is GPIO
direction/input/output state and the actual peer-startup contract, followed
by native AP/CP traffic. Original native IRQ/error/LL/cancel paths and the
physical pre-capture objective remain open.

## 简体中文

模型已实际搬运两套独立RAM中的字节；五组来宾对照证明完整读写512字节、无对端保持RUN、
只搬8/16字节时报告ABORT且不置DONE、屏蔽后保留状态再交付中断。fixture不是原生AP，
不能据此宣称AP／CP通信或相机DMA完成。

原group2 CP实际走过PCIDMA初始化返回，并完成UIPC内存初始化，读到2MiB区域及512KiB
池后进入PCIEIF。下一处缺失是GPIO18方向读取，独立watchpoint确认，未强置输入或就绪位。
控制程序曾发生检查／WFI竞态，旧失败保留，修正掩中断等待后五项重跑通过。LL、STOP／取消、
详细错误、链路／ATU、原生中断处理、消息对端和真实曝光／RAW／保存／还原都未验收。
