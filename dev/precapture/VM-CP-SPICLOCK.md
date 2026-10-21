# SPI selector storage and independent scratch readback

The [DFS stage](VM-CP-DFS.md) reached SPI clock-select SET`0xf1388234`.
Original selector routines now execute through a restricted register model.
Native guests with two independent alias-readback words pass the same
selector/caller boundaries and reach the same following PLL access.
No clock rates, ready signals or physical timing are supplied. Complete
group2 initialization and physical pre-capture remain unverified.

## Source-bound fields and readback scope

Sony's official SCU definitions independently identify CLKSEL_SPI channel3,
base`0xf1388000 + 0x200 + (3 << 4)`, SET+4 and CLR+8. Original CP routines
select these four fields:

| Original entry | Field | Accepted original tokens |
|---|---|---|
|`0x52a774` |bits17..16 |0..3 |
|`0x52a7c8` |bits10..8 |0..6 |
|`0x52a840` |bits6..4 |0..6 |
|`0x52a8a8` |bits2..0 |0..6 |

Each routine writes its selected bits to SET and the complementary field
bits to CLR, preserving other fields. The admitted union is`0x30777`.
After each write, the original helper reads that same alias address and
stores the word at`0x1a764f4`. The helper's return also contains that word.
The observed direct caller at`0xb74530` overwrites R0 before its next service.

[audit_cp_spiclock.py](audit_cp_spiclock.py) executes212 original-instruction
contracts: all25 valid field settings, two initial selector words and four
independent alias words; eight invalid-selector returns without MMIO; and
four observed-caller return-overwrite slices. Different alias words change
the scratch/return word without changing the checked selector updates.
This establishes independence for those routines and that caller slice,
not all firmware or the silicon's actual alias-readback value.

```text
python dev/precapture/audit_cp_spiclock.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_REPORT.json
python dev/precapture/verify_cp_spiclock.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

The first command rejects changed CP fingerprints. The second checks only
host register-model state; neither has a camera connector.

## Model and firmware-free controls

[state.h](vm/cp_boot/spiclock/state.h) and
[qemu_spiclock.c](vm/cp_boot/spiclock/qemu_spiclock.c) store only the known
selection bits and implement SET/CLR. DATA reads expose that model state.
Unqualified DATA writes, unknown bits, unsupported addresses and nonword
accesses fault. The model covers only the12-byte SPI selection window.

Initial selection0 and alias-readback words0/`0xffffffff` are explicit
laboratory inputs. Alias words remain independent of selection state.
They are not measured hardware values. No rate calculation, oscillator,
PLL lock, bus timing, sensor, IRQ or ready flag is supplied; the QEMU CPU
and counter rates remain unchanged. Transient selector bit patterns do
not establish any physical clock behavior.

Ten fresh firmware-free guests execute [control.S](vm/cp_boot/spiclock/control.S):
field updates/preservation and zero SET, independent alias words, and four
fault cases (DATA write, unknown bit, outside-window read and byte write),
each under both alias profiles. Host contracts and19 shared regressions pass.
The independent board retains the prior original GPIO/I2C/eDMA/timer/
watchdog and inferred DFS sources. Build, source and control fingerprints
are retained privately; compiled tools and host operators are not published.

## Original CP and the next PLL access

The native tests retain the exact original loader/CP/factory/TOMCO, declared
BK4 placement, four CPUs, group2 and watchdog configuration. Native DFS/eDMA
backends remain absent; I2C has no native slave. No table pointer or ready
state is forced.

Two fresh guests use alias words0 and`0xffffffff`. Both reach selector
entry`0x52a774` with R0=0, execute SET0/CLR`0x30000`, and return to`0xb74530`.
RAM scratch and R0 contain their independently configured alias word.
At`0xb74534`, the original caller has overwritten R0 with R5 in both cases.
The next external call has not executed at that checkpoint.

Both continuations then fault at write32`0xf1388204`. Two further fresh
guests independently stop **before** that write at Thumb PC`0xb716b8`,
opcode`0x5081`, `str r1,[r0,r2]`: R0=`0x200`, R2=`0xf1388004`, R1=`0xcc10`.
Official CLKSEL_PLL channel0/SET4 definitions match. The required PLL
configuration behavior remains unimplemented. The matched boot-prefix
boundary does not prove complete initialization or physical clock fidelity.

Both fault guests were source/first-fault/watchpoint qualified and their
archives hash-verified before explicit disposal. Watchpoint/control guests
exit at declared boundaries. No observer timeout authorizes restart or replay.

Native AP/CP receipt, pre-trigger exposure, bounded retained RAW pixels,
S2 save/cancel, ordinary shooting and exact physical restoration remain open.
No camera was accessed and no installer is supplied.

## 简体中文

已按原CP核对SPI选择寄存器的四个字段、SET/CLR和临时读回用途。212项原指令契约、
主机检查、10组无固件VM和19项共享回归通过。读回字是明确的实验输入，不是实测硬件值。

原CP在全0和全1两种读回配置下均通过选择流程，返回值被调用方覆盖，随后都到同一处
PLL选择SET写f1388204/cc10；两组独立新VM已在原指令前核对。没有伪造频率变化、PLL锁定
或就绪信号。完整初始化与实机预拍摄闭环仍未完成；本阶段没有操作相机。
