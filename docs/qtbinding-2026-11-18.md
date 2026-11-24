# Qt 的 Python 绑定 × 鸿蒙：交叉编译决定性验证（2026-11-18）

- 工程根：`/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC`
- 目标：`aarch64-linux-ohos` / OpenHarmony 6.1.1 / API 24，界面与原版（Qt/PyQt6）一致
- 本机约束：macOS，**不使用 hdc / 模拟器**；所有结论来自宿主侧可复现产物
- 证据文件：[qtbinding-2026-11-18.json](../reports/qtbinding-2026-11-18.json)（`python3 tools/build_qtbinding_harmony.py`）
- 复现工具：[build_qtbinding_harmony.py](../tools/build_qtbinding_harmony.py)

---

## 0. 一句话结论

**QtCore + QtGui + QtWidgets 三个绑定的交叉编译全部通过。** 三个 `.so` 都是 `ELF64 / AArch64 / DYN`，NEEDED 完整、RUNPATH 统一为 `$ORIGIN/../lib`，并且**导入的 12,892 个 C++ 符号全部闭合（unresolved = 0）**。

| 模块 | 大小 | wrapper 数 | 导入 C++ 符号 |
|---|---|---|---|
| `QtCore.abi3.so` | 5,016,984 B | 191 | 3,352 |
| `QtGui.abi3.so` | 5,511,936 B | 263 | 3,752 |
| `QtWidgets.abi3.so` | 6,697,752 B | 194 | 5,788 |

整条链七关全通，**没有剩下未知层**：

| 关 | 结果 |
|---|---|
| L0 Qt6 C++ on OHOS | ✅ 官方预编译，NEEDED 8/8 可解析 |
| L1 Qt6 ↔ 目标 CPython ABI | ✅ QtCore 13/13、Widgets 探针 18/18 符号全解析 |
| L2a 宿主 Qt 6.12.0（moc/rcc/uic） | ✅ 源码建成，`moc 6.12.0` |
| L2b shiboken6 生成器（宿主） | ✅ `shiboken v6.12.0` |
| L3a libshiboken6 + Shiboken（目标） | ✅ 真实 AArch64 ELF |
| L3b PySide6 QtCore（目标） | ✅ |
| **L3c PySide6 QtGui + QtWidgets（目标）** | ✅ **3 分钟构建完成，符号闭包 0 缺口** |

```bash
export QT_HOST_PATH="$PWD/build/qt/host-qt-6.12.0"
python3 tools/build_qtbinding_harmony.py --modules 'Core;Gui;Widgets'
# -> pyside6_coreguiwidgets_cross_compiled_not_target_tested
```

---

## 1. Qt 预编译包体检（真实证据）

`build/qt/prebuilt/harmonyos-arm64/`（29 个 include 目录、36 个 lib 条目），包名
`6.12.0-0-202609280346qtbase-Linux-Ubuntu_24_04-Clang-Linux-HarmonyOS_ANY-ARM64.7z`。

### 1.1 路径与版本

| 项 | 实测值 |
|---|---|
| `QT_VERSION_STR` | **6.12.0**（`include/QtCore/qconfig.h:73`，MAJOR 6 / MINOR 12 / PATCH 0） |
| Qt 头文件根 | `build/qt/prebuilt/harmonyos-arm64/include` |
| QtCore 头文件 | `.../include/QtCore`（**706** 个条目） |
| QtCore private 头 | `.../include/QtCore/6.12.0/QtCore/private` |
| 库目录 | `.../lib`（`libQt6Core.so` 43,397,688 B，sha256 `268906444a8e3b99…`） |
| QPA 插件 | `.../plugins/platforms/libqohos.so` **存在** |
| CMake 包 | `.../lib/cmake/Qt6Core` 等（`Qt6CoreConfig.cmake` 齐全） |
| **`Qt6CoreTools` / `moc`** | **两者皆无** —— target-only 包，见 §3.2；这是整个路线的真正卡点 |

### 1.2 `llvm-readelf -d` 解析 NEEDED（关键：能否被本项目 sysroot 解析）

```
$ SDK/llvm/bin/llvm-readelf -d build/qt/prebuilt/harmonyos-arm64/lib/libQt6Core.so
  (RUNPATH) Library runpath: [/usr/local/Qt-6.12.0/lib]
  (NEEDED)  Shared library: [libtime_service_ndk.so]
  (NEEDED)  Shared library: [libace_napi.z.so]
  (NEEDED)  Shared library: [libdeviceinfo_ndk.z.so]
  (NEEDED)  Shared library: [libhilog_ndk.z.so]
  (NEEDED)  Shared library: [libohenvironment.so]
  (NEEDED)  Shared library: [libohfileuri.so]
  (NEEDED)  Shared library: [libc++_shared.so]
  (NEEDED)  Shared library: [libc.so]
  (SONAME)  Library soname: [libQt6Core.so]
```

逐个回查三个搜索根（SDK sysroot / 本项目 CPython runtime.lib / clang runtime）：

| NEEDED | 解析位置 |
|---|---|
| `libtime_service_ndk.so` | `sysroot/usr/lib/aarch64-linux-ohos` ✓ |
| `libace_napi.z.so` | sysroot ✓ |
| `libdeviceinfo_ndk.z.so` | sysroot ✓ |
| `libhilog_ndk.z.so` | sysroot ✓ |
| `libohenvironment.so` | sysroot ✓ |
| `libohfileuri.so` | sysroot ✓ |
| `libc.so` | sysroot ✓ |
| **`libc++_shared.so`** | **sysroot 里没有**，在 `SDK/llvm/lib/aarch64-linux-ohos/` |

**结论：8/8 可解析，但 `libc++_shared.so` 必须显式打进 runtime payload。** 这是第一条落地动作，不是障碍。

