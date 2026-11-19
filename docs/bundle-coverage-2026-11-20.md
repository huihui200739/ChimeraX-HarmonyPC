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
