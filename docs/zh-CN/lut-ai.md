# LUT／DCP：给 AI 的完整实施与复现说明

[返回首页](../../README.zh-CN.md) · [English](../en/lut-ai.md) · [用户全流程](custom-lut.md)

**目标：从用户取得的 DCP／LUT 开始，完成选中栏位的实际机内导入、预览、新照片验证及可测试的还原。用户不需要先安装 FL23。** 从原厂 2.01 起步是独立路径；代码复用 `src/fl23` 的通讯／原生写入器源码，不等于运行 FL23 安装，也不允许要求用户先取得研究机身的历史三款状态。

当前 `lut.py` 只提供离线命令；本页给出 AI 必须完成的设备实现及证据要求。先读 [AGENTS](../../AGENTS.md)、[用户全流程](custom-lut.md)、[数据格式](technical/formats.md)、[已知程序布局与哈希](technical/integration.md)、[验证边界](technical/validation.md)和[历史失败](technical/failures.md)。FL23 任务使用[单独的 AI 说明](fl23-ai.md)。

这是给下一位 AI／开发者接手的实现任务书。它覆盖主教程第 7–13 步，包括真正的设备写入。**以下“待实现接口”是开发要求，不是目前 `python lut.py` 已存在的命令。** 不允许通过编造命令、复用另一台机身的设置或直接发送整个固件来假装完成。

## A. 先确定交付路径

| 来源 | AP SHA-256 | CP SHA-256 | 允许的下一步 |
|---|---|---|---|
| 原厂 2.01 | `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b` | `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428` | 实现、审查并测试原厂→自定义运行时适配器 |
| 仅安装 FL23 | `1aaeb8fbe0297950cab454d498d1a5ba874f91542aa2737aae27a73971e324d7` | `60a9de1a0636c7f6b5b98607a4d25eeb48634e25294f632743a6d256e583b370` | 实现、审查并测试 FL23→自定义运行时适配器 |
| 历史三款或当前六款 | 见[来源指纹表](technical/integration.md) | 见[来源指纹表](technical/integration.md) | 调用匹配的现有构建器／换表适配器，再实现设备编排 |
| 其他指纹，包括已经换过色表的六款 | 不自动接收 | 不自动接收 | 读取、比较、审查新的来源登记；旧适配器不自动适用 |

先实现最小可测路径“精确 full7-v4 的选中表更新”，再扩展首次安装。两条路径都需明确交付范围；完成一条不代表另一条完成。当前 `sixbuild.build` 的三款来源本来就已经有运行时补丁，不能把“先装 FL23”当作已经得到这个三款来源。

## B. 现有源码怎么复用

| 组件 | 已实现的入口 | 接手时的工作 |
|---|---|---|
| DCP／CUBE、校准与拟合 | [references.py](../../src/looks/looktool/references.py)、[calibration.py](../../src/looks/looktool/calibration.py)、[native.py](../../src/looks/looktool/native.py) | 保留输入域和校准条件，检查实际拟合结果 |
| 清单和局部更新 | [firmware.py](../../src/looks/looktool/firmware.py)、[six.py](../../src/looks/looktool/six.py) | 复用完整哈希、窗口及逆向约束 |
| 历史三款→完整六款 | [sixbuild.py](../../src/looks/looktool/sixbuild.py) | 只接受已登记的输入，缺原厂适配器时自行实现，不能放宽现有入口 |
| 原生编译输入／报告检查 | [worker.py](../../src/looks/looktool/worker.py) | `prepare_table_worker` 只支持精确六款换表；`validate_worker_report` 按本次契约核对 ABI |
| USB 会话和受限暂存 | [transport.py](../../src/fl23/transport.py) 的 `Session` | 复用身份绑定、超时后停止和暂存能力；保持 FL23 原保护不变 |
| 原生程序写入／还原 | [installer.c](../../src/fl23/native/installer.c)、[sha256.h](../../src/fl23/native/sha256.h) | 用本次动态头重新编译；不能上传固定 FL23 `assets/installer.so` 来执行不同清单 |
| 调用流程参考 | [app.py](../../src/fl23/app.py) 的 `Job.module`、`files`、`audit` | 写独立自定义执行器，不调用其 FL23 `install/restore` 或原样使用其固定目标判定 |
| 保留启动镜像 | [wbi.c](../../src/fl23/native/wbi.c) | 先做通用只读状态探测，满足 mode2 前提才复用失效处理 |
| 私人实物复现测试 | [test_private_reproduction.py](../../src/looks/tests/test_private_reproduction.py)、[test_worker.py](../../src/looks/tests/test_worker.py) | 有合法本地素材就运行；没有时正确跳过，不能伪造实物复现 |

