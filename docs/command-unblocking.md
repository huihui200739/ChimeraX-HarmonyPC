# 命令解锁手册（错误驱动法）

本文件记录在鸿蒙 PC 上让 ChimeraX 命令真正可执行的**可复用方法**与已解锁清单。

## 方法（每轮一次构建 + 一次设备验证）

1. 在 `Index.ets` 的 `ADOPT_SCRIPT` 里对已加载的蛋白执行目标命令，把结果写进 `notes`
   （成功写 `cmd=ok`，失败写 `cmd:异常类型:消息前 40 字`）
2. 读设备 hilog：`hdc shell "hilog -x | grep 'render='"`（脚本结果整段镜像到 hilog）
3. 按错误类型处理：
   - `ModuleNotFoundError: chimerax.X` → 把 bundle `X` 加入
     `tools/stage_chimerax_python.py` 的 bundles 列表（纯 Python bundle 只需暂存）
   - `AttributeError: 'Session' object has no attribute 'Y'` → 在引导里补该会话组件
     （`undo` / `user_colors` / `app_bin_dir` / `commands` …）
   - `ImportError: cannot import name ...` → 多为缺少某个初始化调用（如 `initialize_atomic`）
   - `AssertionError: No amberXX subdirectory` → 外部工具集成的 import 检查，建占位目录绕过
   - `UserError: Unknown command: cmd` → 命令未注册：或在引导里注册（`register_command`），
     或注册核心命令集 `std_commands.register_commands(session)`
   - `UserError: Missing required ...` / `Expected a keyword` → **命令已可用**，只是参数不全
4. 成功后在 `tools/device_app_check.py` 增加断言，防止回归

## 已解锁清单（设备实测）

| 类别 | 命令 | 说明 |
|---|---|---|
| 科学计算 | `mlp` | 脂溶性图（需要 `map_data`） |
| 科学计算 | `coulombic` | 电荷着色（需要 `add_charge`/`addh`/`amber_info` 等 6 个 bundle + `app_bin_dir` + amber 占位） |
| 科学计算 | `morph` | 构象插值（内部调用 `coordset`，需要核心命令集） |
| 结构分析 | `dssp` | 二级结构（`_dssp` 扩展） |
| 结构分析 | `rmsd #3 to #4` | 均方根偏差（实测 `rmsd=ok`） |
| 结构分析 | `align #3 to #4` | 结构比对（实测 `align=ok`） |
| 选择 | `zone #3:5` | 按残基球形选择（实测 `zone=ok`） |
| 核心命令 | `select` `color` `style` `view` `turn` `zoom` `close` `show` `hide` `rmsd` `align` … | 由 `std_commands.register_commands` 注册，共 **81 条**单字命令 |
| 会话 | `list models` `info models/chains/residues/polymers` | 上游 bundle 命令 |
| 探针 | `cxprobe` | 适配自带探针 |

## 已确认"可解析但需参数"（说明命令系统正常）

`rmsd`（缺 `to`）、`align`（缺 `to_atoms`）、`zone`（需单残基）、`style`（需关键字）

## 已知仍需处理

| 命令 | 现象 | 下一步 |
|---|---|---|
| `mask` / `surface` | `register_command` 报 ok 但执行仍 `Unknown command` | 疑似注册到按需初始化的命令表；下一步在注册后立即 `registered_commands()` 里查名字是否存在 |
| `segmentation` | 该名不是完整命令（真实命令是 `segmentation colors` / `segmentation surfaces`） | 用子命令名测试 |
| `surface` 三角化 | 模块内 `triangulate_polygon` 设备返回 0 三角形（主机验证正确） | 需在设备侧定位符号/调用路径 |

## 引导里已补的会话组件（汇总）

```python
session.ui = _NullUI()
core_settings.init(session)
session.tools = Tools(session)
session.models = Models(session)
session.selection = Selection(session)
initialize_atomic(session)
session.undo = Undo(session, first=True)
session.user_colors = UserColors()
chimerax.app_data_dir / app_lib_dir / app_bin_dir（+ amber18 占位目录）
std_commands.register_commands(session)
```
