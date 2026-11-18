# Qt for HarmonyOS 接入 ChimeraX —— 最小交接包

日期：2026-11-18 · 目标：OpenHarmony 6.1.1 / API 24 / aarch64 · Qt 6.12.0 官方 OHOS 预编译
依据：`build/qt/src/qtbase/src/plugins/platforms/ohos/`（Qt 6.12.0 源码，只读）与
`build/qt/src/qtbase/src/harmonyos/templates/`（Qt 官方 ArkTS 模板）。

本目录只放**要粘贴的内容**，不改 `app/`。`patches/qt-ohos/*.diff` 已 `git apply --check` 通过。

---

## 0. 一句话结论

1. ArkTS 侧交给 Qt 的入口只有 `qpa.setupQtApplication({...})` 一个调用，字段固定为
   `appContext / modulesFactories / appName / appArgs / abilityClassName / _unusedQChildProcess`
   （**写 `appName`，不是 `sharedLibraryName`**，后者只出现在日志字符串里）。
2. XComponent 必须 `type: NODE` + `libraryname: 'qohos'` + `id: createInfo.xComponentId`，
   且**页面文件名必须是 `pages/MainWindowNativeNode`**（C++ 里写死的字符串）。
   这张页由 libqohos.so 自己 `loadContent`，你自己的页面不参与 Qt 窗口路径。
3. **必须**有应用自己的 `.so` 导出 `main()`；Python 只能被嵌入（或作为无 UI 子进程）。
   即 `libchimeraxqt.so` = 一个把 CPython + PySide6 拉起来的 `main()`。
4. 最短可行路径 = **7 步 / 约 14 小时**，见第 7 节。

---

## 1. 源码事实（逐条带出处，都是本次实读）

| 事实 | 出处 |
|---|---|
| 导出符号表：`setupQtApplication`、`runQtChildProcess`、`makeXComponentIdForMainWindowWithQAbilityInstanceId`、`checkIsAdapterCApiSupported`、`handleAbilityOn*` / `handleAbilityStageOn*`；末尾调 `QArkUi::QXComponentRegistry::Init(env, exports)` | `qohosjsmain.cpp:1880-1917` |
| napi 模块名 `qohos`（`nm_modname`），靠 `__attribute__((constructor))` 注册 | `qohosjsmain.cpp:1921-1934` |
| `appStartupObj` 读的字段：`appContext`(对象)、`modulesFactories`(对象，值必须 Function)、`appName`(字符串)、`appArgs`(字符串数组)、`abilityClassName`(字符串)、`resourceDir`(可选，缺省 `bundleCodeDir + "/entry/resources/resfile"`) | `qohosjsmain.cpp:1626-1743` |
| `appContext` 精确键名：`bundleCodeDir` `cacheDir` `filesDir` `preferencesDir` `tempDir` `databaseDir` `distributedFilesDir` `resourceDir` | `qohosjsmain.cpp:160-169` |
| `s_appSharedLibName = appStartupObj["appName"]` | `qohosjsmain.cpp:1678` |
| 应用库目录 = `bundleCodeDir + "/libs/arm64"` | `qohosjsmain.cpp:1074-1085, 1683` |
| Qt 自己 `setenv`：`QT_QPA_PLATFORM=ohos`、`QT_QPA_PLATFORM_PLUGIN_PATH`、`QT_PLUGIN_PATH`（都=应用库目录）、`QT_QPA_PLATFORMTHEME=ohos`、`QML2_IMPORT_PATH=<resourceDir>/qml`、`QML_DISABLE_DISK_CACHE=1`、`QV4_FORCE_INTERPRETER=1`、`QT_PRINTER_MODULE=ohosprintersupport`、`TMPDIR`、`HOME`，并 `chdir(filesDir)` | `qohosjsmain.cpp:1698-1723` |
| 应用入口 = `dlopen(<libs>/<appName>)` + `dlsym(handle, "main")`，缺一则 abort | `qohosjsmain.cpp:286-328` |
| `main` 跑在 Qt 自己建的线程上（不是 ArkTS 线程） | `qohosjsmain.cpp:701-763, 775-851` |
| 窗口页路径写死 `pages/MainWindowNativeNode`，LocalStorage 键 `createInfo`，值含 `xComponentId`/`onAttach`/`onAppear`/`onDisAppear` | `qohosjsmain.cpp:1312-1359` |
| XComponent id 格式：`__nnMainWindow_` + qAbilityInstanceId；子窗 `__nnSubWindow_`；浮窗 `__nnFloatWindow_`；渲染型 `RenderXComponent_` | `render/qxcomponent.cpp:13-16, 57-77` |
| Registry **只接受**后三种前缀，`RenderXComponent_` 被显式拒绝；重复 id 直接 abort | `qarkui/qxcomponentregistry.cpp:66-96` |
| 最低 API = 23；设备类型白名单 = `2in1` / `tablet` / `phone`，未识别直接 abort；逃生阀 `QT_IO_EXPERIMENTAL_ALLOW_UNSUPPORTED_DEVICES=true` | `qohosjsmain.cpp:103, 1656-1676`、`qohosdeviceinfo.cpp:13-20, 43-83` |
| `abilityClassName` 只认 `"QAbility"`，其他值 abort | `qohosjsmain.cpp:1728-1740` |
| 预编译 `libqohos.so` 的 `RUNPATH=/usr/local/Qt-6.12.0/lib`（设备上不存在） | `llvm-readelf -d` 实读 |
| 预编译 `libqohos.so` NEEDED 含 `libace_napi.z.so`/`libace_ndk.z.so`/`libnative_window*.so`/`libohinput.so`/`libudmf.so`/`libc++_shared.so` 等 | `llvm-readelf --dyn-syms/-d` 实读 |