仓库不含原研究目录及私人备份。实现不能依赖研究者机器上的路径、旧授权报告或那台机身的 68 份资源原档。缺少源码的模块按下列协议重新实现并测试，而不是让用户去找不存在于发行包的脚本。

## C. 需要实现的设备接口与阶段记录

下列名称是建议的 Python 接口职责，**不是可直接复制运行的公开 CLI**：

| 待实现接口 | 输入 | 必须输出／检查 |
|---|---|---|
| `prepare_device_job` | 项目、目标机身、新工作和第二备份目录 | 身份、完整文件／设置／资源快照、来源适配器、双份哈希、安装计划 |
| `check_device_job` | 固定计划、编译后的 worker | 新鲜来源及字段前置条件、原生 mode0 结果；不改程序／配方 |
| `install_device_job` | 已校验计划、实际电量 | 单次调用意图、分阶段原生结果和完整读回 |
| `inspect_existing_result` | 失败／未知阶段目录 | 只检查已有请求、worker、原生结果及当前完整文件；不重复执行 |
| `verify_after_reload` | 同一机身、写入报告 | 新启动证据、AP 运行片段、CP 磁盘、配方／保护单元、用户观察 |
| `restore_device_job` | 本次逆向材料、当前目标状态 | 依赖逆序还原、完整读回、加载验收；不是任意机身修复 |

工作目录至少保存 `source/`、`settings/`、`resources/`、`candidate-v1/`、`transition-v1/`、`worker-v1/`、`evidence/` 和阶段日志。写前先在日志落盘“即将调用”的身份、worker 哈希、请求模式及预期来源／目标，再执行一次。发生异常写入 `OUTCOME_UNKNOWN`，不自行改成“失败但未写入”。

建议阶段为 `CAPTURED → BACKUPS_VERIFIED → PLAN_VERIFIED → NATIVE_CHECKED → RESOURCES_COMMITTED → PROGRAMS_COMMITTED → SETTINGS_COMMITTED → HOST_VERIFIED → RELOAD_PREPARED → RELOAD_VERIFIED → PHYSICAL_ACCEPTED`。只换表时将无须执行的资源／设置阶段标明为已验证的跳过；每个阶段带独立产物哈希。只有证据满足时才能推进。

## D. 已有六款的原生 worker：可运行的离线编译示例

先按主教程生成选中表的正向／还原清单，将目标机身的新鲜完整文件放在工作目录 `source/appFw.so` 和 `source/cpapp-b.bin`，绑定文件放在 `bindings.json`。在当前工具根目录，用已装好依赖的 Python 运行下面脚本；另需安装适合主机的 Zig，并让 `zig` 在 PATH 可用。脚本仅接受精确 full7-v4，拒绝原厂、FL23 和其他来源。

把下列代码保存为自己的 `prepare_native_worker.py`，传入工作目录。它只在电脑生成私人编译头、worker 和契约，不会连接相机：

