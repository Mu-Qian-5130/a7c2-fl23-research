# A7C II pre-capture research

Unfinished research for firmware 2.01, **not a working feature or installer**.
All public commands in this directory run offline.

This feature branch now includes current main's product/runtime files; the
research remains confined here and has no installable pre-capture entry.
At each phase boundary we review main updates and redundant dependencies,
and compare original-source/model reports before and after refactoring.

[Workflow review](WORKFLOW.md) maps each shooting stage to tested code and
the remaining connections; passing component checks does not close the workflow.
[Continuous lifecycle implementation](CAPTURE-LIFECYCLE.md) adds a complete
transaction against a virtual pixel device; its native camera bindings are pending.
[Sony-kernel VM test](VM-PROCESS.md) records actual pinned-FD child execution
and isolated UIPC allocation/cancel/local loopback in an independent full-system guest.
It now also runs the continuous controller with explicit virtual pixels:
8 transactions, 8 verified files and 71 complete action lifecycles. Physical
pre-capture remains unimplemented.

[Staged original CP startup](VM-CP-BOOT.md) now runs the original loader's
configuration reader, GPIO helper, mode writer and architectural A32 handoff
in an explicitly configured VM. The stock CP reaches its runtime entry and,
in one follow-up, its post-BSS-clear boundary. Full RTOS/peer startup and the
physical AP/CP address alias remain unverified.

[Multicore and interrupt follow-up](VM-CP-SMP.md) supplies the four native
participants expected by CP startup, adds an architectural GICv2 model and
reaches `0x60d46c` before the following initialization/dispatch call. The
timer and task continuation is recorded separately below.

[Timer routing and first native task dispatch](VM-CP-TIMER.md) now qualifies
the explicit2MHz timer channel with four-CPU positive/negative controls.
The original CP activates secondary CPUs and enters a native bootstrap
task; execution then faults at an unsupported peripheral write. Camera
services, exposures and saving remain unverified.

[General-purpose timer and initialization callbacks](VM-CP-GPTIMER.md) adds
an explicitly inferred counter/compare model with independent Sony register
definitions and four-CPU controls. In its group0 fixture, original timer
initialization and the1111-entry callback list return; AP communication and physical capture
remain open. A finalization wait is kept separate from normal initialization.

[Original boot configuration](VM-CP-CONFIG.md) corrects a missing TOMCO input:
the earlier default group0 admitted only TOPPERS_KERNEL. The original741-byte
file is now read back and parsed by CP into group2, which admits transport
entries. Execution reaches a missing watchdog-reset device first. Neither
group admission nor the earlier1111 callbacks proves transport initialization.

[Reset-mode watchdog](VM-CP-WATCHDOG.md) supplies a timed watchdog model
with correct-feed, no-feed, bad-feed and unsupported-access controls. Original
group2 execution now enters PCIDMA_INIT and reaches the PCIe EDMA interrupt-
enable register. A before-read watchpoint qualifies that boundary; no link
readiness, transport receipt, DMA completion or capture result is supplied.

[eDMA byte movement and UIPC initialization](VM-CP-EDMA.md) now verifies
actual model RAM copies, retained RUN without a peer, partial abort and
interrupt masking. Original CP returns from PCIDMA/UIPC initialization and
enters PCIEIF before a missing GPIO-direction read. The fixture peer is
explicitly separate from native AP/CP traffic and physical capture.

[GPIO state and peer-startup guards](VM-CP-GPIO.md) now preserve separate
input/output state and reject undefined pad inputs. Original PCIEIF returns,
but its other-chip trigger byte remains0 with no peer. Eight register/alias
controls, two native high-strap poll controls and22 AP/CP source contracts
qualify this scope. Its next serial-clock access is addressed below.

[I2C initialization and missing native input](VM-CP-I2C.md) identifies that
access as I2C0 and connects the standard DesignWare core through restricted
clock/reset gates. Sixteen final-model byte/NACK/IRQ/gate controls and36
original-instruction contracts pass. Native I2C0 reaches its return boundary;
five controller state records are observed. Continuation then encounters
an unbound table pointer, independently stopped before its dereference.
Original BACKUP_INIT rejects the staged VM's zero table input and skips
the secondary binding; the genuine startup input remains to be reconstructed.
No native table, slave/peer response or capture result is fabricated.

[Original factory-table binding](VM-CP-BACKUP.md) qualifies the original
BK4 headers/checksums and declared address, then observes both native
binding returns using unchanged factory bytes in an independent guest.
The former null-pointer boundary is passed; the next unsupported write
is`0xf1388f4c`, independently stopped before execution. This factory input
is not the current physical body's backup or a deployment candidate.

