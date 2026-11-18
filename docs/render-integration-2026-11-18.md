# ChimeraX 渲染接入设计（HarmonyOS PC）— 2026-11-18

面向对象：主线负责人、设备验证执行者。
范围：`chimerax.graphics` 的 **上下文接入 + 离屏渲染**，不含 GUI 窗口/输入事件。
上游固定提交：`60235d30`（`build/downloads/ChimeraX-src`，只读）。补丁：`patches/0005-render-ohos-egl-context.patch`。

---

## 1. 读码结论（先看事实，再谈方案）

| 事实 | 位置 | 影响 |
|---|---|---|
| `OpenGLContext` 全部方法都是 Qt：`QOpenGLContext()`、`qc.setScreen()`、`qc.setFormat()`、`qc.create()`、`makeCurrent(window)`、`swapBuffers(window)`、`doneCurrent()` | `opengl.py:50-337` | OHOS 上 Qt shim 没有真实 `QOpenGLContext`（`patches/0004` 只补 `Qt/ohos.py` 平台默认值），**这条路在设备上走不通** |
| 全模块只有一处平台分支：`wait_for_vsync()` 里 `platform == 'linux' → _graphics.set_linux_swap_interval` | `opengl.py:254-278` | 这是任务要求的"扩一个 ohos 分支"的落点之一；但真正要换的是**上下文类本身** |
| 离屏上下文已有 duck-typed 模板 `OffScreenRenderingContext`（OSMesa）：不继承任何基类，只约定 `make_current/swap_buffers/pixel_scale/_framebuffers/_bindings/default_draw_target/_framebuffer_color_bits` | `opengl.py:3430-3486` | **EGL 上下文照这个形状写即可**，`Render`/`Framebuffer` 不用改 |
| `Framebuffer.__init__` 只从 context 取 `_framebuffer_color_bits` 和 `default_draw_target`；`w is None` 时 `_fbo = 0`（默认帧缓冲） | `opengl.py:2173-2215` | 自建上下文必须提供这两个属性，否则 `Render.__init__` 直接炸 |
| `View.__init__(drawing, *, window_size=(256,256), trigger_set=None)`：**不碰 GUI、不需要 session** | `view.py:35-56` | 无 GUI 最小可用路径成立 |
| `Session` 自己就构造 `View(self.models.scene_root_model, window_size=(256,256), trigger_set=self.triggers)` | `core/session.py:562`（即 `chimerax/core/session.py`） | 没有 `View(session, size=...)` 这种用法；headless 的入口是 `session.main_view`，只需再 `initialize_rendering(ctx)` |
| 渲染延迟到首次绘制：`View.draw() → _use_opengl() → render.make_current() → _initialize_opengl()` | `view.py:124-145`, `view.py:157-205` | 上下文可以后注入，`View` 构造与上下文解耦 |
| 离屏取像素现成路径：`View.image_rgba()` 自建 `Framebuffer('image capture', ...)` → `activate()` → `draw(swap_buffers=False)` → `r.frame_buffer_image(w,h)` | `view.py:462-521` | **探针只要 `initialize_rendering()` + `image_rgba()`**，不用自己搭 FBO |
| 最低版本要求硬编码在 `Render.check_opengl_version(major=3, minor=3)` | `opengl.py:1119-1126` | GLES 报告 "OpenGL ES 3.x"，必须改为读 context 的 `required_opengl_version` |
| `opengl_version_number()` 取 `GL_VERSION.split()[0]` → 对 `"OpenGL ES 3.2 ..."` 得 `"OpenGL"` → `int()` 抛异常 | `opengl.py:1105-1109` | 必改，否则 `check_opengl_version` 直接崩 |
| GLSL 源码只有两份：`vertexShader.txt` / `fragmentShader.txt`，均为 `#version 330 core`；两者都经过 `Shader.insert_define_macros()` 这一个咽喉 | `opengl.py:2995-3007`, `opengl.py:2932-2952` | **shader 改造成本 = 一个函数**，不是一堆 |
| 图形代码几乎不用 GLES 缺失的特性：`glPolygonMode`/`GL_QUADS`/`glLineWidth`/几何着色器 出现次数均为 0；用到 `glDrawElements`、`glBlitFramebuffer`、`glTexImage3D`（ES3 全支持） | `opengl.py`, `drawing.py` grep | GLES3 可行性高 |
| native 侧已持有 `g_display/g_surface/g_context`，但**没有对外 getter**；导出的 C 符号只有 `ChimeraXGLStatus/ChimeraXGLRender` | `app/entry/src/main/cpp/gl_surface.cpp:106-108,215-233` | 方案 B 需要改 `app/`（本任务禁改），且要重编 HAP |
| Python 与 native **同进程**：`runChimeraCommand` 在 native 里调 CPython | `app/entry/src/main/cpp/chimerax_native.cpp:584-642` | EGL current context 是进程/线程级全局状态 ⇒ **Python 直接 `eglGetCurrentContext()` 就能捡到 native 那份上下文**，不需要句柄传递 |

