# 2026-11-17：两个核心内置命令在应用内成功执行

## 当前结论

**应用内两个 ChimeraX 核心内置命令都跑通了：`toolshed list` 正常返回，`devel dump` 返回上游参数校验错误。设备断言 19/19。**

页面读回：`toolshed-list:ok|devel-dump:Missing or invalid "path" argument|tools=True|toolshed=True|state=session-ready`

## 上一轮"矛盾"的根因（已查明）

上一轮观察到"引导里设置了 `session.tools`，但探针读到 `tools=False`"。根因不是 `Session.__setattr__`，而是**探针脚本自己把全局 `session` 覆盖了**：

- 页面上的 `COMMAND_SCRIPT`（UI 命令通道的默认脚本）里有 `session = Session("ChimeraX", silent=True, minimal=True)`
- 它先于内置命令探针执行，于是 `__main__` 里的持久 session 被换成一个**没有任何 bootstrap 对象的新会话**
- 修复：脚本改为"存在则复用 `session`，不存在才创建"，并在注释里写明原因

修复后 `tools=True`、`toolshed=True`、`toolshed list` 直接通过。

## 现在的命令能力

| 命令 | 结果 |
|---|---|
| `cxprobe <值>`（我们注册的探针） | `cxprobe:<值>` |
| `toolshed list`（上游内置） | 正常执行（返回 `None`，输出走 logger） |
| `devel dump <路径>`（上游内置） | `Missing or invalid "path" argument`（CmdDesc 校验） |
| UI「执行命令」输入框 | 上述任一命令可直接输入执行 |

## 证据

- 设备收据：`reports/device-app-2026-11-17.json`（19 项断言）
- 截图：`reports/device-app-builtin-ok-2026-11-17.jpeg`

## 边界与下一步

- 仍无 `models`/图形栈：`open`/`cd` 等数据命令需要 models 与 graphics 才能显示模型。
- 下一步：评估 `chimerax.graphics` 的 C++ 扩展交叉编译（这是"能看到结构"的门槛），或先接 `chimerax.core.models` 的纯 Python 部分做数据结构验证。