[DFS protocol and initialization return](VM-CP-DFS.md) checks original CP/AP
register sequences and adds an explicitly inferred protocol model with no
clock-rate changes or IRQ route. Eight firmware-free controls and21 source
contracts pass. Original DFS initialization returns without a clock request;
the next independently qualified boundary is SPI clock-select SET`0xf1388234`.

[SPI selection and scratch readback](VM-CP-SPICLOCK.md) adds restricted
selector-bit storage with explicitly independent alias words. The212
original-instruction contracts and10 firmware-free controls pass. Two native
readback profiles pass the same selector/caller prefix and reach PLL SET
`0xf1388204`, independently stopped before execution. No rates or ready
signals are supplied; full initialization and physical capture remain open.

[PLL programming and retained lock wait](VM-CP-PLL.md) qualifies80 original
programming/control/poll contracts and26 final-model firmware-free controls.
Original native configuration writes match its ROM tables; with no PLL
response, two guests execute three original lock-poll cycles and keep waiting.
The model supplies no native LOCK or physical clock rate. Full initialization
and the physical pre-capture workflow remain unfinished.

[Source-constrained PLL experiment](VM-CP-PLL-SOURCE.md) retains the absent-
backend wait and adds private, exact-source tuple constraints for a separate
conditional responder. Original-code continuation reaches logic-clock bit8
only under that supplied experiment response. Existing26 controls,11 source-
data cases and6 startup rejections pass; physical lock and boot remain unproved.

[Clock-gate masks and conditional five-PLL continuation](VM-CP-CLOCK-GATES.md)
qualifies162 original helper/startup contracts and40 final-model controls.
Two explicitly conditional guests return from all five PLL initializers and
reach the next unsupported write`0xf54005d4`. Absent-backend waits remain;
complete initialization and physical pre-capture are still unverified.

[Sparse source-command policy](VM-CP-REQUEST-WORDS.md) derives182 admitted
request words from1,216 original dispatcher executions and89 paired patterns.
The inferred request latches and guest-code pins pass14 reference-data
controls and6 startup rejections. Conditional selector`0x93` execution returns
its software result, then stops at unknown read`0xf5408038`; hardware effects
and the real pre-capture workflow remain unproved.

The same page records the configuration RMW follow-up:385 original
executions and separate stock/current-file96-vector QEMU helper tests.
Those tests use ordinary RAM in place of the register, not a hardware model
or native-boot continuation. The historical October21 read-only camera
snapshot qualifies specific on-disk spans, never loaded RAM or capture.

The optional one-word configuration experiment now continues those staged
native guests to a new unsupported read`0xf5411000`; independent before-read
watchpoints qualify that next boundary. Only bit14 at the previous word is
writable, initial words are explicit inputs and no physical completion is
supplied. See the same page for controls and the remaining limitations.

Host-side research can use a privately pinned copy of main's current
length-delimited Senser transport through
[support/readonly_session.py](support/readonly_session.py). This wrapper
permits named existing-file reads and live/saved settings snapshots only.
Its exit deliberately excludes automatic reauthentication after unknown
results; no upload, deletion, native execution or probe-result cleanup is
allowed. It imports/opens no USB itself and does not update the legacy tools.
Twelve fake-transport controls and six integration controls with the actual
main parser pass; main's34 existing focused tests also pass. These are
offline tests, not a new physical session or pre-capture acceptance.

## What is established

- CP parameter `00030072` caused a half-press crash and restart. That approach
  is retired and must not be retried.
- Native wait0 message allocation/cancel worked on one body. Pre-trigger
  exposures, retained pixels and saved pre-trigger photographs remain unproven.
- The earlier file-only camera child failed setup with `EINVAL`, then exited
  and was cleaned. The corrected AArch64 component passes instruction models
  and an actual Sony-kernel QEMU file/exec test. Camera-side standalone child
  creation/execution has not yet been established.
- The isolated UIPC component passed actual open/query/map/allocate/cancel/
  unmap/close under the original driver in the Sony-kernel VM. No messages
  were sent. It has no camera adapter; asynchronous peer lifetime and direct
  synchronous RPC/log/DMA callback lifetime remain unresolved.
- A subsequent private AP self-loop passes actual allocate/send/one poll/free
  with exact32-byte content in the VM. It is local delivery, not a CP reply.
  Original send code can return0 without a registered remote transport.
- The original PCIe module registers its callback table in a separate no-AP
  guest. Actual pointer/function samples match, but its sender init signal
  stays0; CP startup/receipt and working DMA are not established.
- Removing the VM's native PCIe/PCIDMA initcall skips and adding five missing
  DMA virtual mappings still does not establish a CP peer. A fault policy
  exposes unimplemented MMIO instead of accepting all-ones polling results.
  The relevant ranges receive no accesses during these initialization tests.
