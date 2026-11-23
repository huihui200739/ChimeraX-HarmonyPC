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
| 体积/分割 | `volume mask` / `volume onesmask` / `segmentation colors` | 已注册并可解析（当前报"缺少输入"领域错误） |
| 核心命令 | `select` `color` `style` `view` `turn` `zoom` `close` `show` `hide` `rmsd` `align` … | 由 `std_commands.register_commands` 注册，共 **81 条**单字命令 |
| 会话 | `list models` `info models/chains/residues/polymers` | 上游 bundle 命令 |
| 探针 | `cxprobe` | 适配自带探针 |

## 已确认"可解析但需参数"（说明命令系统正常）

`rmsd`（缺 `to`）、`align`（缺 `to_atoms`）、`zone`（需单残基）、`style`（需关键字）

## `save` 命令：已注册但格式提供者未登记（下一步）

推进过程（设备实测）：
1. 未注册 → `UserError`（Unknown command）
2. 注册 `save_command` 的 `save` → `'Session' object has no attribute 'save_command'`
3. 引导里创建 `SaveManager` → **`Unknown data format: 'pdb'`**

结论与后续（设备实测）：
- `save` 本体与 save manager 已就位（第 2 步已修）
- 格式查找走 `session.data_formats`，因此还要创建 `FormatsManager` 并登记 PDB/mmCIF 格式
- 登记需要 `BundleInfo` 对象，而我们的树是**暂存**的（非 toolshed 安装），`find_bundle` 返回
  `None` → `add_provider(None, ...)` 触发 `'NoneType' object has no attribute 'installed'`
- 已为暂存 bundle 构造最小 `BundleInfo`+`SaverInfo` 垫片（`installed=True` + `run_provider`），
  PDB/mmCIF 格式已登记进 `session.data_formats`
- 随后 `save ... format pdb` 进入 `_pdbio.write_pdb_file`，但在
  `PythonInstance<Atom>::get_py_attr` 处抛 **未捕获的 NoPyAttrError → SIGABRT（进程崩溃）**
- 结论：PDB 写出需要原子属性注册（occupancy/bfactor 等 default attrs）已初始化；
  在补齐之前不能把 save 放回启动流程
- 下一步：`chimerax.atomic.attr` 的属性默认值初始化（`set_default_attr` 系列）

## 已知仍需处理

| 命令 | 现象 | 下一步 |
|---|---|---|
| ~~`mask` / `surface`~~ | **结论：这两个不是命令名**。mask bundle 注册的是 `volume mask` / `volume onesmask`；`surface` 是库 bundle | 已用正确命令名验证：`volume mask` → "缺少 volumes 参数"（领域错误，说明命令可用） |
| ~~`segmentation`~~ | **结论：该名不是完整命令**；真实命令是 `segmentation colors` / `segmentation surfaces` | 已验证 `segmentation colors #3` → "No segmentations specified"（领域错误，命令可用） |
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
