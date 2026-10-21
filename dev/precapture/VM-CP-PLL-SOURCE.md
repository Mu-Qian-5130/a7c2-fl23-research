# Source-constrained PLL fixture and conditional continuation

The later [clock-gate follow-up](VM-CP-CLOCK-GATES.md) qualifies the helper
masks and traces conditional original-code continuation beyond all five PLLs.

The [PLL stage](VM-CP-PLL.md) retains the original lock wait without a
backend. This follow-up keeps that negative control and adds an explicit
**source-constrained experiment responder**. It supplies a conditional
response for tracing later original code; it is not a physical PLL model,
proof of lock, complete native initialization or camera boot safety.

## Why packaged clock definitions are insufficient

The official2.01 kernel archive includes `drivers/clk/cxd/clk-cxd-900xx.c`.
That source defines fixed clock rates and register roles that differ from
the inspected CP routines: its divider at offset`0x10c` and two-bit SPI mux
fields cannot simply describe the CP's five coefficient words and its SPI
fields at bits17..16/10..8/6..4/2..0. Presence in the package does not prove
that driver is bound to the current CP clock hardware. Its nominal24MHz
input is therefore not admitted as the CP PLL reference or lock timing.

The fifteen relevant official source files were extracted read-only from
the pinned archive, fingerprinted and retained privately. Current oscillator
equations, rates, voltage, settling time and physical hardware binding remain
unqualified. No guessed equation or fixed ready word is used as evidence.

## Private source constraints

[build_pll_source_fixture.py](build_pll_source_fixture.py) accepts only the
exact stock2.01 CP fingerprint and emits a new private directory:

```text
python dev/precapture/build_pll_source_fixture.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_FOLDER
```

It extracts the six original preset/mode tuples into a268-byte artifact
and records its SHA256. Each tuple contains the selector, five coefficient
fields and two divider fields. These values are original firmware data:
keep the generated artifact/report private and outside the public repository.
They are experiment inputs, not firmware or camera-deployment files.
Modified/truncated CP images are rejected. The generated tuples match the
independent original-instruction programming audit from the prior stage.

The optional QEMU `source-fixture` backend requires an explicit file and
its SHA256, verifies its format, source header, six records and allowed field
bits, and compares every tuple with the tables actually loaded in guest ROM.
That comparison runs before scheduling and again before responding. Private
native operators separately verify the complete loaded CP fingerprint;
the artifact's source header alone is not whole-firmware admission.

For the pending slot, selector/coefficient fields must match one original
tuple. Slots1 and3 also require their linked divider fields. This is a
per-slot source constraint, not proof of a coherent physical clock tree or
analog validity. A mismatch retains the pending request without LOCK.
The existing generation check still excludes stale responses.

The backend is explicitly selected through these laboratory inputs:

```text
QEMU_SONY_CP_PLL_PROFILE=source-fixture
QEMU_SONY_CP_PLL_ALIAS=zero (or ones)
QEMU_SONY_CP_PLL_SOURCE_FILE=PRIVATE_ARTIFACT_PATH
QEMU_SONY_CP_PLL_SOURCE_SHA256=EXACT_ARTIFACT_SHA256
```

Its synthetic response delay remains an experimental choice. The responder
does not implement oscillator physics, frequency changes, physical timing,
IRQ wiring, exposure or camera recovery. `absent` remains a separate backend
and never supplies LOCK. The older synthetic `fixture` controls also remain
distinct from source-constrained and native hardware evidence.

## Controls and original-code observations

- All26 existing PLL guest controls still pass. Two original CP guests with
  the absent backend still execute three retained lock-wait cycles each.
- Eleven source-data controls load the CP only as reference-table data and
  never execute its code. Five slots under the original preset0/mode1 receive explicit fixture
  responses; selector/coefficient/divider mismatches, an unused artifact-row
  mismatch and actual drift in a copied guest table retain pending state.
- Six startup controls reject incorrect hashes, truncation, source headers,
  counts, unknown field bits and missing digests before guest execution.
- Host source-tuple/state checks and19 shared support regressions pass.

One initial drift control did not change the intended guest word when it
used a generic-loader literal. Guest readback proved the word was unchanged;
the valid fixture response was consequently expected for that actual input.
The failed test, source, registers/logs and readback were archived before
explicit disposal. Fresh revised controls load an explicitly changed
source-data copy and verify the changed word before execution. They pass;
the model was not weakened to hide the ineffective test input.

Two further original-CP guests use the source-constrained responder with
alias words0/`0xffffffff`. Their original requests match the private ROM
tuples, and an explicitly logged fixture event lets the original PLL0
initializer return to`0xb7453c`. No CP instruction, table pointer, return
register or camera parameter is patched. This return is **conditional on
the supplied experiment response**, not proof of real clock lock or boot.

Both conditional continuations then fault at an unsupported logic-clock
clear. Separate fresh before-write watchpoints stop at Thumb`0xb716d4`,
opcode`0x5081`, with R0=`0x70`, R2=`0xf1388008`, R1=`0x100`:
CLKEN_LOGIC channel7 CLR`0xf1388078`, now bit8. Its physical role and required
behavior remain unqualified; the earlier model admits only bit22.
Both fault guests were source/watchpoint qualified and archive-verified
before explicit disposal. Other guests exit at declared boundaries.

No complete group2 initialization, native AP/CP receipt, pre-trigger exposure,
bounded retained RAW, S2 save/cancel, ordinary shooting or exact physical
restoration is established. No camera was accessed and no installer is supplied.

## 简体中文

公开包中旧时钟驱动的布局不能直接套到当前CP，因此没有据此猜测参考频率或锁定时间。
新增的是明确隔离的“原ROM配置约束实验响应器”：文件指纹/格式、客体ROM表、选择器、
系数与相关分频必须吻合，才可提供实验响应；它不是物理PLL模型。

26组原控制仍通过，无响应端的两组原CP仍保留等待。另有11组参考数据对照、6组启动拒绝
测试和19项共享回归通过。两组条件性原CP流程在收到明确标记的实验响应后返回PLL0初始化，
接着到logic bit8清除边界；这不证明真实锁定或完整开机。预拍摄实机闭环仍未完成。
