# Sparse source-command policy and the next control read

The [clock-gate stage](VM-CP-CLOCK-GATES.md) reached write`0xf54005d4`.
It belongs to the original selector`0x93` command sequence. This follow-up
qualifies that sequence and derives a sparse policy from the broader command
family. Conditional CP execution now returns from the software command and
stops at unknown read`0xf5408038`. Hardware effects, complete initialization
and physical pre-capture remain unverified. No camera was accessed.

## Original commands and software returns

[audit_domain93.py](audit_domain93.py) checks16 contracts against exact
stock2.01 CP. Original dispatchers`0x52b4f8` and`0x52cc9c` route selector
`0x93` to its command and inverse. The independent original descriptor
contains offsets`0x5d0`, `0x5e0`, `0xdd0` and two unsupported sentinels.

The command writes13 masks at the three word addresses plus4; the inverse
writes the corresponding masks at the base addresses in its original order.
Their unions are`0x5515`, `0x55`, `0x11`. Both original functions return0
for every tested readback word. That return does not establish physical
clock/reset completion, readiness or hardware acceptance.

This layout must not inherit the earlier SCU DATA/SET/CLR convention:
the inferred clear command is at the base, not base+8. Physical register
roles and readback values remain unqualified.

```text
python dev/precapture/audit_domain93.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_REPORT.json
```

## Deriving an exact sparse policy

[support/request_words.py](support/request_words.py) directly executes the
two original dispatchers for selectors1..152 with four explicit readback
words:1,216 original executions. It admits only returned zero-result paths
whose writes match under those tested words, with base+4 commands, base inverse writes,
matching nonempty bit unions and aligned source offsets. Other paths are
excluded; no original external service is supplied as successful.

For this pinned image,89 selectors have matching paired patterns, yielding
182 sparse words. Fifty selectors return source rejection;13 other paths
do not meet the pairing criteria. Those classifications apply to these
dispatchers and are not a list of physically supported camera functions.

[build_request_policy.py](build_request_policy.py) emits a new private
directory with the1,596-byte policy, manifest and original execution report.
Modified/truncated CP images are rejected.

```text
python dev/precapture/build_request_policy.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_request_words.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

Generated policy/trace data stays private and outside the public repository.
It is an experiment input, not firmware or a camera deployment artifact.
The second command is host-only state testing and has no camera connector.

## Restricted request-word model

[state.h](vm/cp_boot/request_words/state.h) and
[qemu_requests.c](vm/cp_boot/request_words/qemu_requests.c) admit only the
canonical policy fingerprint for the exact stock source. The constructor
requires an explicit file/hash/alias, checks source/code headers and maps182
individual8-byte windows. Gaps and other registers stay unsupported; there
is no whole-IOP or whole-SCU RAM mapping.

Base writes clear modeled **requested bits**; plus4 writes set them. Base
reads return that software request state; plus4 scratch readback is an
independent zero/ones fixture. These are inferred latch semantics, not
confirmed hardware state. No physical clock/reset effect, frequency, IRQ,
sensor response or ready signal is supplied.

Every modeled read/write also checks the guest's original command and
I/O-helper code ranges against the pinned code digest. Unknown words/bits,
offsets/widths and code drift fault. Private native operators separately
verify the complete loaded CP identity; range checks do not replace whole-
image admission or qualify the current camera body.

The optional laboratory inputs are:

```text
QEMU_SONY_CP_REQUEST_POLICY_FILE=PRIVATE_POLICY_PATH
QEMU_SONY_CP_REQUEST_POLICY_SHA256=EXACT_CANONICAL_POLICY_SHA256
QEMU_SONY_CP_REQUEST_ALIAS=zero (or ones)
```

Fourteen reference-data guest controls load CP code only as admission data
and never execute it. Two walk every admitted word through set/read/clear
under both alias profiles. Twelve negative cases cover unknown bits, the
unadmitted plus8 address, unmapped words, byte writes and code drift before
or after a first valid request. The latter confirms the code check is not
merely cached at startup. Deliberate mutations stay within isolated VM data.
Six malformed/missing policy cases are rejected before guest execution.
Host contracts and19 shared regressions pass.

## Conditional original-code evidence

The staged original loader/CP/factory/TOMCO, BK4 placement, four CPUs,
group2 and watchdog configuration remain. PLL responses are still explicit
source-constrained experiment inputs, not physical lock or boot acceptance.
The absent-backend native control retains its PLL wait.

Two alias profiles reach selector`0x93`, execute its original command
sequence and return R0=0 to caller`0x52a928`. Requested-word logs match the
independently audited masks and explicitly mark hardware-confirmed=0. No
instruction, return register, table pointer or camera parameter is patched.

Both conditional continuations fault at read32`0xf5408038`. Separate fresh
before-read watchpoints stop at Thumb`0xb71610`, opcode`0x5840`,
`ldr r0,[r0,r1]`: R0=`0x8038`, R1=`0xf5400000`. Its role and correct initial
value remain unqualified, so the model leaves that read unsupported.
Complete group2 UIN return and native AP/CP receipt remain open.

Fault guests were source/first-fault/watchpoint qualified, archived and
hash-verified before explicit disposal. Successful bounded controls exit
normally; deadlines alone never authorize replay or cleanup. Real half-press
exposures, bounded retained RAW, S2 save/cancel, ordinary shooting and exact
physical restoration remain unfinished.

## 简体中文

已确认选择器93的原命令/撤销序列，软件返回0不代表硬件已完成。扩大扫描后，1,216次
原指令执行得到89个成对模式、182个稀疏字，只接纳精确策略/代码指纹和来源位域。
模型保存的是软件请求，不是物理时钟/复位状态，也不生成就绪信号。

14组参考数据VM、6组启动拒绝、主机检查和19项共享回归通过。在明确PLL实验响应条件下，
两组原CP返回选择器93命令，随后到f5408038未知读取，独立新VM已在原指令前核对。
完整初始化、实际曝光/保留/保存与实机预拍摄闭环仍未完成；本轮没有操作相机。
