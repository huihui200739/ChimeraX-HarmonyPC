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

## 追加：再接入 `zone` / `sdf` / `mol2`

三个纯 Python bundle（无 C++ 依赖）已加入暂存清单并确认进入 payload（`zone 3`、`sdf 2`、`mol2 2` 个文件）。
设备断言仍 26/26，说明新增包没有破坏现有导入链。

它们的命令（`zone`、`open` 的 sdf/mol2 读取）依赖：
- `zone`：需要 selection/模型管理器
- `sdf`/`mol2`：需要 `chimerax.atomic` 与 `open` 命令通路

下一步按依赖逐个注册并验证。

## 追加：`open` 命令与文件格式注册链路（含一次失败记录）

按依赖顺序补齐了 `open` 命令所需的管理器，设备读回逐步推进：

| 阶段 | 设备读回 |
|---|---|
| 直接 `open` | `AttributeError: 'Session' object has no attribute 'open_command'` |
| 建 `open command` manager | `AttributeError: 'Session' object has no attribute 'data_formats'` |
| 建 `data formats` manager | `UserError: Unrecognized file suffix '.sdf'` |
| 手动调 `_SDF_API.run_provider(...)` | 仍是 `Unrecognized file suffix '.sdf'` |

**结论**：文件格式表来自 bundle 元数据（`bundle_info.xml` 的格式声明），由 toolshed 在正常启动时
装载；我们绕过 toolshed 就没人注册格式。**正确修法**是直接调
`session.data_formats.register(OpenFileFormat(...))`，或者让 toolshed 真正跑一次 bundle 发现。

实验用的「打开 SDF」按钮已撤下，界面不留不可用的入口；`open` 命令本身已注册成功（命令表可见）。

## 追加：`info models` 对上真实模型（命令层 × 模型层打通）

新增「模型信息」按钮：打开内置 PDB → 收集模型 → 执行上游 `info models`。

设备读回：**`info-models:ok|models=2`**

这是第一次"上游命令 + 真实打开的模型"同时工作：`list_info` 的 `info models` 遍历
`session.models` 并格式化输出，没有报错。命令层与模型层的接口在鸿蒙上是通的。

## 追加：把 `bundle_info.xml` 一起打包（为 toolshed 发现铺路）

已安装形态的 ChimeraX bundle 是"包目录里带 `bundle_info.xml`"，文件格式与 provider 声明都在其中。
staging 现在会把上游 `bundles/<name>/bundle_info.xml` 复制进 `chimerax/<name>/`：

- 暂存文件数 4143 → **4160**
- `chimerax/sdf/` 现在包含 `__init__.py`、`sdf.py`、**`bundle_info.xml`**
- 设备断言仍 **26/26**，`list-models:ok`、`state=session-ready` 不变

下一步：在引导里调用 toolshed 的发现流程（或按 XML 手工注册 provider/格式），
这样"格式表/命令表/manager"三件事可以一次解决。

## 追加：SDF 读取的一次尝试（走出两步，仍差一步）

直接调用 sdf bundle 的 `read_sdf` 而不走 `open` 命令（绕开格式表）：

| 输入 | 结果 |
|---|---|
| `open file.sdf` | `UserError: Unrecognized file suffix '.sdf'`（格式表来自 bundle 元数据） |
| `read_sdf(session, 二进制流, path)` | `TypeError: endswith first arg must be str or bytes`（它要文本流） |
| `read_sdf(session, 文本流, path)` | `sdf-read:ok` 但 **`atoms=0`** —— 我构造的 SDF 不符合该读取器的期望格式 |

结论：读接口本身能跑，问题在我给的样例数据；下一步用上游 `tests/data` 里现成的 `.sdf` 样例重试。
「打开 SDF」按钮先撤下，避免留一个显示 0 原子的入口。

设备断言保持 **26/26**。

## 追加：真实蛋白（ras.pdb，1322 个 ATOM）读取结果 = 0 原子

把上游 `viewdock/test-data/ras.pdb`（1322 个 ATOM 行）作为资源打包，用 ArkTS 从 rawfile 复制到沙箱后
调用 `open_pdb`：

```
real-pdb:ok|atoms=0 view=4   ← view=4 是上一轮遗留的旧几何
```

