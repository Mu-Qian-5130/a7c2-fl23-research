# 电子快门声音：原生实现研究

[首页](../../../README.zh-CN.md) · [English](../../en/technical/shutter-sound.md)

分支：`feature/electronic-shutter-sound`，基于 main 提交 `80959db`。**目前不是已启用功能或安装器。** 本分支没有相机读写、播放声音或固件／设置修改。

## 目标与参考

复用 Sony 现成的快门音及与实际拍摄同步的播放路径，参考 [A1 II 原生功能](https://helpguide.sony.net/ilc/2440/v1/en/contents/231h_audio_signal_volume.html)。电子快门和静音模式不同；C2 的[静音模式](https://helpguide.sony.net/ilc/2360/v1/en/contents/0414D_silent_mode_setting.html)会锁定拍摄声音关闭，实现必须保留这个行为，不能只因按键或出现 RAW 文件就播放声音。

已阅读 [service-preload 项目](https://github.com/YuuLuo/a7c2-service-preload/tree/1619f938663a36d41e72302a8cfee89a0f6acd1a)，固定提交 `1619f938663a36d41e72302a8cfee89a0f6acd1a`。它说明 USB／Senser 认证、Jiritsu 路径及一次性 root 子进程预加载，不包含电子快门音实现。子进程能运行不等于能访问 CP 状态或同步曝光；永久修改仍需独立实现与恢复方案。参考文档采用 CC BY-SA 4.0；本仓库没有复制其实现代码或 Sony 音效文件。

## 已验证的离线发现

- C2 2.01 已有 `beeplist.txt`、`SysSound.bin`、KA／SHA 和多组 10fps 快门音。71 行登记中有 11 项具备数据的 PIN 条目；A1 II 4.00 为 73 行、9 项。所有有明确长度／偏移的资源均与声音包内对应字节一致。这证明文件存在，不代表扬声器已播放。
- C2 AP 名称表确认拍摄声音属性为 `02cf048b`，派生菜单声音属性为 `02cf00c6`。已有机主备份中分别记录 `00`、`01000000`；历史值不代表当前实机状态。原生四分支转换存在，随意改这些属性不等于启用功能。
- C2 CP 有原生拍摄开始／结束选择函数 `0x4a09f4`／`0x4a0a74`，拍摄声音分派 `0xb19e5c`，声音请求函数 `0xb0a02e`。直接调用检查将这些位置串联，但仍有其他条件和异步消费者，曝光至扬声器的完整行为尚未追通。
- C2 原始判断函数 `0x67f692` 与 A1 II 对应函数 `0x6d17fc`，在所测输入中均仅当请求状态为 `2`、声音模式为 `3` 时返回真。每机 30 组合成状态直接执行原 Thumb 指令及原取值函数，没有模拟播放成功或拍摄成功。不能据此把数字含义扩展成完整相机状态模型。

C2 的 SPOT 连续长度原文确实为 `4.00E+00`，检查器保留原文，不自行改成猜测长度。A1 II 有 RESERVE／条码音效共用编号，保留占位条目。两机的原生编号／偏移不同，不能直接照搬。

## 不连接相机的复现

输入私人提取的原厂 AP／CP 及原始 `avsystemsound` 文件夹。不公开固件、机身设置或音效资源。

```text
python dev/shutter_sound/inspect_native.py --ap appFw.so --cp cpapp-b.bin --sounds avsystemsound --output report.private.json
python dev/shutter_sound/verify_predicate.py cpapp-b.bin --output predicate.private.json
python -m unittest discover -s dev/shutter_sound/tests -v
```

原生判断测试需要 `unicorn`。对照 A1 II 时加 `--model a1ii-4.00`。检查原资源字节和属性描述，不用整份固件哈希白名单。报告与原始字节留在私人目录；此命令行没有安装命令，不打开 USB。

## 仍需完成的实现

确认电子快门的声音事件具体在哪一步丢失：AP 配置、拍摄事件生成、原生 PIN 路由或输出选择。先对照供体真实调用链和 C2 实机配置，再修改指令；保留静音模式、关闭声音、录像音频及正常机械快门行为。之后生成范围明确、可逆的单独修改，离线验证逆向，再实测单拍／连拍同步与声音。能运行 root 子进程或通过局部就绪判断，均不能替代这些步骤。
