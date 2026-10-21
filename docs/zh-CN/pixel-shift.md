# 像素偏移研究：开发分支

[首页](../../README.zh-CN.md) · [English](../en/pixel-shift.md)

目标参照 A7CR 原生流程：三脚架、静态场景、四张位移 RAW，之后在电脑合成。十六张模式作为后续目标。公开程序属于**离线研究，不是可安装或已实现像素位移的正式版本**。

10 月 20 日，两次经机主授权的三字节 RAM 测试均出现菜单，但功能仍被禁止。第二次已装 SD 卡并使用静态 P/M，因此不能把失败归因于缺卡。两次修改都已还原并独立核对，没有拍摄。

继续反汇编后，找到 C2 另一张参数能力表中的未定义项；原生初始化会为此加入四个禁止计数，与实机唯读结果吻合。已解析十条正常排他规则，在当时静态 M、空闲状态下均未触发。第三次私人测试补入 C2 原生参数定义，并只撤掉这四个“参数未定义”禁止计数，同时开启菜单：六处 AP 数据窗口，共 47 字节。独立读回通过，但机主在关机之前进入了空的子菜单。之后唯读检查确认六处均回到原值，无须再写入还原；没有拍摄。

子菜单各选项还有独立的机型支持表。第四次 RAM 测试只增加“关／四张”支持：共八处窗口、51 字节，十六张仍隐藏。读回通过，但机主反馈图标缺失，后来出现相机错误和黑屏。断电后临时表恢复，原生“四张”设置却仍保存在备份中；没有报告拍摄。机主随后自行救回相机，具体方法未记录。后续独立读取确认运行模式、RAM Backup、已保存 Backup 均为 OFF，机主也确认拔线后正常取景 30 秒。候选仍撤回，这不代表像素位移或长期硬件验证成功。试验没有修改 ROM、CP 或校准，但原生菜单确实保存了设置；此处不分发私人实机工具。

## 已实现

