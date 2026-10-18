# 来源与许可

[返回首页](../../README.zh-CN.md) · [English](../en/notices.md)

新编写的代码使用 [MIT 许可](../../LICENSE)。项目是独立研究，与 Sony、Fujifilm、Ricoh、Adobe 无隶属关系；风格名称不代表官方背书或色彩完全一致。

## 代码与研究来源

- [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE)，固定提交 `a82f5baaa8e9c3d9f28f94699e860fb2e48cc8e0`：服务／USB Python 源码位于 `src/fl23/vendor/pmca`；保留[原 MIT 文本](../../src/fl23/licenses/Sony-PMCA-RE-MIT.txt)。
- [A7CR FL2／FL3 研究](https://github.com/lzh2016zzz/a7cr-fl23-research/tree/43ba74441c8f10459ade41e84a379ad8005e6ef4)：参考参数、标签和 WBI 方法。A7C II 偏移另行定位，并未直接刷入 A7CR 偏移。
- [A7C II 服务模式研究](https://github.com/YuuLuo/a7c2-service-preload/tree/1619f938663a36d41e72302a8cfee89a0f6acd1a)，文档为 CC BY-SA 4.0。本工具使用原生 `libJit.so` 加载入口，不使用预载配置或会改时钟的 DEBUG 命令。
- Adobe DNG 规范／SDK 提供 DCP 格式说明。工具仅实现有限的 look／tone 阶段，不是完整 Adobe 显影器。

## 参考配置文件

[18 款原始 DCP](profiles.md) 独立放在 Release；代码的 MIT 许可不涵盖它们。

**DCP 来源：**理光 DCP 来自小红书 **爸总林先森**；富士 DCP 来自小红书 **门萨特里顿**（MTriton）。

- 富士 Film Look 来源：[abpy/FujifilmCameraProfiles](https://github.com/abpy/FujifilmCameraProfiles)；A7C II 适配／测试：**门萨特里顿／MTriton**，适用 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)。原始 DCP、包内 README 和署名保持不变。
- 适配 Sony 的理光 DCP 保留 `Copyright 2022 Adobe Systems, Inc.`。原文件未附单独再分发许可，本项目不声称另有许可，也不改授 MIT。[清单](../profiles/manifest.json)记录原始元数据及来源。
- 早期研究使用的富士官方视频 LUT 不提供下载；当前六款示例使用机主提供的 DCP。

Sony A7C II 2.01 和 Alpha 1 II 4.00 固件用于分析，固件、商标和数据权利仍归原权利人。项目不发布完整固件、官方更新容器、机身备份／校准、照片、凭据或私人衍生载荷。实际测试范围见[验证记录](technical/validation.md)。
