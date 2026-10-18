# 数据格式与精确来源约束

[返回首页](../../../README.zh-CN.md) · [English](../../en/technical/formats.md)

## 校准样本与 JSON

准备对齐、未剪裁的多场景 Sony ST 样本及匹配的线性 ProPhoto RGB／D50 RAW 显影结果。NPZ 的 `st_rgb`、`linear_prophoto` 为归一化 Nx3 数组，`split` 用 0 表示训练、1 表示留出样本。`calibrate` 不解码 RAW，也不对齐图像。验证应使用独立场景；单场景的空间留出只作诊断。

原生 ISP 响应另行量测。响应 JSON 需要有限、可逆的 `response_matrix` 和 `evidence` 描述。单位矩阵只是合成测试素材，不是量测得到的通用相机响应。

所有项目均需校准：

```json
{
  "schema": "a7c2-look-calibration/1",
  "coordinate_model": "bt601-limited-provisional",
  "response_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
  "evidence": "SYNTHETIC EXAMPLE ONLY; replace with measured camera response"
}
```

这里的单位矩阵只是说明，不是量测结果。使用行向量：`delta_rgb = delta_ycc @ response_matrix`，原生修正值先除以 256 再相乘。

DCP 还需 `inverse_axis`、`inverse_curve`、`inverse_matrix`。轴和曲线等长、单调，覆盖 [0,1]；矩阵有限且为 3×3。转换顺序：

1. 将编码的 Sony ST 各通道按逆曲线插值。
2. 乘 `inverse_matrix.T` 得到暂定线性 sRGB／D65。
3. 经 Bradford 色适应转换到线性 ProPhoto RGB／D50。
4. 应用 DCP LookTable（HSV、色相环绕、value 轴编码 0 或 1），再应用保持色相的 tone 样条。
5. 转换为编码 sRGB／D65 输出。

没有实现完整 Adobe RAW、HueSat、baseline exposure 或默认显影过程；相机校准标签只列出，不移植。拒绝不支持或损坏的曲线／表。DCP TIFF 可用 magic 42 或 `0x4352`，支持两种字节序，不支持 BigTIFF。

## 项目 JSON

要求 `schema=a7c2-look-project/1`、`model=ILCE-7CM2`、`firmware=2.01`、相对 `calibration` 路径和 `slots`。栏位 ID 在 1–6 内且唯一，每项含 `name`、`base=ST` 及带署名的来源。

DCP 来源使用 `type=dcp`、`path`，可选 `exposure_stops` 需注明中性锚点；它是显影约定，不会改变相机实际曝光。

Cube 来源使用 `type=cube`、`path`、`input_space=sony-st-srgb`、`output_space=srgb`。若输入域不同，必须有 `bridge`，包含 `path`、`input_space=sony-st-srgb`、与目标 LUT 输入匹配的 `output_space` 及 `evidence`。例如 F-Log2 风格 LUT 需经校准的 Sony ST→F-Log2／F-Gamut 映射；看起来接近 WDR-709 并不构成校准。

Cube 数值可超出 [0,1]，采样遵守声明的域；最终拟合目标须归一化到 [0,1]。拒绝混合 1D＋3D／shaper 文件。

## 候选与原生数据

`candidate.json` 记录来源／校准 SHA-256、署名、栏位、ST 要求、合成拟合误差、收敛和系数限制。每个 `slotN.raw-s8.bin` 为 1,215 字节，依次为 405 个 Y、405 个 C1、405 个 C2 修正；各平面节点索引为 `Y*81+C1*9+C2`。

每个有符号系数限制为 -64..63。硬件 bank 使用另外的 1,620 字节排列，置换依赖固件；不能把原始修正平面直接写到硬件 bank。

## 精确更新清单

私人清单包含完整组件大小／哈希，以及不重叠的 `offset`、`bytes`、`before_hex`、`after_hex` 窗口。正向再逆向必须逐字节还原完整原档，未知来源不接受。候选名称不会更新菜单资源，栏位计划不会改变相机设置。

### 六款 full7-v4 存储

CP 文件 `0x8000`／VA `0x110000` 的八个小端 u32 为 magic `0x364c3741`、内部版本 `0x00010006` 和六个 FNV-1a32。六张各 1,215 字节的原始表从文件 `0x8020`／VA `0x110020` 连续存储。FNV 初值 2166136261、乘数 16777619，每字节处理后模 2^32；它防数据损坏，不是密码学真实性认证。

`--layout full7-v4` 只改所选表及各自 4 字节校验值，仍要求完整 AP／CP SHA-256 匹配。新表产生新的 CP 身份，未经审查的后续来源会被拒绝。数据清单不处理设置、名称或重新加载。

### 可选私人测试素材索引

将 `A7C2_RESEARCH_FIXTURES` 指向仓库外 JSON。路径相对于该 JSON，也支持本机绝对路径：

```json
{
  "three_ap": "three/appFw.so",
  "three_cp": "three/cpapp-b.bin",
  "native_fl23_cp": "fl23/cpapp-b.bin",
  "six_ap": "six/appFw.so",
  "switch_cp": "switch-v2/cpapp-b.bin",
  "v4_cp": "upload-v4/cpapp-b.bin",
  "tables": ["slot1.bin", "slot2.bin", "slot3.bin", "slot4.bin", "slot5.bin", "slot6.bin"]
}
```

测试核对完整已知哈希及本地重建。发布物不含固件、DCP 衍生表、私人索引或生成清单。未设置环境变量时，相应集成测试跳过，不虚构重建成功；原生测试仅在受控内存使用同一组私人组件，不连接 USB。
