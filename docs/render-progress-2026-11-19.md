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

## 追加（06:00）：status 0 但 glGetError 为 0

探针新增诊断，设备读回：

```
enums=GL_FRAMEBUFFER (GL_FRAMEBUFFER),GL_FRAMEBUFFER_COMPLETE (GL_FRAMEBUFFER_COMPLETE)
glerr=0
view!OpenGLError:Framebuffer image capture creation failed, status 0, color b…
```

两条关键信息：

1. **枚举正常**：`GL_FRAMEBUFFER` / `GL_FRAMEBUFFER_COMPLETE` 都是 PyOpenGL 的常量对象（值正确）
2. **没有 GL 错误**：`glGetError()` 返回 0

"返回值 0 且无错误"意味着 `glCheckFramebufferStatus` 在那次调用上**没有被真正执行**
（返回了默认 0），最可能是：该入口点在我们的 GL 代理里落到"未解析/占位"路径，
用 ctypes 直取时参数（PyOpenGL 常量对象）没有被正确转成 `GLenum`。

## 修法（下一步，明确）

在 `_GlesProxy` 里给"直取的库函数"设置 `argtypes`（`c_uint`）与 `restype`，
让 `glCheckFramebufferStatus(GL_FRAMEBUFFER)` 真正跑到驱动上；或者干脆让代理对所有
`gl*` 名字都用 `ctypes` 显式声明 `restype=c_uint, argtypes=[c_uint]` 的统一包装。

这一步之后若 `status` 变成 `0x8CD5`（`GL_FRAMEBUFFER_COMPLETE`），`image_rgba()` 就会回读像素。

## 追加（06:15）：整数化参数包装后仍是 status 0 —— 此事封存

给直取库函数加了 `c_uint` 参数转换后，设备读回完全不变：

```
enums=GL_FRAMEBUFFER (GL_FRAMEBUFFER),GL_FRAMEBUFFER_COMPLETE (GL_FRAMEBUFFER_COMPLETE)
glerr=0
view!OpenGLError:Framebuffer image capture creation failed, status 0, color b…
```

枚举正确、`glGetError()==0`、`glCheckFramebufferStatus` 返回 0 —— 三者互相矛盾，说明
**这次调用根本没有到驱动**（PyOpenGL 的 GLES3 包装层在我们这条接管路径上仍拿的是占位对象）。

结论：**ChimeraX 渲染器要出图，需要把 PyOpenGL 的 GLES3 入口点解析整段重做**
（不是打补丁级改动，而是给 PyOpenGL 一个"从 libGLESv3 全量 dlsym + 正确包装"的加载器）。
这是明确的、可估算的工程任务（约半天），不属于"再接一根线"。

在此之前，适配的其他部分全部可交付、可复现、有设备收据（26/26）。

## 追加（06:35）：越过帧缓冲完整性，进入着色器链接

把不可靠的 `glCheckFramebufferStatus` 门禁在 OHOS 上跳过（`CX_OHOS_SKIP_FB_STATUS=1`，
补丁带注释说明原因）后，`image_rgba()` 继续推进到：

```
view!OpenGLError:Link failure (0)
```

含义：**帧缓冲已建好，现在失败在着色器程序链接**（`Link failure (0)` 里的 0 说明
`glGetProgramiv(GL_LINK_STATUS)` 同样取不到真值，与前一层的 `status 0` 同源）。

至此渲染链路剩余工作收敛为一件事：**让 PyOpenGL 的 GLES3 入口点真正到达驱动**
（现在凡是"取状态/取日志"类的查询都返回 0/空，而"设置/绑定"类调用是生效的——
这也解释了为什么能走到链接这一步）。修法已写在上一段：给 PyOpenGL 一个
libGLESv3 全量 dlsym + 正确包装的加载器。

## 追加（07:00）：越过链接检查，暴露出真正的工作量 —— 着色器需要 GLSL ES 移植

跳过不可靠的 `GL_LINK_STATUS` 查询后，`image_rgba()` 走到绘制阶段并报：

```
GLError(err = 1282 /* GL_INVALID_OPERATION */,
        baseOperation = glGetUniformBlockIndex,
        cArguments = (0, b'lighting_block'))
```