- The original transport startup checks GPIO port17/bit4 before signaling
  its sender threads. An actual VM snapshot shows the mapped input stays0
  before/after module loading. Separate original-instruction audits trace
  this guard and the loader's configured GPIO → EXEC_MODE → CP-poll encoding;
  actual peer/strap values and the AP/CP physical alias remain unqualified.

Camera contents can change during separate color-calibration work. Historical
CP fingerprints are offline fixtures, not current body identity or permission
to overwrite it. Read [AGENTS.md](AGENTS.md) before any device work.

## Code map

| Location | Responsibility |
|---|---|
| `support/build.py`, `elf.py`, `aarch64_abi.py` | Shared offline compilation, ELF/ISA validation and independent target-header ABI checks |
| `support/cp_mapping.py`, `cp_owner.py`, `native_gate.py`, `ap_codec.py` | Original-instruction fixtures shared directly by checks |
| `support/kernel.py`, `uipc.py`, `boundaries.py`, `reference.py`, `memory.py` | Pinned inputs, synthetic memory and execution stopped before native services |
| `support/config_rmw.py`, `audit_config_rmw.py`, `vm/cp_boot/config_rmw/` | Pinned configuration-helper spans, original execution and isolated RAM-backed helper fixtures; no hardware initial value or native boot admission |
| `support/readonly_session.py`, `verify_readonly_session.py` | Explicit named-file/settings-only wrapper for separately reviewed modern host transport; offline guards, no camera enumeration or uploader |
| `support/capture_native.py` | Shared original CAP object/cancellation fixture; six audits import it directly, with legacy replay exports retained |
| `support/ap_model.py` | Generated-component unit calls with explicit modeled outcomes; never used to supply successful native services in source audits |
| `capture_workflow.c/h`, `support/workflow_model.py` | Asynchronous ownership/save/cancel/restore controller and explicit virtual pixel actors; separate from the CP runtime and unbound to native hardware |
| `vm/workflow_guest.c`, `vm/verify_workflow_guest.py` | File-only continuous-controller integration under Linux and independent pixel/journal validation; no native camera adapter |
| `vm/cp_boot/` | Offline staged CP startup source fixtures, explicit EL3 context and QEMU GPIO/alias model; no camera installer |
| `audit_frame_reference.py`, `support/frame_reference.py` | Original frame add/drop and holder-pool lifetime slices; no successful lock, acquired pixel reference or native completion is supplied |
| `audit_frame_clock.py` | Original saved-latch and independent frame-clock stores; no timer or exposure-boundary interpretation is supplied |
| `audit_send_admission.py` | Original zero-return path with no remote transport; no native log or callback success is supplied |
| `audit_transport_registration.py` | Original registration/initialization-signal contracts; not a CP-ready or drain test |
| `audit_transport_startup.py`, `audit_cp_exec_mode.py` | Original GPIO/IRQ startup guards and loader/CP mode encoding; no forced signal, hardware success or qualified physical alias |
| `audit_loader_backup.py`, `support/backup.py` | Original BK4 scalar reader against exact factory inputs, with independent host layout/checksum validation; no live backup admission |
| `audit_cp_smp_boot.py`, `vm/cp_boot/smp/` | Original startup/phase comparison, four-CPU fixtures and architectural interrupt controls; no native timer/dispatch or physical pre-capture acceptance |
| `audit_cp_timer_boot.py`, `vm/cp_boot/timer/` | Original timer/task/peripheral admission slices and tested timer-routing fixtures; no sensor, camera-service or physical pre-capture acceptance |
| `verify_cp_gptimer.py`, `vm/cp_boot/gptimer/` | Host counter contracts and tested experimental QEMU timer fixtures; input clock/mode2/CP routing remain model assumptions |
| `audit_cp_config_group.py` | Original group admission and handler slices; exact original TOMCO required, no callback/service success supplied |
| `verify_cp_watchdog.py`, `support/host_test.py`, `vm/cp_boot/watchdog/` | Shared host-test runner and timed reset-mode watchdog fixtures; physical reset routing/TOP_INIT capability remain unqualified |
| `verify_cp_edma.py`, `vm/cp_boot/edma/` | Non-LL model byte movement/interrupt controls and exact tested fixtures; no native AP peer, physical DMA, LL/cancel or capture acceptance |
| `verify_cp_gpio.py`, `audit_transport_gpio.py`, `vm/cp_boot/gpio/` | GPIO state/input isolation and original AP/CP endpoint guards; no electrical wiring, GPIO IRQ, peer-ready or camera acceptance |
| `ap_child_exec.*`, `ap_ipc_context.*` | Child setup and cancel-only context components; no live adapter |
| `ap_probe_once.*`, `ap_query_once.*`, `ap_poll_once.*`, `ap_reply_once.*` | Allocation/cancel, tagged send, one poll, status validation/release; no live transaction or teardown admission |
| `ap_binding_guard.h`, `precapture_query_wire.h` | Shared private-buffer checks and status wire constants; identity/queue provenance remains external |
| `cp_*.c`, `cp_*.h`, `cp_*.S` | CP control/runtime/retention components; integration incomplete |
| `cp_backend.c`, `cp_runtime_entries.c` | Tagged read-only status replies from the serialized owner; uninstalled, with native-send bounds still unproven |
| Other C sources | Protocol encoding, trigger/frame decisions and queue policy |
| `verify_*.py` | Generated-component models and original-instruction comparisons |
| `audit_*.py`, `trace_*.py`, `decode_cp_blog.py` | Source audits and trace analysis |
| `cp_probe_reply.py` | Exact-source observer review builder, not a deployment tool |

