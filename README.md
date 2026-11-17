# ChimeraX — 鸿蒙 PC 通用兼容性准备

## 当前结论（2026-11-17 内置命令可执行）

**应用内跑通核心内置命令：`devel dump` 返回上游原生参数错误 `Missing or invalid "path" argument`；启动引导补齐 app_dirs/core_settings/toolshed 单例；设备断言 18/18。`toolshed list` 仍缺 `session.tools`，已如实记录。**

详见 [11 月 17 日内置命令可执行](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/chimerax-builtin-run-2026-11-17.md)。

## 上一结论（2026-11-17 内置命令依赖链）

**实测出核心内置命令（`debug`/`devel`/`pip`/`toolshed`）的依赖链：执行需要 `session.toolshed` → `chimerax.app_dirs`（appdirs）→ `core_settings.settings`；`packaging` 与 `appdirs` 已纳入暂存，内置命令执行仍待补齐。**

详见 [11 月 17 日内置命令依赖链](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/chimerax-builtin-commands-2026-11-17.md)。

## 上一结论（2026-11-17 命令语法输入）

**输入框直接吃 ChimeraX 命令语法：`cxprobe ui-command` → `cxprobe:ui-command`；Python 示例按钮 → `ChimeraX 16`；设备断言 17/17。**

详见 [11 月 17 日命令语法输入](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/app-command-syntax-2026-11-17.md)。

## 上一结论（2026-11-17 交互式命令通道）

**应用内已有命令输入框：点"执行"后页面输出 `ChimeraX 16`（持久 Session 的 app_name 与触发器数），设备断言 16/16。**

详见 [11 月 17 日交互式命令通道](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/app-command-channel-2026-11-17.md)。

## 上一结论（2026-11-17 执行 ChimeraX 命令）

**应用内成功执行真实 ChimeraX 命令：注册 `cxprobe` → `commands.run(session, "cxprobe hello-harmony")` → 返回 `cxprobe:hello-harmony|1|hello-harmony`；设备断言 15/15。**

详见 [11 月 17 日命令执行](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/chimerax-command-2026-11-17.md)。

## 上一结论（2026-11-17 Session 与命令子系统）

**鸿蒙应用内可导入 `chimerax.core.{colors,session,commands}`，并用上游 `minimal=True` 路径构造出真实 ChimeraX `Session`（`Session|True|16`）；设备断言 14/14。**

详见 [11 月 17 日 Session 与命令子系统](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/chimerax-session-2026-11-17.md)。

## 上一结论（2026-11-17 numpy 交叉编译）

**ChimeraX 锁定的 numpy 1.26.4 已交叉编译（meson + 设备端 exe_wrapper）并在应用内运行：`1.26.4 / sqrt(16.0)=4.0 / arange(5).sum()=10`，扩展从应用原生库目录加载。设备断言 12/12。**

详见 [11 月 17 日 numpy 交叉编译](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/chimerax-numpy-2026-11-17.md)。

## 上一结论（2026-11-17 ChimeraX core 触发器）

**在鸿蒙 HAP 内，真实 ChimeraX v1.11.1 的 `TriggerSet` 完成"添加触发器 → 注册 handler → 激活"全链路，读回 `cx_app_probe|fired`；`sortedcontainers` 依赖已随包分发；设备断言 10/10。** numpy 交叉编译已尝试但未成功（distutils 忽略 clang 交叉目标），命令解释器尚未跑通。

详见 [11 月 17 日 core 运行时](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/chimerax-core-runtime-2026-11-17.md)。

## 上一结论（2026-11-17 ChimeraX 包）

**真实 ChimeraX v1.11.1 Python 包已在鸿蒙应用中运行：`chimerax.version` 读回 `v1.11.1`，`chimerax.core.errors`/`logger` 导入成功，设备断言 9/9。** 仍未包含 Qt/PyQt 与 GUI 相关模块。

详见 [11 月 17 日 ChimeraX 包运行](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/chimerax-package-2026-11-17.md)。

## 上一结论（2026-11-17 应用入口）

**鸿蒙应用入口已跑通：HAP 安装启动后，应用沙箱内初始化私有 CPython 3.11.18，页面读回解释器版本、`math.sqrt(16)=4.0`、`_ctypes` 经 libffi 调 `libc.strlen=19`、`hashlib.sha256` 前 8 位 `2c1179ae`，设备断言 7/7 通过。** 仍未包含 Qt 与 ChimeraX 应用模块。

