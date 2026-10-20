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

## Follow-up: AP local send/receive/free

A fresh private guest completed an AP self-loop using its own newly allocated
user queue ID for allocation, source, destination, receive and release. The
driver allocated32 bytes; the worker set an opaque test payload, sent once,
called the public `ap_poll_once.c` once with timeout0, checked the received
header/guards and every payload word, then released the received message.
Allocation, send, receive, free, unmap and close returned0; ownership resolved
and the worker exited. The received pointer matched the outgoing pointer.
There was no post-send access until the receive returned caller ownership,
and no payload/header access after free.

This is an AP-local test message, not a CP status response or capture command.
Pointer equality is specific to this self-loop; it is not a requirement for
independently allocated CP replies. Source and receive IDs are equal here,
so this case does not test the different-ID release contract of a CP reply.
It does not exercise `ap_reply_once.c` or qualify a real remote peer.

`audit_send_admission.py` also checks the original driver's missing-transport
branches. With either the transport object or its function absent, the code
logs and returns0. The audit stops before that log, then runs the independent
post-log return instructions; it does not fabricate a successful log/callback.
Thus a zero send result alone cannot authorize CP receipt or context teardown.

## Follow-up: original PCIe transport registration

A separate guest profile disabled AP launch and loaded the original
`pcie-if.ko`. The module load returned0. Read-only QMP samples of actual
kernel memory, with addresses derived from original section offsets and
guest sysfs section addresses, confirmed:

- UIPC's callback slot changed from zero to the PCIe module's actual table.
- Its async/sync entries matched the original module's expected functions.
- The sender initialization signal remained **0**.
- Native high/low PCIe interrupt descriptors were present; both observed
  counters were0 in this run.

The module identities were checked inside the actual boot image. No CP request
was sent, no readiness value was forced, and no native module was unloaded.
The first observer attempt failed on HMP filename syntax before module loading;
its original report remains. The corrected independent run completed, and
the disposable guest was closed.

This verifies registration, not CP startup or working DMA. The underlying
VM still omits parts of normal PCIe/PCIDMA hardware initialization. Table
presence cannot replace a functioning peer, native initialization, firmware
qualification or a matched reply.

`audit_transport_registration.py` separately checks11 original contracts.
UIPC rejects an occupied registration slot, but the PCIe wrapper discards that
return and reports0. UIPC also accepts a nonzero table without validating its
first function. The init signal is stored before wait notifications, and
unregister only clears the pointer. None supplies a peer-drain guarantee.

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

另一次独立测试已跑通 AP 私有队列的32字节本地回环，内容和原生保护字段完整匹配，
接收、释放和退出均通过。它没有连接 CP。原驱动在缺少远端传输回调时也可能返回0，
因此后续不能仅凭发送返回值判断 CP 已收到或安全清理上下文。

原始PCIe模块也已在另一个未启动AP的虚拟机实例中成功装载，内核回调表与原模块
函数地址匹配。但发送初始化标志仍为0，尚无CP握手证据。这次没有发CP请求、
强行改ready标志或卸载模块；注册成功不能代替CP启动、DMA与实际应答验证。
