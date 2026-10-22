"""Format and color-space guidance for the desktop compiler."""
TITLE = 'LUT / DCP 格式与色彩空间'
TEXT = """相机写入页只选 .a7look，不直接写入 .cube 或 .dcp。生成工具只转换电脑文件，不连接相机。

1. 桌面生成器接受什么 CUBE？
输入：Sony ST 标准创意外观、sRGB 编码的 RGB；输出：sRGB。
不是 S-Log3、S-Log2、HLG、S-Gamut3.Cine、DaVinci Wide Gamut 或 ACES。普通 Rec.709 视频 LUT 也不自动等同于这个输入；还要确认传递曲线和色域。
只有标注“适用于 Sony ST / sRGB 照片”的 LUT 才可直接用。文件扩展名 .cube 不包含可靠的色彩空间声明，程序无法自动判断。

2. 我只有 S-Log3 LUT 怎么办？
例如 S-Log3 / S-Gamut3.Cine → Rec.709 的 LUT，不能在当前桌面生成器里直接选用。直接套在 ST 图片上会出现反差、曝光或颜色错误，改扩展名或改文件头不能解决。
请在调色软件中重新导出完整的“Sony ST / sRGB 输入 → 目标风格 → sRGB 输出”的 3D CUBE，包含需要的输入和输出变换。不能只把导出标签改成 sRGB。
高级命令行支持显式输入空间与 ST→该空间的桥接 CUBE；目标 LUT 的输出仍须为 sRGB。当前 GUI 不提供 Log 桥接选项；桥接也不保证重建 Sony 原生 Log 处理。

3. CUBE 文件结构
纯文本独立 3D LUT，LUT_3D_SIZE N；N 支持 2–129，常见 17 / 33 / 65，建议 33。
后面恰好 N³ 行，每行 R G B 三个有限数字（不是 0–255 整数色值）；红通道变化最快。TITLE 可选，DOMAIN_MIN / DOMAIN_MAX 可选，默认 0 0 0 / 1 1 1。
不支持 1D LUT、1D shaper＋3D 混合文件、.3dl、.look、.xmp 或图片。超出 0–1 的输出会在拟合前裁切；导出时建议已在 0–1。

4. DCP 是什么？
.dcp 是 Adobe 相机配置文件，不是 S-Log3 视频 LUT。生成器直接离线解析 DCP 的 LookTable／色调曲线并拟合，无需 Lightroom、显影插件、renderer 配置或联网。
DCP 通过内置共享 ST 映射进行近似拟合，不复制来源机型的传感器矩阵或 HueSat 校准，也不声称完整复现 Adobe 显影。单独 CUBE 不会自动变成 Lightroom RAW 的 DCP 配置。

5. 最后怎么写？
生成新的 .a7look → 添加操作项 → 选择槽位和“写入 A7Look” → 选择文件并填写机内名称 → 查看并应用。多个槽位可一起写，没列出的槽位保持原样。
写入后按弹窗断电加载。效果是机内色表拟合近似；65 点 CUBE 不代表能原样保留全部采样精度，也不能保证与原 DCP / LUT 完全一致。"""
