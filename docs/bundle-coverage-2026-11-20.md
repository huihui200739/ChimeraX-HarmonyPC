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
