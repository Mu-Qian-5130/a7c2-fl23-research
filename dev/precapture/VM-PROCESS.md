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

## Follow-up: initialization and unimplemented hardware

The existing lab's catch-all bus shim returns `0xffffffff` for missing MMIO
and absorbs writes. Polling a ready bit against that value cannot establish
hardware readiness. An independently relinked private QEMU adds `legacy`,
`zero` and `fault` controls over the source-qualified PHY/controller windows.
Twelve firmware-free EL1 instruction tests cover read/write in both windows.
Fault mode produces actual synchronous external aborts with exact FAR and
read/write syndrome. It is a negative control, not a PCIe hardware model;
unselected devices still have the lab's existing behavior.

With fault mode active, separate guests boot the unchanged Sony kernel while
allowing both original PCIe/PCIDMA initialization wrappers. All five native
DMA pointers are statically nonzero even when their virtual addresses are
unmapped. Adding the missing virtual-I/O ranges makes all five translations
correct. It does not implement their devices. Native wrappers return0 and
DMA IRQ descriptors appear, but the controlled ranges receive no accesses.

Another guest combines those mappings/initcalls with original `pcie-if.ko`
loading. Native registration again matches the callback table/functions;
its sender initialization signal remains0. No AP or CP request is launched,
no readiness value is forced, and there is no module unload. Retained native
DTB host/endpoint nodes are disabled; the VM uses a generic PCI host. Native
role/fixup behavior and actual CP-core startup remain unresolved. Pointer
presence, mappings, init return0 and registration are separate observations.

## Follow-up: actual GPIO startup condition

`audit_transport_startup.py` checks28 original module/kernel contracts. After
its interrupt-output call, module startup reads GPIO **port17/bit4**. It calls
`pcieif_snd_init_done` only when the getter returns0 and the value equals1.
IRQ92 also reaches that initializer before receive/send processing; IRQ91's
first handler boundary is receive processing. Source checks stop before GPIO
access, IRQ operations and thread notifications. Independent post-getter
inputs exercise the exact conditional without fabricating a native return.

A fresh no-AP guest then samples original kernel state before and after loading
`pcie-if.ko`. Port17 is registered at `0xfffffffff102e000`; its input register
translates to physical `0xf102e010`. Both actual snapshots contain0, including
bit4, and the sender signal remains0. Module table/functions still match.
These are the VM's register-backing values, not a physical CP signal. No input
bit, initialization flag or IRQ was forced. A missing register mapping is
therefore not the immediate explanation in this guest; peer behavior is absent.

`audit_cp_exec_mode.py` separately checks105 loader/CP contracts. The loader's
`0xfa0173` lookup supplies the destination pointer for its EXEC_MODE word.
Its low byte is1 only for raw context mode1 with bit2 clear; CP uses that byte
to choose the alternate text source `0xd0220000` versus its existing source.
Byte1 comes from context bit0. That bit's producer calls a GPIO strap helper
whose port/bit are obtained through backup IDs `0xf909d5` / `0xf909d6`.
Negative lookup results or a configured `-1` take the helper's zero path;
positive lookup sizes are also accepted. The real configuration/load/log calls
remain unexecuted boundaries. No live strap values are inferred from these IDs.

The CP consumer at `0x108974` polls byte `0x03e42001`: original instructions
repeat for the generated nonzero byte and return for zero, without changing
the input. A host copy into independent CP test RAM checks the encoding only.
The actual AP destination, cross-core physical alias, production of the real
strap/input, full startup and peer reply remain unresolved. This does not
justify clearing a wait byte, raising a GPIO or marking the CP ready.

```text
python dev/precapture/audit_transport_startup.py --pcie PRIVATE_PCIE_MODULE --kernel PRIVATE_KERNEL_IMAGE --output NEW_PRIVATE_REPORT.json
python dev/precapture/audit_cp_exec_mode.py --loader PRIVATE_NOR_LOADER --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_REPORT.json
```

## Follow-up: continuous controller under the original kernel