详见 [11 月 17 日应用入口](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/app-entry-2026-11-17.md)。

## 上一结论（2026-11-17 运行环境）

**私有 CPython 3.11.18 运行环境已在鸿蒙 PC 模拟器上真实运行：解释器自报 cpython 3.11.18、隔离与 UTF-8 模式为真，54 个原生扩展可导入，`_ctypes` 经 libffi 调用 `libc.so` 正确返回，设备检查 8 项断言全过。** 同时修复了设备上暴露的扩展符号可见性缺陷（启动器自我重新执行并预载私有 libpython）。仍未包含 Qt、应用模块与可安装 HAP。

详见 [11 月 17 日设备运行验证](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/device-runtime-2026-11-17.md)。

同时给出应用内嵌可用的结构性修复：`with-libffi-linked` 配置把扩展模块重链接为自带 `NEEDED libpython3.11.so.1.0` + `$ORIGIN/../../lib`，跳过启动器预载后设备上 8 项断言仍全过。

## 上一结论（2026-11-09）

**已在独立增强配置中补齐 libffi / `_ctypes`，鸿蒙 ARM64 的 CPython 3.11.18 私有运行环境现含 54 个通用扩展。89 项本地测试及重复归档核验通过，原 53 扩展基线完整保留。尚未进行该运行环境的设备测试，也未完成完整应用安装、鸿蒙启动或界面验收。**

**当前约束：另一项目尚未确认释放模拟器，本轮没有连接、启动、关闭或部署到模拟器。** 第一轮设备报告仅作历史记录。

最新进度详见 [11 月 9 日通用运行依赖补齐](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/libffi-runtime-2026-11-09.md)。

此前基线记录见 [11 月 9 日运行环境适配](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/runtime-adaptation-2026-11-09.md)。

上一轮记录见 [源码与启动适配](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/local-adaptation-2026-11-08.md)。

本目录是独立的通用兼容性适配工程，包含实际适配代码、版本锁定补丁及本地构建产物；不是 ChimeraX 源码镜像或重写的应用，也不包含可分发的完整安装包。未改动同一工作区中的其他工程。

### 本次只做什么

- 通用安装与卸载、应用入口、普通运行环境及依赖。
- 空白窗口、窗口尺寸、缩放、字体、菜单、文件选择器、键鼠等通用界面行为。
- 本地编写和交叉编译通用平台配置、启动器及运行环境检查；本轮验证不加载原应用、项目数据或专业功能。

不处理专业科研功能、相关算法、数据分析和研究流程。通用控件测试不代表完整应用已兼容。

## 已验证的事实

| 项目 | 本次实测结果 | 不能据此推断什么 |
|---|---|---|
| 开发机 | macOS / arm64，当前 Python 为 3.14.6 | 不是目标机运行环境 |
| 历史目标（11 月 8 日） | 型号 `emulator`，设备类型 `2in1`，aarch64 | 不是实体 PC 验收 |
| 历史目标系统 | OpenHarmony-6.1.1.125，API 24 | 不是所有鸿蒙 PC 的统一环境 |
| 历史原生检测（2026-11-08） | SDK 编译的独立 C 检测程序在目标运行成功 | 不是 ChimeraX 启动成功 |
| 历史运行库检测（2026-11-08） | 当时默认加载环境可加载 libc.so.6、EGL、GLESv3；当次查询的 Python 3.11、Qt 6、桌面 GL 库名未加载成功 | 不能排除应用私有目录中另有运行库；不能判断完整二进制 ABI 兼容性 |
| 历史 Qt 窗口检查（2026-11-08） | 当时开发机 Python 缺少 PyQt6，检查被明确阻断 | 没有 GUI 通过结果，目标 Qt 窗口也尚未测试 |
| 本地适配构建 | ARM64 启动器、引导库交叉编译及 ELF 检查通过 | 不含 Python/Qt/原应用，不是安装包 |
| 主机真实引导 | macOS CPython 3.11 私有目录、中文空格路径、隔离/UTF-8 检查通过 | 不是鸿蒙目标运行 |
| CPython 本地构建 | 增强配置的 3.11.18 运行库与 54 个扩展完成鸿蒙交叉编译，含静态 libffi 支持的 `_ctypes` | 缺少部分可选扩展，不是目标运行通过或完整标准库 |
| 运行环境归档 | 内容摘要和符号链接核验通过，重复生成一致 | 不是 HAP 或完整应用包 |
| 测试 | 当前 89 项独立本地测试通过；合成夹具有明确标记 | 不是上游功能或设备测试 |

