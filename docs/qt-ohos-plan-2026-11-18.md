# ChimeraX × 鸿蒙 PC：Qt6 移植技术调研与落地方案（2026-11-18）

- 工程根：`/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC`
- 目标：UCSF ChimeraX v1.11.1 全量移植到 OpenHarmony 6.1.1 / API 24 / aarch64 / 2in1，**界面与原版一致**
- 调研约束：macOS 本机、**不使用 hdc / 模拟器**；所有证据为宿主侧可复现产物
- 探测证据：[qt-ohos-probe-2026-11-18.json](../reports/qt-ohos-probe-2026-11-18.json)（`python3 tools/qt_ohos_probe.py`，耗时 4.5 s）
- 全部网页资料访问日期：**2026-11-18**

---

## 0. 一句话结论

**Qt 6 在 OpenHarmony 上不是"要不要移植"的问题，而是"选哪种绑定"的问题**：Qt 6.12 LTS 官方已带 HarmonyOS（technology preview）目标，本机已能拿官方预编译包用鸿蒙 SDK clang 交叉编译并链接成功（`<QtCore/qglobal.h>`、`<QtWidgets/QApplication>` 全部 exit=0）；真正未验证、也是唯一高风险项的是 **Python 绑定（PyQt6 / PySide6）在 aarch64-ohos 上的交叉构建**。

---

## 1. Qt6 在 OpenHarmony 上的现状

### 1.1 官方支持程度（有出处）

| 项目 | 事实 | 出处（访问 2026-11-18） |
|---|---|---|
| 支持状态 | **technology preview**，原文："Note: Qt for HarmonyOS is in technology preview and may change in future releases." | <https://doc.qt.io/qt-6/harmonyos.html> |
| 支持矩阵 | HarmonyOS **6.1.0（API 23）及以后**、**arm64-v8a**、Clang 15.0.4 (SDK 6.1.0)、产物为 **HAP**；宿主含 Windows x86_64 / Linux x86_64 / macOS x86_64 / **macOS Apple Silicon** | 同上 + <https://doc.qt.io/qt-6/supported-platforms.html> |
| 版本定位 | Qt **6.12 LTS**（2026-09-30 发布，5 年支持），HarmonyOS 首次进入 LTS 平台矩阵 | <https://lists.qt-project.org/pipermail/development/2026-October/047522.html> |
| 官方预编译包 | Qt Online Installer 里 "Qt 6.12.0 → HarmonyOS" 勾选项即装鸿蒙目标库（含 host 构建 + target 构建） | <https://wiki.qt.io/Qt_for_HarmonyOS/development_with_6.12.0_zh>；安装器 <https://www.qt.io/development/download-qt-installer-oss> |
| 从源码构建 | `configure -ohos-sdk <SDK_ROOT> -qt-host-path <HOST_QT_PATH> -ohos-arch arm64-v8a`，**必须先有一份同版本 host Qt** | <https://doc.qt.io/qt-6/harmonyos-building.html> |
| 前置条件 | OpenHarmony SDK 命令行工具（clang、sysroot、**hvigor**）；`OHOS_SDK_ROOT` 或 `-ohos-sdk` 指路；文档明确 "toolchain is currently developed and tested on **Linux**" | <https://doc.qt.io/qt-6/harmonyos-prerequisites.html> |
| 打包/部署 | 仅 CMake：`cmake --build . --target <t>_make_hap` → `harmonydeployqt` 收集 `libqohos.so`、Qt 模块、QML 模块，调 hvigor 出 HAP | <https://doc.qt.io/qt-6/harmonyos-building-deploying-apps.html> |
| IDE 配套 | Qt Creator HarmonyOS 插件（构建/打包/签名/安装/运行，需 provisioning profile） | <https://github.com/qt-creator/qt-creator/tree/master/src/plugins/harmonyos> |
| 社区/SIG 旧线 | OpenHarmony SIG-Qt，Qt **5.15** 系移植（Qt6 已被上游接管，此线仅作参考） | <https://gitee.com/openharmony-sig/qt>；SIG 说明 <https://gitcode.net/openharmony/community/-/raw/master/sig/sig-qt/sig_qt_cn.md> |