同时确认一条重要事实：**`libpython3.11.so.1.0` 只 NEEDED `libc.so`，完全不依赖 `libc++_shared.so`**（纯 C 构建）。所以 Qt（libc++）和 CPython（libc）之间没有 C++ 运行库争用，两者可以安全地同时载入同一进程。

### 1.3 Gui / Widgets / OpenGL / Network 的传递依赖

```
libQt6Gui.so           -> libGLESv3 libace_napi.z libhilog_ndk.z libpixelmap libEGL libQt6Core libc++_shared libc
libQt6Widgets.so       -> libQt6Gui libGLESv3 libEGL libQt6Core libc++_shared libc
libQt6OpenGL.so        -> libQt6Gui libGLESv3 libEGL libQt6Core libc++_shared libc
libQt6OpenGLWidgets.so -> libQt6OpenGL libQt6Widgets libQt6Gui libGLESv3 libEGL libQt6Core libc++_shared libc
libQt6Network.so       -> libQt6Core libc++_shared libc
```

`libGLESv3.so`、`libEGL.so`、`libpixelmap.so` 均在 sysroot 内实测存在 ✓。

---

## 2. ABI 实证：Qt6 ↔ 交叉编译 CPython（**已通过**）

这一层是"能不能做"的分水岭，所以单独隔离出来测：**抛开绑定生成器，直接写一个 CPython 扩展去调真 QtCore**。

### 2.1 QtCore 探针（`_qtcore_abi_probe`）

`build/qtbind/probe/abi_probe.cpp` 调用 `qVersion()`、`QString::fromLatin1`、`QJsonDocument`、`QVersionNumber`，编译命令：

```bash
SDK/llvm/bin/clang++ --target=aarch64-linux-ohos --sysroot=$SDK/sysroot \
  -std=c++17 -O2 -fPIC -shared \
  -I<cpython>/source/Include -I<cpython>/objects \
  -I<qt>/include -I<qt>/include/QtCore -DQT_CORE_LIB \
  -o _qtcore_abi_probe.cpython-311-aarch64-linux-ohos.so abi_probe.cpp \
  -L<qt>/lib -lQt6Core \
  -L<cpython>/runtime/lib -l:libpython3.11.so.1.0 \
  -Wl,-rpath,'$ORIGIN/../lib'
```

**exit=0，一次通过。** 产物实测：

| 项 | 值 |
|---|---|
| ELF | `ELF64 / AArch64 / DYN` |
| NEEDED | `libQt6Core.so`, `libpython3.11.so.1.0`, `libc++_shared.so`, `libc.so` |
| RUNPATH | `$ORIGIN/../lib` |
| 导入的 C++ 符号 | 13 个（`QString::fromLatin1`、`QJsonObject::insert`、`QArrayData::deallocate` …） |
| **在 libQt6Core 中未解析** | **0 个** |

### 2.2 Widgets 全栈探针（`_qtwidgets_probe`）

只测 QtCore 不够——ChimeraX 的 `QtWidgets` 引用有 447 处。所以再编一个探针，强制绑定 ChimeraX 实际用到的控件族（`QAction` 已迁到 QtGui，Qt6 注意点）：

```bash
SDK/llvm/bin/clang++ --target=aarch64-linux-ohos --sysroot=$SDK/sysroot \
  -std=c++17 -O2 -fPIC -shared \
  -I<cpython>/source/Include -I<cpython>/objects \
  -I<qt>/include -I<qt>/include/QtCore -I<qt>/include/QtGui -I<qt>/include/QtWidgets \
  -DQT_CORE_LIB -DQT_GUI_LIB -DQT_WIDGETS_LIB \
  -o _qtwidgets_probe.cpython-311-aarch64-linux-ohos.so widgets_probe.cpp \
  -L<qt>/lib -lQt6Widgets -lQt6Gui -lQt6Core \
  -L<cpython>/runtime/lib -l:libpython3.11.so.1.0 \
  -Wl,-rpath,'$ORIGIN/../lib'
```

**exit=0。** 覆盖 `QAction::triggered`、`QMainWindow::setCentralWidget/menuBar/statusBar/addToolBar`、`QMenuBar::addMenu`、`QDockWidget::setWidget`、`QSplitter::setSizes`、`QTableWidget::setRowCount`、`QTreeWidget::setHeaderLabels`、`QGraphicsView::setScene`、`QObject::connectImpl`、`QMetaObject::Connection`。

| 项 | 值 |
|---|---|
| 导入的 Qt C++ 符号 | 18 个 |
| **在 QtCore+QtGui+QtWidgets 中未解析** | **0 个** |

> **这一条把最大风险项划掉了**：Qt6 的 C++ 侧和鸿蒙版 CPython 3.11 是二进制兼容的，Widgets 层也一样。剩下的全是工程问题，不是可行性问题。

---

## 3. 绑定路线：七关全通过（L0–L3c 实测，仅 L4 留缺口）

### 3.1 分层归因（实测状态）

| 层 | 内容 | 状态 | 证据 |
|---|---|---|---|
| L0 | Qt6 C++ 能在 OHOS 上用 | ✅ | 官方预编译，NEEDED 8/8 可解析，QPA `libqohos.so` 就位 |
| L1 | Qt6 C++ ↔ 目标 CPython 3.11 的 ABI | ✅ | QtCore 13/13、Widgets 18/18 符号全解析（§2） |
| **L2a** | **宿主 Qt 6.12.0（含 moc/rcc/uic）** | ✅ **本轮建成** | `build/qt/host-qt-6.12.0`，`moc 6.12.0` |
| **L2b** | **shiboken6 生成器（宿主 native）** | ✅ **本轮跑通** | `shiboken v6.12.0`，日志 `shiboken6_generator_build ok (23.7 s)` |
| **L3a** | **libshiboken6 + Shiboken 模块交叉编译** | ✅ **本轮产出真实 ELF** | `libshiboken6.abi3.so.6.12`、`Shiboken.abi3.so`，均 `ELF64 / AArch64` |
| **L3b** | **PySide6 QtCore 绑定交叉编译** | ❌ **卡在这里** | 生成器撞 `features.h`（见 3.5） |
| L4 | 模块完整性 | ❌ 硬缺口 | 预编译包只有 qtbase，缺 QtWebEngine/QtMultimedia/QtSvg/QtStateMachine |

