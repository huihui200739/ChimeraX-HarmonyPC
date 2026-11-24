# 2026-11-18：PyOpenGL + graphics 层在应用内可用

## 当前结论

**应用内 `OpenGL 3.1.10` 与 `chimerax.graphics.opengl`、`chimerax.core.models` 均可导入，读回 `3.1.10|chimerax.graphics.opengl|True`；设备断言 22/22。**

## 关键点：`PYOPENGL_PLATFORM=egl`

PyOpenGL 在 Linux 上默认走 GLX/X11，设备上直接 `import OpenGL` 报
`Unable to load OpenGL or GL library`（`OpenGL/platform/glx.py:24`）。鸿蒙只提供 EGL/GLES，
因此原生引导里设置了 `PYOPENGL_PLATFORM=egl`（`os.environ.setdefault`），PyOpenGL 改用 EGL 后端后
`chimerax.graphics.opengl` 正常导入。

## 证据

- `reports/pyopengl-2026-11-18.json`：PyOpenGL 3.1.10 wheel 的 SHA-256 与暂存的 2877 个模块
- 设备读回见 `reports/device-app-2026-11-17.json` 的 `cx-glstack`
- 页面为单列可滚动布局；探针行合并成 `core API` 一行以免超出视口（检查器改为自上而下滚动收集，避免漏读）

## 现在的完整能力链（22 项设备断言）

HAP 安装 → 启动 → 私有 CPython 3.11.18 → math/ctypes/hashlib → `chimerax v1.11.1` → numpy 1.26.4 →
`_umath` 从原生库目录加载 → 触发器派发 → core 模块 → 命令子系统 + Session（`Session|True|16`）→
命令执行 → 内置命令（`toolshed list` / `devel dump`）→ 命令语法 UI → **atomic 层** → **PyOpenGL + graphics.opengl + core.models** → **EGL/GLES 3.0 表面（Mali-G77）**

## 边界与下一步

- 渲染管线还没接上：现在有 GL 上下文与 Python 层，但 `chimerax.graphics` 仍用自己的上下文创建路径，下一步把它的渲染目标接到我们的 EGL 表面。
- Qt 侧并行线已把 `QtCore/QtGui/QtWidgets` 绑定交叉编译出来（符号闭包 0 缺口），下一步进 ChimeraX shim。