**结论（第 1 题的四个小问）**

- **传什么字段**：见第 0 节 + 下表，`appContext` 直接把 ArkTS 的 `ApplicationContext` 对象丢进去
  （Qt 用 `get<bundleCodeDir>` 等 8 个属性名去取，多传无妨，缺 `bundleCodeDir`/`filesDir`/`tempDir` 必挂）。
- **`libraryname` 写什么**：`'qohos'`（napi 模块名）。写 `'libqohos.so'` 在 `import` 处是对的，
  在 XComponent 的 `libraryname` 处是错的路径。
- **要不要自己编 `.so`**：要。`appName` 指向的 `.so` 必须 `dlsym` 到 `main`。Python 不能是
  `appName`（`libpython3.11.so` 无 `main`）。`runQtChildProcess` 那条路同样要求带 `main` 的 `.so`
  （`qohosjsmain.cpp:1752-1776`），只是无 UI 子进程。
- **环境变量**：`QT_QPA_PLATFORM` / `QT_QPA_PLATFORM_PLUGIN_PATH` / `QT_PLUGIN_PATH` / `QT_QPA_PLATFORMTHEME`
  **由 Qt 自己设**，应用侧一个都不要抢设。应用侧只需要补 Python 侧变量：
  `PYTHONHOME`、`PYTHONPATH`、`PYOPENGL_PLATFORM=egl`（见 `qt_launcher.cpp`）。

---

## 2. 文件落位表

| 本目录文件 | 目标路径 | 说明 |
|---|---|---|
| `EntryAbility.ets` | `app/entry/src/main/ets/entryability/EntryAbility.ets` | 整文件替换；**删掉 `stage.loadContent('pages/Index')`** |
| `QAbilityStage.ets` | `app/entry/src/main/ets/qabilitystage/QAbilityStage.ets` | 新文件；`APP_LIBRARY_NAME` 在这里 |
| `QtUtils.ets` | `app/entry/src/main/ets/qability/QtUtils.ets` | 新文件；Widgets 应用返回 `{}` 即可 |
| `Index.ets` | `app/entry/src/main/ets/pages/MainWindowNativeNode.ets` | **文件名不能改**；原 `pages/Index.ets` 可保留作 CPython 探针页 |
| `qt/libqohos.d.ts` | `app/entry/src/main/qt/libqohos.d.ts` | `import qpa from 'libqohos.so'` 的类型来源 |
| `qt/oh-package.json5` | `app/entry/src/main/qt/oh-package.json5` | 让 hvigor 认出这个 .so 的类型包 |
| `qt_launcher.cpp` | `app/entry/src/main/cpp/qt_launcher.cpp` | 产物 `libchimeraxqt.so` |
| `CMakeLists.append.cmake` | 追加到 `app/entry/src/main/cpp/CMakeLists.txt` 末尾 | 新 target |
| `../../patches/qt-ohos/000{1,2,3}-*.diff` | `git apply -p1` 于仓库根 | `module.json5` / `main_pages.json` / `entry/oh-package.json5` |

---