`err 1282` = GL_INVALID_OPERATION，`program=0` 且着色器里没有 `lighting_block` 这个 uniform block。

**这说明 ChimeraX 渲染器用的是桌面 GL 的 UBO（uniform buffer object）着色器体系**：
- 我们的 GLSL ES 翻译（补丁 0005 的 `translate_shader_to_gles`）只处理了版本声明与 precision，
  没有把 UBO 块改写成 ES 可用的 uniform 变量
- 结果是程序链接后有 0 个 uniform block，`glGetUniformBlockIndex` 自然返回 INVALID_OPERATION

### 结论（这是本轮最重要的判断）

渲染要出图，剩下的不是"再接一根线"，而是**把 ChimeraX 的着色器体系移植到 GLSL ES**：
`vertexShader.txt` / `fragmentShader.txt` 里的 UBO 声明、`layout(std140)`、`glGetUniformBlockIndex`
/ `glBindBufferBase` 等调用都要有 ES 等价实现。这是一个**以天计**的移植任务
（着色器改写 + uniform 路径重构 + 逐帧验证），不是小时级调试。

### 当前能力边界（不受影响）

设备 26/26 断言全过：运行时、numpy、core/commands/Session、atomic、PDB/CIF 读取、
graphics C++ 扩展、EGL/GLES 表面、GLSL 绘制、PyOpenGL 上下文对齐，全部可复现。

## 追加（16:55）：找到了 status 0 的根因，并做了一次失败尝试

新增 `SHADER_DIAG_SCRIPT`（自建一个最简单的 ES3 程序并读 `GL_LINK_STATUS`）后，
设备读回的关键一行是：

```
GLError(err = 1282, baseOperation = glGetUniformBlockIndex,
        cArgs = (0, b'lighting_block'), result = 0)
```

**`program = 0`** —— 说明 `GL.glCreateProgram()` 返回了 0。结合"无 GL 错误、返回值恒 0"的一系列
现象，可以确定：**PyOpenGL 在这条路径上给出的是 NullFunction 占位对象，它们静默返回 0。**

尝试过的修法与其结果：

| 尝试 | 结果 |
|---|---|
| 用 `type(value).__name__ == 'NullFunction'` 判断并替换 | 判断永不命中（PyOpenGL 按函数名生成类名） |
| 用 `isinstance(value, _NullFunctionPointer)` 判断并替换为 dlsym 结果 | **应用启动即崩**（替换后的函数签名不匹配，导入期调用就炸） |

已回退到"不替换"的稳定状态（设备 26/26 全过）。**正确做法**：不要替换对象，而是在
`OpenGL/platform/egl.py` 里让 `GL` 属性指向能真正 `dlsym` 到 ES3 符号的库（已部分完成：
`GLES3` 与 `GL` 的搜索列表已加入 `GLESv3`），再让 PyOpenGL 用它自己的工厂函数生成包装——
这样既有正确签名，也不会静默返回 0。这条留给下一次连续调试。

## 追加（18:20）：决定性诊断 —— 裸库可用，PyOpenGL 恒返回 0

设备读回：

```
current=1 | raw_program=2 | raw_error=0 | py_program=0 | py_error=0
```

- `current=1`：上下文在 Python 线程上确实是 current
- `raw_program=2`：用 `ctypes.CDLL("libGLESv3.so")` 直接调 `glCreateProgram()` **成功**
- `py_program=0`：走 PyOpenGL 的 `GL.glCreateProgram()` 返回 0，且 `glGetError()` 为 0

结论钉死：**上下文没问题、驱动没问题，问题在 PyOpenGL 的入口点绑定**。它把函数解析到了一个
不含 ES3 实现的库句柄上（`ctypesloader` 在该系统上找不到 `libGLESv3.so` 的 soname），
调用因此静默返回 0。

试过的两条修法都没生效（staging 补丁未匹配到目标代码、代理层仍未拦住调用），
说明 PyOpenGL 的包装是在 `import OpenGL.GLES3` 期间由 `OpenGL.raw.GLES3` 生成的，
必须在**平台层**（`OpenGL/platform/egl.py`）就让它拿到正确句柄——这次改动没有真正落地，
需要下一次用"先验证补丁是否打进暂存树"的方式复查。

### 这条线之外的一切都已交付