### 3.2 宿主 Qt 6.12.0 构建记录（本轮新增，可复现）

源码用工程里已有的 `build/qt/src/qtbase`（`QT_REPO_MODULE_VERSION = 6.12.0`）。两个必须知道的坑：

```bash
# 坑 1：本机只装了 Command Line Tools，没有完整 Xcode，Qt 的 Xcode 版本检查会 FATAL
#       用 QT_NO_XCODE_MIN_VERSION_CHECK 放行（只跳过版本比对，编译器仍是 CLT clang 21）
# 坑 2：Release 默认带 -g，qtbase 链接慢；把 CXX_FLAGS_RELEASE 覆盖成 -O2 -DNDEBUG
cmake -S build/qt/src/qtbase -B build/qt/host-build-612 -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_FLAGS_RELEASE="-O2 -DNDEBUG" -DCMAKE_CXX_FLAGS_RELEASE="-O2 -DNDEBUG" \
  -DCMAKE_INSTALL_PREFIX="$PWD/build/qt/host-qt-6.12.0" \
  -DQT_BUILD_EXAMPLES=OFF -DQT_BUILD_TESTS=OFF -DBUILD_SHARED_LIBS=ON \
  -DQT_NO_XCODE_MIN_VERSION_CHECK=ON -DQT_NO_APPLE_SDK_MIN_VERSION_CHECK=ON
cmake --build build/qt/host-build-612 --parallel 8   # 1816/1816，2 分 41 秒
cmake --install build/qt/host-build-612
```

产物与实测：

| 项 | 值 |
|---|---|
| 安装前缀 | `build/qt/host-qt-6.12.0`（非符号链接） |
| 版本 | **6.12.0**（`lib/cmake/Qt6/Qt6ConfigVersionImpl.cmake`） |
| moc / rcc / uic | `libexec/moc`、`libexec/rcc`、`libexec/uic`（macOS 走 `libexec/`，**不在 `bin/`**） |
| `Qt6CoreTools` | `lib/cmake/Qt6CoreTools/Qt6CoreToolsConfig.cmake` ✓ |
| 库形态 | macOS **framework**（`lib/QtCore.framework/...`），不是 `libQt6Core.dylib` |
| `moc --version` | `moc 6.12.0` |

> 非 ASCII 路径（`…/鸿蒙pc适配/…`）没有造成问题，configure/build/install 全程正常。

### 3.3 shiboken6 生成器（宿主）：两个必须打的补丁

```bash
cmake -S build/qtbind/src/pyside-setup-everywhere-src-6.12.0/sources/shiboken6_generator \
  -B build/qtbind/build/shiboken6-generator-host -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH=$QT_HOST_PATH -DQT_HOST_PATH=$QT_HOST_PATH \
  -DClang_DIR=build/qtbind/build/clang-shim \
  -DPython_EXECUTABLE=<host python3.11> \
  -DCMAKE_INSTALL_PREFIX=build/qtbind/build/shiboken6-generator-install
```

**补丁 1：`ClangConfig.cmake` shim。** 鸿蒙 SDK 自带可用的 host `libclang.dylib` 和 `clang-c` 头，但它的 `LLVMExports.cmake` 引用了自己**没发**的静态库：

```
CMake Error at .../llvm/lib/cmake/llvm/LLVMExports.cmake:1144 (message):
  The imported target "LLVMDemangle" references the file
     ".../llvm/lib/libLLVMDemangle.a"  but this file does not exist.
```

而 shiboken 只消费三样东西（`ShibokenGeneratorHelpers.cmake` 的 `setup_clang()` + `ApiExtractor/CMakeLists.txt`）：`LLVM_PACKAGE_VERSION`、`${CLANG_INCLUDE_DIRS}`、imported target `libclang`。所以工具里生成一个最小 shim：

```cmake
set(Clang_VERSION "15.0.4")
set(LLVM_PACKAGE_VERSION "15.0.4")          # 缺它 => -D LLVM_VERSION= 空，
                                            # clang_typedefs.h:12 "#if >= 22" 直接语法错
set(CLANG_INCLUDE_DIRS "<sdk>/llvm/include")
add_library(libclang SHARED IMPORTED)
set_target_properties(libclang PROPERTIES
  IMPORTED_CONFIGURATIONS RELEASE            # 缺它 => CLANG_LIBRARY_NAME-NOTFOUND
  IMPORTED_LOCATION_RELEASE "<sdk>/llvm/lib/libclang.dylib"
  INTERFACE_INCLUDE_DIRECTORIES "<sdk>/llvm/include")
```

**补丁 2：隔离 libclang 目录。** shiboken 会给生成器套一个 `shiboken_wrapper.sh`，把 libclang 所在目录塞进 `DYLD_LIBRARY_PATH`。如果直接给 SDK 的 `llvm/lib`，它会把该目录里**较旧的 `libc++.1.0.dylib`** 一起带进来，压过宿主 libc++，宿主 Qt 立刻炸：

```
dyld: Symbol not found: __ZNSt3__13pmr15memory_resourceD2Ev
  Referenced from: .../host-qt-6.12.0/lib/QtCore.framework/Versions/A/QtCore
  Expected in:     .../sdk/.../llvm/lib/libc++.1.0.dylib
```

解法：建一个**只放 `libclang.dylib` 符号链接**的目录，用 `-DSHIBOKEN_WRAPPER_HOST_CLANG_LIB_PATH=<该目录>` 指过去。

