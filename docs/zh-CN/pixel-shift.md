# 像素偏移研究：开发分支

[首页](../../README.zh-CN.md) · [English](../en/pixel-shift.md)

目标参照 A7CR 原生流程：三脚架、静态场景、四张位移 RAW，之后在电脑合成。十六张模式作为后续目标。公开程序属于**离线研究，不是可安装或已实现像素位移的正式版本**。

10 月 20 日，两次经机主授权的三字节 RAM 测试均出现菜单，但功能仍被禁止。第二次已装 SD 卡并使用静态 P/M，因此不能把失败归因于缺卡。两次修改都已还原并独立核对，没有拍摄。

继续反汇编后，找到 C2 另一张参数能力表中的未定义项；原生初始化会为此加入四个禁止计数，与实机唯读结果吻合。已解析十条正常排他规则，在当时静态 M、空闲状态下均未触发。第三次私人测试补入 C2 原生参数定义，并只撤掉这四个“参数未定义”禁止计数，同时开启菜单：六处 AP 数据窗口，共 47 字节。独立读回确认参数定义及禁止状态已更新，菜单／拍摄人工测试待完成。此前先清除了保留启动镜像；没有修改指令、固件文件、CP 或机身校准。物理位移仍未验证，此处不分发私人实机工具。

## 已实现

- [调用链检查](../../dev/pixelshift/audit.py)：从私人提取的 C2／A7CR 2.01 程序解析像素位移序列的 RTTI 和实际虚函数，核对“序列 → 包装层 → 通用拍摄封包构造”，定位像素位移函数名称的代码引用。
- [原始指令重放](../../dev/pixelshift/native_replay.py)：四／十六张及间隔选择的 18 组对照一致；通用拍摄命令 `0x4036` 的 44 组封包对照一致。选择测试停在蓝牙反馈配置前；封包测试只省略诊断日志调用，并在实际发送前停止，没有模拟硬件操作成功。
- [原生模式设置](../../dev/pixelshift/trinity_replay.py)：固件内部称像素位移为 `TRINITY`。原生命令 `0x40ee` 及 CP 模式赋值的 20 组对照一致，涵盖关闭、四／十六张、间隔及原生测试标记。CP 片段只赋值模式，不代表已驱动传感器。
- [CP 元数据重放](../../dev/pixelshift/cp_metadata_replay.py)：63 组对照核对分组编号、张序号及总张数的原生写入，输出是预先分配的六字节 `PixelShiftInfo`。输入帧状态为合成数据，没有模拟传感器。
- [CP 拍摄模式重放](../../dev/pixelshift/cp_capture_replay.py)：63 组对照执行原始配置选择及 TRINITY 一致性检查。给定原生配置字节 `0xd88` 后，模式 2 可转为模式 23；合成的原生状态字节能阻止转换。选中的模式不兼容时，程序会关闭 TRINITY。没有执行拍摄或驱动调用，AP 到该配置字节的完整来源仍待确认。
- [能力表重放](../../dev/pixelshift/capability_replay.py)：52 组对照执行原生机型映射和表项读取。C2 机型输入 16 对应第 9 列，相关像素位移支持值原为关闭；模拟中修改两字节可开启这个标志。测试不包含运行中的能力缓存或硬件，不生成刷写文件，也不按数字猜测 A7CR 的机型身份。
- [参数资格重放](../../dev/pixelshift/eligibility_replay.py)：新增 26 组原始指令案例，区分菜单支持、参数是否定义及数值是否可接受。C2 的宽松兜底函数接受数值，不代表功能已定义；A7CR 定义了关／四张／十六张。用合成注册表执行 C2 原始初始化，记录到四个禁止通知；模拟补入原生定义后不再产生这些请求。通知函数只观察、不执行。另解析十条进入该参数的排他规则，保留 AUTO／影片、拍摄编码及 AF-ON 等正常限制。
- [RAW 分组检查](../../dev/pixelshift/raw_group.py)：读取 Sony `PixelShiftInfo`（`0x202f`），检查四张不同源文件、序号及曝光记录，拒绝普通连拍、混合分组和已合成文件。元数据通过不等于证明物理位移或合成兼容。
- [RAW 位移量测](../../dev/pixelshift/displacement.py)：分别比较两个绿色 Bayer 子阵列，量测小数像素平移，检查是否形成一像素方形。独立合成场景通过，不位移、间距错误和坏帧案例被拒绝。已核对真实 C2 普通 RAW 的解码，尚无真实像素位移序列。相机／场景运动也能产生类似影像证据，因此它不能认证马达位置或稳定完成。

序列虚函数 `run()`：C2 为 `0x348bcf0`，A7CR 为 `0x348c1b8`。C2 的 `0x34d1508` 调用封包构造 `0x353a260`；A7CR 的 `0x34d19f0` 调用 `0x353a748`。这些是研究地址，不是刷写位置。该通用命令也用于其他拍摄流程，不能依据这份检查直接向相机发送。

## 离线复现

使用 Python 3.10+，安装[研究依赖](../../dev/pixelshift/requirements.txt)：

```text
python -m pip install -r dev/pixelshift/requirements.txt
python dev/pixelshift/audit.py --c2 private/c2/components --reference private/a7cr/components --output private/audit.private.json
python dev/pixelshift/native_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/replay.private.json
python dev/pixelshift/trinity_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/trinity.private.json
python dev/pixelshift/cp_metadata_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/metadata.private.json
python dev/pixelshift/cp_capture_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-capture.private.json
python dev/pixelshift/capability_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/capability.private.json
python dev/pixelshift/eligibility_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/eligibility.private.json
python dev/pixelshift/raw_group.py source.ARW
python dev/pixelshift/raw_group.py 1.ARW 2.ARW 3.ARW 4.ARW --validate-four
python dev/pixelshift/displacement.py 1.ARW 2.ARW 3.ARW 4.ARW --output private/displacement.private.json
python -m unittest discover -s dev/pixelshift/tests -v
```

macOS 改用 `python3`，尚未在 Mac 执行验证。未提供私人固件时，十项原始固件测试跳过。要运行这些测试，将环境变量 `A7C2_PIXELSHIFT_FIRMWARE_ROOT` 指向含 `a7c2-2.01/components` 和 `a7cr-support/components` 的私人目录。十九项测试方法涵盖 260 组配对原生指令案例、26 组参数资格案例、合成元数据异常及位移量测。已有一张真实 C2 普通 RAW 被正确识别为没有像素位移分组。位移量测使用 `rawpy` 保留原 Bayer 采样，四张源 RAW 必须先通过元数据检查。

## 尚需实现

先通过原生菜单验证新版 RAM 测试，再继续追踪单张配置和 CP／防抖定位入口，确认定位单位、稳定完成条件与曝光同步；验证完成／取消后的归位。随后核对实际位移 RAW、分组／校准记录及兼容的合成程序。有五轴防抖或共用函数名称，不代表已具备半像素定位接口。在路径未查清前不提供可刷写候选。

不能只打开菜单、复制 A7CR 机身校准、伪造 RAW 分组／机型，或把普通连拍称为像素位移。完整固件、原始照片和生成报告留在私人目录。main 和 Releases 保持不变。

原生参考：[A7CR 像素位移说明](https://helpguide.sony.net/ilc/2370/v1/en/contents/0414M_pixel_shift_shooting.html)、[Sony 合成流程](https://support.d-imaging.sony.co.jp/app/imagingedge/en/instruction/1_2_about_psm.php)。