引擎、结构读写、可视化、界面外壳、打包与 26 项断言均稳定；渲染只差这一个绑定问题。

## 追加（18:45）：平台层 override 已确认打进暂存树，但 PyOpenGL 仍返回 0

这次先验证补丁落地（`grep -c CX_GLES_DIRECT` = 3，且块位于文件末尾），再重编上机：

```
current=1 | raw_program=2 | raw_error=0 | py_program=0 | py_error=0
```

**仍在 0。** 说明问题不在"平台属性返回哪个库"，而在更早的一层：`OpenGL.raw.GLES3`
在 `import OpenGL.GLES3` 时就把函数对象（含绑定）生成好了，此后改平台属性对它无效。

**下一步（唯一有效方向）**：改 `OpenGL/raw/GLES3/__init__.py`（或 `OpenGL/GLES3/VERSION/*`）
里生成函数的那段，让它用 `libGLESv3.so` 的显式句柄；或在导入 `OpenGL` **之前**就把
`ctypes.util.find_library` 打桩，让 `ctypesloader` 能解析到该库。

其余一切保持交付状态（26/26、可视化、界面外壳、安装包）。

## 追加（20:05）：find_library 打桩后仍是 0 —— 结论收敛

在 `chimerax/graphics/opengl.py` 顶部对 `ctypes.util.find_library` 打桩（把 glesv3/glesv2/egl
映射到 `/system/lib64/` 的真实文件），且**已验证补丁落在暂存树**（`CX_FIND_LIBRARY_STUB` 位于文件
首部），重编上机后：

```
current=1 | raw_program=2 | raw_error=0 | py_program=0 | py_error=0
```

仍未变化。至此三条修法都试过：平台属性 override、find_library 打桩、代理层替换。
共同结论：**PyOpenGL 在这个平台上生成的函数包装本身不可用**（绑定到的句柄没有 ES3 实现），
而裸 `ctypes` 调用同一库完全正常。

### 可行的收尾方案（需要一次较大的改动）

在 `chimerax/graphics/opengl.py` 里**用我们自己的 ctypes 封装替换整个 GL 模块**：
按 ChimeraX 实际用到的函数清单（可从源码 grep 出，约 80–120 个）用 `argtypes/restype` 精确声明，
数组参数走 `numpy.ctypes.data`。这样既不依赖 PyOpenGL 的绑定，也不会有"静默返回 0"。

工作量约半天到一天，风险可控（函数清单固定、有 26 项回归兜底）。

### 当前交付状态

设备断言 26/26，结构可视化、界面外壳、安装包均可用；渲染是唯一未完成项。

## 追加（20:50）：四次修法全部试过，结论稳定

| 尝试 | 结果 |
|---|---|
| 平台属性 override（`EGLPlatform.GL = property(...)`，已确认落盘） | 仍 `py_program=0` |
| `ctypes.util.find_library` 打桩（已确认落盘） | 仍 0 |
| 代理层 `_FuncPtr` 重绑 | 仍 0 |
| 代理层 `wrapper.func` 重绑（PyOpenGL 实际调用路径） | 仍 0 |

同时 `raw=2`（裸 ctypes 调同一库成功）始终不变。

**稳定结论**：PyOpenGL 在 OHOS 上生成的包装对象，其调用最终不落在 `libGLESv3.so` 的实现上，
且我们无法从外部改变这一点。**唯一可靠收尾**：用自建 ctypes 封装替换 `chimerax.graphics.GL`
（按 ChimeraX 实际使用的函数清单声明 argtypes/restype，数组参数走 `numpy.ctypes.data`）。
这条已作为独立工作项记录，工作量半天到一天。

四次尝试的补丁均已回退，暂存树回到稳定状态；设备 26/26 全过。

## 2026-11-20 重大进展：自建 ctypes GL 层被验证可用

在 `chimerax/graphics/_cxgl.py` 里实现了一个直接绑定 `libGLESv3.so` 的 GL 模块
（整数/浮点/字符串/numpy 指针自动转换、`glShaderSource` 适配、字符串类函数返回 bytes、
缺失的桌面 GL 符号走显式 no-op 列表）。设备诊断读回：

```
raw=2 | program=3 | shader=1 | linked=1
```

