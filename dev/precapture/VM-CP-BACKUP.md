# Original factory-table binding in the staged CP guest

The later [DFS follow-up](VM-CP-DFS.md) qualifies original register sequences
and records the scope/limits of the inferred protocol used after this stage.

The missing table from the [I2C stage](VM-CP-I2C.md) now binds through the
original CP code using an exact original factory image. The guest passes
the former null-pointer boundary and reaches a new unsupported hardware
write. Complete initialization, AP/CP receipt and physical pre-capture
remain unverified. No camera was accessed.

## Input qualification

[audit_cp_backup_binding.py](audit_cp_backup_binding.py) accepts only the
pinned stock2.01 CP and the existing exact factory-image fingerprints in
[support/backup.py](support/backup.py). It independently checks both BK4
headers, lengths, table bounds and checksums. The first image's declared
address is`0x04000000`; rounding its total size to a4KiB boundary gives
`0xed000`, the second image's exact offset. The file ends at that second
image's declared end. No padding, table content or pointer is synthesized.

```text
python dev/precapture/audit_cp_backup_binding.py --cp PRIVATE_STOCK_CP --factory PRIVATE_EXACT_FACTORY_IMAGE --output NEW_PRIVATE_REPORT.json
```

Original instruction slices execute the primary binder`0x55df9c`, optional
table-size lookup`0xbe9bd4`, provider`0xbe9c64` and secondary binder`0x55e014`.
Both binders return0; the original provider returns`0x040ed000`. All factory
bytes remain unchanged through these slices. Modified CP/image bytes and
truncated images are rejected. These slices do not execute a full boot.

The image is an original factory configuration, **not a fresh backup or
identity of the current six-look camera**. It is a staged laboratory input;
it must not be uploaded to a camera or described as physical restoration.
The physical loading process and body-specific configuration are unqualified.

## Native guest evidence

The independent guest retains the previous original loader/CP/TOMCO,
four CPUs, group2, watchdog configuration and absent peer/device profiles.
It loads the same immutable factory file at its declared`0x04000000` as
well as the older loader-reader fixture address. Full guest readback before
execution matches the original file's hash at both locations.

The original `BACKUP_INIT` runs and both binder returns are observed with
R0=0. The resulting pointer words at`0x1a7e85c` are:

```text
04000000 04000100 04001432 040ed000 040ed100 040ee432
```

These are original guest stores, independently matching the instruction
audit; no debugger write forces a table pointer. PCIDMA/UIPC/PCIEIF return
observations remain, and the other-chip trigger byte was0 at the PCIEIF
return boundary. No native eDMA copy or positive peer response is supplied.

Continuation reaches write32`0xf1388f4c`, then the strict bus model faults.
A separate fresh guest stops **before** the write at Thumb PC`0x595cfc`:
R0=`0xf1388f4c`, R1=`0x101`, original opcode`0x6001` (`str r1,[r0]`).
The register's meaning and required behavior remain unqualified. Neither
accepting the write as RAM nor returning a ready value is an implementation.
Full group2 UIN return is not yet established.

The faulting guest was retained through source/first-fault/independent
watchpoint qualification, then archived and hash-verified before explicit
disposal. The watchpoint guest exits at its declared boundary. Original
models/firmware and other conversations' guests remain untouched.

The next work is the source-defined behavior of that hardware access and
native peer signaling. Pre-trigger exposure, bounded retained pixels,
S2 save/cancel, ordinary shooting and exact physical restoration remain open.
Compiled diagnostics, factory bytes and private operators are not published.

## 简体中文

原厂BK4文件头声明的地址、两段布局和校验和已核对；把原文件加载到独立虚拟机后，
原CP的两段绑定都返回0，原来的空指针障碍已越过。没有造表，也没有强行改表指针。

这份文件是已知原厂配置，不是当前机身的六款滤镜备份，不可拿去写相机。
下一处是`0xf1388f4c`写`0x101`，已在原指令执行前独立核实，寄存器含义仍待研究。
完整原生初始化和实机预拍摄闭环仍未完成；本阶段没有相机操作。
