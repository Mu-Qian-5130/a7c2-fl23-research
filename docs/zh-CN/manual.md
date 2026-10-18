# 手动命令

[返回首页](../../README.zh-CN.md) · [English](../en/manual.md)

提供的启动器和 FL23 机身操作使用 [Windows](#windows)；Mac 用户使用下方 [macOS](#macos) 的 Python 离线流程。

## Windows

在解压后的工具目录打开 CMD 或 Windows PowerShell 5.1／7。以下命令与图形界面、AI 使用同一套 Python 后端，**不需要升级 PowerShell、激活脚本或修改执行策略**。

### FL2／FL3

```text
.\FL23.cmd --check
.\FL23.cmd --setup-only
.\FL23.cmd check-package
.\FL23.cmd prepare --workspace "D:\CameraWork" --backup-copy "E:\CameraBackup"
```

前三条不连接相机，准备环境时可能联网安装依赖。`prepare` 会连接相机、运行临时诊断、备份本机并核对精确来源，不安装程序改动。工作／备份目录要用两个新空白目录，旧目录保留。驱动及准备条件见[安装说明](fl23.md)。

准备成功、相机持续连接且供电充足后，再单独运行：

```text
.\FL23.cmd install --workspace "D:\CameraWork" --battery-percent 82
```

82 只是例子，请填实际电量，至少 50%。这条会写入相机，不要与备份命令连起来一口气执行，不要在结果未知时重跑，也不要读写中拔线。工具结束后按提示正常断电，检查 FL2／FL3 及 ST 拍照／回放，再接回执行：

```text
.\FL23.cmd verify --workspace "D:\CameraWork"
```

只有明确要还原这次受支持的 FL23 安装，且保有本机已核对的工作目录及受支持来源时，才使用还原命令；它不是通用报错处理：

```text
.\FL23.cmd restore --workspace "D:\CameraWork" --battery-percent 82
```

### DCP／LUT 离线转换

```text
.\Custom-LUT.cmd --setup-only
.\Custom-LUT.cmd inspect "D:\Profiles\profile.dcp"
.\Custom-LUT.cmd plan ".\src\looks\examples\six-looks.json"
.\Custom-LUT.cmd check-bindings "D:\MyLook\project.json" "D:\MyLook\bindings.json"
.\Custom-LUT.cmd calibrate "D:\MyLook\patches.npz" "D:\MyLook\response.json" "D:\MyLook\calibration.json"
.\Custom-LUT.cmd fit "D:\MyLook\project.json" "D:\MyLook\candidate-v1"
.\Custom-LUT.cmd prepare-transition "D:\MyLook\candidate-v1" "D:\MyLook\appFw.so" "D:\MyLook\cpapp-b.bin" "D:\MyLook\bindings.json" "D:\MyLook\transition-v1" --layout full7-v4
```

这些都不连接相机。需要真实量测的校准、精确来源的私人固件及新鲜 ST 绑定证据；不能用单位矩阵伪装量测来让命令通过。输出使用新目录，格式见[数据格式](technical/formats.md)。

程序构建还需使用 `Custom-LUT.cmd --research ...`，通过 `Custom-LUT.cmd --research --help` 查看命令。生成清单不代表装进相机；公开的一键“原厂到六款”安装、名称／设置／设备集成尚未实现。AI 和手动用户都应在此停止，不能拿 FL23 安装器当自定外观刷写器。

### 启动兼容

`FL23.cmd` 和 `Custom-LUT.cmd` 使用 CMD＋Python，不调用 PowerShell。安装 64 位 Python 3.10+，带 `py` 启动器或可用的 PATH 中 `python`。已有 `.venv` 会保留，不完整／不支持时停止，不会直接覆盖。路径中的空格和中文作为独立参数传递。

Python 装在特殊位置时，可在当前 shell 将 `A7C2_PYTHON` 设为完整 `python.exe` 路径后重试。可选 `dev/windows/Start.ps1` 只是 5.1 兼容入口；若执行策略阻止它，直接使用所选 CMD 入口。

## macOS

### 准备 Python

下载并解压同一份 v2.0 工具包，在含有 `src`、`docs` 和 `FL23.cmd` 的解压目录打开终端。`.cmd` 和 `src/launcher.py` 是 Windows 启动器，Mac 直接调用 Python。

从 [python.org](https://www.python.org/downloads/macos/) 安装当前的 64 位 Python 3.10+。Apple Silicon 使用原生 arm64 或 universal2 Python，依赖也使用相同架构。检查解释器，创建一个**新的** Mac 环境：

```sh
cd "$HOME/Downloads/a7c2-tools-2.0"
python3 --version
python3 -m venv .venv-macos
.venv-macos/bin/python -m pip install -r src/looks/requirements.txt
```

如果 `.venv-macos` 已存在，先保留并检查再决定是否复用，不要把 Windows 的 `.venv` 复制到 Mac。下方命令都在工具根目录执行，显式使用虚拟环境，不需要激活脚本、Homebrew、`sudo` 或修改执行策略。

### DCP／LUT 离线操作

```sh
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool --version
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool inspect "$HOME/Downloads/Profiles/profile.dcp"
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool plan "src/looks/examples/six-looks.json"
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool check-bindings "$HOME/MyLook/project.json" "$HOME/MyLook/bindings.json"
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool calibrate "$HOME/MyLook/patches.npz" "$HOME/MyLook/response.json" "$HOME/MyLook/calibration.json"
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool fit "$HOME/MyLook/project.json" "$HOME/MyLook/candidate-v1"
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool prepare-transition "$HOME/MyLook/candidate-v1" "$HOME/MyLook/appFw.so" "$HOME/MyLook/cpapp-b.bin" "$HOME/MyLook/bindings.json" "$HOME/MyLook/transition-v1" --layout full7-v4
```

把示例输入路径换成自己的文件，输出使用新目录。示例 `plan` 不需要 DCP 已存在；其他命令仍需前文所述的量测校准、精确来源和 ST 绑定证据。项目路径使用 Mac 格式（`/Users/...` 或 `/Volumes/...`），相对路径仍相对于项目 JSON。这些命令都不连接相机。

图形界面可选，需要 Python 自带 Tkinter：

```sh
.venv-macos/bin/python src/looks/gui.py
```

若提示缺少 `_tkinter`，使用命令行，或安装带 Tk 支持的 Python。只有程序构建命令才需额外安装 `src/looks/requirements-research.txt`，仍按相同 `PYTHONPATH` 前缀调用 `python -m looktool`；Windows 启动器的 `--research` 不是 looktool 参数。汇编／模拟依赖必须支持所用 Python 和 macOS 架构。

### FL23 文件检查与机身安装

下面只检查包内组件，不需要 USB 驱动，也不连接相机：

```sh
.venv-macos/bin/python src/fl23/app.py check-package
```

当前 Release 尚无经验证的 macOS 机身备份／安装／还原流程。随包的历史 macOS 驱动源码没有接入本工具的服务通讯，不能据此认定支持当前 macOS 或 Apple Silicon。设备操作使用 [Windows FL23 流程](fl23.md)；Mac 文件检查成功不等于 USB 刷写已验证。本项目尚未在真实 Mac 硬件上测试这些操作。

### 在 Lightroom／Camera Raw 使用 DCP

Finder 选择**前往 → 前往文件夹**，输入 `~/Library/Application Support/Adobe/CameraRaw/CameraProfiles`。没有该目录时新建，将原始 `.dcp` 复制进去，重启 Lightroom／Camera Raw，选择 A7C II RAW 后使用。`~` 表示当前用户目录；这是电脑端 RAW 配置安装，不会写入相机。