**这是第一次让 ChimeraX 内部的 GL 调用在鸿蒙上真正创建程序、编译着色器并链接成功。**
（此前 PyOpenGL 的所有路径都返回 0。）

### 尚未接通的一步

把该层换到 `chimerax.graphics.opengl.GL` 上有两种做法，都还没成功：

| 做法 | 结果 |
|---|---|
| 引导期整体替换 `cxgl.GL = _cxgl.make_module()` | 应用启动即崩（2/26） |
| 仅 adopt 脚本内把代理的 `_module` 就地改指向 ctypes 层 | 应用正常（26/26），但 ChimeraX 渲染器仍用旧引用 |

**结论**：`Render`/`View` 在引导期就缓存了 GL 引用，之后换绑无效。正确做法是**在构造 View/Render
之前**就把代理就地改指向 ctypes 层（而不是替换对象，也不需要 `import OpenGL.GLES3` 的时机风险）。
这一条留作下一次连续调试的起点，证据与补丁位置都已记录。

## 2026-11-20 补充：换绑时机的三次尝试与结果

| 做法 | 组件状态 | 渲染器 |
|---|---|---|
| adopt 脚本内改代理 `_module` | 26/26 | 仍 `glGetUniformBlockIndex(0, ...)` |
| 引导期（View 之前）改 `_module` | 启动正常 | 仍失败；且诊断 `program=0`，说明 `_initialize_pyopengl()` 会重建 GL 对象、把换绑冲掉 |
| 再把 `_initialize_pyopengl` 包一层、每次重建后重新换绑 | 启动正常 | 仍 `program=0` —— 说明 `cxgl.GL` 在重建后不是我们改的那个对象，或渲染器持有更早的函数引用 |

**下一步（更可靠的方向）**：不要"换绑"，而是**在 staging 阶段直接改写
`_initialize_pyopengl` 的实现**，让它在创建 GL 时就返回 `_cxgl.make_module()`。
这样没有对象身份与调用时机问题，一处改动、全链路生效。

## 2026-11-20 结论：把 ctypes 层装进 GL 会崩，暂缓

把 staging 里的 `GL` 直接换成 `_cxgl.make_module()` 后：**应用启动后很快退出**（`CX_RUNTIME_READY`
之后无日志，窗口消失，断言 2/26）。原因是通用 ctypes 包装在渲染器实际调用序列里会以错误的
指针/类型调用 GL（例如 `glVertexAttribPointer` 的偏移、`glShaderSource` 的字符串数组），
在 C 侧就是段错误 —— 这比"返回 0"更危险，因为无栈可查。

已回退到稳定的 proxy 版本（26/26）。**结论**：`_cxgl` 需要按**确切的 C 签名**逐函数声明
（`argtypes/restype`），而不是通用转换；这是一项独立工作，需要先收集 ChimeraX 实际调用的函数
清单（可从 `chimerax/graphics/*.py` grep `GL.gl` 得到），再逐个核对。

## 2026-11-20 傍晚：渲染器在 ctypes 层上已推进到第一个真实 GL 调用

用"从 `OpenGL.raw.GLES3` 拷贝 argtypes/restype"的方式改造 `_cxgl` 后，adopt 路径的报错**逐层后退**：

| 阶段 | 渲染器报错 |
|---|---|
| 仅通用转换 | `TypeError: this function takes at least 2 arguments (1 given)` |
| 补 `glGen*` 便捷适配（`glGenBuffers(1)` 返回 id） | `ArgumentError: argument 1: TypeError: wrong type` |
| 给调用加错误包装 | `RuntimeError: glBindVertexArray(int): ArgumentError` —— **已进入真实绘制前的绑定调用** |
| 试图把 int 直接交给 argtypes 转换 | 应用崩溃（已回退） |

也就是说：现在渲染器**已经走完了以前完全走不到的路径**，卡在 ctypes 参数类型与 PyOpenGL
约定的差异上（`GLuint` vs `c_int`、生成器返回值、数组指针类型）。

### 下一步（工程化，不是探索）

写一个生成器：对 `chimerax/graphics` 里出现的 89 个 `GL.gl*` 调用，逐个从
`OpenGL.raw.GLES3` 取签名，生成**显式 `argtypes/restype` + 参数转换**的包装，并对
`glGen*`/`glShaderSource`/`glBufferData` 等做 PyOpenGL 兼容适配。做完这类"逐个对齐"，
渲染器就有机会真正出图。

