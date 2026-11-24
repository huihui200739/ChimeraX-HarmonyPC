# 2026-11-17：应用内交互式命令通道

## 当前结论

**应用里有了可用的命令输入框：默认内容 `print(session.app_name, len(session.triggers.trigger_names()))`，点"执行"后页面输出 `ChimeraX 16`。设备断言 16/16 全部通过（这一条是脚本点按钮 + 读回输出，不是看日志）。**

说明它验证的是：ArkUI 输入 → 原生 `runScript` → 持久 Session 的同一解释器状态 → 输出回显，整条链路真实可用。

## 做法

1. **持久 Session**：在原生初始化阶段（`Py_InitializeEx` 之后）执行一段引导脚本，创建
   `Session("ChimeraX", silent=True, minimal=True)`，注入 `_NullUI`，注册探针命令 `cxprobe`，
   并把 `session` 留在 `__main__` 全局里，供后续输入复用。
2. **UI**：`TextInput`（`cx-cmd-input`）+ `执行` 按钮（`cx-cmd-run`）+ 输出文本（`cx-cmd-output`），
   回车（`onSubmit`）与点击按钮都触发 `native.runScript(text)`。
3. **验证**：`tools/device_app_check.py` 通过 `uitest dumpLayout` 取按钮矩形 → `uitest uiInput click`
   → 4 秒后重新 dump，读 `cx-cmd-output` 断言输出包含 `ChimeraX` 与数字。

## 证据

- 设备收据：`reports/device-app-2026-11-17.json`（16 项断言，含 `command_output = "ChimeraX 16"`）
- 截图：`reports/device-app-channel-2026-11-17.jpeg`

## 边界与下一步

- 输入框目前执行 **Python**；要直接执行 ChimeraX 命令语法，需要在引导脚本里再包一层
  `commands.run(session, text)` 的入口（下一步）。
- 仍无图形栈，命令输出只有文本。