```python
from pathlib import Path
import hashlib
import json
import subprocess
import sys

repo = Path.cwd()
sys.path.insert(0, str(repo / "src/looks"))
from looktool.worker import prepare_table_worker

job = Path(sys.argv[1]).resolve()
read_json = lambda p: json.loads(p.read_text(encoding="utf-8-sig"))
header, contract = prepare_table_worker(
    (job / "source/appFw.so").read_bytes(),
    (job / "source/cpapp-b.bin").read_bytes(),
    read_json(job / "transition-v1/forward.private.json"),
    read_json(job / "transition-v1/reverse.private.json"),
    read_json(job / "bindings.json"),
)
out = job / "worker-v1"
out.mkdir(exist_ok=False)
h = out / "manifest.private.h"
h.write_text(header, encoding="ascii")
worker = out / "transition.so"
native = repo / "src/fl23/native"
command = [
    "zig", "cc", "-target", "aarch64-linux-gnu", "-shared", "-fPIC",
    "-O2", "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
    "-fno-unwind-tables", "-fno-asynchronous-unwind-tables", "-nostdlib",
    "-Wl,--no-undefined", "-Wl,-Bsymbolic", "-Wl,-z,noexecstack",
    "-I", str(native), '-DPATCH_MANIFEST="' + h.as_posix() + '"',
    "-o", str(worker), str(native / "installer.c"),
]
subprocess.run(command, check=True)
contract["worker_sha256"] = hashlib.sha256(worker.read_bytes()).hexdigest()
contract["manifest_sha256"] = hashlib.sha256(h.read_bytes()).hexdigest()
(out / "contract.private.json").write_text(
    json.dumps(contract, indent=2), encoding="utf-8"
)
print("OFFLINE BUILD ONLY; no USB access or camera installation")

```

示例中 `worker-v1` 必须尚不存在。生成头含来源衍生字节，禁止提交 Git。`prepare_table_worker` 会重新构建并比较所选表更新，拒绝对其他区域的改动，验证两份完整清单互逆，以及 JSON 中的 ST 声明；它不能验证真实相机设置。

编译后还需检查 ELF 为 AArch64 ET_DYN、存在 `DT_INIT`、无外部符号和 `DT_NEEDED`、仅允许受支持的本地 RELATIVE 重定位，并运行真实 ELF 的 syscall 故障测试。编译通过还不能进入正式设备写入。程序源码／头／worker 哈希都要绑定到计划，设备调用前再核对。

## E. 真正调用程序写入器的协议

用自定义执行器复用 `Session`，同一时间只开一个服务会话。当前可复用的固定暂存名为 `a7c2-preview-staged.so`、`a7c2.install.request`、`libJit.so`、`a7c2.install.result`；先检查没有先前未处理的内容或预载配置。

1. 将本次 worker 写到暂存名，完整读回并比较字节。
2. 请求为 Python `struct.pack('<8sII', b'A7INS001', mode, 0)`，共 16 字节。mode0 只校验原始来源，mode1 安装，mode2 从本次目标还原到来源。
3. 完整读回请求，持久化调用意图，再**一次性**写入 `libJit.so` 触发本机已有原生加载入口。不要使用 shell、预载配置或 raw flash。
4. 读取并保存 240 字节结果，调用 `validate_worker_report(raw, mode, contract)`。
5. 写入／还原后，独立主机读回完整 `/usr/lib/appFw.so`、`/cp/cpapp-b.bin` 并与对应目标比对；验证 mount、大小／inode、设置保留和清理。

原生报告前 112 字节为 `<8sIIII7q4Q`：magic、version、mode、phase、窗口写入数；status、rollback、remount、readonly、cleanup、euid、pid；AP inode、CP inode、AP size、CP size。之后四段各 32 字节依次为实际操作来源 AP／CP、实际操作目标 AP／CP。接受 magic `A7IRP001`、version1、phase9、所有错误／euid 字段为零；模式、写入数、大小和方向哈希必须符合本次契约。mode0 无目标写入，目标哈希应为零。

程序 worker 自己只允许 `/usr/lib/appFw.so` 和 `/cp/cpapp-b.bin`，保持大小和 inode，逐窗口校验、fsync、完整哈希及只读恢复。它**不**处理资源、Backup 设置、启动镜像和真实拍摄；这些需要独立证据。`src/fl23/core.py` 的固定目标判定也不能原样用于任意新表。

