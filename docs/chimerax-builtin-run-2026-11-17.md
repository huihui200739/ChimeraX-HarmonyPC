# 2026-11-17：核心内置命令在应用内可执行

## 当前结论

**应用内跑通了 ChimeraX core 自带命令的完整解析与参数校验：`devel dump /nonexistent/cx-probe.txt` 返回上游原生的
`Missing or invalid "path" argument`（CmdDesc 校验生效）。写成一句话：这是第一次在鸿蒙应用里跑动"上游自己的命令"，不再只是我们注册的探针。**

同时把启动引导补齐到能注册内置命令的程度（`app_dirs` / `app_data_dir` / `app_lib_dir` / `core_settings.init` / `toolshed.init`），设备断言 18/18。

## 补齐的启动引导（按上游顺序）

| 步骤 | 作用 | 依据 |
|---|---|---|
| `os.environ["HOME"]=运行时目录` | appdirs 需要可写目录，否则落到只读的 `/.local` | 设备实测报 `OSError: Read-only file system: '/.local'` |
| `chimerax.app_dirs = appdirs.AppDirs(...)` | 用户数据/缓存目录 | `chimerax/core/__main__.py:497` |
| `chimerax.app_dirs_unversioned`、`app_data_dir`、`app_lib_dir` | toolshed/help 的安装位置 | 同上 521/552/553 行 |
| `core_settings.init(session)` | 创建 `core_settings.settings` | `core_settings.py:55` |
| `toolshed.init(...)` + `session.toolshed = get_toolshed()` | 命令匹配需要的"可用命令"计算 | `cli.py:2730` 走 `toolshed.get_toolshed()` 单例 |
| `register_misc_commands(session)` | 注册 `debug`/`devel`/`pip`/`toolshed` | `session.py:1312` |

## 设备读回

`cx-builtin = toolshed-list:AttributeError:'Session' object has no attribute 'tools…' | devel-dump:Missing or invalid "path" argument`

- `devel dump`：**内置命令执行 + 参数校验通过**（断言通过）
- `toolshed list`：仍报 `Session` 缺 `tools…` 属性（下一步要补工具注册表），**如实记录，未计入通过项**

## 附带修掉的一个原生缺陷

`ExecuteScript` 之前先读捕获缓冲区再处理异常，导致 `getvalue … returned a result with an exception set`。
改为**先取出/格式化异常、`PyErr_Clear()`，再读缓冲区**，输出与错误两不误。

## 证据

- 设备收据：`reports/device-app-2026-11-17.json`（18 项断言）
- 截图：`reports/device-app-builtin-2026-11-17.jpeg`

## 下一步

- 补 `session.tools`（工具注册表）让 `toolshed list` 也通过
- 引入更多 bundle 后，验证 `open`/`cd` 等真实数据命令（需要 graphics/models 才能显示模型）
