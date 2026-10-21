# PLL programming, pending lock and original wait-loop evidence

The later [source-constrained experiment](VM-CP-PLL-SOURCE.md) adds an explicit
conditional responder while preserving this absent-backend negative control.

The [SPI stage](VM-CP-SPICLOCK.md) reached PLL selector SET`0xf1388204`.
The original CP now programs its PLL configuration, starts PLL0 and retains
the original lock-wait loop when no response backend is present. It has
not completed initialization or produced pre-trigger pixels. No camera was
accessed, and no physical PLL lock or clock rate is claimed.

## Original source contracts

[audit_cp_pll.py](audit_cp_pll.py) checks80 contracts against the exact
stock2.01 CP. It executes the original programming routine`0xb74860`,
register helpers and bounded control/poll slices. The original ROM tables
supply three selector presets and two modes, five coefficient words and
two divider fields. Reports containing those original tables stay private.

The programming routine writes selector SET/CLR with mask`0xfd13`, updates
the five words at`0xf1388100..0xf1388110` through mask`0x043fff1f`, and
updates bits1..10 at`0xf1388150` and`0xf1388158`. Other bits are preserved.
Three synthetic register seeds and two alias words verify that preservation.
Out-of-range original arguments cause no MMIO writes.

Original control helpers set/clear bit28 and clear bit27 in each PLL word.
The start sequence sets bit27; five original poll sites wait for bit24.
Synthetic clear/set lock words verify retained/exit branches. These are
explicit slice inputs, not a supplied hardware response. The program/start
writes do not themselves set the polled bit.

The PLL0 preparation helper also uses CLKEN_LOGIC channel7, bit22, through
SET/CLR. Official Sony SCU definitions match its addresses. Four source
cases qualify that helper and its scratch readback. No whole-SCU RAM
mapping or physical clock-tree connection is inferred.

```text
python dev/precapture/audit_cp_pll.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_REPORT.json
python dev/precapture/verify_cp_pll.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

The second command checks only host model state; neither connects to a camera.
Changed CP fingerprints are rejected. Keep generated source-table reports
outside the public repository.

## Model ownership and limits

[state.h](vm/cp_boot/pll/state.h) and
[qemu_pll.c](vm/cp_boot/pll/qemu_pll.c) separate configuration/control words,
pending responses and the read-only lock bit:

- Guest writes to bit24 cannot manufacture LOCK. Requests remain pending
  without a backend; reads do not complete them.
- An explicit fixture actor can respond to an eligible request. A generation
  check rejects a stale response after stop/restart.
- Active coefficient replacement and changes to preserved/reserved bits
  fault. Configuration holes and unknown selector/divider/gate bits fault.
- The admitted logic-clock field is only bit22 at`0xf1388070` with SET/CLR.
  Its storage does not establish physical clock gating or PLL coupling.
- Selector/gate alias words0/`0xffffffff` and initial configuration0 are
  declared laboratory inputs. Preserved register bits remain distinct from
  writable fields and hardware response state.

Control roles, response behavior, initial values and fixture timing are
inferred. There is no validated oscillator equation, coefficient validity
model, output frequency, voltage/power behavior, physical timing or IRQ
route. CPU and architectural-counter rates are unchanged. Fixture LOCK is
not native hardware or boot-safety evidence; stop/restart checks do not
prove capture-buffer cancellation or physical recovery.

Twenty-six final-model firmware-free guests execute
[control.S](vm/cp_boot/pll/control.S): five fixture lock/stop cases, five
absent-backend waits, five ignored guest-LOCK writes, five requests held
without bit28, and six fault controls for active replacement, reserved bits,
holes and unknown divider/selector/logic-gate bits. Host state contracts and
19 shared regressions pass. Positive fixture coefficients are synthetic;
they are not copied camera configuration or physical clock measurements.

The independent final board retains the earlier GPIO/I2C/eDMA/timer/
watchdog/DFS/SPI sources. The initial narrower model and its25 controls are
preserved separately; final tests use a fresh binary and26 fresh guests.
Compiled programs and host operators remain private.

## Original CP continuation

The staged original loader/CP/factory/TOMCO, declared BK4 address, four CPUs,
group2 and watchdog configuration remain. DFS/eDMA/PLL native backends are
absent, and I2C has no native slave. Factory data is not a fresh identity
or restoration image for the current six-look body.

Both alias profiles reach`0xb74860` with original preset0/mode1, then return
to`0xb74538`. Model trace values for all five coefficient writes and both
divider writes match the independently audited original ROM tables; the
last scratch/return word matches as well. No table pointer or return code
is patched to pass this boundary.

The initial model then faulted at CLKEN_LOGIC CLR`0xf1388078`. Two fresh
before-write watchpoints independently gave Thumb PC`0xb716d4`, opcode
`0x5081`, R0=`0x70`, R2=`0xf1388008`, R1=`0x400000`. Both fault archives
were source-qualified and hash-verified before explicit disposal. Those
initial sources remain preserved separately.

With the source-bound bit22 model, two final-model native guests now reach
the original PLL0 lock poll at`0xb74b02`. Nine actual instruction steps per
guest execute three `ldr`/`tst`/`beq` cycles through PCs:

```text
b74b02 -> b74b04 -> b74b08 -> b74b02
```

The guest reads the original programmed word with bits27/28 set and bit24
clear on every cycle. No fixture lock, successful DFS transition, native
eDMA copy or peer-ready state is supplied. Each declared negative control
exits after observing the retained loop; it does not force the original
initializer to return. Full group2 UIN return remains unobserved.

The next work is the source-defined PLL response/clock behavior and the
native AP/CP services. Real pre-trigger exposure, bounded retained RAW,
S2 save/cancel, ordinary shooting and exact physical restoration remain open.

## 简体中文

原CP的PLL配置值、位域、控制位和锁定轮询已通过80项原指令契约。模型把配置、待响应和
锁定位分开：软件写锁定位不能制造锁定，无响应端时保持等待。26组最终模型VM、主机检查
和19项共享回归通过；独立测试响应端的LOCK不等于真实硬件锁定。

原CP已按ROM表完成五路配置，再发出PLL0启动并进入原等待循环。两种别名配置各实际执行
三轮LDR/TST/BEQ，锁定位持续为0，没有强制原初始化返回。完整初始化、真实曝光与预拍摄
闭环仍未完成；本轮没有操作相机。