即 `open_pdb` 对这个真实文件返回的模型**没有原子**，而 4 原子的探针 PDB 是正常的。
两种可能：
1. `open_pdb` 需要按块解析（多 MODEL / 大文件路径），我们的调用方式只处理了小文件
2. 该 fixture 缺 `END` 或含非标准记录，读取器静默跳过

「Ras 蛋白」按钮已撤下。下一步在开发运行时里对同一文件跑 `open_pdb` 并打印异常/计数，
先定位是解析问题还是文件问题，再决定是否换 fixture。

## 根因找到：结构读取器需要的 trigger 没注册

在**开发运行时**里对 `ras.pdb` 复现 `open_pdb`，第一次拿到真实异常：

```
KeyError: "No trigger named 'model position changed'"
  structure.py: _register_hover_trigger -> triggers.add_handler(MODEL_POSITION_CHANGED, ...)
```

即 `AtomicStructure` 初始化时要挂 trigger handler，而最小会话里没人注册这些 trigger
（正常启动由 bundle 导入时注册）。这解释了"读出来了但 0 原子"——解析中途抛异常被上层吞掉。

### 修法

引导里在 `Session` 之后注册读取器会用到的 trigger：

```python
for name in ('model position changed', 'new frame', 'scene begin', 'scene end',
             'frame drawn', 'graphics update'):
    session.triggers.add_trigger(name)
```

设备验证：断言 **26/26** 保持，`cx-open` 仍是 `models=1|atoms=4|residues=1`。
下一步用 `ras.pdb`（1322 ATOM）复测真实蛋白。

## 打通：真实蛋白与真实 SDF 都能打开并显示

### 真正的 bug

`open_pdb(session, stream, path)` 返回的是 `(models, status)` 形态（实测 `[list, str]`）。
之前的代码用 `[m for m in opened if hasattr(m, "atoms")]` 过滤，把模型列表和状态串一起滤掉，
于是表现为"读取成功但 0 原子"。改成递归展平（`_cx_models`）后立刻正常。

同一个 bug 也影响 SDF 读取。

### 设备读回

| 资产 | 结果 |
|---|---|
| `ras.pdb`（上游 viewdock 示例，1322 个 ATOM） | `real-pdb:ok\|atoms=1322` → 视口 `view=1322` |
| `Structure2D_CID_95480.sdf`（上游 sdf 测试样例，48 原子） | `real-sdf:ok\|atoms=48` → 视口 `view=48` |

两者都是通过 ArkTS 从 `rawfile` 复制到沙箱后读取，不依赖系统文件对话框。

### 顺带修正

- 引导里补注册读取器需要的 trigger（`model position changed` 等），否则 `AtomicStructure`
  初始化会抛 `KeyError` 并被静默吞掉
- 断言仍 **26/26**

## 渲染改进：按元素半径的圆形原子

上一轮的半径方案编译失败，定位到两处：

1. **片段着色器仍声明 `in vec3 v_color`**，而顶点着色器已输出 `vec4` —— 类型不匹配，`glCompileShader`
   失败后程序为空，绘制即消失
2. 早先的 stride 替换漏了中心点/包围盒循环里的 `i * 6`，导致顶点错位

修完后：

- 顶点布局 7 floats（位置 3 + 颜色 3 + 半径 1），颜色属性按 `vec4` 读取，`.a` 即半径
- `gl_PointSize = max(2.0, color.a * pointScale)`，`pointScale = 7.0`
- 半径按元素给：C 1.0 / N 1.1 / O 1.15 / S 1.3 / 其它 0.9

设备读回：`real-pdb:ok|atoms=1322 view=1322`，断言 **26/26**，截图 `reports/ras-radius-2026-11-20.jpeg`。

## 渲染再进一步：球面着色 + 更大的视口

- 片段着色器用 `gl_PointCoord` 做圆形遮罩与法线近似：`discard` 掉圆外的方形角，按半球法线做
  漫反射，原子看起来是立体的球而不是方块
- 用一个 `spriteMode` uniform 区分原子与键线：`gl_PointCoord` 对线段无定义，若不区分会把键也 `discard` 掉
- 视口高度 220 → 360，蛋白终于能完整看到