## F. 首次安装必须另外实现的三块

**运行时适配器：**按来源登记原厂或 FL23 的完整 AP／CP；在私有工作目录重建完整目标，只发布自编生成器和小补丁约束。核对 AP 自定选择器与 CP 交接、色表格式／校验、静态照片及实时预览所有入口、加载 text 范围、BSS、分支指令边界。证明存储位置的加载与生命周期，不能只因“那里都是零”就占用。重新使用已成功六款的机制时，仍须证明相对当前来源的完整差异与逆向；不复用失败显示跳板或已撤回通知写法。

**名称资源：**实现 UXC-v7 解析、添加、逆向及原子资源交易。已研究格式以 `b'uxc\x07\0\0\0\0'` 开头，偏移 8 为 `<HHI`，字符串类 kind=8；已验证的 count/index-span 编码为 `count | (((count+1)&~1)<<12)`，索引为从偏移 16 开始的 u16，数据起点按 4 字节对齐；`0xffff` 表示无记录，其他值指向 `data_base + 4*pointer`。记录为 u32 标识、UTF-8、NUL 和对齐填充。旧 ID／文字、16 位索引范围及每种语言／布局都要验证。现有机身使用 68 份资源，六个 label ID 见[已知布局](technical/integration.md)；不要把某个历史阶段的“+64B／固定 count”当作原厂通用转换。选中栏位才用新名，未选栏位保留动态 getter。资源用同文件系统暂存、核对、原子替换和可核对的原档链接，原档保留到物理验收。不要为改名增加未验证的图标库或 RX 段。

**栏位设置：**从新鲜 AP descriptor 和机身设置推导 Backup key，不能抄另一台的整个 Backup。研究来源的 descriptor 表定位为 `0x57c6710 + (attribute-0x14ea)*32`；base attribute=`0x14ea+selector`，八个调整字段 attribute=`0x1520+i*18+selector`，导入 selector 为 slot+9（10–15）。这些是待按精确来源核验的定位线索，不是盲写地址。核对 descriptor ID、类型、长度、`0x02cf` group 和原生 getter 多值交叉结果；只处理所选的 9×N 字段。基础值为 ST；调整从已校准条件对应的新鲜 ST 基线取得，不统一写零。逐字段核对 before、WRITE 后 READ、一次 group SAVE 后核对保存视图。保留未选配方及 CP 单元 `0x02a40000/01/02/0d`；不在 FL23 的 `AP_KEYS` 或 `CP_KEYS` 上整体放宽保护，新增独立、由本次 descriptor 计划限定的设置写入路径。

首次安装依赖顺序是：资源先可读 → 引用它们的程序 → 选中设置 → 完整保存核对 → 启动镜像处理 → 冷载入与物理验收。多个交易不是一个全局原子操作；日志必须能表达“资源已安装、程序失败”等中间状态，提供兼容的阶段还原，不强行推进。

## G. 启动镜像、未知结果和还原

先实现只读探测实际 image mode/backend 与启动证据。现成 WBI worker 预期 mode2 和 `*wbi4`，不能当作接受所有状态的探针；mode0 时只验证已失效状态，不能重跑 mode2→0。对已知 mode2，满足证据门槛后只执行一次 `image_drop=1` 再 `image_mode=0`，核对写入长度、关闭结果、mode0、backend 和这次新产生的 drop 日志。所有读写结束后才请用户完全断电。

未知结果恢复先只读核对已有请求、暂存 worker、240 字节结果和当前完整文件。如果已完成，就补齐读回／清理，不再调用 worker；若部分损坏，固定正向／逆向未必接受，必须按实际状态单独分析。会话超时后不继续发清理包，不能删除不匹配的暂存内容。

只换表且当前完整目标匹配时，mode2 自身再次检查目标再写回原档；mode0 是正向来源检查，不能拿它代替还原目标的预检。首次安装依赖逆序还原：本次设置 → 程序 → 资源，保持每阶段引用关系兼容，并保留用户后续无关修改。恢复不是初始化相机或写回整个旧 Backup。

