# A7C II pre-capture research

Unfinished research for firmware 2.01, **not a working feature or installer**.
All public commands in this directory run offline.

## What is established

- CP parameter `00030072` caused a half-press crash and restart. That approach
  is retired and must not be retried.
- Native wait0 message allocation/cancel worked on one body. Pre-trigger
  exposures, retained pixels and saved pre-trigger photographs remain unproven.
- The earlier file-only child failed setup with `EINVAL`, then exited and was
  cleaned. The corrected AArch64 open flags pass offline checks; successful
  standalone execution has not yet been established on the camera.
- The isolated UIPC context component models allocation/cancel without sends.
  It has no live adapter. Direct synchronous RPC and the log/DMA route remain
  held pending callback-lifetime proof; process isolation alone is insufficient.

Camera contents can change during separate color-calibration work. Historical
CP fingerprints are offline fixtures, not current body identity or permission
to overwrite it. Read [AGENTS.md](AGENTS.md) before any device work.

## Code map

| Location | Responsibility |
|---|---|
| `support/build.py`, `elf.py`, `aarch64_abi.py` | Shared offline compilation, ELF/ISA validation and independent target-header ABI checks |
| `support/cp_mapping.py`, `cp_owner.py`, `native_gate.py`, `ap_codec.py` | Original-instruction fixtures shared directly by checks |
| `support/kernel.py`, `uipc.py`, `boundaries.py`, `reference.py`, `memory.py` | Pinned inputs, synthetic memory and execution stopped before native services |
| `ap_*.c`, `ap_*.h` | AP message ownership, child setup and cancel-only context components |
| `ap_poll_once.*`, `verify_poll_once.py` | Single zero-wait receive attempt with opaque pointer ownership; no send, payload inspection or live adapter |
| `cp_*.c`, `cp_*.h`, `cp_*.S` | CP control/runtime/retention components; integration incomplete |
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
python dev/precapture/verify_child_exec.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/verify_poll_once.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
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

## 简体中文

本目录是未完成的预拍摄研究，公开工具只做离线验证，没有可安装的预拍摄版本。
代码按“共用工具与原指令夹具、AP／CP 组件、验证与审计入口”分工；重复编译流程
已集中，旧导入名称仍兼容。原固件、机身备份和临时诊断程序保留在私有目录。

半按崩溃的 `00030072` 方案已停用，不能重试。新子进程执行、同步请求的回调生命周期
仍需验证；不能把离线通过当成可以安全上机。后续目标仍是真实预触发曝光、像素保留、
全按存盘、取消释放、正常拍摄和精确还原。任何新写入遵守 AGENTS 中的授权边界。