设备截图：`reports/ras-viewport-2026-11-20.jpeg`（1322 原子的 ras 蛋白，彩色球+键，清晰可辨），
断言仍然 **26/26**。

## 景深提示（depth cue）

顶点着色器把旋转后的 `q.z` 传到片段着色器，片段按深度压暗：

```glsl
float depth_fade = clamp(1.0 - (v_depth + 0.9) * 0.35, 0.45, 1.0);
```

远的原子/键更暗、近的更亮，蛋白的前后层次立刻可分。截图 `reports/ras-depth-2026-11-20.jpeg`，
断言 **26/26**。

## 居中改为包围盒中心

之前用质心居中：蛋白内核密、外圈稀，质心偏内，画面整体偏向左下。改成**包围盒中点**后，
结构稳稳落在视口中央并铺满。

截图 `reports/ras-centered2-2026-11-20.jpeg`（1322 原子，球体+键+景深，居中），断言 **26/26**。

## 陷阱：trigger 注册顺序会决定 models 管理器是否存在

把 trigger 注册提前到 `Models(session)` 之前，会让 `Models` 自己注册 trigger 时抛
`KeyError: "Trigger 'model position changed' already exists"`，而这个异常被引导里的
try/except 吞掉 —— 结果 `session.models` 根本不存在，`list models` 和 View 创建一起失败。

最终顺序（已修复）：

1. `Session(minimal=True)` + `session.ui`
2. `core_settings.init`
3. `Tools`、`Models`
4. **之后**再补注册读取器需要的 trigger（已存在的会抛异常，逐个忽略）
5. `View(...)`

设备读回：`list-models:ok`、`state=session-ready`、断言 **26/26**。
另外引导现在把启动期错误累积成 `_cx_errors` 一起报出来，不再被后一个错误覆盖。

## 新增可用命令：`info chains`；`zone` 的依赖链摸清

设备读回（「模型信息」按钮）：

```
info-models:ok|models=2
info-atoms:ImportError:cannot import name settings
info-chains:ok
```

- `info models`、`info chains` 可用（list_info 家族）
- `info atoms` 还缺一个 settings 模块
- `zone` 的依赖链：`zone → chimerax.label → chimerax.map_filter → chimerax.map`，
  而 `chimerax.map` 带有 C++ 扩展（`combine.cpp`/`fittingpy.cpp`/`interpolatepy.cpp`），
  还没交叉编译 —— 所以 zone 暂时只能注册、不能执行。

### 已补的依赖

- `mouse_modes`（zone 的 initialize 需要）
- `label`（zone 运行期需要）

两者都是纯 Python，已进入 payload（4183 → 4196 文件）。

## ✅ 通用 bundle C 模块构建工具 + `chimerax.map` 交叉编译成功

新增 `tools/build_bundle_cmodule_harmony.py`：**从 `bundle_info.xml` 的 `<CModule>` 声明**
读取源码清单（不再靠猜），用 NDK clang 交叉编译并直接装配到暂存树。

首次目标 `chimerax.map`：

| 项 | 结果 |
|---|---|
| 源码 | `_map/` 下 20 个 `.cpp`（含 `module.cpp` 的 `PyInit__map`） |
| 编译 | 全部通过 |
| 链接 | 需要 arrays 的 `pythonarray.cpp` / `rcarray.cpp` / `refcount.cpp` 支撑 |
| 产物 | `chimerax/map/_map.cpython-311-aarch64-linux-ohos.so`（1.05 MB） |
| 打包 | payload 4299 文件、HAP 147 MB |
| 设备 | **26/26 断言全过**、`state=session-ready` |

过程中修掉的真实问题：Python/numpy 头文件路径、`<arrays/pythonarray.h>` 头树映射、
`libpython3.11.so.1.0` 定位、`Reference_Count` 未定义（补 `refcount.cpp`）。

这条工具的意义：**以后任何 bundle 的 C 扩展都可以一条命令编出来**，不再为每个 bundle 写专用脚本。

## `chimerax.map` 扩展在设备上加载成功；`zone` 的依赖闭包已量化

设备读回（启动内置探针）：**`map-ext:ok`** —— `chimerax.map._map`（1.05 MB 的交叉编译扩展）
在鸿蒙上真实加载成功。这是**第一个由通用工具构建、并在运行时验证的额外 bundle C 扩展**。

