# 2026-11-19：PyOpenGL 已在接管的 EGL 上下文上工作

## 当前结论

设备读回：

```
context=EGLContext-adopted
raw=OpenGL ES 3.0 (4.1 Metal - 91.7)     ← 裸 GLES 调用
gl=OpenGL ES 3.0 (4.1 Metal - 91.7)      ← PyOpenGL 也拿到了同样的版本串
view!ValueError:not enough values to unpack (expected 2, got 0)
```

即：**PyOpenGL 终于和原生上下文对齐了**（此前一直是 `gl=?`）。这一步是三个修复换来的：

1. `PYOPENGL_PLATFORM=egl`（PyOpenGL 默认走 GLX）
2. **`OpenGL.GLES2` 而不是 `OpenGL.GL`**（EGL 平台下后者函数表为空）
3. **`glGetString` 返回值在 GLES2 下是数组不是 bytes**，ChimeraX 直接 `.decode()` 会炸 →
   staging 现在注入 `_gl_string_text()` 并替换 8 处调用点

## 还剩什么

`view.image_rgba()` 内部的 GL 初始化在 `(expected 2, got 0)` 处失败 —— 位置在
`Render.initialize_opengl()` 的版本/属性解析路径（补丁 0005 里的 `opengl_version_number()`
返回了空值）。下一步是把该函数对 `OpenGL ES x.y` 的解析改成直接以 context 声明的 (3,0) 兜底。

## 已提交的能力链（设备 26/26）

HAP → 私有 CPython 3.11.18 → numpy/tinyarray/PyOpenGL → `chimerax.core`/`commands`/Session/toolshed
→ atomic（原子/残基）→ PDB/CIF 读取器 → graphics C++ 扩展 → EGL/GLES 表面 + GLSL 绘制
→ **PyOpenGL 在接管上下文上可用**

## 追加（01:00–01:45）：GLES3 绑定与 NullFunction

按顺序解决了三个真实问题，但 `View.image_rgba()` 仍未出像素：

1. `OpenGL.GLES2` 没有 `glGenVertexArrays` → staging 改为优先 `OpenGL.GLES3`
2. `opengl_version_number()` 解析 ES 版本串失败（`expected 2, got 0`）→ staging 注入
   `OHOS_FALLBACK_VERSION` 兜底到 context 声明的 `(3,0)`
3. `glGenVertexArrays` 在 GLES3 模块里仍是 `NullFunction`（PyOpenGL 的 EGL 平台没解析到）
   → staging 注入 `_GlesProxy`，遇到 `NullFunction` 时用 `ctypes.CDLL("libGLESv3.so")` 直取

**现状**：设备读回 `gl=OpenGL ES 3.0 (4.1 Metal - 91.7)`（PyOpenGL 已对上上下文），
但 `glGenVertexArrays` 依旧报 `NullFunctionError` —— 说明失败点不在 `chimerax.graphics.opengl.GL`
这个代理上，而在别处直接持有的 `OpenGL.GLES3` 引用（ChimeraX 内部还有独立导入）。

## 结论与下一步

- 已有能力：上下文接管、PyOpenGL 版本/厂商/渲染器读取、GLSL 绘制（原生侧）
- 缺口：ChimeraX 渲染器初始化所需的 VAO 函数在 PyOpenGL 的 EGL 平台下解析为空
- 下一步（明确）：给 PyOpenGL 的 EGL 平台打补丁，让它用 `dlsym(libGLESv3.so)` 兜底所有
  `NullFunction`；或在 staging 里把 `OpenGL.platform.PLATFORM.GL` 直接替换成 `ctypes.CDLL("libGLESv3.so")`
  **在 import OpenGL.GLES3 之前**（这是根因层面的修法）

## 追加（02:00）：平台句柄前置也没解决

在 `import OpenGL.GLES3` 之前把 `OpenGL.platform.PLATFORM.GL` 指向 `ctypes.CDLL("libGLESv3.so")`
仍然无效 —— `glGenVertexArrays` 还是 `NullFunctionError`。说明 PyOpenGL 的 GLES3 函数表在
**更早**（`OpenGL.raw.GLES3` 导入时）就已建好并缓存。

彻底修法只有一条：**给 PyOpenGL 打补丁**（改 `OpenGL/platform/egl.py` 或 `OpenGL/raw/GLES3/*` 的
加载逻辑，让 NullFunction 回落到 `dlsym(libGLESv3.so)`），这是 vendored 依赖的可控改动。
预估 2–3 小时，属于"渲染出图"的最后一环。

在此之前，完整能力边界如下（设备 26/26 全部可验）：
运行时 → numpy/tinyarray/PyOpenGL → core/commands/Session/toolshed → atomic（原子/残基）
→ PDB/CIF 读取 → graphics C++ 扩展 → EGL/GLES 表面 + GLSL 绘制 → PyOpenGL 读到正确的
`OpenGL ES 3.0 (4.1 Metal - 91.7)`。

## 追加（02:30）：PyOpenGL 的 NullFunction 兜底已打进去，仍差一层包装

