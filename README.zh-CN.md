# A7C II 工具

[English](README.md) · **简体中文**

用于 **Sony A7C II／ILCE-7CM2 固件 2.01**，按需求选择入口：

| FL2／FL3 | 自定义 LUT／DCP |
|---|---|
| [安装与还原](docs/zh-CN/fl23.md) | [获取 DCP → 写入：全流程与 AI 实施](docs/zh-CN/custom-lut.md) |
| 优先用 **`.\FL23.cmd --help`**；双击 `FL23.cmd` 打开桌面版 | 运行 **`python lut.py --help`**，使用跨平台离线命令行 |

**[下载当前工具 v2.0](https://github.com/QAQLeonard/a7c2-fl23-research/releases/latest/download/a7c2-tools-2.0.zip?rev=20261018-project-guides)** · [Release 与校验值](https://github.com/QAQLeonard/a7c2-fl23-research/releases/latest)

[安装依赖和 Windows／macOS 命令](docs/zh-CN/manual.md)。FL23 保留原启动器、界面和安装流程；仅 LUT／DCP 使用纯命令行，需 64 位 Python 3.10+，不依赖 Tkinter 或 CMD。

`lut.py` 现有命令负责转换和清单。全流程教程提供实际写入／读回／加载／还原的 AI 实施方法，并标明待实现组件。Mac 可运行离线 LUT 处理，USB 写入尚未验证。项目仍属实验研究，不是 Sony 签名更新。

[AI 接手](docs/zh-CN/ai.md) · [开发维护](docs/zh-CN/development.md) · [验证记录](docs/zh-CN/technical/validation.md) · [DCP 参考](docs/zh-CN/profiles.md) · [许可](docs/zh-CN/notices.md)
