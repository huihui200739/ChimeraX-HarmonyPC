# 2026-11-18：把 EGL 上下文接进 `chimerax.graphics`（含实测结论）

## 当前结论

**上游补丁 `patches/0005-render-ohos-egl-context.patch` 已通过 staging 自动应用到暂存树，
`chimerax.graphics.opengl.OpenGLContext` 在首页启动后即为 `EGLContext`；设备断言 26/26。**

但**上下文还没真正"接管"**：应用内探针读回
`context=EGLContext|gl=?|fbo=False|pixel=0,0,0|version=unparsed:AttributeError`。

## 为什么 `gl=?`

native 侧（`gl_surface.cpp`）在 XComponent 回调线程上 `eglMakeCurrent` 建好了上下文；
Python 代码跑在 N-API 回调线程上，`eglGetCurrentContext()` 在该线程**拿不到**上下文，
于是补丁里的 `EGLContext` 走了"自建"分支：

- 自建上下文能创建（前面单独测过：`egl=1.5|version=OpenGL ES 3.0|renderer=Mali-G77`）
- 但 PyOpenGL 的函数指针在导入时就绑定了原生上下文，切换后 `glGetString` 返回 NULL
- 结果：`GL_VERSION` 取不到、FBO 不完整、像素全 0

**方向已经明确**（子代理方案 B）：由 native 侧把 `EGLDisplay/EGLConfig/EGLSurface/EGLContext`
通过 N-API 暴露给 Python，并保证 Python 调用线程与 GL 线程一致（或显式 `eglMakeCurrent`
到同一个 surface），Python 侧只"接管"不自建。

## 本轮另外两处修复

1. **staging 自动打补丁**：补丁路径是上游布局（`src/bundles/<b>/src/...`），暂存树是
   `chimerax/<b>/...`，工具会重写路径到临时补丁再 `patch -p1`，并把结果写进报告。
2. **探针顺序**：渲染探针会切换 GL 上下文，放在所有探针**最后**执行，避免污染前序结果。

## 证据

- 设备收据：`reports/device-app-2026-11-18.json`（26 项断言，含 `cx-render`）
- 设计文档（子代理）：`docs/render-integration-2026-11-18.md`
- 探针脚本：`tools/render_probe.py`（设备侧可独立运行）
- 补丁：`patches/0005-render-ohos-egl-context.patch`（8 hunk，对上游 `git apply --check` 通过）

## 下一步

1. native 暴露 EGL 句柄 + 线程一致性（预计 3–5 小时），之后 `View.image_rgba()` 应能出像素
2. Qt：`setupQtApplication()` ↔ XComponent 交接（子代理已完成 shim 补丁与部署闭包）
