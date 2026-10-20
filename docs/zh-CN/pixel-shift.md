# 像素偏移研究：开发分支

[首页](../../README.zh-CN.md) · [English](../en/pixel-shift.md)

目标参照 A7CR 原生流程：三脚架、静态场景、四张位移 RAW，之后在电脑合成。十六张模式作为后续目标。公开程序属于**离线研究，不是可安装或已实现像素位移的正式版本**。

10 月 20 日，两次经机主授权的三字节 RAM 测试均出现菜单，但功能仍被禁止。第二次已装 SD 卡并使用静态 P/M，因此不能把失败归因于缺卡。两次修改都已还原并独立核对，没有拍摄。

继续反汇编后，找到 C2 另一张参数能力表中的未定义项；原生初始化会为此加入四个禁止计数，与实机唯读结果吻合。已解析十条正常排他规则，在当时静态 M、空闲状态下均未触发。第三次私人测试补入 C2 原生参数定义，并只撤掉这四个“参数未定义”禁止计数，同时开启菜单：六处 AP 数据窗口，共 47 字节。独立读回通过，但机主在关机之前进入了空的子菜单。之后唯读检查确认六处均回到原值，无须再写入还原；没有拍摄。

子菜单各选项还有独立的机型支持表。第四次 RAM 测试只增加“关／四张”支持：共八处窗口、51 字节，十六张仍隐藏。读回通过，但机主反馈图标缺失，后来出现相机错误和黑屏。断电后临时表恢复，原生“四张”设置却仍保存在备份中；没有报告拍摄。机主随后自行救回相机，具体方法未记录。后续独立读取确认运行模式、RAM Backup、已保存 Backup 均为 OFF，机主也确认拔线后正常取景 30 秒。候选仍撤回，这不代表像素位移或长期硬件验证成功。试验没有修改 ROM、CP 或校准，但原生菜单确实保存了设置；此处不分发私人实机工具。

## 已实现