> **"未找到公开可用的 OHOS QPA"这一结论不成立**：Qt 6 的 OHOS QPA 就在上游主干里（见 1.2），并且官方 installer 直接发预编译 `libqohos.so`。只有 Qt 5 才必须依赖 Gitee SIG-Qt 分支。

### 1.2 上游 QPA 实测（本机源码，非二手资料）

本机已有 `build/qt/src/qtbase`（**qtbase 6.12.0**，`.cmake.conf: QT_REPO_MODULE_VERSION "6.12.0"`），其 `src/plugins/platforms/` 下存在 `ohos/` 平台插件，实测文件级构成：

| 能力面 | 上游实现文件（`src/plugins/platforms/ohos/`） |
|---|---|
| QPlatformIntegration | `qohosplatformintegration.cpp`、`qohosplatformscreen.cpp`、`qohosscreenmanager.cpp` |
| 窗口 / 合成 | `qohosplatformwindow.cpp`、`qohoswindowmanager.cpp`、`qohosfloatingwindow.cpp`、`qohosforeignwindow.cpp`、`qarkui/window.cpp`、`qarkui/qembeddedwindownode.cpp`、`qarkui/qxcomponentregistry.cpp` |
| EGL / GLES | `qohoseglplatformcontext.cpp`、`qarkui/vsync.cpp`（native_vsync） |
| 输入（键鼠触摸） | `qarkui/input.cpp`、`qarkui/qnativenodeapi.cpp`、`qohoseventdispatcher.cpp` |
| 输入法 / 软键盘 | `qohosinputcontext.cpp`、`qohosinputmethodeventhandler.cpp`、`qohosinputmethodproxy.cpp` |
| 剪贴板 | `qohosclipboardobject.cpp` |
| 文件对话框 | `qohosplatformfiledialoghelper.cpp`（走 UDMF/file share） |
| 平台主题 / 菜单 | `qohosplatformtheme.cpp`、`private/qohosplatformtheme_p.h`、`qohosstatusbarmenu.cpp` |
| 拖放 | `qarkui/qohosdragaction.cpp` |
| 其他 | `qohosdeviceinfo.cpp`、`qohosapppermissions.cpp`、`qohosdeadlockprotector.cpp`、`qohoseventdispatcher.cpp`、`qohosiconengine.cpp` |
| 元数据 | `ohos.json`：`{"Keys": ["ohos"]}`；插件目标 `qohos`；mkspec `ohos-clang` |

**SDK 侧依赖面已 100% 就绪**（本机 API 24 SDK 实测 `44/44`，缺头文件 0、缺库 0）：
`arkui/native_node.h`、`arkui/native_type.h`、`native_window/external_window.h`、`native_buffer`、`native_vsync`、`EGL`、`GLES3`、`window_manager/oh_display_manager.h`、`database/pasteboard`、`database/udmf`、`inputmethod/*_capi.h`、`multimodalinput/oh_input_manager.h`、`pixelmap_native.h`、`hicollie`、`hiappevent`、`hilog`、`file_uri`、`qos`，库 `libEGL/libGLESv3/libnative_window/libnative_vsync/libpasteboard/libudmf/libohinput/libohinputmethod/libpixelmap/libhilog_ndk.z/libace_ndk.z/...`。

### 1.3 本机已有的 Qt for HarmonyOS 预编译包（真实证据）

`build/qt/prebuilt/harmonyos-arm64/`（135 MB，2026-09-26 解出），包名 `6.12.0-0-202609280346qtbase-Linux-Ubuntu_24_04-Clang-Linux-HarmonyOS_ANY-ARM64.7z`：

- 安装树完整：`bin/`（qmake6、qtpaths6、qt-cmake）、`include/`（QtCore…QtWidgets）、`lib/`、`plugins/platforms/libqohos.so`（3.99 MB）、`mkspecs/ohos-clang/`、`metatypes/`、`config_qtbase.opt`
- CI 构建参数（`config_qtbase.opt`）实证 OHOS 交叉链：`-DOHOS_SDK_ROOT=/opt/harmonyos/command-line-tools/sdk/default/openharmony`、`-DOHOS_ARCH=arm64-v8a`、`-DQT_QMAKE_TARGET_MKSPEC=ohos-clang`、`-DQT_HOST_PATH=/home/qt/work/install`、vcpkg `arm64-ohos-qt`
- 依赖解析（`llvm-readelf -d`）：`libqohos.so` 24 个 NEEDED → 20 个落在本机 API 24 sysroot、3 个落 `libQt6Core/Gui/OpenGL`、1 个 `libc++_shared.so`；**全部可解析**（`prebuilt_loadable_against_sdk`）

