# A7C II pre-capture research

Unfinished research for firmware 2.01, **not a working feature or installer**.
All public commands in this directory run offline.

This feature branch now includes current main's product/runtime files; the
research remains confined here and has no installable pre-capture entry.
At each phase boundary we review main updates and redundant dependencies,
and compare original-source/model reports before and after refactoring.

## Current evidence and remaining work

| Area | Evidence | Still missing |
|---|---|---|
| [Shooting workflow](WORKFLOW.md) / [controller](CAPTURE-LIFECYCLE.md) | Continuous save/cancel/restore controller; [Sony-kernel VM](VM-PROCESS.md) runs eight virtual-pixel transactions | Native sensor, RAW-reference, recording-writer and terminal-fence bindings |
| [Original CP startup](VM-CP-REQUEST-WORDS.md) | Conditional guests return after two write-first MTG period stores/readbacks; independent watchpoints qualify the next read `0xf5410004` | Its physical behavior, complete initialization, timing edges and actual AP/CP receipt |
| AP/CP transport | Original driver VM allocation/cancel/local loopback; source guards and endpoint initialization studied | A local AP delivery or zero return is not CP receipt, peer readiness or safe callback teardown |
| Camera source | Historical October21 file/settings-only snapshot;17 correctly addressed file spans match stock after correction | Fresh loaded RAM, present body state, real pre-trigger exposures and saved photographs |

The MTG/configuration fixtures store explicitly requested fields only. Their
zero/ones initial inputs and PLL experiment responses are **not** measured
reset values, physical timing or hardware readiness. Absent inputs retain the
unsupported access or original wait. The earlier whole-RAM helper test must
never replace the restricted native-startup model.

The old seventeen-range AT74 comparison used the wrong coordinate convention.
It is preserved and invalidated; [the corrected audit](audit_source_spans.py)
checks FILE offsets and original encoded calls. A matching historical span is
not whole-firmware or loaded-RAM admission.

CP parameter `00030072` caused a half-press crash and is retired. Never retry
it. The previous file-only camera child failed setup and was cleaned; its
corrected VM result does not prove camera-side child execution. Native frame
references, late ingress and all-stage release remain open even if a queue is
empty or a status word is zero. Ordinary shooting, exact physical restoration
and preservation of FL2/FL3/six looks need their own physical acceptance.

A privately pinned modern main transport can be wrapped by
[support/readonly_session.py](support/readonly_session.py): named existing
files and bool live/saved snapshots only, no upload/deletion/native execution
or automatic rescue after an unknown exchange. Its13 guard controls and43
focused latest-main tests are offline evidence. Camera contents may have
changed since any archived snapshot; preserve subsequent work and read
[AGENTS.md](AGENTS.md) before a device action.

## Earlier startup studies

These retain original evidence and negative controls; their separate scopes
do not add up to physical pre-capture.

| Subject | Studies |
|---|---|
| Entry and execution | [Loader](VM-CP-BOOT.md), [SMP](VM-CP-SMP.md), [timer](VM-CP-TIMER.md), [counter/callbacks](VM-CP-GPTIMER.md) |
| Configuration and transport | [TOMCO groups](VM-CP-CONFIG.md), [watchdog](VM-CP-WATCHDOG.md), [eDMA](VM-CP-EDMA.md), [GPIO/peer guards](VM-CP-GPIO.md) |
| Input and peripheral configuration | [I2C](VM-CP-I2C.md), [factory BK4](VM-CP-BACKUP.md), [DFS](VM-CP-DFS.md), [SPI selection](VM-CP-SPICLOCK.md) |
| Clock requests | [PLL wait](VM-CP-PLL.md), [conditional PLL source input](VM-CP-PLL-SOURCE.md), [gate masks](VM-CP-CLOCK-GATES.md), [request/configuration/MTG](VM-CP-REQUEST-WORDS.md) |

## Code map

| Location | Responsibility |
|---|---|
| `support/build.py`, `elf.py`, `aarch64_abi.py` | Shared offline compilation, ELF/ISA validation and independent target-header ABI checks |
| `support/cp_mapping.py`, `cp_owner.py`, `native_gate.py`, `ap_codec.py` | Original-instruction fixtures shared directly by checks |
| `support/kernel.py`, `uipc.py`, `boundaries.py`, `reference.py`, `memory.py` | Pinned inputs, synthetic memory and execution stopped before native services |
| `support/config_rmw.py`, `audit_config_rmw.py`, `vm/cp_boot/config_rmw/` | Pinned configuration-helper spans, original execution and isolated RAM-backed helper fixtures; no hardware initial value or native boot admission |
| `support/readonly_session.py`, `verify_readonly_session.py` | Explicit named-file/settings-only wrapper for separately reviewed modern host transport; offline guards, no camera enumeration or uploader |
| `support/capture_native.py` | Shared original CAP object/cancellation fixture; six audits import it directly, with legacy replay exports retained |
| `support/register_source.py`, `audit_mtg_select.py`, `audit_source_spans.py` | Shared explicit-input original register slices, MTG field/label evidence and named FILE-offset comparisons; no hardware ACK or loaded-source admission |
| `vm/cp_boot/config_rmw/qemu_source_word.h`, `vm/cp_boot/mtg_select/` | Shared restricted single-word storage and the optional MTG selector fixture; no timing edges, frame IRQ or sensor |
| `audit_mtg_period.py`, `vm/cp_boot/mtg_period/` | Original indexed period setters/getters and write-first requested-word storage; undefined-before-write, no timing generation |
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
python dev/precapture/verify_mtg_select.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_mtg_period.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/audit_mtg_select.py --cp PRIVATE_STOCK_CP --donor PRIVATE_ORIGINAL_A1II_CP --output NEW_PRIVATE_JSON
python dev/precapture/audit_source_spans.py --cp PRIVATE_STOCK_CP --current-cp PRIVATE_CAPTURED_CP --output NEW_PRIVATE_JSON
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
未知结果后不自动重认证，不上传、清理或执行诊断程序。13项封装检查、43项新版主线
相关检查（含6项实际解析器集成）均为离线结果，不能作为实机预拍摄可用的证据。
