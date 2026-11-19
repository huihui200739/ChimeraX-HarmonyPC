# 2026-11-20：接入 `list_info` / `items_inspection`（bundle 覆盖面）

## 已做

- 暂存树加入 `chimerax/list_info` 与 `chimerax/items_inspection`
- 打包脚本确认把新 bundle 打进 ZIP（`list_info entries: 3`）
- 引导里尝试显式注册 bundle 命令（最小会话不会跑 toolshed 的 bundle 发现）

## 设备读回与卡点

```
list-models:ModuleNotFoundError:No module named 'chimerax.core.commands._atomspec'
state=bundle-register-failed:ValueError:Can not reuse CmdDesc instances
```

两个真实缺口：

1. **`chimerax.core.commands._atomspec` 缺失** —— 它由 `src/commands/_atomspec.peg` 语法文件
   经 PEG 生成器产出 C++ 再编译，属于"按需生成"的扩展，不在我们已有的交叉编译清单里。
   下一步：跑 PEG 生成器 → 得到 `_atomspec.cpp` → 用同一套 SDK clang 交叉编译。
2. **`Can not reuse CmdDesc instances`** —— 我循环注册了同一个命令两次；注册应每个命令一次。

## 影响

`list models` / `info` 这类检视命令暂时不可用；一旦 `_atomspec` 编出来，`list_info` 与
`items_inspection` 应该能直接工作（它们只依赖 core + models）。

## 追加：`list models` 已在设备上执行成功

设备读回：`toolshed-list:ok|devel-dump:...|list-models:ok|tools=True|toolshed=True`

### 打通的三个真实缺口

1. **payload 未包含新 bundle** —— 暂存后忘记重新打包，ZIP 里 `list_info entries: 0`。教训：
   `stage → package → build` 必须按序，缺一步就会用旧树。
2. **`chimerax.core.commands._atomspec` 缺失** —— 它由 PEG 语法 `_atomspec.peg` 生成：
   用 `grako` 生成 19 KB 的 `_atomspec.py`，放进 `vendor/core/`，由 staging 分发。
3. **grako 运行时 + Python 3.11 兼容** —— vendored `grako`（1 MB），并在 `__init__.py` 的
   `from __future__` **之后**注入 `collections.abc` 兼容 shim（第一次插在文件首行导致 SyntaxError）。

### 残留

`info` 子命令注册报 `ValueError`（`list` 成功）。注册已改为逐命令隔离，不影响其他命令；
下一步打印该错误的完整信息再修。