**交叉编译实测（本次新增，最强证据）**，用 `.../native/llvm/bin/clang++ --target=aarch64-linux-ohos --sysroot=<API24 sysroot>`：

| 测试 | 命令要点 | 结果 |
|---|---|---|
| `#include <QtCore/qglobal.h>` | `-I include -I include/QtCore -c` | **exit=0**，产出 AArch64 relocatable `.o` |
| 链接可执行文件 | `-lQt6Core -Wl,--no-undefined` | **exit=0**，ELF64 / aarch64 / DYN |
| `QtWidgets/QApplication + QWidget` | `-lQt6Widgets -lQt6Gui -lQt6Core -shared` | **exit=0**，NEEDED = `libQt6Widgets.so, libQt6Gui.so, libQt6Core.so, libc++_shared.so, libc.so` |
| 目标头文件版本 | `-E -dM` | `QT_VERSION_STR "6.12.0"`、`QT_VERSION_MAJOR 6`、`MINOR 12`、`PATCH 0` |

---

## 2. 两条路线对比

> 口径来自 [bundle-matrix-2026-11-17](../docs/bundle-matrix-2026-11-17.md)：190 bundle / 1281 个 Python 文件，其中 **193 个文件（15.1%）直接 import Qt**，分布在 **90 个 bundle**；`tool.py`（45 个）是工具面板主体，`gui.py`（11）是主界面；Qt 绑定 `PyQt6`（bundle 内出现 4 次）为主、`PySide6`（3 次）经 `prereqs/qtshim` 兼容层。

| 维度 | **B：移植 Qt 6（qtbase + qtdeclarative，用官方 OHOS QPA）** | **A：ArkUI 复刻原版界面** |
|---|---|---|
| 可复用上游 UI 代码比例 | **100%**：193 个 Qt 文件、45 个 `tool.py`、`build_ui.py` 全部零改动运行 | **0%**：193 个 Qt 文件全部重写；`tool.py` 的面板/表格/滑块要逐一对标 ArkUI 组件 |
| 必须自建的中间层 | Python 绑定（PyQt6 或 PySide6）交叉构建 + `libqohos.so` 与 ArkTS AbilityStage 的胶水（`setupQtApplication`/`runQtChildProcess` 契约）+ HAP 打包集成 | Python ↔ ArkTS 全量 RPC（命令、模型树、属性表、事件回调），即自研一套"ChimeraX UI 协议" |
| 工作量（人周粗估） | **6–11 人周**：host Qt + 源码 configure 1、Qt-OHOS 预编译接入 0.5、PyQt6(sip) 交叉构建 2–4（PySide6+shiboken 则 4–8）、QPA/XComponent 胶水 1–2、剪贴板/文件对话框/输入法 0.5、打包+LGPL 合规 1、ChimeraX 接入回归 1–2 | **14–22 人周**：UI 骨架 4、45 个 tool.py 面板 6–8、表格/图表/对话框 3–4、RPC 层 2–3、像素级对齐返工 3–5 |
| 风险 | 集中在**单点**：Python 绑定能否 aarch64-ohos 交叉编译；technology preview 的 API 会变；Qt 官方只在 Linux 上测过 toolchain；SDK 6.1.1(API24) ≠ Qt 编译用 6.1.0(API23) 的符号风险 | 分散且不可收敛：ArkUI 组件与 Qt Widgets 的布局/字体/度量模型不同，**"界面一致"没有终点**，只能无限逼近 |
| 得到"界面一样"的程度 | **像素级一致可达**：同一份 Qt 绘制代码、同一套 QSS/图标/字体栈 | 结构相似、细节不可能一致（表格行高、滑块刻度、菜单弹出动画、字体 hinting） |
| 上游跟进 | 跟随 Qt 6.12 LTS 补丁（5 年支持） | 上游每次改 UI 都要重新人肉同步，永久分叉 |
| 3D 视图 | `graphics/src/opengl.py` 走 Qt GL 上下文，可复用现有 XComponent→EGL 通路 | 需把渲染结果从 Python 侧贴到 ArkUI Surface，等于自研合成器 |

