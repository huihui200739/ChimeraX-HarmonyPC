# 2026-11-17：界面直接执行 ChimeraX 命令语法

## 当前结论

**应用输入框现在接受 ChimeraX 命令语法：输入 `cxprobe ui-command` → 点「执行命令」→ 输出 `cxprobe:ui-command`；点「Python」按钮运行示例脚本 → 输出 `ChimeraX 16`。设备断言 17/17 全部通过。**

两条链路都在界面上真实点按验证（`uitest uiInput click` + 读回输出节点），不是日志。

## 实现

1. **原生 `runChimeraCommand(text)`**：把用户文本作为字面量嵌入
   `commands.run(session, '<text>')` 并执行，返回命令结果。
2. **共用执行器 `ExecuteScript`**：把原先 `runScript` 里的"捕获 stdout + 异常转文本"逻辑抽出来，两个入口行为一致。
3. **UI**：`TextInput`（默认 `cxprobe ui-command`）+「执行命令」(`cx-cmd-run`) + 「Python」(`cx-cmd-py`) + 输出区 (`cx-cmd-output`)。

## 设备读回

| 操作 | 输出 |
|---|---|
| 点「执行命令」（默认 `cxprobe ui-command`） | `cxprobe:ui-command` |
| 点「Python」（示例脚本） | `ChimeraX 16` |

## 边界与下一步

- 可用的命令仍是我们注册的探针；内置命令（`open`/`cd`/`view` 等）来自各 bundle，需要继续引入依赖。
- 无图形栈，命令只有文本输出。
- 下一步：引入一个纯 Python 的轻量 bundle 作为真实内置命令样例（例如 `chimerax.core.commands` 自带的 `help`/`version` 若可用），把"输入内置命令"跑通。
