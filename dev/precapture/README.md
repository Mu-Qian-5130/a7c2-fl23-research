# A7C II pre-capture research

Unfinished research for firmware 2.01, **not a working feature or installer**.
All public commands in this directory run offline.

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
代码按“共用工具与原指令夹具、AP／CP 组件、验证与审计入口”分工；重复编译流程
已集中，旧导入名称仍兼容。原固件、机身备份和临时诊断程序保留在私有目录。

半按崩溃的 `00030072` 方案已停用，不能重试。新子进程执行、同步请求的回调生命周期
仍需验证；不能把离线通过当成可以安全上机。后续目标仍是真实预触发曝光、像素保留、
全按存盘、取消释放、正常拍摄和精确还原。任何新写入遵守 AGENTS 中的授权边界。