- [调用链检查](../../dev/pixelshift/audit.py)：从私人提取的 C2／A7CR 2.01 程序解析像素位移序列的 RTTI 和实际虚函数，核对“序列 → 包装层 → 通用拍摄封包构造”，定位像素位移函数名称的代码引用。
- [原始指令重放](../../dev/pixelshift/native_replay.py)：四／十六张及间隔选择的 18 组对照一致；通用拍摄命令 `0x4036` 的 44 组封包对照一致。选择测试停在蓝牙反馈配置前；封包测试只省略诊断日志调用，并在实际发送前停止，没有模拟硬件操作成功。
- [原生模式设置](../../dev/pixelshift/trinity_replay.py)：固件内部称像素位移为 `TRINITY`。原生命令 `0x40ee` 及 CP 模式赋值的 20 组对照一致，涵盖关闭、四／十六张、间隔及原生测试标记。CP 片段只赋值模式，不代表已驱动传感器。
- [CP 命令分派](../../dev/pixelshift/cp_dispatch_replay.py)：80 组对照以 AP 原生生成的 `0x40ee` 封包执行原始查表、可选一致性回调、模式处理和参数更新标志设置。初始 RAM 与待检查字段为合成状态，只省略诊断打印，没有执行传输、CP 调度或拍摄。
- [CP 配置快照](../../dev/pixelshift/cp_config_replay.py)：八组对照在同一份模拟 RAM 中，将上述原生处理器写入的模式交给原始快照函数及 ARM `memcpy`，3428 个复制字节全部一致。LiRo 的 `+0x180` 落到拍摄配置 `+0x1a0`，测试没有再次给模式赋值。其他输入字段和快照参数为合成数据，两处入口之间的调度未执行。
- [CP 逐张选择](../../dev/pixelshift/cp_sequence_replay.py)：64 组对照执行原始状态字节读取、序列选择及 17 项描述符初始化。在模式 23 下，四个帧序号都选择首列序列；普通模式 2 则能选择后续帧列。测试停在序列配置之前，没有执行选中的回调、曝光或定位。
- [序列／清除边界重放](../../dev/pixelshift/lifecycle_replay.py)：22 组对照核对原生拍摄序列建立请求、排队开关、`0x40ef` 清除封包，以及指向 `TrinityShotEnd` 的 CP 回调描述。两台分别使用自己的管理器地址。明确使用合成状态并省略互斥锁／诊断调用，停在分配、构造、传输或清除服务之前；尚未验证回调完成或传感器归位。
- [CP 元数据重放](../../dev/pixelshift/cp_metadata_replay.py)：63 组对照核对分组编号、张序号及总张数的原生写入，输出是预先分配的六字节 `PixelShiftInfo`。输入帧状态为合成数据，没有模拟传感器。
- [CP 拍摄模式重放](../../dev/pixelshift/cp_capture_replay.py)：63 组对照执行原始配置选择及 TRINITY 一致性检查。给定原生配置字节 `0xd88` 后，模式 2 可转为模式 23；合成的原生状态字节能阻止转换。选中的模式不兼容时，程序会关闭 TRINITY。没有执行拍摄或驱动调用，AP 到该配置字节的完整来源仍待确认。
- [CP 定时重放](../../dev/pixelshift/cp_timing_replay.py)：八组对照追踪 `SetSteadyCapTimer`，停在创建定时器之前。请求延迟为曝光偏移减去 9000 微秒，低于该边界时用一微秒；回调名为 `eventCallback_End_Wait_StartSteadyCap`。这证明了一条按时间调度的路径，不代表传感器位置确认；没有执行定时器／事件 API。
- [能力表重放](../../dev/pixelshift/capability_replay.py)：52 组对照执行原生机型映射和表项读取。C2 机型输入 16 对应第 9 列，相关像素位移支持值原为关闭；模拟中修改两字节可开启这个标志。测试不包含运行中的能力缓存或硬件，不生成刷写文件，也不按数字猜测 A7CR 的机型身份。
- [各选项支持重放](../../dev/pixelshift/option_replay.py)：78 组对照执行原生机型对应的子选项显示判断。子表字段偏移与父表不同，而且必须恰好为 1。C2 的三项原本均隐藏；模拟中只开启“关／四张”后，两项可通过这层判断，十六张继续隐藏。没有执行运行时权限、缓存、菜单绘制或拍摄。
- [参数资格重放](../../dev/pixelshift/eligibility_replay.py)：新增 26 组原始指令案例，区分菜单支持、参数是否定义及数值是否可接受。C2 的宽松兜底函数接受数值，不代表功能已定义；A7CR 定义了关／四张／十六张。用合成注册表执行 C2 原始初始化，记录到四个禁止通知；模拟补入原生定义后不再产生这些请求。通知函数只观察、不执行。另解析十条进入该参数的排他规则，保留 AUTO／影片、拍摄编码及 AF-ON 等正常限制。
- [RAW 分组检查](../../dev/pixelshift/raw_group.py)：读取 Sony `PixelShiftInfo`（`0x202f`），检查四张不同源文件、序号及曝光记录，拒绝普通连拍、混合分组和已合成文件。元数据通过不等于证明物理位移或合成兼容。
- [RAW 位移量测](../../dev/pixelshift/displacement.py)：分别比较两个绿色 Bayer 子阵列，量测小数像素平移，检查是否形成一像素方形。独立合成场景通过，不位移、间距错误和坏帧案例被拒绝。已核对真实 C2 普通 RAW 的解码，尚无真实像素位移序列。相机／场景运动也能产生类似影像证据，因此它不能认证马达位置或稳定完成。

序列虚函数 `run()`：C2 为 `0x348bcf0`，A7CR 为 `0x348c1b8`。C2 的 `0x34d1508` 调用封包构造 `0x353a260`；A7CR 的 `0x34d19f0` 调用 `0x353a748`。这些是研究地址，不是刷写位置。该通用命令也用于其他拍摄流程，不能依据这份检查直接向相机发送。

以 A7CR 为主线的 CP 追踪，现已连接模式分派、配置快照和逐张序列选择。A7CR 的 `0x4036` 拍摄请求发往 `0x90040193`，与 `0x40ee` 参数的目的地 `0x90030001` 不同。原生帧构造器会在 TRINITY 各帧间保留同一个分组对象，最后由 `TrinityShotEnd` 重置序号并释放对象。这些是软件生命周期事实，不代表传感器位移或归位。此前查看的 `+0xb8` 到 `+0x1a0` 复制是配置序列化辅助函数，不是 TRINITY 模式的主要来源；不同结构的偏移相同不能证明语义相同。

