# 开发维护与仓库结构

[返回首页](../../README.zh-CN.md) · [English](../en/development.md)

机主已于 2026 年 10 月 20 日认可将 Recovery、单槽恢复和直接服务认证的 USB 修复合入 `main`，并更新同一个 v2.2-preview.1 提交／Release。Main 保留 FL23 Windows 命令行／桌面工具、Python LUT 命令行和独立 Recovery 三个入口。后续修改使用功能分支；再次改写发布历史需另获授权。

```text
README.md / README.zh-CN.md  英文／简体中文首页
FL23.cmd                   原 FL23 Windows 图形界面／设备命令
lut.py                     跨平台 LUT 导入／单槽恢复命令行
recovery.py                独立完整回退命令行
vertical.py                本分支的竖屏拍摄显示预览
src/
  fl23/                     安装器、固定原生组件和通讯程序
  looks/                    转换、精确来源适配器和测试
  vertical/                 RAM 开关及可撤销的原生资源别名
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
python -m unittest discover -s dev/vertical -v
python dev/release/check_publication.py
python dev/release/build_release.py
python dev/release/verify_release.py
```

在 `src/looks` 安装 `requirements.txt` 及可选 `requirements-research.txt`，再执行 `python -m unittest discover -s tests -v`。私人集成素材通过 `A7C2_RESEARCH_FIXTURES` 提供，见[数据格式](technical/formats.md)；没有素材时相应测试跳过。

LUT 入口直接使用当前 Python，不依赖 Tkinter 或 shell 启动层，不自动安装依赖或重试。FL23 保留原 Windows 启动器和图形界面。没有实机 Mac 测试或 macOS USB 安装声明。历史 USB 修正源码仅作为回归材料保留。

## 文档与发布

用户和技术说明在 `docs/en/`、`docs/zh-CN/` 下逐项对应。文件名和命令保持一致，许可和署名原文保留。`AGENTS.md` 是供工具读取的统一规则，不另作一套用户说明。

预览版提供一份工具包、独立 LUT／Recovery Python 文件及校验值；原始 DCP 继续链接 v2.1 的同一份附件。修改写入[更新日志](changelog.md)，此次修复也包含在 main。打包产物留在忽略的 `dist/`，不把 ZIP、完整固件、机身备份、校准、照片或私人生成清单提交到仓库。见[许可](notices.md)和[验证记录](technical/validation.md)。
