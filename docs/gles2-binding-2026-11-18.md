# 2026-11-18：PyOpenGL 在 OHOS 上绑定 GLES2 入口

## 当前结论

**根因确认并修复：`PYOPENGL_PLATFORM=egl` 下 `OpenGL.GL` 是桌面绑定，函数表为空（`GL=None`），
必须用 `OpenGL.GLES2`。staging 现在在 `chimerax/graphics/opengl.py` 里按平台选择：OHOS 用
`OpenGL.GLES2`，其他平台保持 `OpenGL.GL`。**

证据链（每步都是设备实测）：
1. 接管 native 上下文后，裸 `libGLESv3` 回读 `OpenGL ES 3.0 (4.1 Metal - 91.7)` → 上下文可用
2. 同一时刻 `OpenGL.GL.glGetString` 为 `None` → 桌面绑定在 EGL 平台下不工作
3. 切到 `OpenGL.GLES2` 后，探针不再报"无 GL_VERSION"，而是前进到 `glReadPixels` 参数类型错误
   （`TypeError: byref() argument must be a ctypes instance`）→ **说明 FBO/渲染缓冲这整段 GLES 调用都过了**
4. 把 `glReadPixels` 改为直接传 numpy 数组后，剩下的是探针自身的枚举/参数细节

## 改动

`tools/stage_chimerax_python.py` 新增 staging 期补丁：把

```python
global GL
import OpenGL.GL
GL = OpenGL.GL
```

改为在 OHOS 分支使用 `OpenGL.GLES2`，其余平台不变。这样每次 staging 都可重复，不依赖手工编辑。

## 证据

- 设备收据：`reports/device-app-2026-11-18.json`（26 项断言）
- 探针输出（保留在 `cx-render`）：`context=EGLContext-adopted|raw=OpenGL ES 3.0 ...`

## 下一步

把渲染探针的枚举/参数彻底对齐 GLES3（数值常量、numpy 直传），让 `fbo=True` 与像素回读
成为断言；随后接 `View.image_rgba()` 出图，再把这块 capability 直接用于 Qt 画布。
