# 电子快门声音：实机测试候选

[首页](../../../README.zh-CN.md) · [English](../../en/technical/shutter-sound.md)

分支：`feature/electronic-shutter-sound`，基于 `80959db`。**已准备受控实机测试候选，实际声音和机身稳定性仍未验证。** 本分支全部工作均为离线，main 和 Release 未改。

## 候选与证据

只改 CP 一条两字节 Thumb 指令：文件偏移 `0x3935ca`／运行地址 `0x49b5ca`，`0021` → `0321`，实际仅立即数的一字节不同。普通电子快门路径中，C2 根据传感器描述将声音模式清零；A1 II 的对应分支选择模式 3。候选保留原查询，同样选择模式 3，经现有路径请求 kind 3 拍摄声音。不改 AP、菜单、声音设置、音效资源或校准，不增加运行内存钩子。

实机第一步是**只读声音登记核对**：必须在原生 AP 声音条目 0–5 中找到有缓冲区和长度的 kind 1／2／3（KA／SHA／KASHA），原厂 Audio Signals Off 策略会注销这组声音。对应不上就停在固件写入之前。扬声器路由、静音模式、关闭声音和拍摄时序仍需实测。

| 离线检查 | 结果与边界 |
|---|---|
| [AP／CP 输入片段](../../../dev/shutter_sound/verify_selector_inputs.py) | 8 组将电子请求传到普通 selector 1，另 6 组检查优先级；执行实际型号特性查询、请求写入和快照复制指令，未模拟异步传播。 |
| [选择器对照](../../../dev/shutter_sound/trace_selector.py) | 300 组合成输入，共 600 次原版／候选执行；其他 selector、跳过／延后条件及计数限制保持，异步消费者尚未完整模拟。 |
| 原始 AP 声音策略 | 4 组只观察登记参数，不执行登记；实际 kind 3 所属条目仍需只读实机核对。 |
| [编译后事务](../../../dev/shutter_sound/verify_worker.py) | 18 项系统调用模拟，覆盖预检查、写入、逆向、部分读写、冲突、读回损坏、回滚成功／失败和挂载失败，不是相机／断电模型。 |
| [编译后读者](../../../dev/shutter_sound/verify_probe.py) | 6 项合成进程测试，不是实机登记证据。 |
| 单元／流程测试 | 23 项通过；流程的相机传输是模拟的。 |