## 虚拟机观察

基于 [a7c2-re](https://github.com/chocotan/a7c2-re) 的实验运行原厂 AP，底层虚拟服务仍有限。原生菜单能显示“关／四张”，选择四张时被 Intelligent Auto 限制挡下，模式与虚拟 Backup 仍为 OFF。提前强制进菜单的配置缺少 `0x4bd` 序列，后来在 `sequence_still_record::suspend(NULL)` 异常；另一次正常启动则确实创建了 `0x4bd`，已沿缓存指针读取元数据核对编号和原生虚表，而不是只看指针非零。此时界面仍黑，MENU 输入没有推进画面。因此，提前进菜单配置的失败不能证明 C2 缺少实现，也不能解释先前的真机故障。完整启动、P/M 输入、选择四张、保存开启后入口隐藏的恢复以及拍摄仍未验证，现有模型不包含传感器／防抖行为。

另一轮虚拟机 RAM 开启／还原循环已确认八处字段回到原值，模式和虚拟 Backup 全程 OFF。只移除／补回四个“参数未定义”计数，保留 AUTO 禁止计数。这验证的是 RAM 逆操作，不代表保存开启后的恢复、闪存持久化或实机还原。

## 离线复现

使用 Python 3.10+，安装[研究依赖](../../dev/pixelshift/requirements.txt)：

```text
python -m pip install -r dev/pixelshift/requirements.txt
python dev/pixelshift/audit.py --c2 private/c2/components --reference private/a7cr/components --output private/audit.private.json
python dev/pixelshift/native_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/replay.private.json
python dev/pixelshift/trinity_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/trinity.private.json
python dev/pixelshift/cp_dispatch_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-dispatch.private.json
python dev/pixelshift/cp_config_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-config.private.json
python dev/pixelshift/cp_sequence_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-sequence.private.json
python dev/pixelshift/lifecycle_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/lifecycle.private.json
python dev/pixelshift/cp_metadata_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/metadata.private.json
python dev/pixelshift/cp_capture_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-capture.private.json
python dev/pixelshift/cp_timing_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-timing.private.json
python dev/pixelshift/capability_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/capability.private.json
python dev/pixelshift/option_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/options.private.json
python dev/pixelshift/eligibility_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/eligibility.private.json
python dev/pixelshift/raw_group.py source.ARW
python dev/pixelshift/raw_group.py 1.ARW 2.ARW 3.ARW 4.ARW --validate-four
python dev/pixelshift/displacement.py 1.ARW 2.ARW 3.ARW 4.ARW --output private/displacement.private.json
python -m unittest discover -s dev/pixelshift/tests -v
```

macOS 改用 `python3`，尚未在 Mac 执行验证。未提供私人固件时，十六项原始固件测试跳过。要运行这些测试，将环境变量 `A7C2_PIXELSHIFT_FIRMWARE_ROOT` 指向含 `a7c2-2.01/components` 和 `a7cr-support/components` 的私人目录。二十五项测试方法涵盖 520 组配对原生指令案例、26 组参数资格案例、合成元数据异常及位移量测。已有一张真实 C2 普通 RAW 被正确识别为没有像素位移分组。位移量测使用 `rawpy` 保留原 Bayer 采样，四张源 RAW 必须先通过元数据检查。

## 尚需实现

保持已撤回的实机候选关闭，继续核对虚拟机正常启动／菜单流程和单张配置、CP／防抖定位入口，确认定位单位、稳定完成条件、曝光同步及完成／取消后的归位。再次实机测试之前，需要可独立审查的候选、断电后仍可用的 OFF 入口及精确还原方案。之后仍须验证实际位移 RAW、分组／校准记录和兼容合成。有五轴防抖或共用名称，不代表已具备定位接口，目前没有可刷写候选。

不能只打开菜单、复制 A7CR 机身校准、伪造 RAW 分组／机型，或把普通连拍称为像素位移。完整固件、原始照片和生成报告留在私人目录。main 和 Releases 保持不变。

原生参考：[A7CR 像素位移说明](https://helpguide.sony.net/ilc/2370/v1/en/contents/0414M_pixel_shift_shooting.html)、[Sony 合成流程](https://support.d-imaging.sony.co.jp/app/imagingedge/en/instruction/1_2_about_psm.php)。
