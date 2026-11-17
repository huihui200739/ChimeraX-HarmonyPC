# 2026-11-18：应用内 EGL/GLES 上下文建立（渲染前置条件打通）

## 当前结论

**应用内通过 ArkUI `XComponent` 拿到原生窗口，建立了 EGL + OpenGL ES 3.0 上下文并完成首帧清屏：设备读回
`ready:OpenGL ES 3.0 (4.1 Metal - 91.7):Mali-G77:2014x285`（版本 / 渲染器 / 表面尺寸）。设备断言 21/21。**

## 关键发现：EGL 只能在应用进程里拿

先用 CLI 启动器（`/data/local/tmp/cxdev`）试了多种取显示的方式，全部失败：

| 尝试 | 结果 |
|---|---|
| `eglGetDisplay(EGL_DEFAULT_DISPLAY)` | 返回 0 |
| `eglGetPlatformDisplay(EGL_PLATFORM_OHOS=0x3140)` | 返回 0 |
| `eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA=0x31DD)` | 返回 0 |
| `eglGetPlatformDisplayEXT(...)` | 返回 0 |

结论：**鸿蒙的 EGL 需要应用进程 + 原生窗口**，CLI 进程里拿不到显示。所以渲染测试必须走 HAP 内的 `XComponent`。

## 实现

- 新增 `app/entry/src/main/cpp/gl_surface.cpp`：
  - `OH_NativeXComponent_RegisterCallback` 注册 `OnSurfaceCreated/Changed/Destroyed`
  - `eglGetDisplay(EGL_DEFAULT_DISPLAY)` → `eglInitialize` → `eglChooseConfig(EGL_OPENGL_ES3_BIT)` → `eglCreateWindowSurface(OHNativeWindow)` → `eglMakeCurrent`
  - 首帧 `glClearColor(0.09,0.13,0.20,1)` + `glClear` + `eglSwapBuffers`
  - 状态字符串（含 GL_VERSION / GL_RENDERER / 尺寸）通过 `glStatus()` N-API 暴露给页面
- `CMakeLists.txt` 链接 `ace_ndk.z native_window EGL GLESv3`
- 页面新增 `XComponent(SURFACE, libraryname='chimerax_native')` 与状态行；整页包进 `Scroll`（否则后面的探针行会被裁掉、读不到）

## 附带修复

- 页面行数增加后，`uitest dumpLayout` 读不到视口外的节点 → 检查器增加"滚动后再 dump"的兜底
- GL 状态改为轮询到 `ready:` 为止（表面创建晚于页面首帧）

## 证据

- 设备收据：`reports/device-app-2026-11-17.json`（21 项断言，含 `gl_status`）
- 截图：`reports/device-app-gl-surface-2026-11-18.jpeg`

## 下一步（渲染链路）

1. 把 `chimerax.graphics` 的渲染目标从"它自己的 GL 上下文"改接到这条 EGL 表面（或让它使用我们提供的上下文）
2. 引入 PyOpenGL（纯 Python）并在应用内验证 `OpenGL.GLES3` 能绑定到当前上下文
3. 之后才是"显示真实结构"（需要 atomic/models 层，见并行线的 atomic 扩展产出）

## 并行线状态

- **atomic 扩展**（子代理）：`_ribbons`、`libmolc.so`、`_geometry` 已交叉编译并通过 `--no-undefined` 与符号对账；`cymol/cytmpl/connect` 因缺 Cython 未编（已记录）
- **bundle 依赖矩阵**（子代理）：190 个 bundle → 纯 Python 78 / 需 C++ 32 / 需 Qt 90 / 需 GL 3；关键路径 `core→arrays→graphics→geometry→atomic_lib→atomic→io`
- **Qt 落地评估**：子代理中断，需重派
