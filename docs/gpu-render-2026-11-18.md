# 2026-11-18：设备 GPU 上跑通 GLSL 绘制

## 当前结论

**应用内用 GLSL ES 3.0 着色器在 Mali-G77 上画出三角形并回读像素：`triangle:242,140,38,255`（橙色，非黑）。设备断言 25/25。**

这一步验证的是"鸿蒙设备接受我们的着色器程序"，也正是 ChimeraX 渲染器需要的同一能力：
编译顶点/片元着色器 → 链接程序 → 上传 VBO → `glDrawArrays` → `glReadPixels` 回读。

## 实现

`app/entry/src/main/cpp/gl_surface.cpp`：

- `#version 300 es` 顶点/片元着色器，`layout(location=0)` 属性，输出 `vec4(0.95,0.55,0.15,1)`
- 表面创建后立即渲染一帧：编译 → 链接 → `glGenBuffers`/`glBufferData` → `glDrawArrays(GL_TRIANGLES)` → `glFinish` → `glReadPixels`
- 状态通过 `glStatus()` 的 `render` 字段暴露给页面（节点 `cx-gl-render`）
- 着色器/链接失败会把编译日志原样返回（`vertex-shader:…` / `link:…`），不是静默失败

## 中途踩的坑（值得记）

加了"模型层"引导代码后应用启动即崩，faultlog 报
`FDSAN: attempted to close file descriptor 19 ... owned by FILE*`，页面只剩骨架。

处理：把 `Models(session)` 的创建包进 `try/except`（它只是为了让 `AtomicStructure`
拿到模型触发器，属可选步骤），引导不再因为一段可选逻辑整体失败。顺带修了状态字符串
用未定义变量的问题（`globals().get("_cx_state", "session-ready")`）。

## 证据

- 设备收据：`reports/device-app-2026-11-18.json`（25 项断言，含 `cx-gl-render`）
- 读回值：`triangle:242,140,38,255`

## 下一步

1. 让 `chimerax.graphics` 用这条 EGL 上下文绘制（现在 GL 能力、EGL 表面、PyOpenGL、模型层都在位）
2. Qt 线：`libqohos.so` 的 `setupQtApplication()` / XComponent 交接（子代理已给出 shim 补丁与部署清单）
