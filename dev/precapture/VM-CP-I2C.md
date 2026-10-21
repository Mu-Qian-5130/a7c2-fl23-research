# I2C initialization and the next missing native input

The original CP now reaches all five I2C state records with the expected
controller bases, IRQs and dynamically decoded FIFO sizes. I2C0's original
initialization return boundary is observed. Continuing stops at an unrelated
null table pointer in the final UIN callback; complete group2 initialization
and physical pre-capture are still unverified. No camera was accessed.

## Source and model

The prior serial-clock access belongs to **I2C0**, not UART. The exact stock
CP tables supply five bases `0xf1012000..0xf1016000`, IRQs429..433, serial
clock bits18..22 and reset bits24..28. Sony's official2.01 SCU definitions
independently match the clock/reset DATA/SET/CLR addresses and stride.

The new [board glue](vm/cp_boot/i2c/qemu_none.c) links an unchanged upstream
QEMU DesignWare I2C core. It retains the existing GPIO, timer, watchdog and
eDMA models. [qemu_i2c.c](vm/cp_boot/i2c/qemu_i2c.c) adds the five controllers,
GIC connections and a restricted clock/reset interface:

- Only source-bound I2C clock/reset bits are admitted; unknown bits/accesses
  fault. Initial clock-off/reset-held is an explicit laboratory default.
- Core MMIO is enabled only when its clock is on and reset is released.
  Access otherwise falls through to the strict bus fault policy. This is
  a model guard, not a measured silicon clock-off response.
- Clock removal suppresses the outgoing IRQ while retaining the core's
  pending level. Clock restoration re-forwards that level.
- Reset ends the model bus transaction and invokes standard device reset,
  clearing FIFO/register/IRQ state. It does not erase an external EEPROM.
- The native profile has **no slaves**. The optional256-byte RAM EEPROM at
  address`0x50` is a firmware-free test actor, never sensor evidence.

The standard core is command-driven, not bit-timed. Physical SCL timing,
pad routing, sensor transactions and DMA are unqualified. Upstream slave-mode
and unsupported-register limitations remain. In particular, its
`CLR_TX_ABRT` clears the interrupt but retains `TX_ABRT_SOURCE` until reset;
the tests record that limitation rather than calling it hardware fidelity.
The native initialization trace did not report unsupported core accesses.

## Verification

```text
python dev/precapture/verify_cp_i2c_gate.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/audit_cp_i2c.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_REPORT.json
```

The first command runs host-only clock/reset isolation contracts. The
second checks36 original-instruction/table contracts against the exact
stock CP fingerprint. It stops before external clock/reset/disable calls;
FIFO words and table arguments in slices are explicit synthetic inputs.
It does not initialize hardware or manufacture a successful native call.

Sixteen fresh firmware-free guests on the final model execute
[control.S](vm/cp_boot/i2c/control.S):

- EEPROM writes `37 a9`, repeated-start reads return those exact bytes;
  masked STOP stays pending, unmask reaches GIC429, clear/EOI releases it.
  Clock gating suppresses/re-forwards the IRQ. Reset clears an unread FIFO
  byte and releases an unfinished transaction; a subsequent transfer reads
  the original EEPROM byte again.
- Five absent-target cases deliver address-NACK/abort at the corresponding
  IRQ429..433. Clear releases the IRQ; reset clears the retained syndrome.
- Five clock-off and five reset-held accesses fault at each controller's
  component-parameter register. No ready/FIFO-success value is injected.

An initial control expected abort-source clearing from the upstream core
and failed. Its source/ELF/registers/logs were retained and archive-verified
before explicit disposal. Revised controls separately verify interrupt
clearing and source retention/reset. This limitation is not hidden by a
controller-source patch. Compiled tools and host operators remain private.

## Original CP continuation

The staged original loader/CP/factory/TOMCO run retains four CPUs, group2,
original watchdog configuration and absent eDMA/I2C peers. Original
PCIDMA/UIPC/PCIEIF return observations remain; the other-chip trigger byte
is still0. No native eDMA copy or positive peer signal is supplied.

At I2C0 return boundary`0xbf7a38`, the original result is0 and its state
contains base`0xf1012000`, TX/RX depths16 and IRQ429. Later RAM observations
show the corresponding base/depth/IRQ fields for all five ports. This does
not independently establish every controller's full return path.

The following abort has DFAR`0x10`. A separate fresh run stops **before**
Thumb instruction`0xbe9a14`, `ldrb r12,[r1,#0x10]!`, with R1=0. The pointer
at`0x1a7e868` is0; the callback index is13. A further original-code run
observes `BACKUP_INIT` at`0x55dca4`, then its table-input call with
R0=`0x04000000`. That VM input's first512 bytes are all0. The original
primary binder returns`0xffffffff`; the subsequent lookup also returns
`0xffffffff`, so the original branch skips the secondary binder`0x55e014`.
The primary pointer was stored, but the secondary pointer remains0.

This qualifies missing/invalid backup-table input in the staged fixture.
It does not identify a physical-camera bug. The original backup input's
provenance, complete contents/loading path and lifetime still need
reconstruction. Do not replace it by invented bytes or a forced pointer.

The fault guest was source-qualified against that independent stop and
archive-verified before explicit disposal. Successful boundary controls
exit normally. No observation timeout authorizes replay or cleanup.

Native table binding, complete initialization, peer signaling/receipt,
sensor exposure, retained RAW pixels, S2 save/cancel, ordinary shooting and
exact physical restoration remain open. This model is not an installer.

## 简体中文

前一阶段的串行时钟访问实际属于I2C0。现已接入上游DesignWare控制器，加上有来源的
五路时钟/复位/中断连接；36项原指令契约、主机门控检查和最终模型16组无固件测试通过。
真实字节来自独立RAM EEPROM，原CP启动没有挂传感器或伪造ACK。

原CP已到I2C0初始化返回点，五路状态字段均符合预期。下一处异常是最终UIN回调中的
空数据表指针，已在原指令执行前独立核实。继续追踪确认是当前虚拟机的备份表输入为0，
原绑定返回错误并跳过后续绑定；不填假数据跳过。完整初始化、AP/CP通信和
实机预拍摄闭环仍未完成；本阶段没有操作相机。
