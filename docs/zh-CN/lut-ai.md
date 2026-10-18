# LUT 导入器：AI 复现说明

[首页](../../README.zh-CN.md) · [English](../en/lut-ai.md)

[用户教程](custom-lut.md)是八步人工流程，设备命令已经实现，不能用生成离线清单代替安装。先读[源码约束](../../src/looks/AGENTS.md)、[集成细节](technical/integration.md)和[历史失败](technical/failures.md)。FL23 入口和文件保持不动。

## 执行用户流程

```text
python -m pip install -r src/looks/requirements-device.txt
python lut.py doctor --device
python lut.py import "REFERENCE.dcp" --name "显示名称" --slot 1
python lut.py install "JOB路径" --battery-percent 90
```

默认模型是共用的单场景近似映射，不是机身工厂校准或完整 Adobe 渲染。更好的测量模型用 `--calibration` 指定。CUBE 必须声明 ST 输入或提供桥接，不能默认把 Log 当作 ST。电量使用实际读数，不照抄示例。

读写全部结束后，由用户完整断电加载并检查预览／新照片／回放，再执行 `verify JOB --accept-photos`。不能替用户虚构验收，也不能由读回／模拟推定开机安全。还原用 `restore JOB`，再加载和实机验收；连续导入按最新到最旧还原。

## 代码对应关系

| 源码 | 职责 |
|---|---|
| `devicecli.py`、`devicejob.py` | 人工命令、持久工作状态、拟合、双份备份、原生事务、读回、重载／还原／恢复 |
| `device_layout.py`、`assets/runtime-v1.json` | 精确原厂／FL23／独立 LUT 来源，以及已有 full7-v4 更新 |
| `devicesession.py`、`devicelock.py` | 复用 FL23 通讯；独立有限临时路径、机身身份、进程／工作锁和单次加载执行 |
| `devicesettings.py` | 从新鲜描述符推导选中字段、ST 基线、全设置保留和独立只读遥测对照 |
| `resources.py`、`nameworker.py`、`native/names.c` | 68 个名称资源原子替换、原厂2860→2866扩展和精确逆向 |
| `nativebuild.py` | Zig 编译绑定本次工作的程序，检查 ELF／重定位／依赖／上传上限 |
| `dev/release/build_lut.py` | 校验后释放内部文件的单文件打包，不包含机身数据或外部输入 |

最后一项以外均在 `src/looks` 下。一条命令编排不代表混成一次写入：程序、名称、设置分别提交。DCP 不导入／覆盖工厂校准或受保护 CP 单元。基础风格选择器仍可编辑，不宣称硬锁 ST。

## 精确适配范围

- full7-v4 AP 固定为 `six.AP_SHA`；CP 仅将六张表／校验值排除于代码身份，其他字节全部锁定。每次工作仍保存完整前后哈希。
- 首次安装只接受 `runtime-v1.json` 列出的原厂或匹配 FL23 程序对。独立 AP 通过完整重建核对栏位位图，保留未选默认配方／功能开关；部分导入保留其他栏位动态名称。
- 新名称分派位于既有132字节转换函数；旧10项跳表及其2字节对齐填充改为12项原生映射。离线检查了唯一页／加法引用、外部跳入、原虚调用地址、程序头和重定位。这不是实机启动证据。
- 首次 CP 使用移除旧 DCP 载荷后的 v4 运行代码，未选位置使用零表。原厂 AP 不开启 FL23 菜单，也不配置 FL23 色彩／校准单元；不要求先装 FL23。
- 名称通过原子 inode 替换保留旧 mmap；逆向可使用原硬链接或精确重建。不复用曾导致重启的显示／段／图标修改。

## 中断处理

保留 `job.private.json`、两份来源、输入／模型、候选、清单、原生程序和原始证据，不能修改 JSON 强行推进阶段。

| 状态 | 下一步 |
|---|---|
| `PREFLIGHT_VERIFIED` | 显式 install |
| `AWAITING_RELOAD` | 用户重载／验收，然后 verify |
| `NEEDS_REVIEW` | recover 读取已有结果，不重发加载器 |
| 已确认的程序／名称／设置阶段 | 显式 resume 剩余工作 |
| `RESTORED_AWAITING_RELOAD` | 重载并验证还原 |

只出现服务身份时，仅允许读取／清理已确认归属的临时文件；新执行必须重新识别普通身份。未知原生结果保持原状。有明确失败报告时，也必须先核对回滚／只读状态及完整来源／目标，才能继续。保存遥测只能接受独立观察到的变化，不全局忽略或写回遥测。

## 测试与打包

在 `src/looks` 下运行：

```text
python -m unittest discover -s tests -v
```

可选指令／原生重放依赖在 `requirements-research.txt`。完整镜像测试通过 `A7C2_RESEARCH_FIXTURES` 读取机主私人样本；没有样本是跳过，不是通过。仓库根目录还应运行原有 FL23／主机测试、`dev/release/check_publication.py`，再运行 `dev/release/build_lut.py` 并验证实际单文件命令。

交付报告分别记录软件检查、精确镜像复现、设备读回、运行状态、相机行为及 Mac USB 验收。这版新导入器尚未进行相机／Mac 实机验收；不能为演示而放宽来源检查。
