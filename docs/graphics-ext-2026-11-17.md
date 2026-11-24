# 2026-11-17：图形层 C++ 扩展在鸿蒙应用中运行 + 原版图标

## 当前结论

**两个 ChimeraX 图形相关 C++ 扩展已为 aarch64-linux-ohos 交叉编译并在应用内跑通：`chimerax.arrays._arrays` 与 `chimerax.graphics._graphics`（设备读回 `chimerax.graphics._graphics|3`，即 `count_value` 在 6 元素数组里数出 3 个 5）。设备断言 20/20。**

同时把应用图标换成 **ChimeraX 原版图标**（`src/apps/ChimeraX/ChimeraX-icon512.png`），不再用占位图。

## 怎么编出来的

`tools/build_graphics_ext_harmony.py`（可复现，带 report 与 sha256）：

- 用 SDK 的 `clang++ --target=aarch64-linux-ohos --sysroot=<sdk>/sysroot -std=c++11 -fPIC -shared`
- 头文件：私有 CPython 的 `Include` + 生成的 `pyconfig.h` + numpy 的 `core/include` + 一个名为 `arrays` 的符号链接目录（让 `<arrays/pythonarray.h>` 可解析）
- 链接：`-l:libpython3.11.so.1.0` + `-Wl,-rpath,$ORIGIN/../lib`
- **关键坑**：`_graphics` 复用 arrays 的 C++ 符号，必须把 `pythonarray.cpp`/`rcarray.cpp`/`refcount.cpp` 一起编进去，否则加载报 `Reference_Counted_Array ... symbol not found`
- **平台桩**：鸿蒙没有 GLX/NSOpenGL 的 swap-interval 入口，补了 `set_linux_swap_interval`/`set_mac_swap_interval` 两个桩（返回 false = 未应用），不是伪造功能

## 打包侧的变化

`tools/package_app_runtime.py` 现在把**暂存包里所有 `.so`**（不只是 numpy）按包结构复制进应用原生库目录（`libs/arm64/...`），因为数据目录里的 ELF 在设备上无法 `dlopen`；Python 包本身仍随运行环境 ZIP 分发。

## 证据

- 设备收据：`reports/device-app-2026-11-17.json`（20 项断言，含 `cx-graphics`）
- 构建记录：`reports/graphics-ext-2026-11-17.json`（两个模块的 sha256）
- 图标：`app/AppScope/resources/base/media/app_icon.png`（原版 512×512）

## 边界

- 这解决的是"C++ 图形层能在鸿蒙加载并计算"，**还不是渲染**：真正的绘制需要 PyOpenGL + EGL/GLES 上下文 + `chimerax.graphics` 的 Python 渲染管线。
- 下一步（并行线之一）：PyOpenGL 引入 + 离屏 EGL/GLES 探测。