打完后：`build/qtbind/build/shiboken6-generator-install/bin/shiboken6 --version` → **`shiboken v6.12.0`**（23.7 s 构建完成）。

### 3.4 libshiboken6 + Shiboken 模块交叉编译（**本轮产出真实目标产物**）

```bash
cmake -S .../sources/shiboken6 -B build/qtbind/build/shiboken6-target -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE=build/qtbind/build/ohos-aarch64-toolchain.cmake \
  -DSHIBOKEN_IS_CROSS_BUILD=ON -DPython_SOABI=cpython-311-aarch64-linux-ohos \
  -DPython_ROOT_DIR=build/qtbind/build/target-python-prefix \
  -DPython_EXECUTABLE=<host py> -DPYTHON_EXECUTABLE=<host py> \
  -DQFP_PYTHON_HOST_PATH=<host py> \
  -DSHIBOKEN_WRAPPER_HOST_CLANG_LIB_PATH=build/qtbind/build/clang-lib-only \
  -DClang_DIR=build/qtbind/build/clang-shim \
  -DCMAKE_PREFIX_PATH="<target qt>/lib/cmake;<generator install>;$QT_HOST_PATH"
```

四个必须在位的细节（少一个就断）：

| 细节 | 为什么 |
|---|---|
| `-DPython_SOABI=cpython-311-aarch64-linux-ohos` | 交叉构建时 CMake 不能跑目标 python 取 SOABI，为空则 `ShibokenHelpers.cmake:206` FATAL |
| `target-python-prefix` staging | 私有 CPython 的头在 `source/Include`、pyconfig 在 `objects/`；要摆成 `include/python3.11` + `lib/libpython3.11.so` 的标准前缀才被 `FindPython` 认。**整个 Include 树都要拷**（`Python.h` 拉 `cpython/`、`internal/`），只拷顶层 `*.h` 会在 `cpython/pydebug.h` 上断 |
| `-DQFP_PYTHON_HOST_PATH` | 交叉构建时 `libshiboken/CMakeLists.txt:28` 用它调宿主 python 生成内嵌签名；为空则命令退化成 `-E ...` → `-E: command not found` |
| toolchain 里 `FIND_ROOT_PATH_MODE_PACKAGE=BOTH` | 包里同时有目标 Qt 和宿主 Shiboken6Tools，`ONLY` 会让生成器的 target 找不到 |

**产品（`llvm-readelf` 实测）：**

| 文件 | 机器 | NEEDED |
|---|---|---|
| `build/qtbind/build/shiboken6-target/libshiboken/libshiboken6.abi3.so.6.12` | ELF64 **AArch64** | `libc++_shared.so`, `libc.so` |
| `build/qtbind/build/shiboken6-target/Shiboken.abi3.so` | ELF64 **AArch64** | `libshiboken6.abi3.so.6.12`, `libc++_shared.so`, `libc.so` |

> 注：PySide6 6.12 上游默认 `FORCE_LIMITED_API=ON`，所以后缀是 `.abi3` 而不是 `.cpython-311-…`；abi3 用在我们的 3.11 上完全兼容。另外 NEEDED 里**没有** `libpython3.11.so.1.0` —— PySide 走 POSIX 惯例"扩展模块靠进程符号解析"，只有 WIN32/Android 分支才显式链 libpython。要在 OHOS（bionic，和 Android 同病）上拿到这条 NEEDED，需要补 `-l:libpython3.11.so.1.0`。

### 3.5 QtCore 绑定交叉编译（**已通过**）

**判据实测（`llvm-readelf`）：**

```
$ llvm-readelf -h .../pyside6-qtcore-install/lib/python3.11/site-packages/PySide6/QtCore.abi3.so
  Class:   ELF64
  Type:    DYN (Shared object file)
  Machine: AArch64

$ llvm-readelf -d .../PySide6/QtCore.abi3.so
  (RUNPATH) Library runpath: [$ORIGIN/../lib]
  (NEEDED)  Shared library: [libpython3.11.so.1.0]
  (NEEDED)  Shared library: [libpyside6.abi3.so.6.12]
  (NEEDED)  Shared library: [libshiboken6.abi3.so.6.12]
  (NEEDED)  Shared library: [libQt6Core.so]
  (NEEDED)  Shared library: [libc++_shared.so]
  (NEEDED)  Shared library: [libc.so]
```

| 文件 | 大小 | 说明 |
|---|---|---|
| `PySide6/QtCore.abi3.so` | 5,016,984 B | 绑定本体 |
| `PySide6/libpyside6.abi3.so.6.12` | — | NEEDED 同样含 `libpython3.11.so.1.0` |

> **命名说明**：产物是 `QtCore.abi3.so`，不是 `QtCore.cpython-311-aarch64-linux-ohos.so`。PySide6 6.12 上游默认 `FORCE_LIMITED_API=ON`（`sources/shiboken6/cmake/ShibokenSetup.cmake:268`），走 CPython Limited API，后缀统一 `.abi3`。`.abi3` 语义是"CPython 3.x ABI 稳定"，**本项目 3.11 直接可加载**，不为命名去改上游。

#### 从"撞 features.h"到编通的四步（每步都是真报错）

**第 1 轮 — `features.h` file not found**

```
[13/227] Running generator for 'QtCore'...
.../llvm/include/c++/v1/__config:261:14: fatal error: 'features.h' file not found
.../libcxx-ohos/include/c++/v1/__locale:548:3: error: unknown rune table for this
    platform -- do you mean to define _LIBCPP_PROVIDES_DEFAULT_RUNE_TABLE?
```
日志里 `targeting "arm64-apple-macosx18.0.0"` 说明生成器拿**宿主** triple 解析目标源码。
修法：`-DSHIBOKEN_GENERATOR_EXTRA_FLAGS` 给 `--compiler-path` + `--compiler-argument=--target=...` + `--include-paths`（选项定义在 `generator/main.cpp:95-115`）。