C2 有 71 行音效登记、11 项具备数据的 PIN 资源，含 KA／SHA／10fps；A1 II 为 73 行、9 项。明确的资源区间与 `SysSound.bin` 对应字节一致，文件存在不等于播放。功能参考 [A1 II 原生拍摄声音](https://helpguide.sony.net/ilc/2440/v1/en/contents/231h_audio_signal_volume.html)，C2 的[静音模式](https://helpguide.sony.net/ilc/2360/v1/en/contents/0414D_silent_mode_setting.html)必须继续关闭拍摄声音。

## 离线复现

在本分支仓库根目录，用 Python 3.10+ 和私人提取的 C2 2.01 组件：

```text
python -m pip install -r src/looks/requirements-device.txt unicorn
python dev/shutter_sound/verify_selector_inputs.py --ap appFw.so --cp cpapp-b.bin --output inputs.private.json
python dev/shutter_sound/trace_selector.py cpapp-b.bin --output selector.private.json
python dev/shutter_sound/candidate.py --ap appFw.so --cp cpapp-b.bin --output private-candidate
python dev/shutter_sound/verify_worker.py --plan private-candidate/plan.private.json --output transaction.private.json
python dev/shutter_sound/verify_probe.py --worker private-candidate/probe.so --ap appFw.so --output reader.private.json
python -m unittest discover -s dev/shutter_sound/tests -v
```

[candidate.py](../../../dev/shutter_sound/candidate.py)从不打开 USB。相关指令冲突时停止，不以整份固件哈希白名单判断来源。输出含私人 CP 候选和原生事务、只读声音登记、启动快照插件，不是索尼签名的 SD 卡更新包。

## 受控实机测试

这些[开发测试命令](../../../dev/shutter_sound/trial.py)独立于 FL23／LUT 工具。沿用现有 [USB 设置](../fl23.md)，使用满电电池和稳定连接。先选 P／A／S／M、电子快门、静音模式关、拍摄声音开，记下原设置。

```text
python dev/shutter_sound/trial.py preflight --firmware 2.01 --job private-shutter-job --backup-copy separate-backup-folder
python dev/shutter_sound/trial.py status --job private-shutter-job
python dev/shutter_sound/trial.py apply --job private-shutter-job
```

1. **预检查：**沿用先认证服务的 USB 会话绑定机身，读取当前程序及已保存／运行中设置，重建验证两份压缩备份，核对相关指令，再运行临时只读声音读者和原生 mode 0 检查。不改固件、拍摄设置或启动快照。只有状态为 `ready` 才继续。
2. **写入：**重新读取程序／设置，再检查登记及原生 mode 0，只写这条两字节指令；将两份完整程序与最新预期结果逐字节比较，检查可写 AP 设置和受保护 CP 单元，保留其他 FL23／LUT 改动，没有固件 SHA 来源门槛。
3. **重新加载：**完整读回后，启动快照 mode 2 沿用“丢弃快照，再设 mode 0”，已为 mode 0 则跳过。全部 USB 操作结束，正常关机、等存取灯熄灭、拔 USB／其他供电，取下电池至少一分钟。磁盘读回或新内核启动都不是直接 CP RAM 证据。
4. **验证：**先拍一张电子快门照片，确认声音对应实际保存照片；半按／取消不应多出快门音。再测 Lo／Hi／Hi+ 连拍、声音关、静音模式开、机械快门／电子前帘、对焦提示、录像音轨、FL2／FL3／自定义外观及回放。记录延迟、漏声／多声和故障。单张成功不等于稳定版。

只还原这条指令，保留之后其他位置的改动：

```text
python dev/shutter_sound/trial.py restore --job private-shutter-job
```

还原同样使用最新字节、原生预检查、完整读回、设置核对和启动快照处理。结果不明时进入 `needs_review`，CLI 不会盲目重写、还原或重启，保留原 Job 和原生报告供核对。这种局部逆向与[完整 Recovery](../recovery.md)分开。

## 自定义声音导入

[custom_sound.py](../../../dev/shutter_sound/custom_sound.py)仍是**离线原型**。同长度原生 BIN 替换可更新声音包／资源别名并生成压缩字节逆向，真实 1,216 字节资源已精确往返还原。原生编码未识别，任意 BIN 不等于有效音频。

单声道 PCM16 WAV 可不重采样提取，并生成 LPCM 登记模板。原 AP 支持 ADPCM=0／LPCM=1；[96 组原指令验证](../../../dev/shutter_sound/verify_registration.py)匹配其 40 字节 ABI，停在外部发送之前。PCM 采样率／布局、缓冲区生命周期和硬件播放未解决；24kHz 合成测试不是机内采样率证据。

根文件系统和 `nflasha8` 有两份相同的 66,368 字节 `SysSound.bin`，实际加载／缓存未追通。**本触发候选不替换这两份文件，也不安装 WAV。** 先实测原生快门音，再独立验证自定义声音的解码／加载。

## 参考范围

已阅读 [service-preload](https://github.com/YuuLuo/a7c2-service-preload/tree/1619f938663a36d41e72302a8cfee89a0f6acd1a)，固定提交 `1619f938663a36d41e72302a8cfee89a0f6acd1a`，它说明 USB／Senser／Jiritsu 和一次性 root 子进程预加载，没有快门音实现。本候选沿用本仓库现有临时 `libJit.so` 事务加载器，不创建永久 preload。未复制参考实现或索尼音效，参考文档采用 CC BY-SA 4.0。固件、音频、机身备份及生成报告均保密。
