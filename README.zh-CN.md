# A7C II 工具

[English](README.md) · **简体中文**

用于 **Sony A7C II／ILCE-7CM2 固件 2.01**，按需求选择入口：

| FL2／FL3 | 自定义 LUT／DCP |
|---|---|
| [安装与还原](docs/zh-CN/fl23.md) | [八步：从参考文件到相机](docs/zh-CN/custom-lut.md) |
| 优先用 **`.\FL23.cmd --help`**；双击 `FL23.cmd` 打开桌面版 | **`python lut.py import "look.dcp" --name "Classic Neg." --slot 1`** |

**实验预发布：[v2.1-preview.2](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.1-preview.2)。** Main 仍只保留 FL23 v1.0；LUT 源码位于 `feature/lut-device-import`。

在预发布页面下载单文件 `lut.py` 或完整工具包，原始 DCP 另有独立附件。[FL23 v1.0 下载](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v1.0)。

[安装依赖和 Windows／macOS 命令](docs/zh-CN/manual.md)。FL23 保留原启动器、界面和安装流程；仅 LUT／DCP 使用纯命令行，需 64 位 Python 3.10+，不依赖 Tkinter 或 CMD。

LUT 已实现转换、备份、真实写入／完整读回、重载检查和还原，不依赖 AI 或预先安装 FL23。已在一台 Windows 相机上通过既有六款版本的单槽更新、预览／拍照及单文件重载验证。原厂首次导入和 Mac USB 尚未实测。默认映射是共用单场景近似，不保证完整 DCP 还原，也不是 Sony 签名更新。

[AI 接手](docs/zh-CN/ai.md) · [开发维护](docs/zh-CN/development.md) · [验证记录](docs/zh-CN/technical/validation.md) · [DCP 参考](docs/zh-CN/profiles.md) · [许可](docs/zh-CN/notices.md)
