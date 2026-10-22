# CP request words and timing-control experiments

The [clock-gate stage](VM-CP-CLOCK-GATES.md) reached write`0xf54005d4`.
It belongs to the original selector`0x93` command sequence. This follow-up
qualifies that sequence and derives a sparse policy from the broader command
family. Conditional CP execution now returns from the software command and
stops at unknown read`0xf5408038`. Hardware effects, complete initialization
and physical pre-capture remain unverified. No camera was accessed.

The follow-up below includes a separately authorized, existing-file-only
camera snapshot. It does not change the scope of the earlier offline runs.
The latest optional selector experiment reaches write`0xf5411010`; the
earlier boundaries and their unmodified negative controls are retained below.

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

## Configuration helper follow-up

[audit_config_rmw.py](audit_config_rmw.py) executes the original
`0xb74730` helper with independent first/second readback words. Its385 runs
cover set/clear selectors, untouched-bit preservation, callee-saved registers,
the scratch store and original caller arguments (`0x4000`,1). R0 is the
**second readback**, not a success status. Hardware initial values and the
physical register role remain unknown; the native-boot model still faults.

[config_rmw](vm/cp_boot/config_rmw/) supplies a separate helper-only QEMU
fixture. The register address is ordinary test RAM on this deliberately
non-hardware board. Stock and privately captured current CP each pass96
vectors; a wrong expected word stops at the intended failing vector. This
does not continue native boot, supply a peripheral response or emulate a
camera. Never reuse that broad RAM mapping in the native-startup fixture.

The October21 read-only handoff acquired existing AP/CP files and live/saved
settings, checked body identity, verified three private snapshot copies and
confirmed both program files were unchanged at session end. No code was
uploaded, parameter changed, temporary file removed or capture triggered.
The relevant three on-disk helper/caller spans match stock; the separate
comparison also checks17 pre-capture source ranges. Whole modified firmware,
loaded RAM and current hardware state are not admitted by those comparisons.
The snapshot is historical, not permission to overwrite subsequent work.

**Correction:** the original AT74 report subtracted the fixture load base
from the17 `SPECS` ranges, which are already file offsets. Its named-range
claim was invalid. The original artifact is retained; the later
[audit_source_spans.py](audit_source_spans.py) compares the correct file
windows, independently checks the encoded branch displacements and rejects
17 altered-span controls. All17 correct ranges in that historical snapshot
also match stock. The three absolute helper/caller spans used a distinct,
correct coordinate convention and are unaffected. No camera write relied
on the invalid17-range report.

```text
python dev/precapture/audit_config_rmw.py --cp PRIVATE_STOCK_CP --current-cp PRIVATE_CAPTURED_CP --output NEW_PRIVATE_REPORT.json
```

The optional current-file check uses [support/config_rmw.py](support/config_rmw.py).
It pins the stock input and rejects changed source spans, without qualifying
unrelated regions or generating an installation candidate. Generated reports,
VM operators, compiled helpers and captured firmware remain private.

## Optional single-word continuation

The later [qemu_config.c](vm/cp_boot/config_rmw/qemu_config.c) fixture maps
only four bytes at`0xf5408038`. It has no inferred hardware reset value:
`QEMU_SONY_CP_CONFIG_INITIAL=zero|ones` explicitly selects an experiment
input. With the input absent, the address remains unsupported. It permits
only bit14 to change, preserving every other input bit, and checks all three
original helper/caller code spans on every read and write. It supplies no
physical effect, ready/LOCK bit, frequency, IRQ, sensor or pixel operation.
This is separate from the earlier broad-RAM helper instruction test.

The opt-in [machine wrapper](vm/cp_boot/config_rmw/qemu_none.c) reuses the
request-stage machine; the base build has no configuration device. Host
contracts204, twelve positive/negative controls, two absent-device faults,
three invalid-profile startup rejections and fourteen earlier request-word
regressions pass. Controls reject other changed bits, byte access, the
neighbouring word and code drift before/after a first accepted operation.
CP is admission data, not executed firmware, in those control guests.

In two staged original-CP guests, with the existing explicit PLL source
fixture and the two configuration inputs, the original helper returns at
`0x685314`. R0/scratch match the requested word; that is not hardware success.
Both then fault on a new unsupported read`0xf5411000`. Independent fresh
before-read watchpoints stop at Thumb`0xb9b5a2`, bytes`01 68`, `ldr r1,[r0]`,
with R0=`0xf5411000` and R4=3. Its physical role/value remains unknown and
unmapped. No original instruction, return value or camera parameter was
patched to pass the initialization.

The absent-PLL native control retains its original lock poll. Both first-
fault guests were qualified and archived before explicit disposal; all33
owned guest cases reached terminal state. Shared support checks19 pass.
No camera was accessed during this continuation. The original full physical
pre-capture requirements, including pixel retention and safe release, remain.