Executable sources stay beside their verifiers so existing compilation paths
remain valid. Reusable fixtures live in `support/`; previous helper names stay
exported from their original modules for private evidence replays. Specialized
LTO/linker-script builds and compile-only ABI checks retain their own commands.

[CONTROL-PATHS.txt](CONTROL-PATHS.txt) contains detailed findings and unresolved
boundaries. [history/implementation-notes.txt](history/implementation-notes.txt)
contains older chronological notes whose identities and commands may be obsolete.
Firmware, body backups, generated binaries, private operators and run reports
are deliberately excluded from this repository.

## Offline checks

Dependencies: Python with `unicorn`, `capstone`, `pyelftools`, `keystone-engine`;
compiled checks also need an explicit Zig path (reference version: 0.13).
Every source audit requires the exact private originals its fingerprints admit.
Use a fresh private output location for every run.

```text
python dev/precapture/verify_support.py
python dev/precapture/verify_readonly_session.py
python dev/precapture/verify_config_word.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_capture_workflow.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/audit_frame_reference.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_JSON
python dev/precapture/verify_child_exec.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_poll_once.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_query_once.py --help
python dev/precapture/verify_reply_once.py --help
python dev/precapture/verify_backend_query.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_ipc_context.py --uipc-kernel PRIVATE_UIPC_MODULE --uipc PRIVATE_UIPC_LIBRARY --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/audit_ipc_context_lifetime.py --help
python dev/precapture/audit_native_rpc.py --help
python dev/precapture/audit_sync_lifetime.py --help
python dev/precapture/audit_async_reply.py --help
python dev/precapture/verify_offline.py --firmware-root PRIVATE_FIRMWARE_FOLDER --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

Other scripts expose their inputs through `--help`. Donor comparisons use
`a1ii-4.00/components/` and `a7c2-2.01/components/` under the firmware folder.
Model results, full file readback and inverse manifests do not establish
camera boot safety, successful recovery or physical pre-capture.

The linked runtime now requires two explicit code pages for both ABI3/ABI4.
The native unmap models retain the six-look prefix independently of the CAP
observer option. This remains an emulator layout, with no loaded-page or
physical storage approval. A tagged status reply is not a capture result.
The old `precapture_probe_once(...send_query=1)` now rejects before allocation:
its16-byte packet becomes configuration input on the new runtime. Use the
separate tagged12-byte query component; a matched reply is not quiescence.

## 简体中文

本目录是未完成的预拍摄研究，公开工具只做离线验证，没有可安装的预拍摄版本。

开发分支已对齐当前main，产品文件保持一致。每阶段结束与实机准备前，都检查主线更新、
重复代码及失效依赖；精简前后比较原指令和模型报告，不能为了少文件而删掉必要的取证入口。
代码按“共用工具与原指令夹具、AP／CP 组件、验证与审计入口”分工；重复编译流程
已集中，旧导入名称仍兼容。原固件、机身备份和临时诊断程序保留在私有目录。

半按崩溃的 `00030072` 方案已停用，不能重试。新子进程执行、同步请求的回调生命周期
仍需验证；不能把离线通过当成可以安全上机。后续目标仍是真实预触发曝光、像素保留、
全按存盘、取消释放、正常拍摄和精确还原。任何新写入遵守 AGENTS 中的授权边界。

只读主机诊断已适配单独固定来源的新版主线通讯代码，限制到明确文件与设置快照；
未知结果后不自动重认证，不上传、清理或执行诊断程序。12项封装检查、6项实际解析器
集成检查与主线34项检查均为离线结果，不能作为实机预拍摄可用的证据。