- [调用链检查](../../dev/pixelshift/audit.py)：从私人提取的 C2／A7CR 2.01 程序解析像素位移序列的 RTTI 和实际虚函数，核对“序列 → 包装层 → 通用拍摄封包构造”，定位像素位移函数名称的代码引用。
- [原始指令重放](../../dev/pixelshift/native_replay.py)：四／十六张及间隔选择的 18 组对照一致；触发命令 `0x4036` 的 44 组封包对照一致。另有 24 组核对真正的捕获启动命令 `0x4038`，其六种输入枚举分别映射到不同的传输值。选择测试停在蓝牙反馈配置前；`0x4036` 封包省略一次诊断调用，`0x4038` 省略两次，均在发送前停止。无效捕获枚举离开限定模型时不会得到成功封包，没有执行 CP 放行、曝光或定位。
- [原生模式设置](../../dev/pixelshift/trinity_replay.py)：固件内部称像素位移为 `TRINITY`。原生命令 `0x40ee` 及 CP 模式赋值的 20 组对照一致，涵盖关闭、四／十六张、间隔及原生测试标记。CP 片段只赋值模式，不代表已驱动传感器。
- [CP 命令分派](../../dev/pixelshift/cp_dispatch_replay.py)：80 组对照以 AP 原生生成的 `0x40ee` 封包执行原始查表、可选一致性回调、模式处理和参数更新标志设置。初始 RAM 与待检查字段为合成状态，只省略诊断打印，没有执行传输、CP 调度或拍摄。
- [CP 配置快照](../../dev/pixelshift/cp_config_replay.py)：八组对照在同一份模拟 RAM 中，将上述原生处理器写入的模式交给原始快照函数及 ARM `memcpy`，3428 个复制字节全部一致。LiRo 的 `+0x180` 落到拍摄配置 `+0x1a0`，测试没有再次给模式赋值。其他输入字段和快照参数为合成数据，两处入口之间的调度未执行。
- [CP 帧内传递](../../dev/pixelshift/cp_frame_replay.py)：24 组对照在同一份 RAM 中继续执行原始帧映射，将模式送到 frame `+0x98`，再经过后续控制旗标设置及请求选择片段。设置器读取的 `+0x78` 来自 frame 的 `+0x20` 视图，基址关系已核对。准备阶段的条件与其余字段未执行或采用合成输入；后续请求覆盖与传输未执行，不能把选出的数值认作已识别的位移命令。
- [CP 串行字段传递](../../dev/pixelshift/cp_serial_replay.py)：56 组对照把合成帧的 TRINITY 标志与张序号，经原始 TC 输入／复制／序号片段、原生编码、串行缓冲区填入及校验计算，送到 `0x39` 封包的 `0x6e` 字节，其值为 `(张序号 & 127) | (TRINITY << 7)`。原生接口模式初始化决定是否填入扩展区，另一个标志决定发送描述符使用 100 或 128 字节。测试在同一份 RAM 中执行普通 TC 分支，其余负载字段和接口输入为合成数据；完整 TC 运算、调度、串行传输、物理接收方及位移仍未验证。
- [原生默认参数加载](../../dev/pixelshift/cp_defaults_replay.py)：两组官方参数库对照执行原始 BK4 注册、两项配置查询、完整 256 字节参数复制、接口解码及 TC 分支选择。两机型都加载接口字 `0x0066`，解码为类型 6；后续配置不覆盖时会选择另一条 TC 分支。只省略五次无返回值的互斥锁调用。这修正了上一项的适用范围：合成输入下的普通分支尚不能当成相机实际使用的分支。
- [默认选择的替代 TC 分支](../../dev/pixelshift/cp_alternate_replay.py)：八组、每组四步的配对序列，在同一份 RAM 保留原生默认选择，经过原始入口进入替代函数，再发布／读取两个 32 字节缓冲区。原始代码完整保留序号、更新计数及辅助字。输入、共享旗标和调度为合成状态；刻意使用无效 GPIO 埠，让原生检查在硬件访问之前拒绝。它验证软件传递，不是可用的 GPIO 配置、实际协议或物理位移。
- [原生序号到向量运算](../../dev/pixelshift/cp_vector_replay.py)：12 组配对步骤在上述 RAM 继续执行原始帧旗标导出、192 字节发布／快照复制，以及由 TRINITY 旗标控制的向量运算。序号 0–3 产生四步原始图样，再乘上参数 `0x000f0025` 中的三个比例字节。两机型官方参数库加载的三字节均为零；另用非零比例及指数做合成敏感性检查。这个有条件的运算片段不包含之前的模式选择、完整调度、传输或驱动。物理单位及实际运行时比例来源仍未明确，不提供比例值刷写方案。
- [替代分支封包／回覆校验](../../dev/pixelshift/cp_alternate_wire_replay.py)：八组配对案例把上述向量继续送过完整原始 40 字节封包构造器及原生 XOR 校验。向量保留在第 4／8／12 字节，TRINITY 在第 28 字节。24 组配对回覆案例验证原始类型／校验分支及完整接收快照复制，包括拒绝错误资料时不改动已接受缓冲区。回覆是独立注入的合成输入；没有验证实际传输、硬件确认、稳定、曝光或归位。
- [替代分支反馈解码](../../dev/pixelshift/cp_feedback_replay.py)：24 组对照在同一份仿真 RAM 中，从已接受回覆继续执行其原生解码器和有符号读取器。回覆第 4／6／8 字节的三个半字得到保留，另执行独立的 16 字节上下文／历史复制及 20 项环形缓冲区回绕。历史输入为合成数据。此路径与普通反馈解码器读取的缓冲区不同；读到数值不等于已识别传感器位置或到位反馈。
- [Darwin 接收／解析重放](../../dev/pixelshift/darwin_capture_replay.py)：276 组对照执行原始消息查询、34 字节 RX 到稳定缓冲区的复制、快照获取及解析前段。覆盖每个输入位元，核对完整快照及状态写入范围。RX 和初始状态为合成数据；没有替代外部调用，停在后续控制调用之前。串行接收、完整 CP 到 Darwin 衔接、驱动控制及传感器位移尚未验证。
- [CP 逐张选择](../../dev/pixelshift/cp_sequence_replay.py)：64 组对照执行原始状态字节读取、序列选择及 17 项描述符初始化。在模式 23 下，四个帧序号都选择首列序列；普通模式 2 则能选择后续帧列。测试停在序列配置之前，没有执行选中的回调、曝光或定位。
- [CP 回调阶段分派](../../dev/pixelshift/cp_stage_replay.py)：19 组对照以合成上下文阶段分别调用这两个回调，执行原始跳转表，停在选中子处理器之前。核对七／八个有效阶段及原生无效阶段返回值。它建立处理器顺序；调度器没有推进阶段，也没有子处理器执行曝光或归位。
- [拍摄状态检查](../../dev/pixelshift/capture_gate_replay.py)：102 组对照执行原始 `0x4040` 请求编码、CP 有效遮罩与回覆字段形成、AP 解码，以及 `REQUEST_CAPTURE`／`CAPTURE_NG` 事件分支。回覆字节由电脑端桥接，未执行传输、CP 状态刷新、回覆分配或事件分派；状态输入为合成数据。这层软件检查通过不代表传感器定位就绪或拍摄成功。
- [CP 触发路由](../../dev/pixelshift/cp_trigger_replay.py)：72 组对照执行原生 AF／AE／AWB 优先级初始化与仲裁、触发消息转换，以及选定的内部消息路由。AF 准备分支停在辅助函数之前，捕获开始分支停在处理函数之前；AWBL 开／关执行原始旗标设置。注册表、前一触发值和内部对象为合成状态；未执行发送器本体、分配、传输或对象调度。这些测试区分准备／锁定与捕获，不模拟曝光成功。
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