## 3. ArkTS 侧调用（精确字段与示例值）

```ts
qpa.setupQtApplication({
  appContext: this.context.getApplicationContext(), // ApplicationContext
  modulesFactories: {},                             // object，值必须是 Function；Widgets 给空表
  appName: 'libchimeraxqt.so',                      // 必须在 <bundleCodeDir>/libs/arm64/ 下
  appArgs: ['--cx-files-dir', filesDir,
            '--cx-runtime-glob', `${filesDir}/cx-runtime-*/cx-generic-runtime`,
            '--cx-stage', 'probe'],                 // 会变成应用 .so 的 argv[1..]
  abilityClassName: 'QAbility',                     // 只认这一个值
  _unusedQChildProcess: {}                          // 只为让 hvigor 保留 ChildProcess 类
});
```

`appArgs` 是 ArkTS → C++ 唯一干净的传参通道：`setupQtApplicationImpl` 之后环境变量已被 Qt
覆盖，`chdir` 也发生了，靠 `setenv` 传递不可靠。

---

## 4. CMake

`app/entry/src/main/cpp/CMakeLists.txt` 末尾追加 `CMakeLists.append.cmake` 的内容。要点：

- 链 `python3.11 hilog_ndk.z dl`，**不要链 Qt**（理由写在文件注释里：进程内已有 Qt，
  再链一份会出现两套 QCoreApplication 状态）。
- `main` 必须导出：源码里已写 `extern "C" __attribute__((visibility("default")))`，
  并且**不要**加 `-fvisibility=hidden`。
  实测（DevEco SDK clang，`--target=aarch64-linux-ohos -fPIC -c` + `llvm-nm`）：
  `extern "C" int main(...)` 与普通 `int main(...)` 都导出符号 `main`（C++ 的 `main` 不 mangle），
  保留 `extern "C"` 只是为了让符号名确定。

---

## 5. 部署（拷什么、拷到哪）

设备侧路径 = `<bundleCodeDir>/libs/arm64/`（工程侧目录名是 `arm64-v8a`，Qt 代码里叫 `libs/arm64`，
两者对应同一个 ABI 目录，不要被名字差异带偏）。

必备清单：

| # | 文件 | 来源 | 说明 |
|---|---|---|---|
| 1 | `libchimeraxqt.so` | 本次新增 target | 导出 `main` 的那个 |
| 2 | `libqohos.so` | `build/qt/prebuilt/harmonyos-arm64/plugins/platforms/libqohos.so` | **一份文件两用**：既被 `import 'libqohos.so'` 当 napi 模块加载，又被 QPA 当 `platforms/libqohos.so` 插件（靠 `QT_PLUGIN_PATH` 指同一个目录） |
| 3 | `libQt6{Core,Gui,Widgets,Network,OpenGL,OpenGLWidgets,PrintSupport,Sql,Xml,Concurrent,Test}.so` | `build/qt/prebuilt/harmonyos-arm64/lib/` | 11 个，全部平铺在同一目录 |
| 4 | `libc++_shared.so` | `$DEVECO_SDK/default/openharmony/native/llvm/lib/aarch64-linux-ohos/libc++_shared.so` | **`app/entry/libs/arm64-v8a/` 里目前没有**，而 libqohos.so 的 NEEDED 里有它 → 缺失即 dlopen 失败 |
| 5 | `PySide6/{QtCore,QtGui,QtWidgets,QtNetwork,QtOpenGL,QtOpenGLWidgets}.abi3.so` + `libpyside6.abi3.so.6.12` + `libshiboken6.abi3.so.6.12` | `build/qtbind/out/deploy-manifest.txt`（已列 22 个 ELF） | 放在 `libs/arm64-v8a/PySide6/`；`libpyside6*`/`libshiboken6*` 必须与 `PySide6/` **同级**（`libs/arm64/`） |
| 6 | CPython 通用运行层 | 现有 `cx-runtime-v4.zip` → 探针页解包 | `qt_launcher.cpp` 用 `--cx-runtime-glob` 去 glob，取最新的一份 |

`libpython3.11.so.1.0` 已在 `libs/arm64-v8a/`（现有 native 用），`libchimeraxqt.so` 链的就是它，
同一个进程里只有一份解释器 → **不要**同时启用现有 `libchimerax_native.so` 的 `initializeRuntime`
与 Qt 路径（`Py_InitializeEx` 只能跑一次，第二次直接崩）。

