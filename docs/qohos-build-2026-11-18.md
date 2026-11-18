# libqohos.so 重编（去掉两处 `napi_run_script` 求值）— 2026-11-18

**结论**：插件已编出，`build/qt/ohos-plugin/libqohos.so`（ELF64 / AArch64 / DYN，4,024,760 B，
NEEDED **24 条与官方预编译版逐条一致**，含 `libc++_shared.so`）。改动只有一处机制：
把 `LocalStorage` 的来源从"脚本求值"换成"ArkTS 交底 + napi 函数调用"。
整编 qtbase 没走到——**只单独编这个插件**这条路一次跑通，configure 0.9 s、编译 40.4 s。

---

## 1. 改了什么

### 1.1 补丁

`patches/qt-ohos/0102-ohos-no-eval-localstorage-handoff.patch`（280 行，`git apply` 干净）

```
sha256 1cdce1cbac2486d0e99138f32ccfb274327c33437636ee05b943a4547868444c
```

上游树 `build/qt/src/qtbase` **没有改动**；补丁应用到副本
`build/qt/ohos-src/src/plugins/platforms/ohos`（`build/qt/ohos-src` 是独立 git 仓库，
pristine 提交 `3ab18ff`，补丁单独一个提交，`git diff HEAD~1` 就是补丁本体）。

校验：

```bash
cd build/qt/src/qtbase
GIT_DIR=/nonexistent git apply --check -v ../../../../patches/qt-ohos/0102-ohos-no-eval-localstorage-handoff.patch
# exit 0，三文件 "Checking patch ..." 全过
```

> 坑：`/build/` 在仓库 `.gitignore` 里，在仓库内直接 `git apply` 会对每个文件打印
> `Skipped patch '...'` 并以 0 退出（假通过）。必须 `GIT_DIR=/nonexistent` 走纯文件系统模式。
> 另外我还在 pristine 拷贝上真跑了一次 apply 并 diff 比对，结果与 `ohos-src` 完全一致。

### 1.2 三处代码改动

| 文件 | 行 | 内容 |
|---|---|---|
| `qohoslocalstorageprovider.h` | 新文件 219 行 | `QtOhos::LocalStorageProvider`：一次性解析 ArkTS 交底，`makeNewLocalStorage()` 用 napi 函数调用取实例 |
| `qohosjsmain.cpp` | 58 | `#include "qohoslocalstorageprovider.h"` |
| `qohosjsmain.cpp` | 1323 | `loadWindowStageContentPage()`：`jsState.eval<QNapi::Object>("LocalStorage.makeNewLocalStorage()")` → `QtOhos::LocalStorageProvider::makeNewLocalStorage(jsState, Q_FUNC_INFO)` |
| `qohosjsmain.cpp` | 1645 | `setupQtApplicationImpl()`（紧跟 `modulesFactories` 读取之后）：`QtOhos::LocalStorageProvider::initFromAppStartupObject(jsState, appStartupObj)` |
| `render/qohoswindowproxydatafactory.cpp` | 9 | `#include <qohoslocalstorageprovider.h>` |
| `render/qohoswindowproxydatafactory.cpp` | 89 | `makeLocalStorage()` 函数体 → `QtOhos::LocalStorageProvider::makeNewLocalStorage(jsState, Q_FUNC_INFO)`（子窗口 / 浮动窗口两条调用点因此一起改掉） |

### 1.3 机制（方案 1，C++ 侧读取交底）

`setupQtApplicationImpl()` 里按顺序找一次，命中即保存成持久引用，之后两处都用它：

1. `appStartupObj.localStorageFactory` —— 函数，返回新 `LocalStorage`（或返回带
   `makeNewLocalStorage` 的模块接口对象，两种形态都识别）
2. `appStartupObj.localStorage` —— 现成实例
3. `appStartupObj.modulesFactories.LocalStorage` —— **Qt 自己的 ArkTS 模板契约**
   （`harmony/.../QtUtils.ets` 的 `getModulesFactoriesMapForQt()` 已经提供了它），
   **不需要改任何 ArkTS**

命中后每次取实例就是 `maker.Call({})`——纯 napi 调用，不走表达式求值器，因此不会再撞
`global expression doesn't start with known module path`。

只有三者都没有时才回落旧的 `jsState.eval<...>("LocalStorage.makeNewLocalStorage()")`
并打一条 warning（行为与现状一致，不会比今天更糟）。