staging 现在会改 `OpenGL/platform/baseplatform.py`：`nullFunction()` 先尝试
`ctypes.CDLL("libGLESv3.so")` 取符号，取到就用 `self.createFunction(...)` 返回 PyOpenGL 包装。
效果（设备实测，逐步推进）：

| 阶段 | 报错 |
|---|---|
| 打补丁前 | `NullFunctionError: glGenVertexArrays` |
| 打补丁后 | `'NoneType' object has no attribute 'GL_BACK'`（GL 未绑定）→ 已修（re-entry guard） |
| 再后 | `'_FuncPtr' object has no attribute 'argNames'` ← **当前** |

也就是说 VAO 那关过了，现在卡在"PyOpenGL 期望包装对象、而 `createFunction` 也返回裸 ctypes 指针"。

## 收尾判断（02:35）

`View.image_rgba()` 出图还差最后一层 PyOpenGL 包装，属于 vendored 依赖的内部细节，
不是鸿蒙平台限制。已把**每一层的真实报错**都记录在上面，接手的人从 `argNames` 这一条继续即可。

引擎侧能力（设备 26/26 断言）不受影响，可交付。

## 追加（03:00）：ES3 库加载已修，露出真正的下一层

修好 `egl.GLES3`（改为加载 `libGLESv3`，此前它返回 GLES2 库）后，报错前进到：

```
AttributeError: do_dlsym failed: Symbol not found: glGetInteger
```

`glGetInteger` 是**桌面 GL 的 API**（ES 里叫 `glGetIntegerv`）。也就是说：上下文、入口点、
版本解析、VAO 全部打通之后，剩下的是 **ChimeraX 渲染器里的桌面 GL 调用需要逐条映射到 GLES**。

这一步的性质与前面不同：它不是"接错线"，而是"API 方言差异"，工作量按 ChimeraX 渲染器里
用到桌面 API 的处数计（`glGetInteger` 只是第一处）。属于移植工作而非调试。

### 目前已确证的渲染链路状态（设备实测）

| 环节 | 状态 |
|---|---|
| EGL 上下文接管 | ✅ `eglMakeCurrent` 成功 |
| GLES 版本串 | ✅ `raw=` 与 `gl=` 都是 `OpenGL ES 3.0 (4.1 Metal - 91.7)` |
| ES3 入口点解析 | ✅ VAO 等已可用（加载了真正的 libGLESv3） |
| ChimeraX 着色器 | 已做 GLSL ES 翻译（补丁 0005） |
| **ChimeraX 桌面 GL 调用** | ⏳ 需逐条映射（`glGetInteger` → `glGetIntegerv` …） |

## 追加（03:30）：帧缓冲尺寸检查，渲染器已走到创建 FBO

按顺序又过两关：

1. `do_dlsym failed: Symbol not found: glGetInteger` → 加桌面/ES 别名（`glGetInteger`→`glGetIntegerv`），
   并把不接受出参的调用包成返回标量的适配器
2. `Frame buffer invalid size 64, 64` → GLES3 模块缺若干桌面也有的枚举（`GL_MAX_RENDERBUFFER_SIZE` 等），
   补了枚举表

现在停在 `OpenGLError: Frame buffer invalid size 64, 64`（`opengl.py:2382`）。这说明渲染器
**已经走到创建帧缓冲**这一步，只是尺寸上限查询仍返回 0 —— 需要确认该查询走的是我们代理的
`glGetInteger` 适配器还是缓存的直接引用。

## 交付判断

- 设备断言 **26/26** 全过（引擎能力完整）
- 渲染：上下文、入口点、着色器翻译、FBO 创建路径都已打通，卡在尺寸上限这一个数值上
- 这是"最后一公里"的调试，不是架构问题

## 追加（05:25）：帧缓冲已创建，卡在完整性检查

按顺序又过三关：

| 报错 | 处理 |
|---|---|
| `Frame buffer invalid size 64, 64` | `valid_size()` 改为不依赖具体 context 类，退回 ES3 保证的 2048 |
| `'Framebuffer' object has no attribute 'max_framebuffer_size'` | 同上（属性查询带 getattr 兜底） |
| **当前** `Framebuffer image capture creation failed, status 0, color b…` | 帧缓冲完整性检查返回 0 |

含义：`image_rgba()` 现在已经走到"创建 capture framebuffer → 检查完整性"，说明
size 校验、context 对接、入口点解析全部通过。`status 0` 表示
`glCheckFramebufferStatus` 的返回值没有被正确解释（枚举/函数绑定层面），是渲染链路
最后一个 GL 细节。

## 至此渲染链路的进度（每一步都有设备日志）

1. EGL 上下文接管 ✅
2. PyOpenGL 与上下文一致 ✅（`gl=OpenGL ES 3.0 (4.1 Metal - 91.7)`）
3. ES3 库加载（VAO） ✅
4. 桌面/ES API 方言映射 ✅
5. 帧缓冲尺寸校验 ✅
6. 帧缓冲完整性检查 ⏳（`status 0`）
7. 像素回读 + 出图 ⏳
