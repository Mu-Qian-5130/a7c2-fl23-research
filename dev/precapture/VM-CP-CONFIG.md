# Original CP boot configuration and initialization admission

The previous staged fixture omitted the original TOMCO boot configuration.
Its default group0 ran `TOPPERS_KERNEL`, including the1111-entry callback
list, but skipped `PCIDMA_INIT`, `OSAL_UIPC_INIT` and `PCIEIF_INIT`.
Those callback-loop results remain valid **within that narrower scope**;
they do not establish full CP or transport initialization.

The corrected fixture supplies the exact original741-byte `tomco.txt` to
the original parser. It produces group2 naturally. Execution then reaches
an unsupported watchdog-reset register before the later initialization
path. No camera was accessed and no readiness/configuration flag was forced.
Physical pre-capture remains unfinished.

## Original input and parser

The pinned2.01 CP partition has SHA-256
`8700f570aed3eb32038f313590759736a06162f402637518f8078dd51b6f1541`.
Read-only FAT extraction of `/tomco.txt` gives741 bytes with SHA-256
`02b202a9b4fbf7bdcbe93d032bfe475a21859019a3c02d1766ac133a779650d3`.
It matches the extracted asset inventory and the privately staged file.
Neither the original partition nor other VM files are changed.

The original file begins with `[TOMCO]` and `usrrtn_cfggrp=2`; its closing
TOMCO marker is part of the original file. CP routine`0x60cb90` checks the
marker at`0x100000`, tokenizes the input and dispatches option handlers.
Its `usrrtn_cfggrp` handler is`0x634790`.

The fresh guest loads the complete original file at`0x100000` and fully
reads it back before executing the original loader/CP path. After the
native parser returns at`0x601ae4`, its group word at`0x1a9e53c` reads2.
The host never writes that word or calls a fake successful parser.
The file's memory mappings and watchdog options remain intact.
This corrects a staged-input omission; it is not a full physical cold boot.

## Which initialization entries are admitted

The original UIN table contains14 records of20 bytes, with masks tested
by instructions at`0x6349b8`. Its parallel names identify the components:

| Configuration group | Original admission predicate |
|---|---|
| 0, previous fixture default | Only `TOPPERS_KERNEL` |
| 1 |11 entries, including the transport entries |
| 2, original file | All14 entries |

Admission is a mask decision, not evidence that the callbacks executed
or succeeded. The corrected run currently stops before those later calls.

`audit_cp_config_group.py` passes151 original-instruction contracts for
mask admission, the keyword-service boundary, independent post-keyword
results and independent post-conversion stores. It stops before native
services/callbacks. It also checks ARM register-shift edge cases; they
are not permission to choose arbitrary group values. The complete parser
result comes from the separate native guest, not these slices.

```text
python dev/precapture/audit_cp_config_group.py --cp PRIVATE_STOCK_CP --tomco PRIVATE_ORIGINAL_TOMCO --output NEW_PRIVATE_REPORT.json
```

Both source inputs require exact fingerprints. The Sony configuration,
firmware, compiled programs and raw guest reports remain private.

## Next unsupported operation

The first unsupported MMIO is a write32 to`0xf1388344`. Its paused CPU0
state has PC`0x6333cc`, R4=`0xf13883a0`, R5=`0x40000`; the original
instruction is `str r5,[r4,#-0x5c]`.

Sony's [official2.01 kernel source distribution](https://oss.sony.net/Products/Linux/DI/ILCE-7CM2_Ver201.html)
independently defines SCU base`0xf1388000`, reset channel address
`SCU+0x300+(channel<<4)`, timer channel4 and SET offset4. These give the
same address. The native path is entered with the original watchdog
configuration enabled. The current model does not implement that reset
controller/watchdog path; no register-success shim or disabled-watchdog
substitute was used.

The stopped guest was kept through instruction/register/first-fault
qualification. Its evidence was archived and hash checked before explicit
disposal. Timeout alone did not authorize restart or cleanup.
The next work is reset/watchdog semantics, followed by the actual transport
initializers and their peer requirements. No AP/CP receipt, DMA, exposure,
retained RAW, saved pre-trigger photos or physical restoration is proven.

## 简体中文

上一轮夹具漏了原厂TOMCO配置，默认组0只允许TOPPERS_KERNEL。因此1111项回调的
结果只证明该内核初始化路径，不能说PCIDMA／UIPC／PCIEIF已经初始化。
原分区的741字节tomco.txt已只读提取并核对指纹，完整文件作为VM输入，由原CP解析成组2，
没有直接改组号。151项原指令检查独立确认组0只选1项、组2允许14项；允许不等于执行成功。

保持原厂看门狗配置后，下一处缺失设备是f1388344的SCU计时器复位SET访问，PC6333cc、
写值40000与原指令及官方寄存器定义吻合。没有删配置或填成功状态绕过，也没有相机操作。
后续需实现复位／看门狗，再验证传输初始化、对端通信和真实拍摄路径。