---

## 2. 方案 A —— Python 侧用 PyOpenGL `OpenGL.EGL` 自建上下文（**推荐**，已落补丁）

### 2.1 两条子路径（同一份代码里自动选择）

A1 **沿用（adopt）native 已建好的上下文**（首选）
应用进程里 `OnSurfaceCreatedCB()` 已经 `eglMakeCurrent(g_display, g_surface, g_surface, g_context)`。Python 在同一进程同一 GL 线程执行时：

```
display  = eglGetCurrentDisplay()
context  = eglGetCurrentContext()        # != 0 就说明 native 已经建好并使能
surface  = eglGetCurrentSurface(EGL_DRAW)
```

- 不创建任何新对象 ⇒ 无句柄传递、无 N-API、**不需要改 `app/`**
- 画面直接落在 XComponent 窗口表面上（所见即所得）
- 离屏仍由 ChimeraX 自己的 `Framebuffer` 承担（`View.image_rgba()`）

A2 **自建 pbuffer 上下文**（CLI / 无表面 / 线程不对时兜底）

```python
display = eglGetDisplay(EGL_DEFAULT_DISPLAY)      # 应用进程可拿到；纯 CLI 进程通常返回 0
eglInitialize(display, &major, &minor)
eglChooseConfig(display,
    [EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
     EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
     EGL_RED_SIZE,8, EGL_GREEN_SIZE,8, EGL_BLUE_SIZE,8, EGL_ALPHA_SIZE,8,
     EGL_DEPTH_SIZE,24, EGL_NONE], &cfg, 1, &n)
surface = eglCreatePbufferSurface(display, cfg, [EGL_WIDTH,W, EGL_HEIGHT,H, EGL_NONE])
context = eglCreateContext(display, cfg, EGL_NO_CONTEXT,
            [EGL_CONTEXT_MAJOR_VERSION,3, EGL_CONTEXT_MINOR_VERSION,2, EGL_NONE])   # 退化到 3.1 → CLIENT_VERSION 3
eglMakeCurrent(display, surface, surface, context)
```

要点：
- `eglGetDisplay(EGL_DEFAULT_DISPLAY)` 在**应用进程**可用（native 已证明），在**纯 CLI 进程**通常失败 → 方案 A2 只作为应用内兜底，这是"CLI 拿不到 display"的准确表述。
- 需要 `PYOPENGL_PLATFORM=egl`（已设置）+ `libEGL.so` 能被 dlopen（`/system/lib64/libEGL.so`，必要时用 `CHIMERAX_OHOS_EGL_SO` 指定绝对路径）。
- PyOpenGL 的 EGL 平台用 `eglGetProcAddress` 解析所有 GL 入口（`OpenGL/platform/egl.py:89-93`），因此 `GL.glDrawElements` 等自动落到 GLES 驱动，**无需 GLX/GLVND**。

### 2.2 GLSL 与版本校验（不可省的连带改动）

- `insert_define_macros()` 之后追加 `translate_shader_to_gles()`：`#version 330 core` → `#version 300 es`（可用 `CHIMERAX_OHOS_GLSL_VERSION` 覆盖为 `310 es`/`320 es`），并在首个非注释行插入 `precision highp float/int/sampler2D;`。
- `Render.check_opengl_version()` 改为读 `context.required_opengl_version`，EGL 上下文声明 `(3,0)`、`required_opengl_core_profile = False`（GLES 无 core profile 概念）。
- `opengl_version_number()` 增加 `OpenGL ES` 前缀解析。

### 2.3 改动点（已在补丁内）

