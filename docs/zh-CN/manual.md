# Python 命令行：安装与命令参考

[返回首页](../../README.zh-CN.md) · [English](../en/manual.md)

FL23 继续双击 `.\FL23.cmd` 使用原图形界面，完整流程见[FL23 教程](fl23.md)。只有 LUT／DCP 改为根目录的 `lut.py` 命令行，没有 GUI 或 CMD 启动器，也不自动安装依赖。

## Windows

安装 64 位 Python 3.10+，完整解压工具，在含 `lut.py` 的目录打开终端。第一次可以创建新的虚拟环境并安装依赖：

```text
python -m venv .venv-lut
.\.venv-lut\Scripts\python.exe -m pip install -r src/looks/requirements.txt
.\.venv-lut\Scripts\python.exe lut.py doctor
```

`.venv-lut` 已存在时先检查，不覆盖旧环境。后续命令中的 `python`，在这个例子里应换成 `.\.venv-lut\Scripts\python.exe`。环境不用激活，不需要 Tkinter 或调整 PowerShell 执行策略。

## macOS

安装适合主机架构的 64 位 Python 3.10+（Apple Silicon 使用原生 arm64／universal2），完整解压后在工具根目录打开终端：

```sh
python3 -m venv .venv-lut
.venv-lut/bin/python -m pip install -r src/looks/requirements.txt
.venv-lut/bin/python lut.py doctor
```

后续命令中的 `python`，在这个例子里换成 `.venv-lut/bin/python`；文件路径使用 `/Users/...` 或 `/Volumes/...`，不用 Windows 盘符。不要从 Windows 复制虚拟环境。Mac 可运行离线转换、报告和文件检查；FL23 保留原 Windows 启动方式，macOS USB 写入尚未验证。

## 每条命令做什么

下列 `python` 表示装好依赖的解释器；`doctor` 会打印它的实际路径。尖括号或示例路径都要换成自己的文件，不要把整段包含设备写入的命令一口气连跑。

| 命令 | 干什么 | 是否修改相机 |
|---|---|---|
| `python lut.py --help` | LUT 命令帮助 | 否 |
| `python lut.py doctor` | 检查 LUT 所用 Python、平台和依赖；不安装任何东西 | 否 |
| `.\FL23.cmd check-package` | 核对固定 FL23 组件 | 否 |
| `.\FL23.cmd prepare ...` | 读取本机、双份备份、生成候选、原生只校验 | 不安装程序／配方，执行临时诊断 |
| `.\FL23.cmd install ...` | 安装受支持的 FL23 修改，完整读回 | **是** |
| `.\FL23.cmd verify ...` | 重开后检查已安装文件／参数 | 不重新安装 |
| `.\FL23.cmd restore ...` | 用本机受支持备份还原本次 FL23 修改 | **是** |
| `python lut.py ...` | 参考解析、计划、校准、拟合和离线清单 | 否，现有命令不包含设备安装 |

实际 FL23 设备操作按[完整步骤](fl23.md)执行，备份成功才安装，完成后才断电／重新加载。自定义导入按[获取 DCP 到写入的全流程](custom-lut.md)及[AI 实施教程](lut-ai.md)继续；缺少的设备接口需要实现，不存在可以直接调用的 `lut.py install`。

## 六步离线转换命令

```text
python lut.py --help
python lut.py doctor
python lut.py inspect "D:/MyLook/references/look.dcp"
python lut.py plan "D:/MyLook/project.json"
python lut.py check-bindings "D:/MyLook/project.json" "D:/MyLook/bindings.json"
python lut.py calibrate "D:/MyLook/measurements/patches.npz" "D:/MyLook/measurements/response.json" "D:/MyLook/calibration-v1.json"
python lut.py fit "D:/MyLook/project.json" "D:/MyLook/candidate-v1"
python lut.py prepare-transition "D:/MyLook/candidate-v1" "D:/MyLook/source/appFw.so" "D:/MyLook/source/cpapp-b.bin" "D:/MyLook/bindings.json" "D:/MyLook/transition-v1" --layout full7-v4
```

项目 JSON 中的相对路径以该 JSON 所在目录为起点。校准需要真实量测，不使用虚构单位矩阵；输出使用新文件／目录。生成清单只接受精确支持的来源。每项输入、输出和完成标准在[全流程教程](custom-lut.md)逐步解释。

可选程序构建命令需要额外依赖：用同一解释器执行 `python -m pip install -r src/looks/requirements-research.txt`。命令仍是 `python lut.py prepare-six-program ...` 或 `prepare-preview-retry ...`；没有额外的 `--research` 启动标志。真实参数见 `python lut.py --help`。

## Mac 上的离线文件检查和 DCP 使用

`.venv-lut/bin/python src/fl23/app.py check-package` 只核对工具字节，不需要相机和 USB 驱动，不证明 USB 刷写可用。

若只在 Lightroom／Camera Raw 使用 DCP，Finder 选择“前往 → 前往文件夹”，输入 `~/Library/Application Support/Adobe/CameraRaw/CameraProfiles`，复制原始 DCP 后重启应用，选择 A7C II RAW。Windows 对应目录为 `%APPDATA%\Adobe\CameraRaw\CameraProfiles`。这是电脑显影配置，不会写进相机。

## 常见命令行问题

- `python` 找不到：检查 Python 安装，Windows 可用 `py -3`，Mac 常用 `python3`；后续 pip 和工具调用始终使用同一个解释器。
- 依赖缺失：按错误给出的 `-m pip install -r ...` 安装到当前 Python。工具不自动安装、切换环境或重试设备操作。
- 路径含中文或空格：给整个路径加双引号。
- 操作超时、断线或结果未知：保留工作目录和原生结果，检查已有交易；不要重跑写入。