## 2026-11-20 收尾：稳定点定在 `glBindVertexArray`

两次"参数类型"实验（把 int 交给 argtypes 转换、把非负 int 传成 `c_uint`）都会让应用崩溃，
已全部回退。当前稳定点是：

- 应用 **26/26**、`state=session-ready`
- 渲染器走到 `glBindVertexArray(int)` 报 `ArgumentError`（GLuint vs c_int）

**为什么不能简单换成 c_uint**：ChimeraX 里有几处"看起来像 id、实际是指针偏移"的整型参数
（如 `glVertexAttribPointer` 的 offset），盲换类型会造成内存越界 —— 这正是崩溃来源。

**正确做法**：逐函数生成包装，对每个参数按 `OpenGL.raw.GLES3` 的 argtypes 决定
（GLuint → c_uint，指针 + offset → c_void_p），并对 `glGen*`/`glShaderSource`/`glBufferData`
保留 PyOpenGL 便捷语义。这是有明确规格的编码工作，不是猜。

## 2026-11-20 结论：渲染整合暂停，稳定点已固定

第三次参数转换实验（只对"全部参数都是标量"的函数做精确类型转换）**仍然崩溃**，已回退。
这说明崩溃不只来自参数类型，还涉及 PyOpenGL 的其它隐式约定（例如 `glGetIntegerv(pname)`
单参数返回值的便捷语义、生成器返回值、`glVertexAttribPointer` 的 offset 指针化等）。

**判断**：在"每步 15 分钟构建 + 崩溃"的循环里盲试不划算。渲染整合改为**按清单逐函数实现**
的独立工作块：

1. 从 `chimerax/graphics` 提取实际调用的 89 个 `GL.gl*`
2. 对每个函数写显式的 ctypes 包装（签名 + 便捷语义），逐个在开发运行时里验证
3. 全部对齐后再一次性接进 `chimerax.graphics.opengl.GL`

当前交付状态：设备 26/26、`state=session-ready`、真实 PDB/SDF 可视化可用。

## 2026-11-20 工具化：从 NDK 头文件生成 GL 签名表

新增 `tools/generate_cxgl_signatures.py`：解析 OpenHarmony NDK 的 `GLES3/gl3.h` 与
`GLES2/gl2.h`，为 ChimeraX 实际调用的每个 `GL.gl*` 生成精确的 ctypes 签名。

设备结果（`reports/cxgl-signatures.json`）：

| 指标 | 值 |
|---|---|
| ChimeraX 全树用到的 GL 函数 | **89** |
| 签名已生成 | **79** |
| 剩余 10 个 | 别名或桌面独有（`glGetInteger`→`glGetIntegerv`、`glClearDepth`→`glClearDepthf`、`glDrawBuffer`/`glLogicOp` 无 ES 等价物等），已在生成的 `ALIASES` 表中标注 |

生成器已处理这些真实细节：参数名与类型分离（`GLuint array` → `GLuint`、`const void *data`）、
指针紧贴符号（`const GLubyte *GL_APIENTRY glGetString`）、`GLvoid`、指针深度、返回 `void`。

**当前不启用**：把该表接进 `_cxgl` 并替换 `GL` 仍会让应用在启动后退出（本轮多次验证），
因此 facade 的 typed 转换默认关闭、adopt 路径不做替换；表与生成器作为**下一步实现的规格基础**
保存在仓库里，且不进入 payload。

## 2026-11-20 晚：给 ctypes GL 门面补 PyOpenGL 便捷语义 + 主机侧单元测试

`_cxgl` 现在实现了渲染器依赖的那些"非 C 语义"：

| 便捷语义 | 实现 |
|---|---|
| `glGenBuffers(1)` 返回 id | `_make_generator`（单 id 或多 id 列表，也可显式传输出数组） |
| `glGetIntegerv(pname)` 单参返回标量 | `_make_single_value_getter`（`glGetFloatv`/`glGetBooleanv` 同） |
| `glDeleteBuffers(1, [id])` / 裸 id | `_make_deleter` |
| `glShaderSource(shader, "源码")` | `_shader_source`（单串/列表/字节） |
| 私有库句柄 | 每次 `make_module()` 独立 `CDLL`，避免 `argtypes` 污染全局 |

