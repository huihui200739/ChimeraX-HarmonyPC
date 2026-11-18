# 2026-11-18：Python 成功接管 native 的 EGL 上下文（PyOpenGL 绑定是最后一环）

## 当前结论

**设备上 Python 侧用 native 交出的 EGL 句柄 `eglMakeCurrent` 成功，并且裸 `libGLESv3` 在该上下文上
正确回读：`raw=OpenGL ES 3.0 (4.1 Metal - 91.7)`。设备断言 26/26。**

剩下的一环很明确：**PyOpenGL 的函数入口没有跟着上下文走**（`gl=?`、FBO 建不起来、像素全 0），
而同一时刻裸 GLES 调用是好的 —— 说明上下文本身没问题，问题在 PyOpenGL 的符号解析。

## 本轮新增的 native 能力

`app/entry/src/main/cpp/gl_surface.cpp`：
- `ChimeraXGLDisplay/Context/Surface()` —— 交出 EGL 句柄
- `ChimeraXGLRelease()` / `ChimeraXGLReacquire()` —— 在渲染线程与解释器线程之间移交上下文
  （EGL 同一时刻只允许一个线程持有）

`chimerax_native.cpp` 通过 N-API 暴露 `glHandles()`（句柄以十进制字符串返回，因为 napi 无 64 位整数）
与 `glReacquire()`；页面在 `setTimeout(3000)` 里取句柄（表面是首帧之后才创建），
构造接管脚本、执行、再交还上下文。

## 关键诊断（保留在设备收据里）

```
context=EGLContext-adopted|raw=OpenGL ES 3.0 (4.1 Metal - 91.7)|gl=?|fbo=False|pixel=0,0,0
```

- `context=EGLContext-adopted` → 接管成功（`eglMakeCurrent` 返回真）
- `raw=OpenGL ES 3.0` → 上下文真的可用
- `gl=?` → PyOpenGL 的 `GL.glGetString` 返回 NULL

## 下一步（很具体）

PyOpenGL 在 `_initialize_pyopengl()` 时用当时的环境构建了函数表。接管之后需要让它**基于当前
display 重新解析**：调用 `OpenGL.EGL.eglGetProcAddress` 逐函数取址，或者让 `OpenGL.platform`
指向携带我们 display 的实例；补丁里 `_initialize_pyopengl()` 已放在接管之后调用，但 PyOpenGL 的
platform 单例是进程级的，需要一个"重置 platform"入口（`OpenGL.platform.PLATFORM = ...`）。
预计 2–4 小时。
