# 2026-11-17：在鸿蒙应用内执行真实 ChimeraX 命令

## 当前结论

**应用内完成了一次完整的 ChimeraX 命令执行：用 `chimerax.core.commands.register` + `CmdDesc` 注册命令 `cxprobe`，再通过 `chimerax.core.commands.run(session, "cxprobe hello-harmony")` 执行，返回 `cxprobe:hello-harmony`，计数器确认回调被调用 1 次（页面读回 `cxprobe:hello-harmony|1|hello-harmony`）。设备断言 15/15 全部通过。**

## 打通的两个真实障碍

| 现象 | 原因 | 处理 |
|---|---|---|
| `ValueError: Missing initial "session" argument` | ChimeraX 的 `CmdDesc` 要求注册函数首参为 `session` | 回调签名改为 `def _cx_probe(session, value)` |
| `AttributeError: 'Session' object has no attribute 'ui'` | 命令日志路径会访问 `session.ui.is_gui`，minimal Session 没有 UI | 注入极简 `_NullUI`（`is_gui = False`，其余属性返回空操作） |

`:py:class:` 说明：这两处都是**上游接口约定**，不是绕过；`session.ui` 在没有图形栈的平台上本就该由平台侧提供。

## 新增原生能力：`runScript`

`chimerax_native.runScript(code)` 用 `PyRun_String(..., Py_file_input)` 执行多行脚本，并把 `sys.stdout` 重定向到 `StringIO` 取回输出；失败时返回异常文本。这是应用侧"命令通道"的基础设施，后续可直接接到 ArkUI 的输入框。

## 调试提速：设备上的开发运行环境

为避免每次都等 HAP 构建（约 10 分钟），把 linked 运行时解到 `/data/local/tmp/cxdev/`，用 `chimerax/core/__main__.py` 作为探针入口，配合 `CX_HARMONY_PRELOADED=1` 直接跑脚本 —— 单次迭代约 1 分钟。本轮两个错误都是在这个循环里定位，再一次性落到应用里。

## 产物与证据

- HAP：`build/hap/entry-default-unsigned.hap`（62 MB，未签名 debug）
- 设备收据：`reports/device-app-2026-11-17.json`（15 项断言）
- 截图：`reports/device-app-command-2026-11-17.jpeg`

## 边界与下一步

- 执行的是**自定义探针命令**，不是 ChimeraX 内置命令（内置命令来自各 bundle，需要更多依赖）。
- 仍无图形栈：`chimerax.graphics` 的 C++ 扩展未交叉编译，因此没有渲染。
- 下一步：把 `runScript` 接成 UI 的命令输入框（可输入任意 Python/命令），再评估 graphics bundle 的交叉编译。