| 文件 | 函数/类 | 改动 |
|---|---|---|
| `src/bundles/graphics/src/opengl.py` | 模块级新增 | `running_on_ohos()`、`_detect_ohos()`、`ohos_glsl_version()`、`_pin_ohos_egl_libraries()` |
| 同上 | `_initialize_pyopengl()` | OHOS 下 `setdefault('PYOPENGL_PLATFORM','egl')` + 预加载 libEGL/libGLESv3（RTLD_GLOBAL） |
| 同上 | 新增 `EGLContext` | duck-typed 上下文：`created/make_current/done_current/swap_buffers/swap_interval/wait_for_vsync/pixel_scale/stereo/enable_stereo/set_offscreen_color_bits/delete`；属性 `_framebuffers/_bindings/_framebuffer_color_bits/default_draw_target` |
| 同上 | 模块尾部 | `if running_on_ohos(): OpenGLContext = EGLContext`（全仓都是惰性 `from .opengl import OpenGLContext`，重绑定即可，diff 最小） |
| 同上 | `remember/restore_current_opengl_context()` | OHOS 走 `_egl_remember_current()` / `_egl_restore_current()` |
| 同上 | `opengl_version_number()`、`Render.check_opengl_version()`、`Shader.insert_define_macros()` | 见 2.2 |

### 2.4 风险
1. **线程归属**：EGL 上下文只在创建它的线程有效。native 在 XComponent 回调线程 make current；若 Python 执行在另一个线程，A1 会拿到"别处 current"或空。判据见 §5 的 `adopted_existing_context` 字段。
2. **`eglGetCurrentDisplay()` 在同一进程多 display 时**可能不是预期的那个（本工程只有一个，风险低）。
3. **GLES 与桌面 GL 的着色器语义差**：`#version 300 es` 下 `gl_FragDepth`、`textureLod` 等存在差异；若 `fragmentShader.txt` 用了 ES3 不支持的构造，需按编译日志逐条改（预估 0–2 处）。
4. **`EGL_DEPTH_SIZE=24` 配置**若不被采纳，`Render.initialize_opengl()` 会因 `framebuffer_depth_bits() != 24` 自动走 `offscreen_outline`，属可接受降级（轮廓描边多一次 blit）。
5. **pbuffer 尺寸上限**：由 `CHIMERAX_OHOS_OFFSCREEN_WIDTH/HEIGHT` 与 `GL_MAX_RENDERBUFFER_SIZE` 决定。

### 2.5 验证判据（方案 A）
- `context_class == 'EGLContext'`、`GL_VERSION` 含 `OpenGL ES 3.`、`SHADING_LANGUAGE_VERSION` 含 `ES`
- 探针 stage `fbo`：1×1 读回 `[64,128,191,255] ±4`
- 探针 stage `drawing`：中心像素红通道 > 60 且 > 绿通道、左上角 < 20、红像素占比 0.15–0.75
- 探针 stage `shader-translation`：两份 shader 均无 `#version 330`，含 `precision`
- 设备上 `view.image_rgba()` 返回非 None 且尺寸正确

### 2.6 工作量：**6–9 h**
- 上下文类 + 平台探测 + 库加载：3 h（已由补丁覆盖约 2/3）
- GLSL ES 迁移与着色器编译调试：2–4 h
- 像素判据调平（相机取景、光照、背景）：1–2 h

---

## 3. 方案 B —— native 通过 N-API 把 EGL 句柄交给 Python

### 3.1 需要的句柄与调用
```
napi 导出 getEglHandles(): { display: bigint, context: bigint, surface: bigint, width, height, threadId }
```
Python 侧用 `ctypes.c_void_p(int(handle))` 复原成 `EGLDisplay/EGLContext/EGLSurface`，然后只做：
```
eglMakeCurrent(display, surface, surface, context)   # 其余交给 ChimeraX
```
句柄以 `int` 传递（JS number 安全整数或 BigInt），**不能**传裸指针对象。

