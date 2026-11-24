# 2026-11-17：核心内置命令的依赖链（实测记录）

## 当前结论

**`chimerax.core` 自己注册的内置命令共 4 个 —— `debug`、`devel`、`pip`、`toolshed`（设备上 `registered_commands()` 实测输出）。它们能被解析匹配，但执行会触发 ChimeraX 的"可用命令/工具架"计算，需要 `session.toolshed`，而 `Toolshed` 又需要 `chimerax.app_dirs` 与 `chimerax.core.core_settings.settings`。**

本轮把这个链条实测出来了，并把两个真实依赖（`packaging`、`appdirs`）纳入暂存流程。**未完成的**：把 `Toolshed` + `core settings` 在无 GUI 下构造出来，因此内置命令的执行仍未验证。

## 实测链条（设备 dev runtime 上逐步复现）

| 步骤 | 结果 |
|---|---|
| `session.register_misc_commands(session)` | 注册 4 个内部命令 |
| `run(session, "devel alias a b")` | `UserError: Expected name of a folder to open/read…`（未匹配，回退到 `open`） |
| 直接 `run(session, "debug")` | `AttributeError: 'NoneType' object has no attribute 'register_available_commands'` → 需要 `session.toolshed` |
| 构造 `Toolshed(...)` | `ImportError: cannot import name 'app_dirs' from 'chimerax'` → 需要 `appdirs` 生成的应用目录 |
| 设置 `chimerax.app_dirs`（`appdirs.AppDirs`） | 路径取决于 `HOME`；设备上 `HOME` 缺省会落到只读的 `/.local`，需显式设置 |
| `HOME` 正确后 | `ImportError: cannot import name 'settings' from 'chimerax.core.core_settings'` → 还需创建 core settings 实例 |

## 本轮落地改动

1. `tools/stage_chimerax_python.py` 现在会一并暂存三个纯 Python 依赖：
   `sortedcontainers`、`packaging`（`chimerax.core.commands` 需要）、`appdirs`（`Toolshed` 需要），并记录各自 wheel 的 SHA-256。
2. 设备依赖记录：`reports/chimerax-python-deps-2026-11-17.json`。

## 边界

- 应用内的 17 项验收断言不受影响（探针命令 `cxprobe` 仍正常）。
- 内置命令（`debug`/`devel`/`pip`/`toolshed`）**尚不能在应用内执行**，因为缺 `session.toolshed` 与 core settings；下一步按上表顺序把这两个对象补齐，再重跑 `devel alias` 验证。