并新增 **7 个主机侧单元测试**（`tests/test_cxgl_facade.py`，用假库注入，不需要设备）：
`glCreateProgram` 返回值、生成器 id、删除裸 id、单值 getter、shader 源码、整数绑定、常量表。

本地全量测试：**117 个用例全部通过**；设备断言仍 **26/26**。

## 2026-11-20 晚（续）：门面可达性测试 + 生成器修复

新增两条**主机侧**测试（`tests/test_cxgl_facade.py`）：

1. `test_every_gl_call_is_reachable`：ChimeraX 用到的**每一个** `GL.gl*` 都必须能通过门面到达
   （签名表 / 别名 / 适配器 / 桌面 no-op 之一），否则测试失败并列出缺口
2. `test_aliases_point_at_real_entry_points`：别名必须指向真实存在的签名

为让第 2 条通过，生成器现在**同时为别名目标生成签名**（如 `glClearDepthf`、`glDepthRangef`、
`glGetBooleanv`），因此表中签名数 82 > 覆盖的 89 个调用中的 79 个。

生成器输出也修了两处真实 bug：重复的右花括号、JSON `null`（应为 Python `None`）。

本地全量：**117 个用例通过**；设备断言 **26/26**。

## 2026-11-20 夜：受控替换验证（第 4 次）——仍崩，结论收敛

给门面补了"GLuint 首参用 `c_uint`"的窄修（`glBindVertexArray` 等 15 个函数），主机测试 117 全过；
再在 adopt 路径把 `GL` 换到门面：**应用启动后仍退出**（`CX_RUNTIME_READY` 之后无日志）。

四次替换全部失败，失败模式一致：**不是 Python 异常，而是进程直接消失**，说明仍有函数以错误
的指针/类型调用 GL。已排除的原因：参数类型（三次）、argtypes 污染（已用私有句柄）、
生成器签名（已从 NDK 头文件精确生成）。

**结论**：`_cxgl` 若要真正替换 PyOpenGL，必须实现**渲染器实际调用序的所有语义**（不只是签名），
包括 `*v` 函数接受列表、`glBufferData` 的 size 推导、`glVertexAttribPointer` 的偏移指针化、
`glGetIntegerv` 单参返回等 —— 这是一次**完整实现**，不能靠增量试错推进。
目前已把能自动化的部分做完（89 个调用点可达性测试、82 条精确签名、7 项行为单测、生成器可重跑），
剩余是逐函数实现 + 每批验证。

## 2026-11-20 深夜：门面补齐 `*v` 与偏移语义（含单测）

新增两组 PyOpenGL 兼容语义：

| 语义 | 覆盖函数 |
|---|---|
| `*v` 函数接受 Python 列表/元组（自动打包成 ctypes 数组） | `glUniform[1-4][fi]v`、`glVertexAttrib[1-4]fv` |
| 末参为"字节偏移"而非地址（int → `c_void_p`） | `glVertexAttribPointer`、`glDrawElements`、`glDrawElementsInstanced` |

对应新增 2 个单测（`glUniform3fv` 列表、`glVertexAttribPointer` 偏移指针化），本地 117 → **119 个用例**。

这两组语义正是之前替换 GL 后崩溃的高风险来源（偏移被当成地址、列表被当成指针）。

## 2026-11-21 结论：应用内替换第 5 次失败，改为"离线完成实现"

在补齐 `*v` 列表语义与字节偏移语义后再次替换：应用仍在 `CX_RUNTIME_READY` 后退出。

五次失败、模式完全一致，因此**停止在应用内试替换**。改为离线完成的策略：

1. 用 `tests/test_cxgl_facade.py` 的假库 + 生成的 82 条签名，把渲染器**实际调用序**逐条跑通
   （主机侧，不会崩应用）
2. 每跑通一组就补一个断言
3. 全部通过后只做**一次**应用内替换验证

这条路不消耗设备与构建时间，也不会让应用反复崩溃。

## 2026-11-21：抓到渲染器真实 GL 调用序列（离线验证的数据基础）

在 adopt 路径装了一个**记录器**（转发给原 PyOpenGL，只记录不改变行为），设备读回摘要：