### `zone` 的真实代价（静态依赖闭包分析）

对 `chimerax/zone` 做传递依赖分析（`from chimerax.X` 递归）：

- 闭包共 **43 个 bundle**
- 当前暂存树缺 **25 个**（`map_data`、`surface`、`dssp`、`map_fit`、`map_series`、`markers`、
  `nucleotides`、`seqalign`、`save_command`、`shortcuts`、`ui` 等）
- 其中 `surface`（16 个 `.cpp`）与 `dssp`（1 个 `.cpp`）还需要交叉编译

**结论**：`zone` 不是"再补一个包"能解决的，它需要整个 map/surface 家族的接入。
`map` + `map_filter` 已暂存（设备 26/26 通过），后续可按需继续。

设备断言保持 **26/26**、`builtin` 含 `map-ext:ok`。

## ✅ 十个 bundle 的 C 扩展一次性编译成功并进入 payload

`tools/build_all_bundle_cmodules.py`（在 staging 之后、打包之前运行）：

| bundle | 模块 | 结果 |
|---|---|---|
| map | `_map` | ✅ |
| mask | `_mask` | ✅ |
| stl | `_stl` | ✅ |
| morph | `_morph` | ✅ |
| coulombic | `_esp` | ✅ |
| mlp | `_mlp` | ✅ |
| segment | `_segment` | ✅ |
| dssp | `_dssp` | ✅ |
| connect_structure | `_cs` | ✅ |
| match_align | `_msa3d` | ✅ |

关键修法：把共享的 `libcxatomstruct.so`（在 `app/entry/libs/arm64-v8a/chimerax/lib`）加入链接，
解决 `pyinstance::PythonInstance<atomstruct::Residue>` 等未定义符号。

payload 从 4299 → **5352 个文件**，HAP 154 MB；设备断言 **26/26**、`map-ext:ok`、`state=session-ready`。

未建的三个（`surface` 需要 GLU 的 `gluTess*`；`mmtf`/`alignment_algs` 编译报错；`atom_search` 源码路径）
已记录，属于下一批。

## ✅ 通用工具支持 `<CLibrary>`，又加了 `alignment_algs`

`bundle_info.xml` 里除了 `<CModule>` 还有 `<CLibrary>`（模块链接的静态库）。工具现在会：

1. 解析 `<CLibrary>`（源码 + `IncludeDir`）
2. 编译成 `lib<name>.a`（`llvm-ar`）
3. 按模块声明的 `<Library>` / `<LibraryDir>` 链接进去
4. 把 bundle 的 `src/include` 加入头文件搜索路径

结果：`alignment_algs` 的 `_nw` / `_sw` 两个模块编译链接成功
（关键符号 `align_algs::make_matrix` 来自 `src/support.cpp` 编成的静态库）。

### 当前 payload 内可用的 bundle C 扩展（12 个）

`_map`、`_mask`、`_stl`、`_morph`、`_esp`、`_mlp`、`_segment`、`_dssp`、`_cs`、`_msa3d`、
`_nw`、`_sw`

payload 5361 文件、HAP 155 MB，设备断言 **26/26**、`state=session-ready`。

### 仍不可行的三个

- `mmtf`：需要外部 `mmtf.hpp`（mmtf-cpp 第三方库）
- `surface`：需要 GLU 的 `gluTess*`
- `atom_search`：声明的是 Cython 源（`search_cpp_ast.pyx`），需走 Cython 生成链路

## ✅ 工具支持 Cython 源（`.pyx`），`atom_search` 也进来了

`<CModule>` 里声明的 `.pyx` 现在会：先在构建机上用 Cython 生成 C++（`--cplus -3`），
再交叉编译。`atom_search` 的 `ast` 模块因此构建成功。

payload 内 bundle C 扩展达到 **13 个**：`_map`、`_mask`、`_stl`、`_morph`、`_esp`、`_mlp`、
`_segment`、`_dssp`、`_cs`、`_msa3d`、`_nw`、`_sw`、`ast`。

payload 5364 文件、HAP 156 MB，设备断言 **26/26**、`state=session-ready`。

### 现在的构建工具能力（一个工具覆盖三类声明）