**结论：B 与 A 的工作量不是同一量级，且只有 B 能满足"界面与原版一致"这一硬指标。A 不是备选路线，只是 B 失败后的降级方案。**

---

## 3. 分阶段里程碑（每阶段有可验收判据）

| 阶段 | 内容 | 验收判据（可机器判定） | 估时 |
|---|---|---|---|
| **M0 环境归零** | 装 Qt 6.12.0 host（macOS arm64）+ HarmonyOS 预编译包到**纯 ASCII 路径**；qtbase 源码 configure 打通 | `python3 tools/qt_ohos_probe.py --jobs configure` 中 `doc_ascii_prefix` 变体**不再**停在 `QtBuildHelpers.cmake:397 You need to set QT_HOST_PATH`；日志出现 `Building for: ohos-clang (arm64` | 3 天 |
| **M1 Qt-OHOS 可用性冻结** | 用官方预编译包 + 本项目 SDK 交叉编译两个最小程序（Widgets 空窗口；GL 空上下文）并进 HAP | ① 探测 JSON `qt_sdk_compile.verdict == qt_for_harmonyos_sdk_usable`；② `hvigor` 产出 HAP，`unzip -l` 内可见 `lib/arm64/libqohos.so`、`libQt6Core/Gui/Widgets.so`；③ `llvm-readelf -d` 无未解析 NEEDED | 1 周 |
| **M2 Python 绑定 go/no-go（关键闸门）** | 用私有 CPython 3.11.18(ohos) + 预编译 Qt，交叉构建 **PyQt6 的 QtCore/QtGui/QtWidgets 三个模块**（备选 PySide6 全量） | 设备侧（由应用线执行，允许 hdc）：`import PyQt6.QtCore as c; print(c.QT_VERSION_STR)` 输出 `6.12.0`；`QApplication` 能起事件循环 100 ms 无崩溃 | 2–4 周 |
| **M3 ChimeraX 界面起窗** | `chimerax` 走 Qt 主窗口；XComponent ↔ `libqohos.so` 容器接线；153 个 import-clean bundle 保持绿 | ① `import chimerax.<90 个 Qt bundle>` 逐个通过（脚本化，0 失败）；② 主窗口 + 菜单栏 + 至少 5 个工具面板可交互；③ 3D 视图首帧非黑 | 2 周 |
| **M4 像素级对齐** | 45 个 `tool.py` 面板、表格、对话框、剪贴板、文件对话框、输入法 | 与 macOS 原版同分辨率截图做逐像素比对：主窗口与 top-20 工具面板差异 ≤ 2%；剪贴板/中文输入/文件选择 3 项手工用例全通过 | 2–3 周 |
| **M5 合规与交付** | LGPL 义务落地 + 许可证结论执行 + 打包 | HAP 内 Qt 全部**动态链接**且 `.so` 可替换；随包 `LICENSES/Qt-LGPLv3.txt` + 源码获取指引 + 构建脚本；法务/上游书面结论归档 | 1 周 |

---

## 4. 许可证结论（实际影响，不是条文罗列）

先纠正一个容易搞错的点：**ChimeraX 本身不是 GPL**。`build/downloads/ChimeraX-src/License.md` 是 *UCSF ChimeraX Non-Commercial Software License Agreement*：仅限非商业用途，且**未经 The Regents 书面许可不得向第三方分发**（插件除外）。