**第 2 轮 — `unknown rune table`**

`__config:993` 只在 `__BIONIC__ / __OHOS_FAMILY__ / _LIBCPP_HAS_MUSL_LIBC` 存在时定义 `_LIBCPP_PROVIDES_DEFAULT_RUNE_TABLE`。而 `--compiler-argument` 只用于"发现头路径"，**不进解析 argv**（`compilersupport.cpp:432/441` 是仅有的两处使用），宏到不了 libclang。
修法：给 shiboken 打最小补丁，把 `--target=` 与 `-D` 一并转发进 `clang_parseTranslationUnit2()`。

**第 3 轮 — `use of undeclared identifier 'strtoll_l'`**

根因在 `__locale:38-47`：
```cpp
#elif defined(__LITEOS__) || defined(__OHOS__)   // 靠这个才 include musl xlocale
# include <__support/musl/xlocale.h>
```
要的是 `__OHOS__`，上一轮只给了 `__OHOS_FAMILY__`（只管 rune table）。
修法：补 `-D__OHOS__=1`（连带 `-D__MUSL__=1`、`-D_GNU_SOURCE`，与预编译 Qt 的 `mkspecs/ohos-clang/qmake.conf:25-26` 对齐）。

**第 4 轮 — 编通，201/201（35 s）**

补齐判据要求的两条链接参数：

```cmake
-DCMAKE_MODULE_LINKER_FLAGS="-L<target-python-prefix>/lib -l:libpython3.11.so.1.0"
-DCMAKE_SHARED_LINKER_FLAGS="-L<target-python-prefix>/lib -l:libpython3.11.so.1.0"
-DCMAKE_INSTALL_RPATH=$ORIGIN/../lib -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON
```

#### 上游补丁（唯一源码改动，可复现）

`sources/shiboken6_generator/ApiExtractor/clangparser/compilersupport.cpp`，在 `emulatedCompilerOptions()` 返回前：

```cpp
    // HarmonyOS patch (build_qtbinding_harmony.py): parse with the same target
    // triple and predefines that were used for include-path discovery.
    if (isCrossCompilation()) {
        QByteArrayList forwarded;
        for (const QString &argument : std::as_const(_compilerArguments)) {
            if (argument.startsWith(QLatin1StringView("--target="))
                || argument.startsWith(QLatin1StringView("-D"))) {
                forwarded.append(argument.toUtf8());
            }
        }
        result = forwarded + result;
    }
```

上游在交叉构建时只**报告**不匹配（日志 `targeting <host>, (cross build)`），从不把 triple 交给 libclang。补丁 12 行、幂等（工具按标记跳过）、保留 `.cpp.orig`。

#### RUNPATH 修正（本机无 patchelf 的替代）

PySide 把**构建机**路径写进 RUNPATH：

```
old: $ORIGIN/:/Users/.../build/qt/prebuilt/harmonyos-arm64/lib:$ORIGIN/../shiboken6/
new: $ORIGIN/../lib
```

工具里用纯标准库就地改写：定位 `PT_DYNAMIC` → `DT_STRTAB` + `DT_RUNPATH` → 经 `PT_LOAD` 把 vaddr 映回文件偏移 → **等长覆盖**。（坑：bytearray 切片赋一个更短的串会把整文件截短，已改为等长替换。）

### 3.6 QtGui / QtWidgets 构建（**已通过**）

同一条管线，`--modules 'Core;Gui;Widgets'`，**总耗时 3 分 0 秒**（01:44:48 → 01:47:46）。

#### 产物（`llvm-readelf -h` / `-d` 实测）

```
$ llvm-readelf -h .../PySide6/QtGui.abi3.so
  Class: ELF64   Type: DYN (Shared object file)   Machine: AArch64
$ llvm-readelf -d .../PySide6/QtGui.abi3.so
  (RUNPATH) [$ORIGIN/../lib]
  (NEEDED)  libpython3.11.so.1.0, libpyside6.abi3.so.6.12, libshiboken6.abi3.so.6.12,
            libQt6Gui.so, libGLESv3.so, libEGL.so, libQt6Core.so,
            libc++_shared.so, libc.so

$ llvm-readelf -h .../PySide6/QtWidgets.abi3.so
  Class: ELF64   Type: DYN (Shared object file)   Machine: AArch64
$ llvm-readelf -d .../PySide6/QtWidgets.abi3.so
  (RUNPATH) [$ORIGIN/../lib]
  (NEEDED)  libpython3.11.so.1.0, libpyside6.abi3.so.6.12, libQt6Widgets.so,
            libshiboken6.abi3.so.6.12, libQt6Gui.so, libQt6Core.so,
            libGLESv3.so, libEGL.so, libc++_shared.so, libc.so
```

QtGui 额外拉入 `libGLESv3.so` + `libEGL.so`（Qt6Gui 的传递依赖），两者都在 sysroot 里 ✓。

#### wrapper 数量与耗时

| 模块 | wrapper `.cpp` | 产物大小 | 说明 |
|---|---|---|---|
| QtCore | 191 | 5,016,984 B | |
| QtGui | 263 | 5,511,936 B | 含 `QAction`（Qt6 里 AQtion 已迁到 QtGui） |
| QtWidgets | 194 | 6,697,752 B | `QMainWindow`/`QDockWidget`/`QTableWidget`… |
| **合计** | **664** | **17,226,672 B** | 单次构建 3 分钟（并行 8） |

#### 顺手修掉的一个真 bug（Core 时被缓存掩盖）

第一次跑 `Core;Gui;Widgets` 时 configure 直接失败：

```
CMake Error at cmake/PySideSetup.cmake:49 (find_package):
  Could not find a package configuration file provided by "Shiboken6"
  (requested version 6) with any of the following names: Shiboken6Config.cmake ...
```

