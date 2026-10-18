# 自定义 LUT／DCP：从文件到相机

[首页](../../README.zh-CN.md) · [English](../en/custom-lut.md)

**可以纯人工操作，不需要 AI。** `lut.py` 已包含转换、备份、真实设备写入、完整读回和还原；不必先安装 FL23。只接受已识别的 A7C II／ILCE-7CM2 2.01 程序。已在一台 Windows 相机上通过既有六款版本的单槽更新、预览／拍照及单文件重载验证。原厂首次导入和 macOS USB 写入仍未实测，请将它视为实验版。

先下载工具，再按[安装说明](manual.md)准备 Python 和 USB：

| 需要什么 | 下载／查看 |
|---|---|
| 直接使用，推荐 | [单文件 lut.py](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1-preview.2/lut.py)；保存文件，不要复制网页内容 |
| 完整工具、源码及说明 | [完整工具包 ZIP](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1-preview.2/a7c2-tools-2.1-preview.2.zip)；解压后进入含 `lut.py` 的目录 |
| 阅读／修改源码 | [本版源码](https://github.com/QAQLeonard/a7c2-fl23-research/tree/v2.1-preview.2) · [LUT 实现](https://github.com/QAQLeonard/a7c2-fl23-research/tree/v2.1-preview.2/src/looks) |

附件和校验值见[发布页](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.1-preview.2)。`main` 目前只有 FL23；LUT 最新开发源码在 [feature/lut-device-import](https://github.com/QAQLeonard/a7c2-fl23-research/tree/feature/lut-device-import)。初次使用建议下载上表的固定版本。

在 `lut.py` 所在目录打开终端，以下命令都从这里执行。Windows 使用 `python`，Mac 换成 `python3`；若按安装说明建立了虚拟环境，使用其中安装依赖的 Python。单文件和完整工具包的操作相同，区别只是[安装依赖的方法](manual.md#python-和依赖)。

## 1. 选择 DCP／LUT

准备自己的 `.dcp` 或 `.cube`；[参考包](profiles.md)提供原始 DCP。选一个自订栏位 1–6，填写希望显示的名称。一次导入一个栏位，多款依次执行；每次工作目录及还原记录都单独保存。

DCP 默认使用随工具提供的 **A7C II 单场景近似映射**，提取 LookTable／色调，不移植其他相机的传感器矩阵。这不是完整 Adobe 渲染，也不保证精确复刻富士／理光。自己的测量模型可用 `--calibration "model.json"` 替换；原始机身工厂校准不会被覆盖。

CUBE 必须输出 sRGB。输入已为 Sony ST sRGB 时加 `--input-space sony-st-srgb`；Log 等其他输入必须同时提供 `--input-space "空间名称" --bridge "ST到该空间.cube"`。工具不会把 Log LUT 当作 ST LUT。

## 2. 转换

```text
python lut.py import "look.dcp" --name "Classic Neg." --slot 1
```

不带 `--write` 时只准备、备份和检查，不安装色表。此命令会连接相机进行诊断，但不改写固件／名称／配方。无需编辑项目 JSON、编写补丁或找 AI 实现接口。

## 3. 备份相机

第 2 步的同一命令会先转换色表，再读取完整程序、68 个名称资源及保存／运行设置，生成两份核对过的备份、精确还原数据，并运行原生只校验。此处不用再执行另一条备份命令。

记下输出的 **Job 路径**。第二份默认在 `~/.a7c2-lut/backups`，建议通过 `--backup-dir "外置盘上的新空目录"` 放到另一块盘。保留整个 Job 和备份目录。

## 4. 写入

准备完成且显示 `PREFLIGHT_VERIFIED` 后，用实际电量执行：

```text
python lut.py install "JOB路径" --battery-percent 90
```

也可以合并前面几步：

```text
python lut.py import "look.dcp" --name "Classic Neg." --slot 1 --write --battery-percent 90
```

程序分别写入所需程序窗口、名称资源和选中栏位的 ST 配方。保留未选栏位和已有 FL2／FL3；导入栏位应继续使用 ST，基础风格选择器没有硬锁。写入期间保持供电和 USB，不操作相机。

## 5. 完整读回

程序自动核对完整 AP／CP、全部名称资源及设置保存结果；不是只比较几个补丁字节。出现错误会停止并保留证据。只有显示 `AWAITING_RELOAD`，才进入下一步。

## 6. 重新加载

所有读写结束后，拔掉 USB 和其他外接电源，正常关机；等存取灯熄灭后取出电池至少一分钟，再装回开机。第一次开机可能较慢。不要通过重刷来处理未重新加载。

## 7. 验证预览和照片

先不按快门，在 ST 与导入栏位之间多次随机切换，确认实时预览更新；再拍摄、回放新照片，检查名称和原有风格。拍摄正常不能代替预览验证。

接回大量存储模式，执行：

```text
python lut.py verify "JOB路径" --accept-photos
```

只有确实完成上述实机检查后才加 `--accept-photos`。程序还会检查新启动、磁盘程序、AP 运行片段和配方；它没有直接读取运行中的 CP 指令／色表。

## 8. 必要时还原

```text
python lut.py restore "JOB路径" --battery-percent 90
```

自动还原该次导入前的配方、程序和名称，完整读回后显示 `RESTORED_AWAITING_RELOAD`。重复第 6、7 步，再运行 `verify ... --accept-photos` 确认。多次导入应按相反顺序还原；后续导入会改变完整来源指纹，不能跳过它们强行还原旧 Job。

**如果断线或结果未知：**保留目录，先运行 `python lut.py recover "JOB路径"`。它只读取已有结果、核对状态和清理可确认归属的临时文件，不重新刷写；只有恢复到明确阶段后才运行 `python lut.py resume "JOB路径" --battery-percent 90`。仍为 `NEEDS_REVIEW` 就停止，不能重新执行 import／install 碰运气。

开发与复现细节见[AI 文档](lut-ai.md)，普通安装不需要阅读它。