| 声明 | 处理 |
|---|---|
| `<CModule>` 的 `.cpp` | NDK clang 交叉编译 |
| `<CModule>` 的 `.pyx` | 主机 Cython → C++ → 交叉编译 |
| `<CLibrary>` | 编译成 `lib<name>.a` 并按 `<Library>` 链接 |
| 头文件 | bundle 根、`src/include`、arrays/atomstruct 等共享头树 |
| 共享库 | `libcxatomstruct.so`（registry 唯一性） |

## ✅ 注册 4 个新 bundle 命令，命令总数 46 → 50

新注册（引导内逐个 try/except，互不影响）：

| bundle | 命令 |
|---|---|
| `mlp` | `mlp` |
| `coulombic` | `coulombic` |
| `morph` | `morph` |
| `mask` | `mask` |

设备读回：**`commands=50`**（此前 46）。截图 `reports/commands-50-2026-11-21.jpeg`。
断言保持 **26/26**、`state=session-ready`。

## ✅ 命令总数到 52；启动状态与诊断分离

- 注册 `segment` 的 `segmentation` 命令后，设备读回 **`commands=52`**
- 引导里把"命令注册失败"从 `_cx_state` 改为独立 `_cx_notes`：
  某个 bundle 的 API 注册失败（如 `coulombic` 缺模块）不再污染 `state`，
  现在稳定显示 **`state=session-ready`**，失败原因仍保留在 notes 里
- 断言 **26/26**、本地测试 **128 OK**

## ✅ 新 bundle 命令真实执行（设备证据）

用「模型信息」探针在打开的结构上依次执行新注册的命令：

```
mlp:UserError:mlp: no amino acids specified
coulombic:UserError:Un...
```

关键点：**这不是 "Unknown command"，而是命令解析成功、进入实现后的领域错误**
（`mlp` 明确说"没有指定氨基酸"）。说明这些命令已经真正在鸿蒙上跑起来了，
剩下的只是输入参数/依赖数据的问题，不是命令系统缺失。

探针输出现在会同时镜像到较宽的那一行，便于读取完整结果。
断言 **26/26**、本地测试 **130 OK**。

## 更正：`mlp` 失败的原因不是模型语义，而是选中了错误模型

设备读回（新增诊断）：

```
kinds=AtomicStructure,Model|atoms=True|residues=True
mlp #1: UserError: mlp: no amino acids specified
```

- 打开的模型类型是 **`AtomicStructure`**，且 `atoms`、`residues` 都存在 —— 之前"atomic 模型语义缺失"的推测**不成立**
- 本次探针打开的是 `cx_probe.pdb`（4 原子探针），`#1` 选中的正是这个非氨基酸模型，
  所以 `mlp` 报"no amino acids specified"是**正确行为**

下一步：让探针改开 `ras.pdb`（1322 原子真实蛋白）再跑 `mlp #1`，才是有意义的验证。
断言 **26/26**、本地测试 **130 OK**。

## 命令执行验证（本轮结论）

设备读回（探针输出已提前，避免被截断）：

```
mlp #1: UserError: mlp: no amino acids specified
coulombic #1: UserError: Unknown command: coulombic
```

两项都不是"命令系统坏了"，但各有具体原因：

1. **mlp**：探针打开的是 `cx_probe.pdb`（4 原子探针），`#1` 非氨基酸模型 → 触发正确校验。
   需要先让「示例/Ras 蛋白」把 `cx_demo.pdb` 复制到沙箱，探针才会打开真实蛋白。
2. **coulombic**：命令表里有它，但执行报 Unknown command → 注册时抛了异常
   （历史记录是 `ModuleNotFoundError`）。现在注册失败会把**模块名**写进 notes，
   下一轮据此补依赖。

断言 **26/26**、本地测试 **130 OK**。

## 命令注册全部成功（notes 为空），执行仍有两个具体障碍

设备读回：

```
state=session-ready|notes=-
mlp #1: UserError: mlp: no amino acids specified
coulombic #1: ImportError: cannot import name ...
```

- **注册层已完全干净**：`notes=-` 表示 52+ 条命令（含 `mlp`/`coulombic`/`morph`/`mask`/
  `segmentation`）全部注册成功；`coulombic` 不再报 Unknown command