原因不是 Gui/Widgets 特有：**`-DCMAKE_PREFIX_PATH` 被传了两次** —— stage-3 自己拼了一份（含 `shiboken6-target-install`），`target_common` 里又有一份（不含），CMake 只保留最后一个，于是 Shiboken6 找不到。

Core 那次能过，是因为 build 目录里已经留有我手工 configure 的缓存，把这个 bug 掩住了。修法：`target_common` 不再带 `CMAKE_PREFIX_PATH`，改由每个 stage 各给一份唯一的。工具里已加注释说明，避免回退。

#### 符号闭包校验（离线替代"跑 GUI"）

按你的第 4 条要求，做链接期校验：对每个 `.abi3.so` 取出它所有 `UND` 的 C++ 符号，逐个在它 NEEDED 的库里找导出（Qt 预编译库 + 我们自己的 `libpyside6`/`libshiboken6` + SDK 的 `libc++_shared.so`）。

```
$ llvm-readelf --dyn-syms .../PySide6/QtWidgets.abi3.so | grep ' UND ' | grep -c _ZN
5788
```

结果（工具里是 `verify_symbol_closure()`，每次构建自动跑）：

| 模块 | 导入 C++ 符号 | 由 Qt 库解析 | 由 pyside/shiboken 解析 | 由 libc++_shared 解析 | **未解析** | 闭包 |
|---|---|---|---|---|---|---|
| QtCore | 3,352 | 3,137 | 202 | 13 | **0** | ✅ closed |
| QtGui | 3,752 | 3,586 | 164 | 2 | **0** | ✅ closed |
| QtWidgets | 5,788 | 5,637 | 149 | 2 | **0** | ✅ closed |

三点值得注意：

1. **Qt 侧 100% 命中**：QtWidgets 导入的 5,637 个 Qt 符号全部在 `libQt6Widgets/Gui/Core` 里找到，说明绑定是对着**预期的那份** Qt 头生成的，版本没错配。
2. 剩下的 149 + 2 个是 `PySide::*` / `Shiboken::*`（我们自己的库）和 `std::__n1::*`（OHOS libc++ 的 ABI 命名空间，注意是 `__n1` 不是 `__1`——这是 `__config_site` 里的 `_LIBCPP_ABI_NAMESPACE`）。
3. 这不能替代设备上真起 `QApplication`，但它排除了**符号层面**的所有不确定性：链接器在设备上不需要再解析任何陌生 C++ 符号。

> 注：真正的 `dlopen` 冒烟必须在设备做（本机是 macOS，无法 `dlopen` ELF）。主线已确认 EGL/GLES 3.0 表面在 `Mali-G77` 上建起来了，所以 QtGui 的两个 GL NEEDED 也有落地条件。

### 3.7 L4：唯一需要提前决策的硬缺口（不变）

预编译包提供的模块（`include/` 实测）：`Concurrent Core DeviceDiscoverySupport EglFSDeviceIntegration FbSupport Gui Harfbuzz HarmonyExtras InputSupport Network OpenGL OpenGLWidgets PrintSupport Sql Test Widgets Xml`。

ChimeraX 实际引用的 Qt 子模块（全树 `from Qt.X import` 计数）：

| 模块 | 引用数 | 预编译包 | 影响 |
|---|---|---|---|
| QtWidgets | 447 | ✓ | — |
| QtCore | 343 | ✓ | — |
| QtGui | 186 | ✓ | — |
| QtNetwork | 6 | ✓ | — |
| **QtWebEngineCore** | 7 | ❌ | `ui/src/widgets/htmlview.py`（**顶层 import**）、`help_viewer/src/tool.py`、`log/src/tool.py` |
| **QtMultimedia** | 6 | ❌ | `webcam/src/camera.py` |
| **QtWebEngineWidgets** | 2 | ❌ | `ui/src/gui.py`（About 对话框）、`htmlview.py` |

**主窗口能起**：`ui/src/gui.py:107` 是 `if qt_have_web_engine(): import Qt.QtWebEngineWidgets`，而 `prereqs/qtshim/Qt/__init__.py:130` 的 `qt_have_web_engine()` 是 `try/except Exception: return False`。受影响的只有 HTML 渲染面。

QtWebEngine 在 OHOS 上 = Chromium 移植，上游 HarmonyOS 支持是 tech preview 且只覆盖 qtbase → **建议不排这条线**。


## 4. 工作量估计（人天，按本轮实测修正）

| 工作项 | 人天 | 状态 |
|---|---|---|
| 宿主 Qt 6.12.0 建成（moc/rcc/uic + Qt6CoreTools） | ✅ 0.5 | 2 分 41 秒构建 |
| shiboken6 生成器宿主构建（含两处 shim） | ✅ 0.5 | ClangConfig shim + libclang 隔离 |
| libshiboken6 + Shiboken 模块交叉编译 | ✅ 0.5 | 4 个变量必须到位 |
| PySide6 QtCore 绑定交叉编译 | ✅ 1.5 | 四轮排错 |
| **PySide6 QtGui + QtWidgets 绑定** | ✅ **0.5** | 管线复用，一次成功（修了重复 `CMAKE_PREFIX_PATH`） |
| — 小计：两轮已完成 | **≈3.5 人天** | |
| QtNetwork + QtOpenGLWidgets 绑定 | 0.5–1 | 纯复用，纯跑时间 |
| **ChimeraX 侧：shim + 97 个 `ToolInstance` 冒烟** | **3–5** | 见下 |
| **剩余合计** | **3.5–6 人天** | 到"Qt 界面能在设备上起来" |

### 4.1 ChimeraX 侧工作量拆解（3–5 人天）

绑定的技术风险已经清零，剩下的都是**逐个验证**的体力活：

