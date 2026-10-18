# 手动命令

[返回首页](../../README.zh-CN.md) · [English](../en/manual.md)

在解压后的工具目录打开 CMD 或 Windows PowerShell 5.1／7。以下命令与图形界面、AI 使用同一套 Python 后端，**不需要升级 PowerShell、激活脚本或修改执行策略**。

## FL2／FL3

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

## DCP／LUT 离线转换

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

## 启动兼容

`FL23.cmd` 和 `Custom-LUT.cmd` 使用 CMD＋Python，不调用 PowerShell。安装 64 位 Python 3.10+，带 `py` 启动器或可用的 PATH 中 `python`。已有 `.venv` 会保留，不完整／不支持时停止，不会直接覆盖。路径中的空格和中文作为独立参数传递。

Python 装在特殊位置时，可在当前 shell 将 `A7C2_PYTHON` 设为完整 `python.exe` 路径后重试。可选 `dev/windows/Start.ps1` 只是 5.1 兼容入口；若执行策略阻止它，直接使用所选 CMD 入口。