```text
python dev/precapture/verify_config_word.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

## MTG selector source qualification

[audit_mtg_select.py](audit_mtg_select.py) stops the original diagnostic
display prefix before its service, where its arguments identify
`0xf5411000` as `MTG_REG_SEL`. The source's actual caller supplies selector3.
The target's setter/getter and the independently pinned A1 II source share
68 identical bytes. These are source/field facts, not a qualified physical
clock model or measured chip equivalence.

The126 original contracts cover both sources, the native logger boundary,
independent post-log stores, low-two-bit truncation, preservation of other
bits, ABI and getter results. The setter returns a second, independently
supplied readback word; it does not acknowledge hardware. Native logging is
never made successful to connect those separate slices.

[support/register_source.py](support/register_source.py) now supplies the
shared source fixture to both this audit and the previous configuration
audit. Its ROM is read-only; unspecified IO, stores, missing/unused input
words and instruction exhaustion fail. Twelve failure/coordinate controls
pass, and the earlier385-case configuration report is unchanged. No MTG
edge, frame interrupt, sensor, pixels or native save/release is provided.

```text
python dev/precapture/audit_mtg_select.py --cp PRIVATE_STOCK_CP --donor PRIVATE_ORIGINAL_A1II_CP --output NEW_PRIVATE_REPORT.json
python dev/precapture/verify_register_source.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_REPORT.json
```

## MTG selector storage experiment

[qemu_mtg.c](vm/cp_boot/mtg_select/qemu_mtg.c) opts in only four bytes at
`0xf5411000`, with bits0..1 writable and every other input bit preserved.
`QEMU_SONY_CP_MTG_SELECT_INITIAL=zero|ones` is required; no input leaves the
word unsupported. Every access checks original helper/getter, caller, name
and diagnostic-prefix bytes. This generates no timing edge, frame IRQ,
frequency, sensor data or physical completion.

Both single-word devices now share
[qemu_source_word.h](vm/cp_boot/config_rmw/qemu_source_word.h), and their
control guests share static assembly with per-device constants. The old
control's loaded segments/header/entry are identical; only non-loaded debug
line metadata changes. Each new ELF is separately pinned in private runs.
All28 prior configuration/request/absence control marker records match the
earlier build exactly;768 MTG and204 original configuration host contracts,
42 control guests and six pre-execution profile rejections pass. Reference
CP code is not executed in those control guests.

Two conditional original-CP guests return from the selector at`0xb977cc`,
with the separate explicit PLL/configuration inputs still required. They
then fault at unsupported **write**`0xf5411010`. Independent fresh write
watchpoints stop at Thumb`0xb9b69e`, bytes`04 60`, `str r4,[r0]`, with
R0=`0xf5411010` and R4=`0x1b7e47`. This software-requested value does not
qualify the word's physical timing or behavior. Nothing maps it yet.

The absent-PLL native control still retains its original poll. Both first
faults were archived and verified before explicit disposal; all47 owned
guest cases are terminal. The observer now records a normal host exit after
an explicitly requested, successful VM disposal, without replay or automatic
cleanup on an unknown outcome. No camera was accessed; no physical
pre-capture requirement is replaced by these results.

```text
python dev/precapture/verify_mtg_select.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

## 简体中文

已确认选择器93的原命令/撤销序列，软件返回0不代表硬件已完成。扩大扫描后，1,216次
原指令执行得到89个成对模式、182个稀疏字，只接纳精确策略/代码指纹和来源位域。
模型保存的是软件请求，不是物理时钟/复位状态，也不生成就绪信号。

14组参考数据VM、6组启动拒绝、主机检查和19项共享回归通过。在明确PLL实验响应条件下，
两组原CP返回选择器93命令，随后到f5408038未知读取，独立新VM已在原指令前核对。
完整初始化、实际曝光/保留/保存与实机预拍摄闭环仍未完成；本轮没有操作相机。

后续已单独完成配置读改写辅助函数的385次原指令检查，以及两组各96个向量的QEMU
检查；错误预期值也能被拒绝。这里的QEMU寄存器地址只是测试RAM，不是硬件模型，
不能用于绕过原生启动的未知寄存器。10月21日另获授权的只读交接已保存当前文件与设置，
核对相关磁盘代码；没有上传程序、写参数或改固件，也没有验证运行中的RAM或真实预拍摄。

后续另加只映射4字节、只准许改动bit14的可选配置实验。初值必须明确选择zero/ones，
没有初值时仍停在未知读取。204项主机检查、12组配置控制、2组缺少设备、3组启动拒绝
及14组原请求回归通过。在原有PLL实验响应条件下，两组原CP返回该配置辅助函数，
再停在未知读取f5411000；另用独立VM在b9b5a2读取前核对。未写入相机，也未完成真实预拍摄。

原调试入口将该字标为MTG_REG_SEL；A7C II与A1 II的68字节选择器代码相同。126项
原指令检查与12项失败/坐标控制通过，但不代表真实时钟、边沿、传感器或保存功能。
另外纠正AT74报告：SPECS中的17段是文件偏移，原报告误减了加载基址。旧报告保留且
作废，按正确偏移重做后17段仍相同；没有据错误报告写相机，也没有据此接纳整份固件或RAM。

可选MTG实验只保存选择器低2位，其他位保留明确初值，不产生边沿、中断或真实曝光。
共享旧配置字的实现及控制脚本后，28份旧控制结果逐项相同；42个控制VM与6个启动拒绝通过。
两组原CP返回选择器后，继续到f5411010写入；独立新VM在b9b69e的STR前核对值1b7e47。
47个自有VM均已结束，没有相机I/O；该写入的真实时序及完整预拍摄仍未实现。