| 组件 | 许可 | 对本项目的实际影响 |
|---|---|---|
| Qt 6.12（qtbase/qtdeclarative） | **LGPLv3**（或 GPLv3 / 商业） | 选 LGPLv3 可行：**必须动态链接**（`.so` 独立、可被用户替换），随包提供 LGPLv3 文本 + 对应源码/构建脚本获取方式。**不能**静态链接进单一 `.so`/可执行文件，否则触发"提供目标文件以便重链接"义务 |
| **PyQt6** | **GPLv3 或商业**（无 LGPL 选项） | 用开源 PyQt6 = 整个衍生作品须按 GPLv3 分发（含源码、允许商业再分发）。这与 ChimeraX 的"禁止第三方分发 / 仅非商业"**直接冲突**。三条出路：① 不公开分发（内部/自用，风险最小）；② 买 **PyQt6 商业授权** + 拿到 UCSF 书面分发许可；③ **改用 PySide6（LGPLv3）** |
| **PySide6** | **LGPLv3**（Qt for Python 官方） | 与 Qt LGPLv3 同构，方案最干净；代价是 shiboken 交叉构建比 sip 更难（M2 估时上浮）。ChimeraX 已有 `prereqs/qtshim` 兼容层，`PySide6` 在 bundle 矩阵中出现 3 次，切换成本可控 |
| ChimeraX 本体 | UCSF 非商业许可 | 公开上架（如侧载站/应用市场）需 UCSF 书面许可；仅做技术验证与内部演示不触发 |
| 鸿蒙侧 | OpenHarmony 系统库为 Apache-2.0/BSD 类 | 动态依赖系统 `.so`，无额外义务；签名与 2in1 上架要求另行处理 |

**建议**：技术验证先用 PySide6（LGPL 全线，无授权阻塞）；若 PySide6 交叉构建被证伪、而 PyQt6 走通，则必须同步推进"PyQt6 商业授权 + UCSF 分发许可"两件事，否则产物只能内部使用。

---

## 5. 推荐路线与理由

**先做 B（移植 Qt），并把 M2 定为唯一 go/no-go 闸门。**

1. Qt 侧已不是未知数：官方 6.12 LTS 带 OHOS QPA 与预编译包，本机实测 qglobal/Widgets 交叉编译链接全绿（见 1.3），SDK 依赖面 44/44 齐备。
2. "界面与原版一致"只有 B 能达成——同一份 Qt 代码，不是"模仿"。
3. B 的工作量集中在可提前验证的一点（Python 绑定），失败也能在 1–2 周内知道，沉没成本低；A 的返工风险贯穿全程。
4. 已有资产全部复用于 B：EGL+GLES3 上下文（XComponent→OHNativeWindow→eglCreateWindowSurface）、私有 CPython 3.11.18、numpy、命令通道；A 会把这些成果降级为"只服务非 UI 部分"。

**A 的定位**：仅当 M2 在 2 周内被证伪（PyQt6 与 PySide6 都构建不出可用的 aarch64-ohos 绑定），才切 A，且届时只承诺"结构一致 + 核心工具可用"，不承诺像素一致。

---

## 6. 探测卡点（本次真实报错，逐条可复现）

| # | 卡点 | 真实证据 | 处置建议 |
|---|---|---|---|
| 1 | **本机没有 host Qt**，交叉 configure 直接停住 | `CMake Error at cmake/QtBuildHelpers.cmake:397 (message): You need to set QT_HOST_PATH to cross compile Qt.`（变体 `doc_ascii_prefix`、`duplicate_prefix` 均如此） | 用 Qt Online Installer 装 macOS arm64 版 Qt 6.12.0（含 host 工具），再 `-qt-host-path` 指过去 |
| 2 | **工程路径含中文，Qt 的参数解析器会把选项值弄坏** | `-prefix /Users/huihui/Documents/鸿蒙pc适配/...` → `CMake Error ... QtProcessConfigureArgs.cmake:719: Invalid command line parameter 'pc'.`；同一命令换成 ASCII 前缀即通过解析 | 所有传给 Qt 的**选项值**（`-prefix`、`-qt-host-path`、`-DOHOS_SDK_ROOT` 之外的路径类参数）必须 ASCII；建议在 `/Users/huihui/qt-ohos-probe/` 下建独立构建树 |
| 3 | `cmake` 不在 PATH（macOS 无系统 cmake） | `configure: line 149: cmake: command not found`（变体 `bare_path`，exit 127）；SDK 自带 cmake 在 `native/build-tools/cmake/bin/cmake` | 探测脚本已自动把 SDK 的 cmake/ninja 前置进 PATH |
| 4 | `/tmp` 是符号链接，Qt 拒绝 | `cmake/QtBaseHelpers.cmake:47: The path "/tmp/qcfg" contains symlinks` | 构建树放在**非符号链接**目录（`$HOME/...`），或 `cd $(realpath ...)` |
| 5 | `-qt-host-path` 指向 OHOS target 包无效（架构不对） | 变体 `host_qt_ohos_prebuilt` 停在参数解析（路径含中文），且即便解析通过也会因 host 工具是 aarch64 而被拒 | host 与 target 必须成对：host=macOS arm64 构建，target=HarmonyOS arm64-v8a |
| 6 | SDK 版本错位 | Qt 官方支持矩阵写 HarmonyOS **6.1.0 / API 23**、Clang 15.0.4；本项目 SDK 是 **6.1.1.125 / API 24** | 预编译包 NEEDED 已能在 API 24 sysroot 全解析（实测），但运行期符号缺失仍需设备验证；若报 `undefined symbol`，用 6.1.0 SDK 重编或降级链接 |
| 7 | 官方只在 Linux 上测 toolchain | 文档原文："The Qt for HarmonyOS toolchain is currently developed and tested on Linux." | macOS 上若遇 hvigor/打包异常，改用 Linux 容器做打包环节（交叉编译本身已在 macOS 走通） |
| 8 | PyQt6/PySide6 无 aarch64-ohos 官方产物 | 公开渠道未见 OHOS wheel；ChimeraX 又要 PyQt6 API | **M2 闸门**：先只构建 QtCore 单模块验证 sip/shiboken 工具链，再放量 |

