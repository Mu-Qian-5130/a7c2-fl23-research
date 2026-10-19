# 竖屏拍摄显示——开发预览

[首页](../../README.zh-CN.md) · [English](../en/vertical-display.md)

用于 **A7C II／ILCE-7CM2，固件 2.01**。此分支提供试验性的拍摄信息转向工具。一台通过 Windows 连接的相机已确认：开启原生开关后曝光数字能转向，补上三条资源别名后，大部分缺失的竖屏图标恢复。Av／Tv／Ev／ISO 拨轮功能提示的位置已由用户确认可以保留。

**已保存的竖屏设置保持关闭。**工具只开启当前运行会话；三条文件系统别名会保留，直到主动移除。不替换 AP／CP 程序、原图形文件、图形索引、创意外观或已保存设置。这不是 Sony 官方更新文件，也不是永久开机启用版。

## 使用

下载或克隆**本分支的完整源码**，现有 Release 工具包不包含这项试验。使用 64 位 Python 3.10+。以下 Windows 命令使用 `python`，macOS 改成 `python3`。沿用[现有 USB 配置](manual.md)，相机设为大量存储模式；操作期间保持电量充足、USB 稳定连接，不同时运行其他相机工具。

```text
python -m pip install -r src/vertical/requirements.txt
python vertical.py status --firmware-version 2.01
python vertical.py enable --firmware-version 2.01
```

`enable` 检查运行／保存开关和资源路径，缺少时新增三条别名，完整读取别名内容并与原图形逐字节比较，最后开启 RAM 开关。已有且目标正确的别名会复用。私人事务报告保存在 `vertical-work`；因为不改写原程序或图形，不重复存放整份程序／图形备份。需要指定位置时加 `--work-dir "另一个目录"`，后续命令继续使用该目录。

完成后保持开机，拔 USB，分别向两侧竖握，检查拍摄图标、边框和曝光数字；保持开机接回后可运行 `status`。相关 RAM 重载后会回到保存值，不能用普通关开一次就断定已经重载。后续会话需要开启时，再执行 `enable`。工具不保存开关，相机后续是否自动保存尚未经过长期验证。

## 关闭或移除

```text
python vertical.py disable --firmware-version 2.01
python vertical.py remove --firmware-version 2.01
```

`disable` 关闭运行开关，保留资源别名。`remove` 先关闭运行开关，再删除目标完全匹配本试验的三条符号链接；其他链接或普通文件不会覆盖、删除。撤销竖屏试验请用此命令，现有 FL23／LUT Recovery 不负责清理新增的资源别名。

如果中断或结果未知，保留 `vertical-work` 及报告，不要反复执行 `enable`。`status` 不会自动清除未解决的事务；若相机上残留原生临时文件，需要先核查，再继续执行。

## 实现与 AI 复现

源码：[入口](../../vertical.py)、[主机事务](../../src/vertical/verticaltool/device.py)、[原生模块](../../src/vertical/native)、[离线测试](../../dev/vertical)。

- 原生参数 `0x7e3`，主 RAM 地址偏移 `0x7e732b8`：**0 开、1 关**。固定四字节写入前核对 `0x286caa0` 的 getter 指令及原生机型。不新增固件来源哈希白名单。
- 备份键 `0x02cf1906`：保存记录与 Backup-RAM 记录均须保持 `01`。主运行 RAM 是另一个值，工具不调用备份写入／保存 API。
- 在 `/usr/share/app` 新增 `image_00_23_IPSX.uxc → image_00_32_IPSX.uxc`，`01`、`02` 同理。复用本机原图形，不换其他机型图形、不扩展图形索引或 ELF 段。模块会恢复并检查 `/usr` 为只读。
- 使用共用相机锁，一次服务会话完成检查、修改和完整读回。已知新增失败可清理自身链接，原生结果未知则停止，不重放写入。实际拍摄显示必须独立于读回结果验证。

可选的源码重编译与测试，不需要相机或私人固件：

```text
python -m pip install -r dev/vertical/requirements.txt
python dev/vertical/build_workers.py
python -m unittest discover -s dev/vertical -v
```

四个小型 ARM64 模块已附在 `src/vertical/assets`，普通使用不需要 Zig。`build_workers.py --zig 路径` 可指定现有 Zig 可执行文件。

## 验证边界

41 个原生系统调用场景、15 项主机／命令行用例离线通过，覆盖 RAM 开关、既有或冲突别名、读回失败、清理和未知结果。此前私人试验已在一台相机上显示大部分拍摄图形；本次整合后的公开 CLI 经过离线测试，没有另做一次实机安装。别名移除、永久开机启用、长期使用、完整 MENU 转向及 macOS USB 尚未实测；复用的横屏图形与专用竖屏图形仍可能存在尺寸或形状差异。