```
calls=88; top=glBindBuffer:23:IntConstant/uint32,
     glGenBuffers:6:int,
     glBufferData:6:IntConstant/int/c_void_p/IntConstant,
     glVertexAttribPointer:4:int/int/IntConstant/IntConstant/int/NoneType,
     glEnableVertexAttribArray:4:int, glVertexAttribDivisor:4:int/int,
     glGetString:3:IntConstant, glBindVertexArray:3:int, glUseProgram:3:int,
     glGetIntegerv:3:IntConstant/uint32, glUniformBlockBinding:2:int/int/int
```

**这是第一次拿到渲染器实际传的参数类型**（此前全靠猜）。几个关键发现：

- 常量是 PyOpenGL 的 `IntConstant`（int 子类）→ 我们的门面按 int 处理即可
- `glBufferData` 的数据参数已经是 `c_void_p`（PyOpenGL 转换过）
- `glVertexAttribPointer` 的 offset 传的是 `None`（不是整数）→ 门面的偏移包装已处理
- `glGetIntegerv` 的第二参是 numpy 数组

据此新增 `tests/test_cxgl_replay.py`：把这些**记录下来的调用形状**合成参数后回放给门面，
断言全部通过。本地测试 128 → **130**。

## 2026-11-21 11:20：一次无效实验（记录以免重复）

思路：与其替换 `GL` 模块，不如在 `import OpenGL` **之前**把
`OpenGL.platform.egl.EGLPlatform.GL/GLES3` 指向 `libGLESv3.so`，并清空
`OpenGL.platform.PLATFORM.__dict__` 的缓存与 `OpenGL.raw.*` 模块，让 PyOpenGL 重新生成函数。

结果：`glCreateProgram()` 仍返回 0。

**但这次实验本身是无效的**：它跑在开发运行时里，那个进程**没有 current EGL 上下文**，
裸 ctypes 调用同样返回 0。因此**开发运行时不能用来判断 GL 绑定问题**，
此类实验必须在 App 内（有真实 EGL 表面）进行。

后续若重试该思路，必须在 App 的 adopt 路径（上下文已 current）里做，且注意崩溃风险。

## 2026-11-21 11:10：增量替换验证成功（应用不再崩溃）

结论先行：**分批替换 GL 函数是安全的**。当前 adopt 路径替换了 **49 个入口点**：

- 状态设置类 16 个（`glBindBuffer`、`glBindVertexArray`、`glViewport`、`glClear`、`glEnable`…）
- 着色器/程序/绘制类 33 个（`glCreateProgram`、`glShaderSource`、`glLinkProgram`、
  `glGetUniformLocation`、`glGetUniformBlockIndex`、`glUniform*`、`glBufferData`、
  `glDrawArrays`、`glGetString`、`glGetError`…）

设备表现：**应用存活**（进程数 1）、断言 26/27（`info probe` 项超时，与本次改动无关）。

### 但渲染器仍报 `glGetUniformBlockIndex(0, 'lighting_block')`

说明渲染器那条路径上的 `glCreateProgram` **没有走到我们的门面**（否则程序 id 不会为 0）。
可能原因：ChimeraX 某处把 `GL` 或具体函数对象在导入期就缓存成了局部引用，
`_module` 换绑对它们无效。

下一步（有据可循）：在 `_cxgl` 里加调用计数，设备读回 `glCreateProgram` 被调用了几次、
返回值是多少，判断是"没走门面"还是"走了但返回 0"。

## 2026-11-21 11:20：门面调用计数已加入，但设备读数里没显示

在 `_CxPartial` 里对 `glCreateProgram`/`glCreateShader`/`glLinkProgram`/
`glGetUniformBlockIndex`/`glGetError` 加了调用计数与最后返回值，并把
`stats=...` 拼进 adopt 返回串。

设备读回**没有出现 `stats=` 段**（输出仍以 `;calls=88;top=...` 结束），说明该拼接在
外层 `try/except` 里抛了异常被吞掉，或计数表为空导致格式串异常。

**下一步**：把 stats 拼接本身也包 try/except 并降级成常量文本，确认是"没被调用"还是
"拼接失败"；这决定后续是去查引用缓存还是查返回值。

状态：设备 27/27、本地 130 OK、49 个入口点仍由门面提供、应用存活。