---

## 7. 下一步动作（谁做 / 多久 / 交付什么）

| # | 动作 | 负责 | 时长 | 完成标志 |
|---|---|---|---|---|
| 1 | 用 Qt Online Installer 安装 "Qt 6.12.0 → macOS arm64 + HarmonyOS" 到 `/Users/huihui/qt-ohos-probe/qt`（ASCII、非符号链接），导出 `QT_HOST_PATH` | 构建线（1 人） | 1–2 天 | `qtpaths6 -query QT_VERSION` 输出 6.12.0；`.../harmonyos/bin/qmake6 -query QT_ARCH` 可见 arm64 |
| 2 | 复跑探测：`python3 tools/qt_ohos_probe.py --jobs env,qt_sdk_compile,configure`，把 `doc_with_host_qt` 变体打开 | 构建线（1 人） | 0.5 天 | `configure` 越过 host-Qt 检查，日志出现编译器/平台识别行；新报错（如有）写入当日 JSON |
| 3 | **M2 前置 spike**：写一个最小 PyQt6（或 PySide6）交叉构建配方——只编 QtCore 模块，链接本机 CPython 3.11.18(ohos) 与预编译 Qt | Python 运行时线（1 人） | 3–5 天 | 产出 `PyQt6/QtCore.*.so`（aarch64-ohos），`llvm-readelf -d` 的 NEEDED 全部可解析；设备侧 `import` 成功（由应用线用 hdc 代跑） |
| 4 | 把 `libqohos.so` + Qt `.so` 装进现有 HAP 骨架，验证 XComponent 容器与 QPA 的接线契约（`setupQtApplication` / `runQtChildProcess`） | 应用线（1 人） | 1 周 | HAP 起窗，Qt 事件循环跑起，ArkTS 侧收到窗口创建回调 |
| 5 | 许可证与分发合规准备：LGPL 动态链接清单、`LICENSES/`、源码获取指引；PySide6 vs PyQt6 商业授权的决策会 | 项目负责人 + 法务 | 3 天（并行） | 一页决策记录归档到 `docs/` |

**决策点（第 2 周末）**：动作 3 若在 5 天内无法让 `import PyQt6.QtCore` 成功，则 M2 判负 → 立即切 A（ArkUI 复刻）并把目标从"像素一致"下调为"结构一致"，同时保留 Qt 线作为长期押注（Qt 侧证据已足够支撑后续重开）。

---

## 附：本次证据清单

- `reports/qt-ohos-probe-2026-11-18.json` —— 6 个 job 全量结果（env / headers 44-44 / smoke / qt_sdk_compile / configure 4 变体 / prebuilt 依赖解析）+ `upstream_facts`（网页出处与访问日期）
- `build/qt/logs/configure-*.log` —— 每次 configure 的完整 stdout/stderr
- `build/qt/prebuilt/harmonyos-arm64/` —— 官方 6.12.0 HarmonyOS 预编译包（含 `config_qtbase.opt` 原始 CI 参数）
- `build/qt/probe/` —— 交叉编译产物（`qt_sdk_compile`、`libqt_sdk_widgets_probe.so`、ELF 头）
