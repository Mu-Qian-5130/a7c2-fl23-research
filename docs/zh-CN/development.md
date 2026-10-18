# 开发维护与仓库结构

[返回首页](../../README.zh-CN.md) · [English](../en/development.md)

维护同一个 `main`：FL23 保留原 Windows 入口，LUT 使用独立 Python 命令行。开发分支用于改动，标签用于 Release。

```text
README.md / README.zh-CN.md  英文／简体中文首页
FL23.cmd                   原 FL23 Windows 图形界面／设备命令
lut.py                     跨平台 LUT 命令行
src/
  fl23/                     安装器、固定原生组件和通讯程序
  looks/                    转换、精确来源适配器和测试
  launcher.py               原 FL23 Windows 启动器
docs/
  en/                       英文说明；technical/ 存放实现与证据
  zh-CN/                    逐项对应的简体中文说明
  profiles/                 原始 DCP 清单和许可原文
dev/                        打包和离线 USB／CLI 测试
```

## 离线检查

装好依赖后，在仓库根目录执行：

```text
python -m unittest discover -s dev/usb/tests -v
python -m unittest discover -s src/fl23/tests -v
python dev/release/check_publication.py
python dev/release/build_release.py
python dev/release/verify_release.py
```

在 `src/looks` 安装 `requirements.txt` 及可选 `requirements-research.txt`，再执行 `python -m unittest discover -s tests -v`。私人集成素材通过 `A7C2_RESEARCH_FIXTURES` 提供，见[数据格式](technical/formats.md)；没有素材时相应测试跳过。

LUT 入口直接使用当前 Python，不依赖 Tkinter 或 shell 启动层，不自动安装依赖或重试。FL23 保留原 Windows 启动器和图形界面。没有实机 Mac 测试或 macOS USB 安装声明。历史 USB 修正源码仅作为回归材料保留。

## 文档与发布

用户和技术说明在 `docs/en/`、`docs/zh-CN/` 下逐项对应。文件名和命令保持一致，许可和署名原文保留。`AGENTS.md` 是供工具读取的统一规则，不另作一套用户说明。

Release 只提供一份当前工具包、一份独立原始 DCP 包和校验值。打包产物留在忽略的 `dist/`，不把 ZIP、完整固件、机身备份、校准、照片或私人生成清单提交到仓库。见[许可](notices.md)和[验证记录](technical/validation.md)。
