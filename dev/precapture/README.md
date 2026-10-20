# A7C II pre-capture research

This is an unfinished research implementation, **not a working pre-capture
feature or an installer**. All public commands here run offline.

## Current state

- A real half-press experiment using CP parameter `00030072` crashed and
  restarted the camera. That approach is retired; do not repeat it.
- Native wait0 message allocation/cancel worked on one body. No pre-trigger
  exposure, retained pixels or saved pre-trigger photograph has been proven.
- The isolated file/process child returned a setup error (`EINVAL`), then
  exited. Its temporary files were cleaned and complete AP/CP files matched
  the state before that diagnostic. Standalone execution is still unproven.
- The camera subsequently held a separate native-photo calibration trial.
  The older six-look CP fingerprint is an offline reference, **not the current
  camera source**. Existing CP observer candidates must reject the newer file.

The next implementation dependency is a verified isolated process/native
context with correct source binding and terminal recovery. Direct RPC can
wait indefinitely. The old log/DMA path also has unresolved callback lifetime.
Neither belongs in an AP loader constructor.

## Code map

| Files | Purpose |
|---|---|
| `support/` | Shared ELF/ISA checks, pinned references, UIPC fixtures and service boundaries; no camera access |
| `ap_probe_once.*`, `ap_rpc_probe_once.*`, `ap_transport.c` | AP message components and explicit ownership states; no live binding or installer |
| `ap_child_exec.*`, `verify_child_exec.py` | Child-only descriptor/exec setup with per-step error evidence; no parent launcher or live entry |
| `cp_*.c`, `cp_*.h`, `cp_*.S` | CP control, runtime, backend and release/retention components; integration remains incomplete |
| `offline_codec.c`, `capture_gate.c`, `s1_trigger.c`, `frame_route.c`, `deferred_queue.c`, `retention_policy.c` | Protocol and frame-policy primitives |
| `verify_*.py` | Component models and original-instruction comparisons |
| `audit_*.py`, `trace_*.py`, `decode_cp_blog.py` | Original firmware evidence and trace decoding |
| `cp_probe_reply.py` | Exact-source, uninstalled observer **review** builder; not a deployment tool |
| [CONTROL-PATHS.txt](CONTROL-PATHS.txt) | Detailed findings, boundaries and failure evidence |
| [history/implementation-notes.txt](history/implementation-notes.txt) | Old chronological notes; source identities and commands can be obsolete |

Shared helpers live in `support/`, rather than being implemented inside a
verifier and imported by other checks. Old exported helper names remain for
private evidence replays. Keep executable C/S sources beside their verifiers
so existing source paths and compilation commands still work.

## Offline checks

Install Python packages `unicorn`, `capstone`, `pyelftools`, and `keystone-engine`.
Compiled component checks additionally require an explicit Zig compiler path;
the current reference build uses Zig 0.13. Inputs must be exact private
originals matching each tool's fingerprints. Generated outputs stay private.

```text
python dev/precapture/verify_support.py
python dev/precapture/verify_child_exec.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/audit_child_kernel.py --kernel PRIVATE_ORIGINAL_KERNEL --output NEW_PRIVATE_REPORT.json
python dev/precapture/verify_ap_rpc_probe.py --uipc-kernel PRIVATE_UIPC_MODULE --uipc PRIVATE_UIPC_LIBRARY --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
python dev/precapture/audit_native_rpc.py --uipc-kernel PRIVATE_UIPC_MODULE --pcie PRIVATE_PCIE_MODULE --output NEW_PRIVATE_REPORT.json
python dev/precapture/verify_offline.py --firmware-root PRIVATE_FIRMWARE_FOLDER --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

The firmware folder for donor comparisons contains `a1ii-4.00/components/`
and `a7c2-2.01/components/`. Each command's `--help` describes its inputs.
No offline pass, inverse manifest or full file readback establishes camera
boot safety, live CP execution or working pre-capture. See [AGENTS.md](AGENTS.md)
before continuing device work.

The child setup verifier distinguishes directory-open/read/validation/close,
descriptor-close and exec errors. Its30 explicit syscall models are not real
exec evidence. A returned `EINVAL` never causes a fallback/retry; only
`ENOSYS` permits one same-FD fallback. It consumes a zeroed result once and
uses a caller-owned4KiB workspace, avoiding new inherited-stack allocation.

The pinned cached kernel audit checks24 syscall/exec/directory/mm boundaries.
It supports `execveat` with `AT_EMPTY_PATH`; that does not prove our executable
has run. `get_task_mm` and the fork branch establish that the UIPC owner's
task+2d8 field is an mm identity on this reference kernel. A post-exec child
needs its own context. These cached instructions are not a live kernel read.

## 简体中文

这里仍是未完成的预拍摄研究，没有可用的预拍摄安装包。公共命令只做离线验证。
公共代码按“共用验证工具、AP／CP 组件、原固件审计”划分；旧进展记录放入 `history/`。
已移除旧的强制原生预读方案生成器，避免再使用导致半按崩溃的方向。

最近一次临时子进程未完成自测，已确认退出并清理；相机保留另一轮色彩标定程序。
旧 CP 诊断候选不能直接用于当前相机。后续仍需完成真实预触发曝光、像素缓存、
全按存盘、取消释放、普通拍摄与精确还原的实机验证。
