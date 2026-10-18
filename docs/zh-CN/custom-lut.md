# 自定义 LUT／DCP

[返回首页](../../README.zh-CN.md) · [English](../en/custom-lut.md)

打开 **Custom-LUT.cmd**，进入独立的离线界面：

- 检查 DCP／CUBE，查看项目栏位计划。
- 核对 ST 绑定文件，按已校准的项目拟合机内色表。
- 为精确支持的来源生成选中栏位的更新及还原清单。

选择操作、填写所需路径，输出使用新目录。拟合前先准备项目所需的量测校准。界面不连接 USB、不安装相机固件；名称、现场设置、设备写入和冷加载验收仍需独立工程处理。

[18 款 DCP](profiles.md) · [工具细节](technical/integration.md) · [手动命令](manual.md) · [AI 接手](ai.md)

机主自定 1–6 依次为 NC、CC、NN、Eterna、GR 正片、GR 负片，均以 ST 为基础；照片及最新 v4 预览切换在单台机身上回报正常。这不代表离线界面已成为通用六款刷写器。

## 操作流程

检查文件 → 规划选中的 ST 栏位 → 核对绑定证据 → 量测校准 → 拟合 → 生成精确来源的正向／还原清单。见[手动命令](manual.md)和[数据格式](technical/formats.md)。

DCP 是 RAW 显影参考，只提取 look／tone，保留 Sony 机身校准；视频 Log LUT 需要量测输入域映射。拟合到原生 5×9×9×3 有符号 7 位网格可保留原生精度，但不能保留更大 DCP 的全部条目。基础外观选择器仍可编辑，非 ST 会关闭导入效果，并没有锁住菜单。

[集成细节](technical/integration.md) · [验证限制](technical/validation.md) · [历史错误](technical/failures.md)
