# Original clock-gate masks and conditional five-PLL continuation

The later [sparse request-policy follow-up](VM-CP-REQUEST-WORDS.md) identifies
the next command family and records its software-return/physical-effect limits.

The [source-constrained PLL experiment](VM-CP-PLL-SOURCE.md) reached logic
bit8. This follow-up qualifies the original helper group and a later startup
sequence, then extends only their software register fields. Conditional CP
execution now returns from all five PLL initializers and reaches write
`0xf54005d4`. Physical clocks, complete initialization and pre-capture remain
unverified. No camera was accessed.

## Source-qualified register operations

[audit_cp_clock_gates.py](audit_cp_clock_gates.py) executes162 contracts
against the exact stock2.01 CP. Twenty original helpers cover nineteen
CLKEN_LOGIC bits and one CLKEN_MEDIA bit. Each helper uses SET only for
argument1 and CLR otherwise, then reads the same alias into scratch.
Arguments0/1/2/`0xffffffff` and independent alias words0/`0xffffffff` verify
the original writes and scratch values. No external service is replaced.

The original startup routine`0xb7454a` separately writes logic SET bits
24,23,22,7,19 in that order. Two alias-word cases execute the complete
original routine. The resulting admitted masks are:

| Bank | Address | Known software bits |
|---|---|---|
| CLKEN_LOGIC7 |`0xf1388070` |mask`0x01fffde3` |
| CLKEN_MEDIA0 |`0xf1388000` |bit8, mask`0x100` |

The official Sony SCU definitions independently match bank channels and
SET/CLR offsets. These facts qualify software register operations; physical
domain wiring, gate effects, clock rates and the active hardware binding
remain unqualified. Other SCU registers and unknown bits remain unsupported.

Logic-bank bits23/24 are distinct from the read-only PLL lock bit24 in the
separate PLL configuration words. Storing a logic-bank bit does not set LOCK.
Only the explicitly selected PLL experiment actor can supply that response.

```text
python dev/precapture/audit_cp_clock_gates.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_REPORT.json
python dev/precapture/verify_cp_pll.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

The first command rejects changed CP fingerprints. The second is host-only
state/constraint testing; neither has a camera connector.

## Models and controls

The updated PLL board stores only these two gate-word masks and keeps their
alias words independent from stored state. It does not add a whole-SCU RAM
window or physical clock-tree behavior. The prior source-fixture and absent
PLL backends remain distinct, with the same private ROM-tuple admission.

The revised26 PLL controls pass. The earlier negative logic-bit21 test is
replaced with bit9 because the original source now qualifies bit21; unknown
bits are still tested rather than silently accepted. Fourteen additional
firmware-free guests execute [gate_control.S](vm/cp_boot/pll/gate_control.S)
under both alias profiles. They check known-bit updates, field preservation,
bank isolation, independent alias words and unchanged PLL0 state, plus six
fault cases for unknown bits, DATA writes, outside-window reads and byte writes.
Host contracts and19 shared support regressions pass.

The initial narrower model, its source bytes and40 controls are preserved
separately. Its two conditional guests reached all five PLL returns, then
faulted at the first startup bit24 write. Independent before-write controls
confirmed that original access; both archives were verified before explicit
disposal. Final controls use a separately built model and fresh guests.

## Conditional native prefix and next unsupported access

The original loader/CP/factory/TOMCO, declared BK4 input, four CPUs, group2
and watchdog configuration remain. The conditional path explicitly uses
the source-constrained experiment responder; it is not physical lock or
boot acceptance. Original code/table pointers and return registers are not
patched, and no real AP/CP peer or native eDMA transfer is supplied.

Two alias profiles observe original returns from PLL0, PLL1/2 and PLL3/4
initialization. Their traces contain five separately identified fixture LOCK
events. After those returns and the original startup sequence, both guests
fault at write32`0xf54005d4`.

Two separate fresh before-write controls give Thumb PC`0xb7164e`, opcode
`0x5081`, `str r1,[r0,r2]`: R0=`0x5d0`, R2=`0xf5400004`, R1=1.
The register's role and behavior remain unqualified. The model keeps this
boundary unsupported instead of accepting an arbitrary register write.
Complete group2 UIN return remains unobserved.

The absent backend still retains the original PLL0 poll under both alias
profiles. One initial debugger observation stopped at the starting PC again
after a step packet, so no completed instruction could be counted. It was
excluded from success, source/stopped-state qualified and archive-verified
before explicit disposal; its root cause remains unresolved.

Fresh observations explicitly select GDB thread1, request supported single-
step flags and use `vCont;s:1`. Their packet journals and CPU0 snapshots
verify nine instructions/three retained poll cycles per guest. Debug stepping
suppresses IRQ/timer delivery during those local observations; this is not
physical timing, interrupt, watchdog-liveness or whole-system progress evidence.
No unknown camera operation is retried by this observer procedure.

Both final conditional fault guests are retained through source/first-fault/
watchpoint qualification and archive verification before explicit disposal.
Successful bounded controls exit normally; a deadline alone never authorizes
restart or cleanup. Native AP/CP receipt, exposure, bounded retained RAW,
S2 save/cancel, ordinary shooting and exact physical restoration remain open.

## 简体中文

已通过162项原指令契约核对门控辅助函数和固定启动序列，只接纳logic掩码01fffde3及
另一个bank的bit8。新门控字与PLL只读锁定位分离，不直接产生锁定。40组最终模型控制、
主机检查和19项共享回归通过；无响应端仍保留原等待。

在明确的原ROM约束实验响应条件下，两组原CP流程已返回五路PLL初始化，随后到f54005d4
写1的未知边界，独立新VM已在原指令前核对。一次重复PC的调试观察没有算通过，保留证据
后用明确CPU/单步控制重新核对。真实时钟、完整初始化与实机预拍摄闭环仍未完成。