### 3.2 注意事项
- **线程**：N-API 调用返回的句柄只在其 EGL 上下文所属线程可用；跨线程 `eglMakeCurrent` 会失败或崩。必须让 Python 渲染在 native 的 GL 线程上执行（`napi_threadsafe_function` 回投），或让 native 在 Python 取值时把 thread id 一并返回、Python 侧断言一致。
- **共享上下文**：若要 Python 自建上下文与 native 共享 GL 对象（纹理/FBO），第三个参数传 `share_context = native g_context`；本方案不建上下文，故无需。
- **生命周期**：`OnSurfaceDestroyedCB()` 会 `eglDestroyContext/Terminate`，Python 侧必须把句柄当作可失效（每次绘制前 `eglGetCurrentContext()` 复核，或用 `glStatus` 轮询）。
- **窗口尺寸变化**：`OnSurfaceChangedCB()` 后 surface 仍有效但尺寸变，`View.resize(w,h)` 要跟着调用。

### 3.3 改动点
| 文件 | 位置 | 改动 |
|---|---|---|
| `app/entry/src/main/cpp/gl_surface.cpp` | 匿名命名空间 + 新增 C 导出 | 保存 `g_config`、暴露 `ChimeraXGLDisplay/Context/Surface/ThreadId()` |
| `app/entry/src/main/cpp/chimerax_native.cpp` | `napi_define_properties` 表（`~636-643`） | 增 `getEglHandles` |
| `chimerax/graphics/opengl.py` | 同方案 A 的 `EGLContext` | 增加 `_from_handles()` 构造分支（不做 `eglCreate*`） |

### 3.4 风险
- 需要改 `app/` 并重编 HAP ⇒ **与"不改 app/native"的硬约束冲突**，只能由主线另开任务。
- 线程语义最脆：native 回调线程 ≠ CPython 执行线程时必失败，需要 threadsafe-function 回投，牵动 `runChimeraCommand` 的调用约定。
- 句柄裸转 int 的 ABI 依赖（32/64 位、`EGLNativeDisplayType` 是否为指针）需在设备上核对。

### 3.5 验证判据
- `getEglHandles()` 返回四元组且 `context != 0`
- Python `eglGetCurrentContext() == 传来的 context`
- 之后与方案 A 相同的 `fbo`/`drawing` 像素判据

### 3.6 工作量：**8–12 h**（含改 native + 重编 + 线程模型调试）
**相对方案 A 无净收益**：同进程下 `eglGetCurrentContext()` 已经免费拿到全部句柄，方案 B 只是在拿不到时才有意义 —— 而拿不到的场景（线程不符）恰恰是方案 B 也解决不了的。

---

## 4. 方案 C —— 纯离屏（OSMesa / 软件光栅）

### 4.1 可行性评估
- CHimeraX 上游已有 OSMesa 通道：`_configure_pyopengl_to_use_osmesa()` + `OffScreenRenderingContext`（`opengl.py:378-399`, `3430-3486`），要的是 `libOSMesa.so`（Mesa `--enable-gallium-osmesa`，桌面 GL 3.3 core）。
- 在 OHOS aarch64-musl 上自建 Mesa/OSMesa：需要 llvmpipe（LLVM JIT）或 softpipe；交叉编译量大（LLVM + Mesa + musl），本任务明确"不联网编译大型依赖" ⇒ **本轮不可行**。
- 只做软件光栅（自己写三角形填充）意味着重写 `Drawing.draw` 的整条管线（shader、光照、透明度排序、轮廓），量级数百小时，且与上游分叉。

### 4.2 结论与保留价值
- **不作为主路径**；作为"绝对兜底 + 回归基线"：若设备 GLES 侧出现驱动级问题，可用桌面端 OSMesa 产生参考图做像素回归。
- 改动点（若将来做）：`_configure_pyopengl_to_use_osmesa` 的库定位 + `requirements` 增加 `osmesa` 包；Python 侧零改动（`OffScreenRenderingContext` 现成）。
- 风险：性能（llvmpipe 单线程，分子场景不可用）、包体（+80–150 MB）、交叉编译链复杂。
- 验证判据：与设备 GLES 渲染同场景做 SSIM/像素差回归。
- 工作量：**40–80 h**（交叉编译 Mesa/LLVM）+ 后续维护。

---

## 5. 推荐与落地方案

**推荐方案 A（A1 沿用 native 上下文，A2 pbuffer 兜底）**，理由：
1. 同进程 ⇒ 无需句柄传递，`eglGetCurrentContext()` 一步到位，**零 native 改动**，符合"不改 app/native"约束。
2. 与上游 `OffScreenRenderingContext` 同构，`Render`/`Framebuffer`/`View` 全部复用，补丁只有 8 个 hunk、约 330 行新增。
3. GLES3 缺失特性在本代码里几乎为零（§1 表），GLSL 只有两份且单点改造。
4. 失败可降级：A1 失败 → A2 pbuffer → 仍失败则明确报出 `EGL: no display`，比方案 B 的线程死锁更可诊断。