为什么值得试第 3 条：原实现的求值器 `JsStateImpl::extractModuleFromEvalExpr()`
（`qohosplugincore.cpp:695`）只认 `m_jsModulesFactories` 里的前缀；
`@ohos.*` 来自内置 `napiLoadableModules[]`，而 `LocalStorage` 只能来自 ETS 工厂表。
工厂表是用 `for (prop : jsModulesFactoriesObj)` **枚举**出来的
（`qohosjsmain.cpp:852`），ArkTS 类实例的字段经 napi 枚举时很可能拿不到——
这正好解释了"设备上 `@ohos.*` 能求值、`LocalStorage.*` 必失败"。
改法绕开了枚举：用 `napi_get_named_property` 按名取（`modulesFactories.LocalStorage`）。

---

## 2. 怎么复现

工作目录：`/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC`（下文 `$ROOT`）。
构建工程：`docs/qt-ohos-standalone-build/`（本次实际用的 `build/qt/ohos-plugin-proj/`
与之逐字节一致，sha256 都在报告里）。构建目录必须是 ASCII 相对路径
`build/qt/ohos-build`（`/tmp` 是符号链接、工程路径含中文，两者都被 Qt/CMake 坑过）。

```bash
cd "$ROOT"
SDK=/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native
CM=$SDK/build-tools/cmake/bin/cmake          # 3.28.2，DevEco 自带；本机 PATH 上没有 cmake
NINJA=$SDK/build-tools/cmake/bin/ninja

# 1) 准备改过的源码副本
mkdir -p build/qt/ohos-src/src/plugins/platforms
cp -R build/qt/src/qtbase/src/plugins/platforms/ohos build/qt/ohos-src/src/plugins/platforms/ohos
cd build/qt/ohos-src
GIT_DIR=/nonexistent git apply -p1 ../../../patches/qt-ohos/0102-ohos-no-eval-localstorage-handoff.patch
cd "$ROOT"

# 2) configure（0.9 s）
$CM -S docs/qt-ohos-standalone-build -B build/qt/ohos-build -G Ninja \
  -DCMAKE_MAKE_PROGRAM=$NINJA \
  -DCMAKE_TOOLCHAIN_FILE=$SDK/build/cmake/ohos.toolchain.cmake \
  -DOHOS_ARCH=arm64-v8a -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH="$PWD/build/qt/prebuilt/harmonyos-arm64" \
  -DQT_HOST_PATH="$PWD/build/qt/host-qt-6.12.0" \
  -DQOHOS_SRC="$PWD/build/qt/ohos-src/src/plugins/platforms/ohos" \
  -DNODE_ADDON_API_ROOT=/Users/huihui/.dsh/profiles/node_modules

# 3) 编译（40 s / 10 核 / 92 个 target）
$CM --build build/qt/ohos-build            # 产出 build/qt/ohos-build/libqohos.so

# 4) strip + 交付
mkdir -p build/qt/ohos-plugin
cp build/qt/ohos-build/libqohos.so build/qt/ohos-plugin/libqohos.so
$SDK/llvm/bin/llvm-strip --strip-unneeded build/qt/ohos-plugin/libqohos.so
```

### 2.1 这条路为什么成立（以及在哪些配置项上卡过）

* 官方预编译包 `build/qt/prebuilt/harmonyos-arm64` 里**带了私有头文件**
  （`include/QtCore/6.12.0/QtCore/private/...`）、逐模块 cmake 包
  （`Qt6CorePrivate`、`Qt6GuiPrivate`、`Qt6OpenGLPrivate`）和 11 个 `libQt6*.so`，
  所以插件可以当"用户插件"编：`find_package(Qt6 ... )` + `target_link_libraries(Qt6::GuiPrivate ...)`，
  不需要 `qt_internal_add_plugin`，也不需要整编 qtbase。
* **卡点 A**：OHOS toolchain 把 `CMAKE_FIND_ROOT_PATH_MODE_PACKAGE/_LIBRARY/_INCLUDE`
  钉成 `ONLY`，只搜 sysroot，`CMAKE_PREFIX_PATH` 直接被吞。
  → 工程里把每个 `CMAKE_PREFIX_PATH` 追加进 `CMAKE_FIND_ROOT_PATH` 并把三个 `*_MODE_*`
  改成 `BOTH`（在 `project()` 之后设，否则被 toolchain 覆盖）。
