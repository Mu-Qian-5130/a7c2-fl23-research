# Inferred CP DFS protocol and initialization return

The [factory-table stage](VM-CP-BACKUP.md) stopped at write`0xf1388f4c`.
Original CP register sequences and the original AP UPM module now identify
its DFS context. A bounded **inferred protocol model** lets the original
DFS initializer return, without starting or completing a clock transition.
The following unsupported write is`0xf1388234`. Complete group2 UIN return
and physical pre-capture remain unverified. No camera was accessed.

## Original instruction evidence

[audit_cp_dfs.py](audit_cp_dfs.py) checks21 contracts against the exact
stock2.01 CP and original AP `upm.ko` fingerprint. CP diagnostics include
DFS frequency/state names; AP symbols independently name the DFS driver.
Original slices establish these sequences:

| Operation | CP register address | AP kernel virtual address |
|---|---|---|
| Pre-request write`0x101`; completion poll |`f1388f48` |`fffffffff1388f50` |
| Initialization write`0x101` |`f1388f4c` |`fffffffff1388f54` |
| Start write1 |`f1388f50` |`fffffffff1388f58` |
| Packed command write |`f1388f54` |`fffffffff1388f5c` |
| Status read |`f1388f58` |`fffffffff1388f60` |

The addresses are endpoint-specific observations, not proof of shared
physical registers or wiring. Generic SCU DATA/SET/CLR aliases must not be
imposed on this block just because the addresses have a4-byte stride.

The CP original request routine waits while status bit8 is set, then
writes `arg0 | (arg1 << 8)` followed by start1. With arg1=1 it waits until
`poll & 0x101 == 1`. Independent synthetic status words verify retained
busy/completion loops; no payload/start is written through the busy loop.
A trial flag can skip register access entirely. External service calls are
unexecuted boundaries, and post-service/flag/status slice inputs are explicit.
Changed CP/module fingerprints are rejected.

```text
python dev/precapture/audit_cp_dfs.py --cp PRIVATE_STOCK_CP --upm PRIVATE_ORIGINAL_UPM_MODULE --output NEW_PRIVATE_REPORT.json
python dev/precapture/verify_cp_dfs.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

The second command checks only host model state. It has no VM/camera connector.

## Bounded model and limits

[state.h](vm/cp_boot/dfs/state.h) and
[qemu_dfs.c](vm/cp_boot/dfs/qemu_dfs.c) implement an inferred CP-view protocol:

- Initialization/control writes are recorded independently from completion.
  Writing`0x101` does not create a completed request.
- The admitted profile accepts tokens0..6 with argument1=0/1. Broader trial
  arguments, unknown bits, duplicate starts, active-command replacement and
  unqualified register reads fault. These bounds are model admission rules.
- A started request remains active/busy with no completion when the backend
  is absent. Reads, control changes and event acknowledgement do not finish it.
- Only an explicit fixture actor can complete it. The actor returns the
  requested token and latches completion; acknowledgement clears that event.

Event-clear/control roles, initial values, status composition and fixture
completion are inferred laboratory semantics. There is no supplied clock
tree, measured frequency, voltage/power effect, physical timing or IRQ route.
The QEMU CPU/counter frequencies are unchanged. The control word does not
establish a hardware interrupt mask. Unsupported error/cancel behavior is
not reported as successful. The positive fixture is separate from native
CP execution and physical hardware.

Eight firmware-free guests execute [control.S](vm/cp_boot/dfs/control.S):
one explicit actor completion/acknowledgement, one absent-actor request
retained through64 polls, initialization-only with no request, and five
fault controls for unknown control bits, out-of-profile commands, duplicate
start, active replacement and an unqualified control-register read.
The21 source contracts, host model checks and19 shared regressions pass.

The independent board links unchanged GPIO/I2C/eDMA/timer/watchdog source
with the new protocol object. Source/build/control fingerprints are retained;
compiled programs and host operators remain private. An initial A64 control
assembly used an unencodable logical immediate and failed compilation; it
was corrected before any control guest ran.

## Native continuation and next boundary

The native guest keeps the exact original loader/CP/factory/TOMCO inputs,
declared BK4 placement, four CPUs, group2 and original watchdog configuration.
DFS and eDMA backends are absent; I2C has no native slave. Original table
binding and PCIDMA/UIPC/PCIEIF observations remain.

Original DFS entry`0x595c44` now returns to`0xc0bf0a` with R0=0. The actual
model trace records only its control write`0x101`, with active=0/starts=0.
There is no fixture completion or native eDMA copy. The initializer's return
does not establish a real clock transition or a ready peer.

Continuation faults at write32`0xf1388234`. An independent fresh guest
stops **before** Thumb PC`0xb716b8`, opcode`0x5081`, `str r1,[r0,r2]`:
R0=`0x230`, R2=`0xf1388004`, R1=0. Sony's official SCU base and CLKSEL
channel3/SPI/16-byte stride/SET4 definitions independently match the address.
The next original instruction path also reads the write address for a
scratch readback; that behavior remains unmodeled.

The first fault guest was retained until source/first-fault/watchpoint
qualification and archive verification, then explicitly disposed. The
watchpoint guest exits at its declared boundary. Observation deadlines
never authorize automatic restart, replay or disposal.

Complete initialization, physical clocks/IRQ wiring, native AP/CP receipt,
pre-trigger exposure, bounded retained RAW pixels, S2 save/cancel, ordinary
shooting and exact physical restoration remain open. No installer is supplied.

## 简体中文

原CP和AP模块的原指令已确认DFS寄存器访问顺序；21项契约通过。新增的是明确标为推断
的协议模型，未实现真实频率/电压/时序或IRQ线路。没有响应端时请求一直等待，只有独立
测试响应端能完成请求；8组无固件VM、主机检查和19项共享回归通过。

原CP的DFS初始化已返回，日志没有调频请求或完成事件。下一处是SPI时钟选择SET地址
f1388234写0，已在原指令前独立核对。完整初始化、AP/CP收发与实机预拍摄闭环仍未完成；
本轮没有操作相机。