[vm/workflow_guest.c](vm/workflow_guest.c) links the unchanged
`capture_workflow.c` and `frame_route.c` with file-only **virtual** actors.
The static AArch64 executable's hash is verified inside a fresh no-AP guest
before execution. Eight transactions run on the original `4.9.337-scel+` kernel:

- Pre-trigger selection excludes expired frames and frames at/after S2;
  queued late frames enter before the virtual terminal fence.
- Save → cancel → save rearms the same state with increasing generation and
  action tickets. Releasing S1 after S2 preserves the selected saves.
- Capacity pressure rejects caller-owned references without overwriting held
  pixels; an ineligible synthetic frame never transfers ownership.
- Cancellation before start prevents readout. Full press before an in-flight
  start completion leads through stop/fence/save/restore.
- Even leases are consumed by the virtual writer; odd leases need a separate
  release. Every transferred reference is released exactly once.

All 71 action lifecycles finish. Eight 32×16 16-bit PGM files pass guest
fsync/reopen/content checks. The child exits0 and its `/proc` entry is absent.
After export, a separate host verifier checks every pixel against an independent
formula, action ordering, the exact saved set and release accounting. All files
and journals match a host execution byte for byte. Six corruption cases—pixel
change, missing completion, duplicate request, duplicate application, unexpected
file and duplicate transferred offer—are rejected.

To build this file-only test from the repository root using Zig0.13:

```text
zig cc -target aarch64-linux-musl -O2 -g -static -Wall -Wextra -Werror dev/precapture/vm/workflow_guest.c dev/precapture/capture_workflow.c dev/precapture/frame_route.c -o PRIVATE_DIRECTORY/workflow-guest.elf
```

Run it **inside a disposable Linux VM**, using a new output directory:

```text
/simulation/workflow-guest.elf --virtual-only /tmp/NEW_WORKFLOW_DIRECTORY
```

Export only that directory's two text files and eight PGM files to a private
host folder, then verify it:

```text
python dev/precapture/vm/verify_workflow_guest.py --run-dir EXPORTED_FOLDER --output NEW_PRIVATE_REPORT.json
```

The verifier checks artifacts; it cannot attest their execution origin. The
private VM run separately records kernel/ELF/source hashes and process termination.
This executable includes a static libc and is a guest test, not an integer-only
ROM payload or installer. Virtual metadata is synthetic input to the admission
guard, not evidence of a qualified native frame. No original sensor, CP RPC,
RAW-reference method, recording writer or native completion is substituted with
a successful return. Guest tmpfs is not an SD card. Native camera bindings and
physical pre-capture remain incomplete; no camera was used in these tests.

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

进一步检查发现虚拟机未实现的寄存器原来会返回全1，不能把轮询成功当作硬件就绪。
新加的独立负对照能让选定寄存器访问真实触发总线异常，12项无固件指令测试通过。
原厂PCIe／PCIDMA初始化及5路DMA地址映射已在独立来宾中接回；原模块也能注册，
但初始化没有访问这些硬件窗口，发送初始化标志仍为0，未建立CP通信。

同一连续控制器现已在原厂内核虚拟机里实际跑完8组事务，生成8张虚拟图像、记录
71次动作的发出／执行／完成，保存、取消、重用、迟到帧及逐项释放均通过。程序退出，
导出图像与日志和电脑端逐字节一致；6组故意损坏的材料均被独立校验器拒绝。
这是控制逻辑与内核文件操作的连续验证，曝光／像素／服务回执属于显式虚拟设备；
尚未接通真实传感器、CP、RAW引用和原生写卡接口，因此实机预拍摄仍未闭环。

启动条件进一步定位到原模块读取GPIO17/bit4：读取成功且值为1才通知发送线程。
独立来宾已确认这个端口及地址映射存在，但模块加载前后实际输入位均为0，发送标志
也为0。28项模块／内核原指令合同通过，没有强行修改GPIO、ready或IRQ。

另105项检查把CP早期EXEC_MODE等待字节追到加载器的配置GPIO读取：端口／位来自
备份ID f909d5／f909d6，context bit0进入模式字第二字节，CP原指令据此等待或返回。
测试只在独立RAM间复制编码；真实配置、物理地址别名及CP完整启动仍需继续验证。
