# FL23：给 AI 的安装与复现说明

[返回首页](../../README.zh-CN.md) · [English](../en/fl23-ai.md) · [用户安装步骤](fl23.md)

目标是在 Windows 为精确支持的原厂 A7C II 2.01 安装 FL2／FL3，完成双份备份、写入、独立读回、冷加载、拍照／回放和还原。**命令行为主，桌面版为同一后端的替代入口。** 本任务不导入自定义 LUT，也不改 LUT 的设置或资源。

## 1. 从哪里开始

先读 [AGENTS](../../AGENTS.md)、[用户安装说明](fl23.md)、[手动命令](manual.md)和[已有验证范围](technical/validation.md)。仅支持 ILCE-7CM2；版本页面 2.01 之后还要检查完整文件身份。原厂 AP SHA-256 为 `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`，CP 为 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。

Windows 使用含 Tkinter 的 64 位 Python 3.10+；启动器准备本地 `.venv`，GUI 需要 Tkinter，设备依赖见 `src/fl23/requirements.txt`。正常／服务 USB 身份分别为 `054C:0E8A`、`054C:0336`，按用户说明为相机准备 libusbK。Mac USB 没有实测支持结论。

## 2. 已有实现及必须保留的边界

| 源码 | 作用 |
|---|---|
| [app.py](../../src/fl23/app.py) | `Job.prepare/install/verify/restore`：阶段、备份、候选、交易与验收 |
| [gui.py](../../src/fl23/gui.py) | Windows 桌面按钮转发到同一 `app.py` 命令 |
| [core.py](../../src/fl23/core.py) | `ORIGINAL/FINAL`、固定补丁、机身数据合并、保护和原生报告判定 |
| [transport.py](../../src/fl23/transport.py) | `Session`：身份绑定、认证、有界 I/O、未知结果停止、受限临时文件／Backup 写入 |
| [assets/manifest.json](../../src/fl23/assets/manifest.json) | 已编译原生组件及其精确指纹 |
| [native/installer.c](../../src/fl23/native/installer.c) | 固定窗口、大小／inode 保留、mode0 检查／mode1 安装／mode2 还原 |
| [native/wbi.c](../../src/fl23/native/wbi.c) | 已知起点的保留启动镜像检查／失效处理 |
| [tests/test_offline.py](../../src/fl23/tests/test_offline.py) | 机身隔离、占用拒绝、额外设置变化、临时冲突与未知会话测试 |

不要重新推测偏移，或把这里的固定 FL23 worker 用于不同 LUT 清单。保留原生组件字节和服务／写入通道；未知来源应明确诊断，不是放宽哈希的理由。备份只能属于当前机身。

## 3. 离线检查与 Windows 启动

在工具根目录运行：

```text
.\FL23.cmd --check
.\FL23.cmd --setup-only
.\FL23.cmd check-package
```

三者不连接相机。准备环境可能联网安装依赖；已有不完整环境会被保留，不盲目覆盖。直接双击 `FL23.cmd` 则打开桌面版。不要同时运行 GUI 和命令行设备操作。

## 4. 命令行完整步骤

1. 新建本次工作和第二备份目录，最好在不同磁盘，两个均为空；保存原来的工作目录。
2. 执行以下 `prepare`，成功状态必须是 `prepared`，日志确认备份／候选／实机只校验完成。

```text
.\FL23.cmd prepare --workspace "D:/CameraWork-A7C2-01" --backup-copy "E:/CameraBackup-A7C2-01"
```

3. 检查本机身份、双份备份、候选和 native mode0 结果，实际电量至少 50% 且能持续连接。安装命令中的 82 必须换成真实百分比，不能照抄。

```text
.\FL23.cmd install --workspace "D:/CameraWork-A7C2-01" --battery-percent 82
```

4. `installed_pending_cold_start` 与完整读回成功之后，确认所有 I/O 结束，再按用户说明拔除所有外部供电、正常关机、等存取灯熄灭、取电池至少一分钟后开机。核对 FL2／FL3 名称、无快门预览、新照片／回放及原 ST。接回大量存储模式：

```text
.\FL23.cmd verify --workspace "D:/CameraWork-A7C2-01"
```

5. 核对完整程序、保存参数及 AP 运行片段，单独记录用户观察。成功文件读回不等于真实拍摄或所有模式稳定。

## 5. 每段应该发生什么

`prepare` 读取目标程序和完整机身数据，检查原厂来源，合并本机外观参数、检查未占用区域、生成固定候选，两份原档写入及读回核对后执行实机只校验。临时诊断会运行，程序／保存配方尚不安装。

`install` 要求仍是同一机身及 `prepared` 阶段，重新核对程序／目标设置，再执行固定程序窗口、完整读回、目标参数合并保存、无关设置保留检查，以及受条件保护的保留镜像步骤。`verify` 不重复安装，检查重载后的完整文件、目标参数和相应 AP 运行片段。

所有原生模块都应在调用前记录意图，暂存读回后一次调用，按各自 magic／版本／模式／长度／错误／hash 校验结果。失败或超时后会话未知时停止继续发包，不连清理也反复发送。保留 `state.json`、日志、已有原生结果和临时文件，先查本次执行结果。

## 6. 还原与故障处理

只有明确要撤销受支持的本次 FL23 安装，保有本机完整双份备份且当前完整程序可识别时，才按用户说明选择 ST、正常完整重载、接回，再用原工作目录执行：

```text
.\FL23.cmd restore --workspace "D:/CameraWork-A7C2-01" --battery-percent 82
```

这会恢复本次程序和目标参数，不能作为任意循环重启、部分损坏或未知状态的通用恢复。结果未知时先检查已有结果和当前文件，不重发安装／还原。还原完成后同样需要完整读回、重载及实际新照片验证。

## 7. AI 的测试和交付

运行 `python -m unittest discover -s src/fl23/tests -v` 及 `python -m unittest discover -s dev/usb/tests -v`；后者覆盖真实 Windows CMD／PowerShell 5.1／7 转发、中文／空格路径、退出码和 USB 状态边界，设备 I/O 为离线模拟。相机 native 完整启动、安全断电和第二台机身兼容性不能由这些测试代替。

交付命令、退出码、源／目标及双备份哈希、`prepared`／写入／核对阶段、完整读回、保留设置和清理结果、加载检查、用户新照片／回放及还原证据。没有授权或相机可用时停在离线验证并明确剩余实机阶段，不虚构安装成功。