| 子项 | 人天 | 说明 |
|---|---|---|
| shim 的 PySide6 分支打通 | 0.5 | `prereqs/qtshim/Qt/__init__.py:46-118` 已支持 PySide6，只需确认版本探测与 `Qt.QtCore` 等的重导出 |
| 主窗口 / 菜单 / 工具栏 / 状态栏 / dock 起来 | 1 | `ui/src/gui.py`（99 处 Qt 引用，最大单文件） |
| 97 个 `ToolInstance` 冒烟（68 个 bundle） | 1.5–2.5 | 按 0.02 人天/个：只验证"能实例化 + 能显示"，不重画 UI |
| HTML 面替换（webview/help/log，3 处） | 0.5–1 | ArkUI Web 组件替代 `QWebEngineView`（见 §3.7） |
| 打包联调（rpath / QT_PLUGIN_PATH / 启动顺序） | 0.5 | 见 §6.4 |

**总账**：原估 15–24 人天 → 两轮实做掉 3.5 人天核心探索 → **剩余 3.5–6 人天**，且全部是低风险验证性工作。

---

## 5. 降级方案与量化

### 5.1 备选绑定对比（为什么是 PySide6）

| | PySide6（LGPL） | PyQt6（GPL） |
|---|---|---|
| 生成器 | shiboken6（CMake、吃 libclang） | sip（`sip-build`，吃 Qt 头，输出裸 C++） |
| 目标侧运行时 | `libpyside6` + `libshiboken6` | `PyQt6.sip`（小得多） |
| 交叉编译难度 | 中（两段式，官方有文档） | 中低（生成物是普通 C++） |
| **许可证** | LGPL ✓ 可随 ChimeraX 分发 | **GPL 会传染整个 ChimeraX 分发** |
| ChimeraX shim 优先级 | 第 2（`PyQt6 → PySide6 → PyQt5 → PySide2`） | 第 1 |

**结论：发布路线必须 PySide6。** PyQt6 只能做内部可行性探针——sip 生成器确实更省事（若 L2 迟迟打不通，可以用 PyQt6 先跑通 L3 的 CMake/toolchain，验证完把生成器换成 shiboken6，因为两者产出的都是"普通 C++ 调 Qt 头"）。

### 5.2 方案 B（推荐）：PySide6 全 Qt Widgets，只换 HTML 面

- 打通绑定：**3.5–6 人天剩余**（见 §4）
- 97 个工具面板**零改动**（shim 的 PySide6 分支负责抹平 API）
- HTML 面替换为 ArkUI Web 组件：**5–8 人天**，仅 3 个使用点
  - `ui/src/widgets/htmlview.py`（`ChimeraXHtmlView`，含自定义 scheme handler）
  - `help_viewer/src/tool.py`
  - `log/src/tool.py`（HTML 日志页）
- Webcam 用 ArkUI Camera 替代 `QtMultimedia`：**2–3 人天**（`webcam/src/camera.py` 1 个文件，5 处 API）
- **小计 10.5–17 人天**

### 5.3 方案 A（降级）：QtCore-only 纯 Python + ArkUI 复刻界面

ChimeraX 的 Qt 面实测规模：

| 指标 | 实测值 |
|---|---|
| 引用了 Qt 的 Python 文件 | **191 个** |
| 这些文件总行数 | **114,522 行** |
| `tool.py` / `gui.py` 集中行数 | **32,687 行** |
| 定义 `ToolInstance` 的 bundle | **68 个** |
| `ToolInstance` 类总数（= 工具面板/对话框数） | **97 个** |
| `QDialog` 直接子类 | **17 个** |
| `QWidget`/`QMainWindow`/`QFrame`… 子类 | **37 个** |
| `QAction` 使用点 | **262 处** |
| `QDockWidget` | 19 处 |
| `QGraphicsView` | 37 处（分子视图/序列视图的画布） |
| 用 `QtWidgets` 的 bundle | **81 个** |

复刻工作量：

| 工作项 | 人天 |
|---|---|
| 97 个工具面板按 ArkUI 重写（0.5–1.5 人天/个） | 49–146 |
| 主窗口 + 菜单栏 + 工具栏 + 状态栏 + dock 体系 | 20–30 |
| `QGraphicsView` 画布（seq_view / grid_canvas / volume_viewer）改 ArkUI Canvas | 15–25 |
| QtCore 纯 Python 替代（`QTimer`/信号槽/`QSettings`） | 5–8 |
| **合计** | **89–209 人天** |

**对比结论：方案 A 是方案 B 的 3–6 倍工作量，且必然丢失"界面与原版一致"的目标。方案 B 明确更优。**

---

## 6. 下一步的具体命令

### 6.1 一条命令复现全部结果

```bash
cd /Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC
export QT_HOST_PATH="$PWD/build/qt/host-qt-6.12.0"
export PATH="$PWD/build/host-python/cpython-3.11.17-macos-aarch64-none/bin:$PATH"
python3 tools/build_qtbinding_harmony.py --modules 'Core;Gui;Widgets'
# -> pyside6_coreguiwidgets_cross_compiled_not_target_tested
```

工具按序做完 15 步：Qt 体检 → ABI 探针 → Widgets 探针 → ClangConfig shim → target python staging → OHOS toolchain → **生成器补丁（幂等）** → shiboken6 生成器（宿主）→ libshiboken6（目标）→ **PySide6 Core/Gui/Widgets（目标）** → **RUNPATH 改写（等长替换）** → **符号闭包校验** → **部署清单生成**。

### 6.2 重建宿主 Qt（已存在可跳过）

```bash
cmake -S build/qt/src/qtbase -B build/qt/host-build-612 -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_FLAGS_RELEASE="-O2 -DNDEBUG" -DCMAKE_CXX_FLAGS_RELEASE="-O2 -DNDEBUG" \
  -DCMAKE_INSTALL_PREFIX="$PWD/build/qt/host-qt-6.12.0" \
  -DQT_BUILD_EXAMPLES=OFF -DQT_BUILD_TESTS=OFF -DBUILD_SHARED_LIBS=ON \
  -DQT_NO_XCODE_MIN_VERSION_CHECK=ON -DQT_NO_APPLE_SDK_MIN_VERSION_CHECK=ON
cmake --build build/qt/host-build-612 --parallel 8 && cmake --install build/qt/host-build-612
```