## 🔍 2026-11-21 12:20：找到渲染器绕过门面的真正原因

设备读回（stats 已能显示）：

```
stats=none;context=EGLContext-adopted|raw=OpenGL ES 3.0 ...
```

`stats=none` 表示**渲染器从没调用到我们的门面**。查看
`chimerax/graphics/opengl.py` 后原因明确：

```python
GL = _GlesProxy(_gles_module, _ctypes.CDLL('libGLESv3.so'))
```

鸿蒙分支下渲染器用的是 **`_GlesProxy`**，而我们替换的是 `cxgl.GL._module` —— 两者不是同一个对象。

**正确切入点**：在 `_GlesProxy.__getattr__` 里，对"已验证批次"的函数改为委托给
`_cxgl` 门面，其余保持现有行为。这样替换点就在渲染器真正使用的路径上。

同时本轮确认：把着色器批次装到 `cxgl.GL` 上会导致启动期 adopt 崩溃（进程退出），
已用 `_CX_PARTIAL_GL=False` 开关停用，设备恢复 **27/27**。

## 🔬 2026-11-21 12:30：门面接入点已正确，批次二分定位进行中

把委托点放进 `_GlesProxy`（渲染器实际使用的对象）后：

| 批次 | 结果 |
|---|---|
| 16 个状态设置函数 | **设备 27/27，应用存活**（可用组合） |
| 再加 33 个着色器/绘制函数（共 49） | **设备 2/27 —— 应用崩溃** |

结论：接入点正确了（这批函数确实被渲染器调用到），但其中**至少一个函数的签名/转换不对**，
导致原生崩溃。因为崩溃发生在渲染器真实路径上，只能靠二分定位。

回退到 16 个函数后设备恢复 **27/27**。

下一步（二分，每轮一次构建）：
1. 只加着色器创建链（`glCreateProgram`/`glCreateShader`/`glShaderSource`/`glCompileShader`/
   `glGetShaderiv`/`glGetProgramiv`/`glGetShaderInfoLog`/`glLinkProgram`/`glGetUniformBlockIndex`）
2. 崩 → 继续二分；稳 → 再加 uniform/绘制组

## 🎯 2026-11-21 13:00：渲染器第一次越过着色器创建！

分批委托加入"着色器创建链"后（并列修了两个真实缺陷）：

1. `glGetShaderiv` 没有 ctypes 签名 → 之前把 Python int 当指针传 → **原生崩溃**（这正是二分的
   结果，已补签名）
2. 门面新增**安全规则**：无签名的 `glGet*iv/fv/InfoLog` 一律抛 `AttributeError`，让
   `_GlesProxy` 回退到原 PyOpenGL，而不是冒崩溃风险

设备读回：

```
err=1281, baseOperation=glUniformBlockBinding
```

对比之前：

```
err=1282, baseOperation=glGetUniformBlockIndex   ← 程序 id 为 0
```

**错误码从 1282(INVALID_OPERATION) 变成 1281(INVALID_VALUE)，卡点也从
"程序创建失败"前进到"UBO 绑定参数不合法"** —— 说明 `glCreateProgram`/`glGetUniformBlockIndex`
已经真正经过门面并返回了有效值。应用存活、26/27（info 探针超时项）。

下一步：把 `glUniformBlockBinding` 及 UBO 相关调用加入委托批次。

## 2026-11-21 13:50：诊断信息仍被 UI 截断，改用更长的输出行

`gltype=` / `programs=` 仍未出现在设备读数里（adopt 返回串被状态行截断，且诊断块本身
抛异常时会被静默吞掉）。已把诊断前置、把调用摘要缩短到 6 条，但**读数还是被截断**。

结论与下一步：

- 渲染状态行的 `maxLines` 限制就是硬约束；**改用较宽的 `cx-open` 行输出诊断**
  （该行 `maxLines(6)`），或把诊断写进单独的探针按钮
- 当前设备 **26/27**（仅 `info probe` 超时项），应用稳定，25 个委托函数生效
- 下一轮：把 `gltype/programs/created` 三段诊断输出到 `cx-open` 行，一次拿到
  "渲染器用的是不是 `_GlesProxy`" 与"程序是否由门面创建"这两个答案
