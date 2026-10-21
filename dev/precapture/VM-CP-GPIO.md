# GPIO state, peer-startup guards and PCIEIF return

This records the GPIO-stage boundary. The later
[I2C follow-up](VM-CP-I2C.md) implements the restricted serial-clock/reset
path and documents the next missing native input.

The original CP now passes the formerly unsupported GPIO18 direction read
and returns from PCIEIF initialization. Its other-chip trigger byte stays0
with no peer present. It then reaches a separate serial-clock enable access.
No GPIO-ready bit, native notification or successful receive was forced.

These are register-model and native initialization observations. GPIO IRQs,
pad/mux behavior, electrical/inter-chip wiring, native AP/CP traffic, DMA
ownership, exposure, retained pixels, saving/cancel and physical restoration
remain unverified. No camera was accessed.

## Register contract and unknown inputs

Sony's original2.01 `regs-gpio.h` independently defines direction0,
input`0x10`, input-enable`0x20`, function`0x30`, output`0x40`, and SET/CLR
aliases+4/+8. The native direction getter uses base`0xf101d000 + port*0x1000`.

[state.h](vm/cp_boot/gpio/state.h) models direct/set/clear updates separately
from external input. Guest configuration/output writes cannot overwrite
input. The profile defines GPIO17 as disconnected IRQ-bank input0, and
GPIO18 as the configured strap actor. Ordinary pad inputs are undefined;
reading them faults rather than inventing unpressed buttons or sensor state.

Input-enable/function fields are stored, but electrical gating, mux effects,
output-pad loopback and GPIO IRQ generation are not supplied. Input/output
isolation is a declared fixture contract, not a physical pin measurement.
The original alias/boot memory model is retained unchanged; GPIO access
does not write EXEC_MODE, native phase or any peer-readiness word.

## Host and guest controls

```text
python dev/precapture/verify_cp_gpio.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

This runs only the host C contract: direct/set/clear, high-strap retention,
output/input isolation, unknown input and unsupported-access rejection.
It has no VM/camera connector.

Eight fresh firmware-free guests run on the final model:

- The four prior alias controls cover banks4/8 and low/high strap inputs.
  Bidirectional alias access and the original unsupported-MMIO abort remain.
- Four new [control.S](vm/cp_boot/gpio/control.S) cases exercise direction,
  input-enable, function and output registers. Incoming low/high values
  survive output writes; unsupported guest input writes produce model aborts.

Two additional native original-loader/CP high-strap controls preserve
EXEC_MODE word`0x100`. Three actual read/compare/back-branch steps return
to original CP poll`0x10897c`; no byte is cleared to make it boot. Both
declared controls exit normally. This checks that the GPIO extension did
not erase the original startup condition.

Sources are exact tested build inputs under [gpio/](vm/cp_boot/gpio/),
GPL-2.0-or-later, [license](vm/cp_boot/COPYING.QEMU). The independent build
replaces only the bus object; existing timer/watchdog/eDMA objects and
the original bus source/object stay unchanged. Binaries and host operators
remain private.

## Original AP/CP startup contracts

`audit_transport_gpio.py` passes22 original-instruction contracts against
the exact stock CP and original AP `pcie-if.ko`. It resolves AP records
through the original relocation and stops before semaphores and GPIO
operations. CP post-getter levels are explicit independent slice inputs;
the notification routine is never executed to manufacture success.

| Endpoint | Output descriptor0 | Output descriptor1 | Startup input |
|---|---|---|---|
| AP module |GPIO18/bit9 |GPIO18/bit8 |GPIO17/bit4 |
| CP code |GPIO18/bit3 |GPIO18/bit2 |GPIO17/bit2, required value1 |

These records describe software endpoints. Correspondence between table
indices does **not** establish physical wiring, IRQ routing or a working
peer. The existing AP startup audit separately requires successful getter
status and value1. No positive hardware/peer result is supplied here.

```text
python dev/precapture/audit_transport_gpio.py --cp PRIVATE_STOCK_CP --pcie PRIVATE_ORIGINAL_PCIE_MODULE --output NEW_PRIVATE_REPORT.json
```

Changed source fingerprints are not admitted. A callback table, output
register write or initialization-function return is not message receipt.

## Native return, absent-peer evidence and next access

The fresh normal run keeps original loader/stock CP/factory/SMP/TOMCO,
group2, original watchdog settings and an absent eDMA peer. The original
PCIDMA and UIPC initializer returns remain observed. PCIEIF at`0x56a920`
now also returns to its original caller`0x634d7c`.

The original code writes GPIO18 output register bit3. It subsequently reads
GPIO17/bit2 as0, so the strict equality-to1 branch skips routine`0x56c6c4`.
That routine's original diagnostic names a trigger from the other chip.
Its byte at`0x1a7ea70` remains0 in actual RAM readback. This preserves the
absent-peer state; it is not an initialized transport admission.

Continuing toward the remaining UIN callbacks reaches write32`0xf1388054`.
An independent before-write watchpoint gives PC`0xbef42a`, R0=`0x50`,
R2=`0xf1388004`, R1=`0x40000`; the original instruction is `str r1,[r0,r2]`.
The official SCU definitions give base`0xf1388000`, CLKEN_SERIAL channel5,
16-byte channel stride and SET offset4, matching the address. This clock
register is still unimplemented; full group2 UIN return is not established.

The faulting guest was retained through source/first-fault/watchpoint
qualification, then its archive was hash verified before explicit disposal.
Successful checkpoints and high-strap controls exit normally. No replay or
cleanup was authorized by timeout alone. The next work is serial clock/reset
behavior and native peer signaling, followed by actual AP/CP traffic.

## 简体中文

GPIO现在保留方向/输入使能/功能/输出的独立寄存器状态，输出写入不会改外部输入。
普通未定义引脚输入会报未知，不能填0冒充按键/传感器状态。最终模型的8组无固件对照、
2组原CP高输入轮询对照和22项AP/CP原指令契约通过；没有清EXEC_MODE或设置就绪信号。

原PCIEIF初始化已返回，但GPIO17/bit2读0，其他芯片触发byte也仍0。输出寄存器改变不
代表物理线缆对端已收到。下一处是f1388054串行时钟使能写，独立watchpoint和官方定义
吻合；完整UIN、GPIO中断/电气连线、原生AP/CP通信和真实预拍摄都尚未验收。