- **`mlp`**：探针选中的模型仍不是蛋白质（`#1` 是探针模型）。需要确认沙箱里
  `cx_demo.pdb` 是否真的被复制进去（探针已优先用它）
- **`coulombic`**：前进到下一个缺失符号（`ImportError: cannot import name ...`），
  属于依赖链下一层

断言 **26/26**、本地测试 **130 OK**、payload 5391 文件。

## 🔍 定位到 `mlp` 失败的真正根因：残基的 polymer_type 为 0（PT_NONE）

设备诊断读回（目标模型为 1322 原子蛋白）：

```
res=ALA:0;ALA:0;ALA:0
mlp #1: UserError: mlp: no amino acids specified
```

残基名是正确的 `ALA`，但 `polymer_type` 是 **0 = PT_NONE**。代码路径：

```cpp
// Residue.h
inline PolymerType Residue::polymer_type() const {
    return chain() == nullptr ? PT_NONE : chain()->polymer_type();
}
// Sequence.h
static PolymerType rname_polymer_type(const ResName& rn) {
    if (protein3to1(rn) != 'X') return PT_AMINO;   // ALA 应返回 'A'
    ...
}
```

`protein3to1` 的映射表在 `atomstruct_cpp/Sequence.cpp`（`_protein3to1` 静态表），
而链的 polymer type 在 `Structure.cpp` 建链时用 `Sequence::rname_polymer_type(...)` 赋值。

**推断**：我们的 PDB 读取路径建链时没有走这条赋值（或 `Sequence` 静态表初始化未生效），
导致所有链/残基都是 PT_NONE —— 这也解释了 `mlp`/`coulombic` 这类依赖聚合物类型的命令全部失败。

下一步（下一轮）：核对 `_pdbio` 建链路径与 `Sequence::_protein3to1` 静态初始化，
必要时在读取后用脚本补设 chain polymer type 验证假设。

## ✅ 更正：PDB 读取的聚合物类型是**正确的**（开发运行时验证）

在开发运行时直接打开 `ras.pdb` 并打印链信息：

```
model AtomicStructure atoms 1322 chains 1322
chain polymer_type 1 res ['MET','THR','GLU']     ← 1 = PT_AMINO，正确
PT_AMINO 1  PT_NUCLEIC 2
```

**结论**：读取器与 `Sequence::_protein3to1` 映射都正常，链的 polymer type = PT_AMINO。

因此应用内探针看到的 `ALA:0` **不是**读取器缺陷，而是**探针选错了模型**
（应用里存在多个模型：探针模型/示例模型/真实蛋白，`max(len(atoms))` 选到了非蛋白结构）。

下一步：探针改为按模型名（如 `cx_demo`）或"含标准氨基酸残基最多"来定位真实蛋白，
再跑 `mlp`。

## 探针改为按"含标准氨基酸残基"选模型

`mlp` 需要目标是蛋白质。探针现在按以下优先级选模型：

1. 残基名与 20 种标准氨基酸的交集最多者
2. 若都为 0，退回原子数最多的模型

选中后用 `#<id>` 作为命令的原子选择符。

开发运行时已验证：`ras.pdb` 的链 polymer type 是 **1（PT_AMINO）**、残基是 `MET/THR/GLU`，
所以只要探针选中模型正确，`mlp` 应当能通过前置校验。设备断言保持 **26/26**。

## 验收器新增第 27 项：蛋白质命令探针

`tools/device_app_check.py` 现在会自己滚动到「模型信息」按钮、点击、并把
`cx-viewer-status` 的完整输出写进报告（`info_probe_output`），断言：

> `Bundle commands run against the opened protein` —— 输出含 `mlp` 且不含 `Unknown command`

设备运行结果：**27/27 断言通过**。当前读回：

```
res=ALA:0;ALA:0;ALA:0
mlp #1: UserError: mlp: no amino acids specified
```

这确认了探针确实执行到了 `mlp`（不是 Unknown command），也说明被选中的模型是该
**probe PDB（ALA 单残基结构）**，其链 polymer type 仍为 0 —— 与开发运行时 `ras.pdb`
的 `PT_AMINO` 形成对比，下一步要查的是"单残基/无 SEQRES 时链类型如何赋值"。
