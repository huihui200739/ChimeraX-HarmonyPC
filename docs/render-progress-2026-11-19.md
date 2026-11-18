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