## H. AI 必须执行的测试和验收

1. 先运行 `src/looks/tests` 与 `src/fl23/tests` 离线套件。新 `test_worker.py` 覆盖错误模式／方向、失败阶段、错误／权限、大小／inode、哈希／长度、未知来源及真实文件的选中表限制。
2. 对新设备执行器做伪设备测试：来源中途变化、第二备份不符、暂存冲突、调用前／后断线、结果已成功但主机超时、未知结果恢复不重发、原生报告损坏、完整主机读回不符、保存设置意外变化、清理失败。
3. 对新编译 worker 执行真实 ELF 的检查／安装／还原、短 I/O、tamper、错误大小、缺文件、坏请求、非 root、读／写／fsync 错误、损坏读回、挂载及只读恢复失败。不能只测 Python mock 或 C 文本。
4. 对资源转换做所有输入布局的 parse→transform→parse→inverse 测试；原子替换故障、原档链接、旧 mmap 以及未选 getter 都需覆盖。新 settings 路径验证字段边界、before 条件、保存和无关设置保留。
5. 经用户授权的实机阶段，先只校验，再分项写入及完整读回；停止所有 I/O 后只请求必要的完整断电。冷加载后核对 AP、CP 磁盘、实际设置／保护单元，并分别收集名称、无快门预览、新照片／回放、原生外观结果。没有直接读 CP RAM 就保留该限制。

最后交付真正存在的设备入口、帮助和操作文档、已测试还原、任务阶段及证据路径。成功只能在实际完成的机身／模式范围内报告。**用户只有 DCP 时，缺少校准或 stock 适配器就是仍需完成的实现任务，不能编造默认校准或只交付一份候选来宣称已写入。**

## I. macOS 支持如何落地，怎样算完成

离线层只安装 `src/looks/requirements.txt`，运行 `python lut.py doctor`、解析／校准／拟合和清单生成；不导入 FL23 安装器、Tkinter 或 USB 库。用原生架构的 Python 和匹配 NumPy／SciPy 验证，路径采用 `/Users/...`、`/Volumes/...`，不要套用 Windows 驱动说明。纯 Python 路由测试不等于真实 Mac 测试。

要做 **macOS 实际写入**，AI 必须另外实现并验证 USB 主机层：

1. 为 Intel／Apple Silicon 确认所用 libusb／PyUSB 依赖和架构；核对真实 USB 枚举、接口认领和释放的错误行为。
2. 在真实 Mac 上先仅测试身份读取、服务身份切换与认证、完整文件读取和有界超时。当前 `Session`／通用 libusb 源码可供移植，但不能从文件存在推断它已在 macOS 可用。
3. 若大量存储接口被系统占用，明确诊断接口／驱动所有权，选用经过验证的用户态访问方案。不能通过忽略认领错误或绕过前置检查宣称支持，也不要求普通用户修改系统安全设置。
4. 在 Mac 上验证请求／结果字节协议、短 I/O、断线／未知结果和恢复不重发。具备本机双份备份、确切来源和原生只校验结果后，再在获得授权的机身做单次安装与完整读回、加载、预览／拍照和还原验收。

在这些步骤通过之前，交付状态必须分别写为“Mac 离线流程可运行／实测情况”和“Mac USB 写入未验证或尚未实现”，不得将 Windows 成功直接沿用。当前公开工具没有可保证 Mac 从原厂一键安装的程序；本页的工作项就是为了让接手 AI 按步骤实现该路径。

## J. 交给用户的最终记录

按[主教程第 7–13 步](custom-lut.md#从转换文件到真正装入相机第-713-步)逐项填写：输入 DCP／LUT、校准来源与误差、目标栏位、机身身份、原厂或已修改来源、备份、程序／资源／设置目标、原生只校验和写入报告、主机读回、加载证据、用户预览／照片回报、还原测试、平台与尚未验证项。只完成离线阶段时明确报告具体阻塞项并保留工作目录。