`RUNPATH=/usr/local/Qt-6.12.0/lib` 是预编译包里的死路径。只要 Qt 的 `.so` 全部平铺在
`libs/arm64/`，OHOS 链接器会先在应用库目录里解析 NEEDED，RUNPATH 失效不影响；若真出现
`library "libQt6Core.so" not found`，再 `patchelf --set-rpath '$ORIGIN'`。

---

## 6. 两阶段（为什么先 probe）

`qt_launcher.cpp` 有两条内嵌脚本，靠 `--cx-stage` 选：

- `probe`（默认）：只做 `PySide6 → QApplication → QMainWindow.show() → app.exec()`，
  窗口里写 `platformName`、Qt/PySide6 版本、`PYTHONHOME`。**这一步过 = 胶水通了**，
  与 ChimeraX 载荷无关。
- `real`：`QApplication` 后 `Session('ChimeraX')` + `session.ui.gui_start()`。
  这一步的前提是 `patches/0004-qt-ohos-pyside6-shim.patch` 的 `Qt/ohos.py` 不要把
  `QT_QPA_PLATFORM` 改成别的值（它现在"不覆盖已有值"，而 Qt 已经设成 `ohos`，所以安全）。

先 probe 的理由：五个失败点里有四个能在 probe 阶段一次性定位（见 `docs/qt-glue-2026-11-18.md`）。

---

## 7. 最短可行路径（7 步 / 约 14 小时）

前提结论：**Qt 必须由应用自己的 `.so` 承载，Python 只能被嵌入。**

| 步 | 动作 | 产物 | 验收（可判定） | 小时 |
|---|---|---|---|---|
| 1 | 落位 ArkTS 三件套（`EntryAbility.ets`/`QAbilityStage.ets`/`QtUtils.ets`）+ 3 个 diff | 编译通过的 HAP 骨架 | `hvigor` 构建成功；启动后 hilog 有 `CX_QT_SETUP start`，且紧接着 `setupQtApplication() - sharedLibraryName:` 调试行 | 2 |
| 2 | `libqohos.so` + 11 个 `libQt6*.so` + `libc++_shared.so` 进 `libs/arm64-v8a/` | 部署闭包 | 启动无 `dlopen failed`；`import qpa` 不再 undefined | 1.5 |
| 3 | `pages/MainWindowNativeNode.ets` + `main_pages.json` | 窗口页 | 屏上出现 Qt 空窗（或 `createInfo` 缺失提示）；hilog 出现 `XComponentId: __nnMainWindow_... onAppear` | 1.5 |
| 4 | `qt_launcher.cpp` + CMake target，`--cx-stage probe` | `libchimeraxqt.so` | 窗口里显示 `platformName=ohos`、`Qt=6.12.0` | 3 |
| 5 | PySide6 六个 `.abi3.so` + 两个运行时 `.so` 落位 | 可 import PySide6 | probe 阶段 `pyside6=6.12.0`，无 `libshiboken6` undefined | 1.5 |
| 6 | 切 `--cx-stage real`，接 ChimeraX `ui.gui_start()` | ChimeraX 主窗口 | 标题 `ChimeraX`、菜单栏 File/Tools/Help 可展开、进程存活 ≥ 30 s | 3 |
| 7 | 3D 视图（`QGraphicsView`/GL）首帧 | 非纯黑首帧 | `grab()` 采样方差 > 阈值；`PYOPENGL_PLATFORM=egl` 生效 | 1.5 |
| | | | **合计** | **14** |

---

## 8. 与现有 `app/` 的冲突点（交给主线决策）

1. 现有 `pages/Index.ets` 是 CPython 探针页 + 自建 EGL 表面；Qt 模式启动时
   `loadContent('pages/MainWindowNativeNode')` 会把它顶掉。二者不能同屏。
   建议：probe/real 两阶段用 `--cx-stage` 之外，再用 Want 参数或一个 ArkTS 常量做开关，
   决定 Ability 是走 Qt 路径还是走探针路径。
2. `libchimerax_native.so`（napi）与 `libchimeraxqt.so`（导出 main）**同时初始化 CPython 会崩**。
   Qt 路径下 `initializeRuntime` 必须不调用。
3. `module.json5` 加了 `isolationProcess: true` 与 `launchType: "specified"`（官方模板如此）。
   如果主线要做多实例/hot start 才需要；单实例最低配置可只加 `srcEntry`（AbilityStage）。