* **卡点 B**：`napi.h` 谁都不带（OHOS SDK、预编译 Qt 都没有）。Qt 的
  `FindNodeAddonApi.cmake` 靠 `NODE_ADDON_API_ROOT` 找 `node-addon-api/napi.h`；
  本机唯一一份在 `/Users/huihui/.dsh/profiles/node_modules/node-addon-api`。
* **卡点 C**：`qohosplatformfontdatabase.cpp` 需要 `<fontconfig/fontconfig.h>`。
  官方 Qt for HarmonyOS 是把 fontconfig **静态链进 libQt6Gui.so** 且导出 `Fc*`
  （`llvm-nm -D` 能看到 `FcInit@@Qt_6` 等），所以本机不需要 fontconfig 库，只需要声明。
  → 工程里带了一份 4 个声明的 shim 头 `fontconfig-shim/fontconfig/fontconfig.h`。
  结果：我们编出的插件里 `FcInit@Qt_6` 等是 **UND** 且版本绑定到 `Qt_6`，由
  `libQt6Gui.so` 提供，NEEDED 里**不会**多出 `libfontconfig.so`（与预编译版一致）。

未走的路线：`lib/cmake/Qt6BuildInternals` 虽然存在，但 `qt_internal_add_plugin`
依赖一整套 qtbase 构建上下文；整编 qtbase 预计 30 min+，预算 90 min 内没必要冒险。
`extras/` 子插件（`libQt6HarmonyExtras`）**没重编也没改**。

---

## 3. 产物与验证

```
build/qt/ohos-plugin/libqohos.so       4,024,760 B  sha256 6dcddfe8…6fd7fed   (交付，已 strip)
build/qt/ohos-build/libqohos.so        8,863,216 B  sha256 130188a5…8857f0b   (未 strip，留着看符号)
build/qt/prebuilt/.../libqohos.so      3,989,552 B  (官方预编译参照)
```

```bash
RE=/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native/llvm/bin/llvm-readelf
$RE -h build/qt/ohos-plugin/libqohos.so | grep -E 'Class|Type:|Machine'
#   Class: ELF64 / Type: DYN (Shared object file) / Machine: AArch64

$RE -d build/qt/ohos-plugin/libqohos.so | grep -E 'NEEDED|RUNPATH|FLAGS'
# 24 条 NEEDED：libEGL.so libGLESv3.so libace_napi.z.so libace_ndk.z.so
# libhiappevent_ndk.z.so libhilog_ndk.z.so libnative_display_manager.so libnative_vsync.so
# libnative_window.so libnative_window_manager.so libohfileshare.so libohfileuri.so
# libohhicollie.so libohinput.so libpasteboard.so libpixelmap.so libqos.so libudmf.so
# libohinputmethod.so libQt6OpenGL.so libQt6Gui.so libQt6Core.so libc++_shared.so libc.so
# FLAGS: BIND_NOW / FLAGS_1: NOW     （无 RUNPATH）
```

与预编译版对比结论：

* **NEEDED 集合逐条相同**（排序后 `diff` 为空），`libc++_shared.so` 在列。
* `BIND_NOW`/`NOW` 也相同（这是 SDK toolchain 默认，别去 `-z,lazy`）。
* 唯一已知差异：预编译版有 `RUNPATH=/usr/local/Qt-6.12.0/lib`（构建机路径），我们没有；
  导出符号 155 vs 66（预编译用了 Qt 生成的 version script，我们把
  `CXX_VISIBILITY_PRESET` 设成 `hidden` 后只剩 `qt_plugin_instance` /
  `qt_plugin_query_metadata_v2` 和插件自己的 `Q_DECL_EXPORT` 接口，
  **没有任何 Qt6::Core/Gui 符号外泄**——`llvm-nm -D | grep -c '_ZN7QString'` = 0）。
* 链接带 `-Wl,--no-undefined`，所有引用符号在链接期就必须在预编译 Qt / API24 sysroot 桩里存在；
  相对预编译版新增的 5 个 UND 符号（`QString::append`、两个 libc++ `basic_string::*`、
  `memchr`、`napi_add_finalizer`）全部已解析。

改动的静态证据：