### 5.1 补丁内容（`patches/0005-render-ohos-egl-context.patch`）
对 `src/bundles/graphics/src/opengl.py`，8 个 hunk：
1. 模块级 OHOS 探测与工具函数（`running_on_ohos/_detect_ohos/ohos_glsl_version/_pin_ohos_egl_libraries`）
2. `_initialize_pyopengl()`：OHOS 固定 `PYOPENGL_PLATFORM=egl` 并预加载 EGL/GLES
3. `remember_current_opengl_context()` → `_egl_remember_current()`
4. `restore_current_opengl_context()` → `_egl_restore_current()`
5. `opengl_version_number()`：解析 `OpenGL ES x.y`
6. `Render.check_opengl_version()`：按 context 声明的最低版本判定
7. `Shader.insert_define_macros()`：接入 `translate_shader_to_gles()`
8. 新增 `EGLContext` 类 + `translate_shader_to_gles()` + 模块尾部 `OpenGLContext = EGLContext` 重绑定

已验证：`cd build/downloads/ChimeraX-src && git apply --check ../../../patches/0005-render-ohos-egl-context.patch` → OK，上游树保持 0 改动。

### 5.2 设备验证步骤（由主线执行）
```bash
# 1) 应用补丁到暂存包树（不改上游树）
cd build/chimerax-python && patch -p3 --dry-run < ../../patches/0005-render-ohos-egl-context.patch
#    确认后去掉 --dry-run

# 2) 环境变量（应用内执行，继承 native 环境）
export PYOPENGL_PLATFORM=egl
export CHIMERAX_OHOS=1
export CHIMERAX_PIXEL_SCALE=1.0        # 若 XComponent 是 2x density 则设 2.0

# 3) 探针
python3 tools/render_probe.py --size 256x256 --out /data/local/tmp/render-probe.json
echo "exit=$?"     # 0 = 全部通过

# 4) 需要真实分子时
python3 tools/render_probe.py --atomic --size 512x512
```
判据（与 §2.5 一致）：`context` → `GL_VERSION` 含 `OpenGL ES 3.`；`fbo` → 1×1 像素 `[64,128,191,255]±4`；`drawing` → 中心红>60、角落<20、红占比 0.15–0.75；`shader-translation` → 无 `#version 330`。
失败时分阶段定位：`environment` 失败=包树/路径问题；`context` 失败=`eglGetDisplay` 或 libEGL 加载；`fbo` 失败=FBO/深度格式；`drawing` 失败=GLSL ES 或相机取景。

### 5.3 已知风险与缓解
| 风险 | 缓解 |
|---|---|
| Python 与 native 不同线程 | 探针报告 `adopted_existing_context`；为 false 时走 A2 pbuffer 并提示主线把绘制投到 GL 线程 |
| GLSL ES 编译失败 | `CHIMERAX_OHOS_GLSL_VERSION=310 es/320 es` 逐级尝试；编译日志经 `OpenGLError` 原样抛出 |
| 深度 24 位未满足 | 自动 `offscreen_outline=True`（上游已有逻辑），仅影响描边路径 |
| 高分屏像素比 | `CHIMERAX_PIXEL_SCALE` 覆盖 `pixel_scale()` |
| 上下文随 surface 销毁失效 | `EGLContext.delete()` + `OnSurfaceDestroyedCB` 后重建；`created` 属性反映失效 |

---

## 6. 交付物
- `patches/0005-render-ohos-egl-context.patch`（8 hunk，`git apply --check` 通过）
- `tools/render_probe.py`（设备侧自检，退出码 0/1/2）
- `reports/render-plan-2026-11-18.json`（结构化结论）

## 7. 工时汇总
| 方案 | 工作量 | 是否需改 app/native | 结论 |
|---|---|---|---|
| **A（推荐）** | **6–9 h** | 否 | 采纳 |
| B | 8–12 h | 是（+重编 HAP） | 无净收益，暂不做 |
| C | 40–80 h | 否 | 仅作回归基线 |
