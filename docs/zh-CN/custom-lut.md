# 自定义 LUT／DCP

[返回首页](../../README.zh-CN.md) · [English](../en/custom-lut.md)

打开 **Custom-LUT.cmd**，进入独立的离线界面：

- 检查 DCP／CUBE，查看已有项目的 ST 栏位计划。
- 核对 ST 绑定文件、根据事先量测的数据生成校准，再拟合机内色表。
- 为精确支持的来源生成选中栏位的更新及还原清单。

选择操作并填写对应路径；校准输出为新的 JSON 文件，拟合和更新清单输出为新目录。界面不连接 USB、不安装相机固件；名称、现场设置、设备写入和冷加载验收仍需独立工程处理。

[18 款 DCP](profiles.md) · [工具细节](technical/integration.md) · [手动命令](manual.md) · [AI 接手](ai.md)

机主自定 1–6 依次为 NC、CC、NN、Eterna、GR 正片、GR 负片，均以 ST 为基础；照片及最新 v4 预览切换在单台机身上回报正常。这不代表离线界面已成为通用六款刷写器。

## 操作流程

界面菜单与下表逐项对应：

| 菜单操作 | 对应命令 | 事先准备的输入 | 输出 |
|---|---|---|---|
| 1. 检查 DCP / CUBE | `inspect` | DCP／CUBE 文件 | 日志中的规格、哈希 |
| 2. 查看 ST 栏位计划 | `plan` | 已编辑好的项目 JSON | 日志中的栏位计划，不编辑项目 |
| 3. 核对 ST 绑定文件 | `check-bindings` | 项目 JSON、绑定 JSON | 文件一致性检查，不读取相机 |
| 4. 根据量测生成校准 | `calibrate` | 已对齐色块 NPZ、已量测 ISP 响应 JSON | 新的校准 JSON 文件 |
| 5. 拟合机内色表 | `fit` | 指向真实校准和参考文件的项目 JSON | 新目录：`candidate.json`、所选栏位色表 |
| 6. 生成更新与还原清单 | `prepare-transition` | 候选目录、精确来源 AP／CP、绑定 JSON、来源布局 | 新目录：`forward.private.json`、`reverse.private.json` |

开始前，复制并编辑[项目示例](../../src/looks/examples/six-looks.json)，设置目标栏位、名称、参考文件和校准路径；第 2 步只查看这个文件。绑定 JSON 也是电脑端声明，实机保存／运行值需要另行核对，不能直接拿示例充当实机证据。

第 4 步处理已有量测数据，不会自动拍照、解码 RAW、对齐图像或测量 ISP。它的输出路径应写入项目 JSON 的 `calibration` 字段；已有有效的真实校准时可以复用。命令见[手动说明](manual.md)，数据要求见[格式说明](technical/formats.md)。

DCP 是 RAW 显影参考，只提取 look／tone，保留 Sony 机身校准；视频 Log LUT 需要量测输入域映射。拟合到原生 5×9×9×3 有符号 7 位网格可保留原生精度，但不能保留更大 DCP 的全部条目。基础外观选择器仍可编辑，非 ST 会关闭导入效果，并没有锁住菜单。

[集成细节](technical/integration.md) · [验证限制](technical/validation.md) · [历史错误](technical/failures.md)