```bash
strings -a build/qt/ohos-plugin/libqohos.so | grep -E 'LocalStorage hand-off|localStorageFactory|modulesFactories.LocalStorage'
# %s: LocalStorage hand-off accepted from '%s' (%s)
# localStorageFactory
# modulesFactories.LocalStorage
```

---

## 4. 主线怎么部署

1. **备份再覆盖**（`libqohos.so` 就在 app 的 native 库目录里，与 `libQt6*.so`、
   `libc++_shared.so` 同级）：

   ```bash
   cd "$ROOT"
   cp app/entry/libs/arm64-v8a/libqohos.so \
      "app/entry/libs/arm64-v8a/libqohos.so.prebuilt-2026-11-18.bak"
   cp build/qt/ohos-plugin/libqohos.so app/entry/libs/arm64-v8a/libqohos.so
   ```

2. **不需要 `patchelf` 改 RUNPATH**。理由有两条：
   * 官方预编译版那条 `RUNPATH=/usr/local/Qt-6.12.0/lib` 在设备上根本不存在，它照样能加载
     ——说明 `libQt6*.so` 是靠"同目录 + 应用 native 库搜索路径"解析的；
   * 我们这份的 NEEDED 与它逐条相同，`libQt6Core/Gui/OpenGL` 同样躺在
     `app/entry/libs/arm64-v8a/` 里。
   若日后想更保险，可以加 `$ORIGIN`（不改也行）：
   `patchelf --set-rpath '$ORIGIN' app/entry/libs/arm64-v8a/libqohos.so`

3. **不改 ArkTS 也能生效**：`modulesFactories.LocalStorage` 是 `QtUtils.ets` 早就提供的契约。
   如果想要 100% 确定性（不依赖 napi 枚举/取属性在 ArkTS 类实例上的行为），
   让 ArkTS 显式交底即可（这是 `app/` 的改动，本任务按约束没有动，留给主线）：

   ```ts
   // app/entry/src/main/ets/qabilitystage/QAbilityStage.ets, setupQtApplication(...) 里加一行
   qpa.setupQtApplication({
     appContext: appContext,
     modulesFactories: QtUtils.getModulesFactoriesMapForQt(),
     appName: APP_LIBRARY_NAME,
     appArgs: QAbilityStage.buildAppArgs(appContext),
     abilityClassName: abilityClassName,
     _unusedQChildProcess: QtUtils.getModulesFactoriesMapForQt(),
     localStorageFactory: () => new LocalStorage(),   // ← 新增，C++ 侧优先读它
   });
   ```

   （`libqohos.d.ts` 的 `QtApplicationSetupParams` 也随之加
   `localStorageFactory?: () => LocalStorage`。C++ 侧读的是可选字段，老 ArkTS 不会报错。）

4. **上线后怎么确认走到了新路径**（hdc 由主线做）：

   ```bash
   hdc shell hilog -T Qt | grep -E "LocalStorage hand-off|falling back to script evaluation"
   ```

   * `LocalStorage hand-off accepted from 'modulesFactories.LocalStorage' (factory)` → 新路径生效
   * `ArkTS provided no usable LocalStorage hand-off ...` → 退化了，按第 3 步加 ArkTS 那行
   * 彻底的 `global expression doesn't start with known module path` 不该再出现

---

## 5. 剩余风险（老实说）

1. **没有设备验证**（本任务明确禁用 hdc/模拟器）。`modulesFactories.LocalStorage`
   能不能用 `napi_get_named_property` 从 ArkTS 类实例上取到，只有设备能给答案；
   取不到时插件会 warning + 回落旧 eval（即回到今天的行为，不会更差），
   再按第 3 步补 ArkTS 那行即可。
2. 若 ArkTS 交的是**单个实例**而不是工厂，它只会被主窗口消费一次；多窗口
   （子窗口/浮动窗口）需要工厂形态，否则该窗口仍走旧 eval。日志里会明确打印。
3. 导出符号没做 version script 过滤，比预编译版多出插件自身的 `Q_DECL_EXPORT` 接口
   （实测无 Qt 命名空间符号外泄）。
4. 编译用的是本机 DevEco 的 API 24 sysroot 桩；运行时 API 行为（尤其
   `libace_napi.z.so` 的 napi 版本能力）未在设备上跑过。
5. `extras/`（`libQt6HarmonyExtras.so`）没重编，仍是原预编译产物——本次没改它。