像素位移的开始拍摄辅助函数会先执行 `0x4040` 状态检查。CP 在请求遮罩与有效状态位没有交集时回覆 `0xf000`，否则回覆 `0xf001`；AP 随后选择发出 `REQUEST_CAPTURE` 或 `CAPTURE_NG`。这定位了查询与事件边界；前面的 CP 触发路径与该事件接收者如何衔接实际曝光仍待追踪，不能把该回覆当作曝光或马达到位确认。

三条原生触发分支各有用途。已检查的 `0x4036` 构造器使用触发值 20，可请求 AE、AF 和 AWB 处理。`0x300e` 转成内部消息 `0x102`，进入 AF 准备；`0x302e` 转成 `0x8307`，已检查的分支只设置 AWBL 旗标，二者都不是捕获开始处理器。另一种 `0x300c` 封包先产生 `0x8202`、再产生 `0x100`，后者才进入会调用配置快照包装层的原生处理器。其发送器前面还有独立的 14 槽捕获注册表及状态／AF 条件。现已重放原始 `0x4038` 的 AP 封包构造，并定位 CP 接收函数，但从 AP 模型事件到物理曝光的完整衔接仍未验证。不能把锁定消息当作位移命令。

串行追踪现已定位元数据路径之外的组合标志／序号字段。`0x6e` 位于 100 字节格式以外，因此即使算出了该字节，扩展区被禁用或发送长度未覆盖它时也不足以传出。这两个条件均用合成输入覆盖；内部接口模式数字不是 Sony 机型编号，也不能证明两台相机实际运行时的协议配置。已静态定位下游 SIO 服务注册及分派函数，但物理接收端如何解释、位移轨迹、稳定等待及归位仍须核对。

官方默认参数实际选择另一条 TC 路径，帧序号会保留在双缓冲的控制快照中；已定位使用该快照的函数，但物理含义仍不明确。另已找到 Darwin 的 34 字节拍摄设置消息及解析函数。重放前段之后的字段进入计时／控制状态，尚未证明是 X/Y 位移坐标。仅封包长度相同，不能连接 CP 发送端与接收端，也不能证明像素位移。

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
python dev/pixelshift/cp_frame_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-frame.private.json
python dev/pixelshift/cp_serial_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-serial.private.json
python dev/pixelshift/cp_defaults_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-defaults.private.json
python dev/pixelshift/cp_alternate_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-alternate.private.json
python dev/pixelshift/cp_vector_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-vector.private.json
python dev/pixelshift/cp_alternate_wire_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-alternate-wire.private.json
python dev/pixelshift/cp_feedback_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-feedback.private.json
python dev/pixelshift/darwin_capture_replay.py --c2 private/c2/components/darwin_core.bin --reference private/a7cr/components/darwin_core.bin --output private/darwin-capture.private.json
python dev/pixelshift/cp_sequence_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-sequence.private.json
python dev/pixelshift/cp_stage_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-stage.private.json
python dev/pixelshift/capture_gate_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/capture-gate.private.json
python dev/pixelshift/cp_trigger_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-trigger.private.json
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

macOS 改用 `python3`，尚未在 Mac 执行验证。未提供私人固件时，二十八项原始固件测试跳过。要运行这些测试，将环境变量 `A7C2_PIXELSHIFT_FIRMWARE_ROOT` 指向含 `a7c2-2.01/components` 和 `a7cr-support/components` 的私人目录。默认参数／替代分支／向量／封包／反馈重放还需要将各机型官方的 `CX*00_ALLLANG.bin`、`CX*01_ALLLANG.bin` 放在对应 components 目录；Darwin 测试需要将私人提取的 `0640_darwin/darwin_core.bin` 放在那里。三十七项测试方法涵盖 1195 组配对原生指令案例、26 组参数资格案例、合成元数据异常及位移量测。已有一张真实 C2 普通 RAW 被正确识别为没有像素位移分组。位移量测使用 `rawpy` 保留原 Bayer 采样，四张源 RAW 必须先通过元数据检查。

## 尚需实现

保持已撤回的实机候选关闭，继续核对虚拟机正常启动／菜单流程和单张配置、CP／防抖定位入口，确认定位单位、稳定完成条件、曝光同步及完成／取消后的归位。再次实机测试之前，需要可独立审查的候选、断电后仍可用的 OFF 入口及精确还原方案。之后仍须验证实际位移 RAW、分组／校准记录和兼容合成。有五轴防抖或共用名称，不代表已具备定位接口，目前没有可刷写候选。

不能只打开菜单、复制 A7CR 机身校准、伪造 RAW 分组／机型，或把普通连拍称为像素位移。完整固件、原始照片和生成报告留在私人目录。main 和 Releases 保持不变。

原生参考：[A7CR 像素位移说明](https://helpguide.sony.net/ilc/2370/v1/en/contents/0414M_pixel_shift_shooting.html)、[Sony 合成流程](https://support.d-imaging.sony.co.jp/app/imagingedge/en/instruction/1_2_about_psm.php)。
