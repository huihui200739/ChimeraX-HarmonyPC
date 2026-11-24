# 2026-11-17：内置命令执行确认 + `session.tools` 观察

## 当前结论

**内置命令在应用内确实执行：`devel dump /nonexistent/...` 返回上游原生校验错误
`Missing or invalid "path" argument`，设备断言维持 18/18。**

`toolshed list` 仍未通过，本轮把它的失败原因定位到"应用进程里 `session.tools` 取不到"，并记录了一个**尚未解释的矛盾**（见下）。

## 已确认的事实

| 事实 | 证据 |
|---|---|
| 启动引导已包含 `Tools(session)` 赋值 | 打包出的 `libs/arm64-v8a/libchimerax_native.so` 内 `strings` 可读到 `session.tools = Tools(session)` 与 `_cx_state = "session-ready"` |
| 引导整体成功 | 探针读回 `state=session-ready`（若中途抛异常会变成 `session-error:…`） |
| 同一段代码在设备开发运行时（`/data/local/tmp/cxdev`）行为正常 | 直接跑同序列脚本：`TOOLS_OBJ Tools`、`HASATTR tools True`、`dict True` |
| 但应用进程内探针读回 `tools=False`、`toolshed=False` | `cx-builtin` 行末尾的 `|tools=False|toolshed=False|state=session-ready` |

## 尚未解释的点（如实保留）

同一段引导在两条路径上表现不同：开发运行时里 `session.tools` 可读，应用进程内 `hasattr(session, "tools")` 为 False，而引导又没有报错。
下一步需要区分：是 `Session.__setattr__` 在 minimal 会话下把该对象登记到状态管理器而非 `__dict__`，还是应用进程里存在两个 Session 实例。

## 本轮附带修复

`register("cxprobe", ...)` 之前用 `registered_commands()` 做去重，而该属性在 app 侧模块里不存在，导致**整段引导被异常中断**（`_cx_state=session-error:module 'chimerax.core.commands' has no attribute 'registered_commands'`）。改为 `try/except` 包裹后引导恢复，`devel dump` 立即通过。

## 边界

- 应用内仍无 `models`/图形栈，`open`/`cd` 等数据命令未验证。
- `toolshed list` 未通过，不计入通过项。
