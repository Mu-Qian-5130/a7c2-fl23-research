# A7C II 工具

[English](README.md) · **简体中文**

适用于 **Sony A7C II／ILCE-7CM2，固件 2.01**，请选择一个入口：

| FL2／FL3 | 自定义 LUT／DCP |
|---|---|
| [进入 FL2／FL3 说明](docs/zh-CN/fl23.md) | [进入自定义外观说明](docs/zh-CN/custom-lut.md) |
| 打开 **`FL23.cmd`**，进行备份、安装、核对和还原 | 打开 **`Custom-LUT.cmd`**，进行离线参考文件和色表处理 |

**[下载最新工具 v2.0](https://github.com/QAQLeonard/a7c2-fl23-research/releases/latest/download/a7c2-tools-2.0.zip?rev=20261018-guides)** · [Release 与校验值](https://github.com/QAQLeonard/a7c2-fl23-research/releases/latest)

提供的启动器和 FL23 设备流程使用 Windows、64 位 Python 3.10+，不需要升级 PowerShell。Mac 用户可用 [Python 离线流程](docs/zh-CN/manual.md#macos)。首次安装依赖需联网；Windows FL23 连接相机还需设置 USB 驱动。

自定义入口可检查 DCP／CUBE、查看 ST 栏位计划、拟合色表和生成精确来源的更新清单，不会自动刷入六款外观，仍需独立的机身工程集成。DCP 是 RAW 配置，不是存储卡固件。

仍属实验项目，不是 Sony 签名更新。[AI 接手](docs/zh-CN/ai.md) · [手动命令](docs/zh-CN/manual.md) · [源码](docs/zh-CN/development.md) · [许可](docs/zh-CN/notices.md)。

[技术验证](docs/zh-CN/technical/validation.md) · [DCP 下载说明](docs/zh-CN/profiles.md)。
