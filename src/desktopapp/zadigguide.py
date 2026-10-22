"""Manual Zadig driver steps for Windows; the same procedure as the README."""
URL = 'https://zadig.akeo.ie/'
TITLE = '用 Zadig 手动安装驱动'
TEXT = """自动安装驱动失败时，大多数电脑改用 Zadig 手动安装就能成功。整个过程不写入相机，只更换这台电脑上相机两个 USB 身份所用的驱动。

相机有两个 USB 身份，两个都要装驱动：
· 普通连接：Zadig 里显示 ILCE-7CM2，USB ID 054C 0E8A。相机开机、选海量存储、接上电脑后出现。
· 服务模式：Zadig 里显示 Sony USB Device，USB ID 054C 0336。本软件认证之后才出现，相机通常显示“请检查所连接的设备”。

准备
1. 点下方“打开 Zadig 下载页”，下载最新版 zadig-x.x.exe（单个文件，不用安装）。
2. 相机开机，菜单里的 USB 连接选“海量存储（Mass Storage）”。用能传数据的线直接接电脑，不要经过扩展坞；台式机用机箱后面的口。

第一部分：给 0E8A 装驱动
1. 右键 Zadig，选“以管理员身份运行”。询问是否检查更新时，选哪个都可以。
2. 在菜单 Options 里勾选 List All Devices。不勾选就看不到相机。
3. 在上方下拉框里选 ILCE-7CM2。
4. 核对 USB ID 一栏是 054C 0E8A。对不上就是选错了，换一项再核对。不要给键盘、鼠标、U 盘、网卡等其他设备换驱动。
5. 在绿色箭头右边的驱动框里，用上下箭头选 libusbK。
6. 点 Replace Driver（当前没有驱动时显示为 Install Driver），等 1–2 分钟，直到提示 The driver was installed successfully。
7. 换好后，电脑上相机的盘符消失、相机显示“请检查所连接的设备”，都是正常的。

第二部分：让 0336 出现，再给它装驱动
1. Zadig 先不要关。在本页点“准备两阶段驱动并测试连接”。
2. 软件会沿用刚装好的 0E8A 驱动进行认证，之后相机变成 Sony USB Device（054C 0336）。
   · 日志出现“服务连接成功，驱动准备结束”：已经完成，直接看第三部分。
   · 日志提示 0336 没有驱动、接口打不开，或一直等不到 0336：先不要拔线，也不要关相机，继续下一步。
3. 回到 Zadig，再点一次 Options → List All Devices 刷新列表，选 Sony USB Device，核对 USB ID 是 054C 0336。
   · 列表里找不到 0336，说明相机已经退出服务模式：回到本部分第 1 步再测一次，0336 出现后马上在 Zadig 里刷新。
4. 驱动同样选 libusbK，点 Replace Driver 或 Install Driver，等到提示成功。

第三部分：断电后重新测试
1. 拔掉 USB，相机关机，取出电池约 1 分钟。装回电池开机，选海量存储，重新接上。
2. 在本页再点一次“准备两阶段驱动并测试连接”。日志出现“服务连接成功，驱动准备结束”后，就可以去首页一键安装。

检查是否装对：打开 Windows 设备管理器，应能看到“libusbK USB Devices”分类，下面有 ILCE-7CM2；装过 0336 后还会有 Sony USB Device。

遇到问题
· libusbK 安装失败：重新以管理员身份运行 Zadig 再试；仍然失败，可以改选 WinUSB。本软件可以使用 WinUSB、libusbK、libusb0 中的任意一种。
· 下拉框里没有相机：确认已勾选 List All Devices，相机已开机并选了海量存储，换一根能传数据的线。
· 想恢复原样：在本页点“卸载相机驱动，恢复 Windows 默认连接”，Zadig 装的驱动也会一起卸载。之后拔插 USB，相机会重新显示为 U 盘。
"""