第一轮目标临时检测程序已删除，并通过独立的文件不存在检查确认。未安装 HAP，未改系统设置或任何现有应用。

## 交付内容

- [最新：通用运行依赖补齐与限制](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/libffi-runtime-2026-11-09.md)
- [增强版 CPython 本地构建报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/cpython-local-with-libffi-2026-11-09.json)
- [增强版归档核验](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/runtime-archive-with-libffi-2026-11-09.json)
- [89 项本地测试报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/unit-tests-with-libffi-2026-11-09.json)
- [基线产物保留核验](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/baseline-preservation-with-libffi-2026-11-09.json)

此前阶段的构建、测试和设备观察报告（不是增强版设备结论）：

- [本轮运行环境适配与限制](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/runtime-adaptation-2026-11-09.md)
- [CPython 本地构建报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/cpython-local-2026-11-09.json)
- [通用运行环境归档核验](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/runtime-archive-2026-11-09.json)
- [69 项本地测试报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/unit-tests-2026-11-09.json)
- [详细兼容性审查](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/compatibility-audit-2026-11-08.md)
- [上游版本及元数据校验记录](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/upstream.lock.json)
- [环境实测报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/environment-2026-11-08.json)
- [模拟器原生检测报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/native-loader-2026-11-08.json)
- [开发机 Qt 阻断报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/qt-host-2026-11-08.json)

本地验证工具均为独立实现，不导入上游应用。启动适配器保留原应用入口，但本次仅执行独立单元测试和标准库引导检查。第一轮运行库检测曾在明确指定连接目标后临时上传自有检测程序，现已清理；本轮未再使用设备。

## 当前推荐：只做本地适配验证

```sh
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/build_harmony_local.py'
```

该工具只交叉编译并检查 ELF，不联系设备。下列默认命令复查保留的基线；增强版须按最新进度文档显式选择 `with-libffi` 配置与独立归档路径：

```sh
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/build_cpython_harmony.py'
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/package_generic_runtime.py'
```

这些命令同样不联系设备。详细的补丁应用及真实主机引导复查方法见本轮进度文档。

## 第一轮设备复查方法（当前不要运行）

下面设备相关命令仅保留作历史复现说明。**模拟器被另一个窗口使用期间不要执行；本轮没有执行它们。**

只读盘点；`auto` 仅在连接一个目标时生效，多目标时要求指定目标，不会擅自选择：

```sh
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/inspect_environment.py' \
  --hdc '/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc' \
  --device auto \
  --output '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/environment-recheck.json'
```

编译并临时运行原生检测程序，仅限已授权的开发目标：

```sh
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/run_native_probe.py' \
  --sdk '/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native' \
  --hdc '/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc' \
  --device auto \
  --output '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/native-recheck.json'
```

空白 Qt 窗口检查需先有**适用于执行端的** Python 和 PyQt6/PySide6。工具不会代装依赖，不会把开发机窗口结果当作目标机结果。下面命令在当前开发机预期因缺少 PyQt6 而返回退出码 2：

```sh
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/qt_window_probe.py' \
  --binding PyQt6 --quit-after 3 \
  --report '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/qt-recheck.json'
```

可选 `--opengl` 只检查空白的桌面 OpenGL 3.3 上下文，不加载数据。中文输入法、实际键鼠、高分屏、多显示器、系统文件选择器仍须人工验收；自动按键事件不是人工输入验收。无显示或 offscreen/minimal 插件不计为界面通过。

独立单元测试（测试输入均明确标为合成数据，不写入实测记录）：

```sh
python3 -m unittest discover \
  -s '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tests' -v
```

## 完整应用仍缺少的前置条件

1. 核实允许内部改动和后续分发的授权范围；当前上游是带用途与分发限制的自定义许可证，不能按 MIT/Apache 处理。
2. 单独落实目标平台 Python 3.11、Qt 和 Python Qt 绑定的可构建、可加载方案。
3. 本地启动入口适配已实现；目标空白窗口、通用显示与生命周期验证通过后，再集成完整应用并生成正式安装包。不能只把 Linux 平台名改成 HarmonyOS，或把 Linux ARM64 轮子当作原生鸿蒙依赖。
4. 有实体鸿蒙 PC 后，单独验收安装、卸载、启动、退出及界面交互，不混用模拟器结论。
