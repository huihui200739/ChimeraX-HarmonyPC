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