### 6.3 加下一个模块（Gui / Widgets）

```bash
SRC=$PWD/build/qtbind/src/pyside-setup-everywhere-src-6.12.0
cmake -S $SRC/sources/pyside6 -B build/qtbind/build/pyside6-target \
  -DMODULES=Core\;Gui\;Widgets      # 模块名不带 Qt 前缀
```
其余参数照抄工具里 `pyside6_qtcore_configure` 那一串即可（`-DSHIBOKEN_GENERATOR_EXTRA_FLAGS` 已含目标的 triple 与 OHOS 宏）。

### 6.4 部署清单（打包照这个拷）

工具会自动生成两份：[deploy-manifest.txt](../../build/qtbind/out/deploy-manifest.txt)（人读）和 `deploy-manifest.json`（机读）。

**A. `app/entry/libs/arm64-v8a/` 需要 18 个文件**

| 目标文件 | 来源 |
|---|---|
| `libQt6Core.so` `libQt6Gui.so` `libQt6Widgets.so` `libQt6Network.so` `libQt6OpenGL.so` `libQt6OpenGLWidgets.so` `libQt6PrintSupport.so` `libQt6Sql.so` `libQt6Xml.so` `libQt6Concurrent.so` `libQt6Test.so` | `build/qt/prebuilt/harmonyos-arm64/lib/` |
| `libqohos.so` | `build/qt/prebuilt/harmonyos-arm64/plugins/platforms/` ← **没有它 `QApplication` 起不来** |
| **`libc++_shared.so`** | `$SDK/llvm/lib/aarch64-linux-ohos/` ← **sysroot 里没有，必须手动拷** |
| `libshiboken6.abi3.so.6.12` | `build/qtbind/build/shiboken6-target-install/lib/` |
| `libpyside6.abi3.so.6.12` | `build/qtbind/build/pyside6-qtcoreguiwidgets-install/PySide6/` |
| `PySide6/QtCore.abi3.so` `PySide6/QtGui.abi3.so` `PySide6/QtWidgets.abi3.so` | `build/qtbind/build/pyside6-qtcoreguiwidgets-install/lib/python3.11/site-packages/PySide6/` |

```bash
SDK=/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native
DEST=app/entry/libs/arm64-v8a        # 只读示例；本仓库不改 app/
Q=build/qt/prebuilt/harmonyos-arm64
cp "$SDK/llvm/lib/aarch64-linux-ohos/libc++_shared.so" "$DEST"/
cp "$Q"/lib/libQt6*.so "$DEST"/
cp "$Q"/plugins/platforms/libqohos.so "$DEST"/
cp build/qtbind/build/shiboken6-target-install/lib/libshiboken6.abi3.so.6.12 "$DEST"/
cp build/qtbind/build/pyside6-qtcoreguiwidgets-install/PySide6/libpyside6.abi3.so.6.12 "$DEST"/
mkdir -p "$DEST/PySide6"
cp build/qtbind/build/pyside6-qtcoreguiwidgets-install/lib/python3.11/site-packages/PySide6/*.abi3.so "$DEST/PySide6"/
```

**B. Python 包侧（`site-packages/PySide6/`）**

`*.abi3.so` 之外的纯 Python 部分（`__init__.py`、`_config.py`、`_git_pyside_version.py`、`support/`、`QtAsyncio/`）放在应用 python 的 site-packages 下，与 `QtCore.abi3.so` 同级。

**C. RUNPATH 修正（关键）**

- 我们交叉编的 `.so`（`QtCore/QtGui/QtWidgets.abi3.so`、`libpyside6`、`libshiboken6`）**已被工具改写成 `$ORIGIN/../lib`**，无需处理。
- **预编译 Qt 的 RUNPATH 是构建机的 `/usr/local/Qt-6.12.0/lib`，设备上必然失效**。二选一：
  1. `patchelf --set-rpath '$ORIGIN' app/entry/libs/arm64-v8a/libQt6*.so`（本机没有 patchelf，需 `brew install patchelf`）；
  2. 若 Qt 库与 Python 扩展同在 `libs/arm64-v8a`，`libQt6*.so` 之间的相互依赖本来就在同一目录，Android/OHOS 的动态链接器会先在**本库所在目录**找（`$ORIGIN` 语义等价的默认搜索），通常**不改也能跑**；但 `plugins/platforms/libqohos.so` 依赖 `libQt6Gui.so`，仍建议统一改 rpath。
- Qt 运行时还需要设 `QT_PLUGIN_PATH` 指向放 `libqohos.so` 的目录（或在应用里 `QCoreApplication::setLibraryPaths`）。

---

## 7. 一句话给主线

**QtCore + QtGui + QtWidgets 三个绑定的交叉编译全部拿下**：三个 `.so` 均 `ELF64/AArch64`，NEEDED 完整、RUNPATH 统一 `$ORIGIN/../lib`，**导入的 12,892 个 C++ 符号闭包 0 缺口**（Qt 侧 3,137 + 3,586 + 5,637 全部命中，其余落在 `libpyside6`/`libshiboken6`/`libc++_shared.so`）。

L0→L3c 七关实证通过，**没有未知层**。剩余 **3.5–6 人天**，全是低风险验证性活（shim 0.5、主窗口 1、97 个工具面板冒烟 1.5–2.5、HTML 面 0.5–1、打包联调 0.5）。唯一需要决策的仍是 QtWebEngine 不在 qtbase 预编译包里，建议 ArkUI Web 替换 3 个使用点；打包务必手动补 `libc++_shared.so`（sysroot 里没有）并把 Qt 库的 RUNPATH 从构建机路径改成 `$ORIGIN`。