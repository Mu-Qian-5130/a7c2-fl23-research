# Sony-kernel VM process test

On October 21, 2026, a separate instance of the existing
[a7c2-re QEMU lab](https://github.com/chocotan/a7c2-re) ran the public
`ap_child_exec.c` component under the original Sony ARM64 kernel and native
AP menu process. This is an actual guest-kernel execution, separate from
the Unicorn component models.
The launcher is a guest-shell child; the AP is running independently. This
does not test creation of a child from inside the native AP service.

The completed run established:

- Guest kernel: `4.9.337-scel+`, AArch64; native `im.elf` was running.
- Static launcher and payload bytes matched their SHA-256 values inside the
  guest before execution. Neither binary needs a dynamic interpreter.
- The child component closed **5 inherited descriptors** and executed the
  payload through its pinned executable FD path.
- The new image observed **0 inherited descriptors**, read the exact 64-byte
  test input, and returned matching nonce and content checksum evidence.
- The shell received successful completion and `/proc/PID` confirmed the
  child was gone. The result was collected before destroying the guest.

The first three runs retain their original failed harness reports: BusyBox
did not provide `sha256sum`, `od` or `ps`. Dedicated read-only collection
helpers and a shell-only terminal check resolved those harness dependencies.
The fourth fresh run passed every stage. Earlier reports were not rewritten.

Only disposable guest `/tmp` files were written. No USB, physical card, block
device or networking was passed through. Original assets were read-only;
the guest image and run directory were private copies. Other VM sessions and
the sealed camera diagnostic job were not used or modified. Compiled tests,
Sony assets, private host operators and full reports remain private.

This verifies file/exec/descriptor behavior in that VM. It does not establish
camera-side child creation from AP, asynchronous peer/context lifetime, CP startup,
sensor exposure, retained RAW ownership, actual photographs or camera safety.
Successful exec does not identify whether `execveat` or its allowed `ENOSYS`
fallback performed the final image replacement; that route was not traced.
Preflight checks hash privately staged guest files before opening the pinned
FD. This controlled-file harness does not replace concurrent-tamper-resistant
FD admission required by the eventual camera operator.

## Follow-up: isolated UIPC allocate/cancel

The public `ap_ipc_context.c` and `ap_probe_once.c` now also pass a real
post-exec guest-kernel test with the original `osal_uipc.ko`. Its exact SHA-256
was checked in the actual initramfs, and the VM's transport-error replacement
module was not requested. No successful driver responses were mocked.

The worker completed six lifecycle syscalls and three driver ioctls:

| Operation | Observed result |
|---|---|
| Path stat, open, FD stat | Same character device; descriptor0 was valid |
| Local context query | 2 MiB shared area and expected pool sizes; a fresh opaque user queue ID |
| Shared mapping | Returned a valid, aligned mapping |
| One wait0 allocation | Native16-byte packet with matching allocator header/guards |
| One cancellation/free | Returned0; **no send attempt** |
| Unmap, close | Each attempted once and returned0 |
| Process completion | Ownership NONE; worker absent in `/proc` |

This establishes the never-sent allocation/cancel case in that VM. It does
not authorize the same teardown after sending: a matched reply, empty poll,
or successful close is not a peer-quiescence proof. The retained-UNKNOWN path
remains in the component and test worker; this successful run did not exercise
an unresolved native outcome. CP receipt, native AP child creation, capture
and camera-side operation remain unverified.

## 简体中文

已用独立原生相机虚拟机实际执行诊断子进程：关闭 5 个继承描述符，经固定 FD
执行新程序，新程序检测到 0 个遗留描述符，64 字节文件内容、nonce 与校验值
匹配，随后确认子进程已退出。它验证了原厂来宾内核中的这段文件／执行流程。

原有相机诊断封存包未动，实机没有操作。真实 AP 子进程创建、IPC／CP、传感器、
RAW 保留和拍摄存盘仍未完成，不能把本测试当作实机预拍摄或上机安全验证。

后续已用原始 UIPC 驱动完成独立上下文的实际建立、查询、共享映射、一次分配／
取消、解除映射与关闭，各阶段返回0。消息没有发送，子进程退出后确认已消失。
它验证的是这一个未发送消息的生命周期，不能据此关闭已有请求在途的上下文，
也不能当作 CP 已接收请求或预拍摄已经完成。
