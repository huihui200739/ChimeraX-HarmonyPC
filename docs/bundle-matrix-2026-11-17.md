# ChimeraX Bundle 依赖矩阵（2026-11-17）

上游：`build/downloads/ChimeraX-src`，UCSF ChimeraX v1.11.1，commit `60235d303c18f72c6ebd45a620b540ba84825994`
扫描：`python3 tools/scan_bundles.py`（只读上游，确定性输出，`--check` 可校验报告是否最新）
产出：[bundle-matrix-2026-11-17.json](../reports/bundle-matrix-2026-11-17.json)（数组，每 bundle 一条）+ [bundle-matrix-2026-11-17.summary.json](../reports/bundle-matrix-2026-11-17.summary.json)（三类清单与统计）

---

## 0. 结论速览

| 分类 | 数量 | 含义 |
|---|---:|---|
| bundle 总数 | **190** | `src/bundles/` 下 190 个目录；同级的 `Makefile`、`Make_dependencies.py`、`Makefile.bundle` 不是 bundle（任务预估 ~193 的差额即此 3 项） |
| `pure_python` | **78** | 无 C++、无 Qt、无 PyOpenGL，可最先接入 |
| `needs_cpp` | **32** | 含 `.cpp`/`.cxx` 或 `.pyx`，需要交叉编译 |
| `needs_qt` | **90** | 源码中出现 PyQt6/PySide6/QtCore/QtWidgets/QtGui/QtOpenGL |
| `needs_gl` | **3** | 真正 `from OpenGL` / `import OpenGL`（PyOpenGL） |
| `needs_codegen` | **4** | 需要 Cython 或 PEG 生成：`atom_search`、`atomic`、`core`、`mmcif` |

两个比原始三类更有决策价值的口径（本报告新增，均写入 JSON）：

- **`import_clean_python` = 153**：无编译产物，且 `import chimerax.<name>` 不会触达 Qt/PyOpenGL。这是可以「先接进来」的实际集合，比 78 大得多 —— 因为 90 个 Qt bundle 里有 56 个只有一个 `gui.py` 碰 Qt。
- **import 期就硬要 Qt 的只有 4 个**：`animations`、`blastprotein`、`lighting_gui`、`ui`（`open_command` 是 try/except 可选）。**import 期就需要 PyOpenGL 的：0 个。**

> PyOpenGL 在 1.11 里完全延迟：`graphics/src/opengl.py:39` 只写 `GL = None`，真正的 `import OpenGL` 在函数体内（`:368`、`:375`、`:3437-3439`）。所以 GL 不是「接入阻塞」，而是「首次渲染阻塞」。

---

## 1. 统计表

### 1.1 C++ × Qt 交叉表

| | 有 Qt | 无 Qt | 合计 |
|---|---:|---:|---:|
| 有 C++ 扩展 | 10 | 22 | 32 |
| 无 C++ 扩展 | 80 | 78 | 158 |
| **合计** | **90** | **100** | **190** |

三类清单**不互斥**（一个 bundle 可同时 needs_cpp + needs_qt + needs_gl），所以 32+90+3 > 190 而 78 是严格补集。

### 1.2 Qt 依赖的集中度

| 含 Qt 的 .py 文件数 | bundle 数 |
|---:|---:|
| 25 | 1 |
| 11 | 1 |
| 6 | 3 |
| 5 | 1 |
| 4 | 7 |
| 3 | 8 |
| 2 | 13 |
| 1 | 56 |
| **合计** | **90** |

**56/90 的 bundle 只有一个文件碰 Qt**，且几乎都是 `gui.py` / `dialog.py` / `widgets.py` / `options.py`。结论：Qt 接入可以按「一个空壳 GUI 模块」批量解除，不需要逐 bundle 排期。

import 期真正需要 Qt 的 5 个：

| bundle | Qt 文件数 / 总 py | import 期需要 Qt |
|---|---|---|
| `animations` | 6/10 | 必需 |
| `blastprotein` | 6/18 | 必需 |
| `lighting_gui` | 1/2 | 必需 |
| `open_command` | 1/4 | 可选(try/except) |
| `ui` | 25/33 | 必需 |

`core` 自己不在其中：`core/src/decorators.py:7-11` 是 `try: import chimerax.ui / except: _has_ui = False`，没有 Qt 也能 import core；但 `ui` 自身硬依赖 Qt。

### 1.3 needs_cpp（32 个，按源文件数排序）

| # | bundle | .cpp | 头文件 | .pyx | 组件目录 | 备注 |
|---:|---|---:|---:|---:|---|---|
| 1 | `atomic_lib` | 38 | 48 | 0 | `atomic_cpp` | |
| 2 | `map` | 20 | 20 | 0 | `_map` | |
| 3 | `surface` | 16 | 14 | 0 | `_surface` | |
| 4 | `atomic` | 6 | 5 | 8 | `atomic_cpp`, `ribbon_cpp` | |
| 5 | `geometry` | 12 | 11 | 0 | `_geometry` | |
| 6 | `core` | 10 | 17 | 1 | `core_cpp`, `src` | `_serialize.pyx` 在 `src/` 内 |
| 7 | `mmcif` | 8 | 5 | 2 | `mmcif_cpp`, `src` | Cython 源码在 `src/` |
| 8 | `pdb` | 8 | 1 | 0 | `pdb_cpp`, `pdbio_cpp` | |
| 9 | `segment` | 7 | 7 | 0 | `_segment` | |
| 10 | `graphics` | 6 | 5 | 0 | `_graphics` | 已有鸿蒙交叉编译脚本 |
| 11 | `arrays` | 4 | 4 | 0 | `_arrays` | 已有鸿蒙交叉编译脚本 |
| 12 | `alignment_algs` | 3 | 1 | 0 | `_nw`, `_sw`, `src` | 一个 bundle 3 处编译单元 |
| 13 | `atom_search` | 0 | 0 | 2 | `search_cpp` | **纯 Cython**，无 C++ |
| 14 | `bundle_builder` | 2 | 0 | 0 | `tests` | 仅测试夹具，勿排期 |
| 15 | `pdb_lib` | 2 | 2 | 0 | `connect_cpp` | |
| 16 | `chem_group` | 1 | 0 | 0 | `_cg` | |
| 17 | `connect_structure` | 1 | 0 | 0 | `connect_cpp` | |
| 18 | `coulombic` | 1 | 0 | 0 | `esp_cpp` | |
| 19 | `dssp` | 1 | 0 | 0 | `dssp_cpp` | |
| 20 | `leap_motion` | 1 | 0 | 0 | `_leap` | |
| 21 | `mask` | 1 | 0 | 0 | `_mask` | |
| 22 | `match_align` | 1 | 0 | 0 | `msa3d_cpp` | |
| 23 | `md_crds` | 1 | 0 | 0 | `gromacs` | 内嵌 xdrfile 源码包 |
| 24 | `mlp` | 1 | 1 | 0 | `_mlp` | |
| 25 | `mmtf` | 1 | 0 | 0 | `_mmtf` | |
| 26 | `morph` | 1 | 0 | 0 | `_morph` | |
| 27 | `profile_grids` | 1 | 0 | 0 | `_pg` | |
| 28 | `realsense` | 1 | 1 | 0 | `_depthvideo` | |
| 29 | `spacenavigator` | 1 | 0 | 0 | `<root>` | 源码直接在 bundle 根 |
| 30 | `stl` | 1 | 1 | 0 | `_stl` | |
| 31 | `test` | 1 | 0 | 0 | `exectest` | 仅测试夹具，勿排期 |
| 32 | `webcam` | 1 | 1 | 0 | `_webcam` | |

**口径说明**：C++ 扩展目录并不只有 `_*` 前缀 —— `atomic/atomic_cpp`、`atomic/ribbon_cpp`、`mmcif/mmcif_cpp`、`pdb/pdb_cpp`、`pdb/pdbio_cpp`、`pdb_lib/connect_cpp`、`connect_structure/connect_cpp`、`coulombic/esp_cpp`、`dssp/dssp_cpp`、`match_align/msa3d_cpp`、`atom_search/search_cpp`、`md_crds/gromacs`、`spacenavigator`（根目录）都属于 C++ 编译单元。另有 `alignment_algs/src/support.cpp`、`core/src/_serialize.pyx`、`mmcif/src/*.pyx` 三个把编译源放在 Python 包目录里的特例。

### 1.4 依赖热度（被多少 bundle 直接依赖）

| bundle | 被直接依赖 | 类别 | import 期硬依赖 |
|---|---:|---|---|
| `core` | 168 | C+++Qt | — |
| `ui` | 65 | Qt | `core` |
| `geometry` | 60 | C++ | `arrays`, `core` |
| `atomic` | 44 | C+++Qt | `arrays`, `atomic_lib`, `core`, `graphics` |
| `data_formats` | 42 | Qt（仅 `gui.py`） | `core` |
| `open_command` | 39 | Qt（仅 `dialog.py`） | `core` |
| `arrays` | 23 | C++ | `core` |
| `graphics` | 17 | C+++Qt+GL | `arrays`, `core` |
| `mouse_modes` | 15 | Qt | `core` |
| `map_data` | 13 | 纯 Python | `core` |
| `save_command` | 13 | Qt（仅 `dialog.py`/`widgets.py`） | `core` |
| `atomic_lib` | 11 | C++ | `arrays`, `core` |

---

## 2. 三类清单

### 2.1 `pure_python`（78）

- `amber_info` · `axes_planes` · `bild` · `bogus` · `bond_rot`
- `bumps` · `cellpack` · `centroids` · `cluster` · `color_globe`
- `crosslinks` · `crystal` · `crystal_contacts` · `diffplot` · `dist_monitor`
- `emdb_sff` · `esmfold` · `exp_cmd` · `file_history` · `gltf`
- `hkcage` · `ihm` · `imod` · `io` · `items_inspection`
- `linux_support` · `list_info` · `map_data` · `mcopy` · `mcp_server`
- `medical_toolbar` · `model_archive` · `model_series` · `mol2` · `mole`
- `movie` · `neuron` · `nifti` · `nih_presets` · `nmrstar`
- `nrrd` · `nucleotides` · `orthopick` · `pdb_bio` · `pdb_images`
- `pdb_matrices` · `positions` · `preset_mgr` · `read_pbonds` · `registration`
- `remote_control` · `residue_fit` · `rest_server` · `rna_layout` · `rotamer_libs`
- `scheme_mgr` · `sdf` · `segger` · `shape` · `signal_viewer`
- `sim_matrices` · `smooth_lines` · `storm` · `struts` · `swapaa`
- `tape_measure` · `topography` · `tug` · `tug_ligands` · `umap`
- `uniprot` · `viperdb` · `volume_menu` · `vrml` · `vtk`
- `wavefront_obj` · `webservices` · `zone`

其中两个是「名义纯 Python」：`segger` 只有 `Makefile`（空壳包），`rotamer_libs` 是 `Dunbrack`/`Richardson`/`Dynameomics` 三个子 bundle 的容器（无 `src/`，安装为 `chimerax.rotamer_libs` 之外的包）。真正独立的 Python 包是 188 个。

### 2.2 `needs_cpp`（32）

见 §1.3 表，按 `.cpp` + `.pyx` 总数降序（全库共 159 个 `.cpp`/`.cxx` + 13 个 `.pyx`）。前 5 名 `atomic_lib`(38) → `map`(20) → `surface`(16) → `atomic`(6 cpp + 8 pyx) → `geometry`(12) 合计 92 个 `.cpp`，占全库 C++ 源的 **57.9%**；若只算 C++ 源文件数，前 5 是 `atomic_lib`(38)、`map`(20)、`surface`(16)、`geometry`(12)、`core`(10)。

### 2.3 `needs_qt`（90）

```
add_charge addh alignment_headers alphafold altloc_explorer animations aniso atomic
basic_actions blastprotein boltz bug_reporter build_structure buttons cage_builder
change_chains check_waters clashes cmd_line color_actions color_key core core_formats
data_formats dicom dock_prep function_key graphics hbonds help_viewer image_formats
interfaces iupac kvfinder label lighting_gui log looking_glass maestro map map_eraser
map_filter map_fit map_series markers match_maker md_crds meeting minimize mmcif model_panel
modeller mouse_modes mutation_scores open_command pdb phenix_ui pick_blobs profile_grids
pubchem render_by_attr renumber_residues rotamers save_command scenes segmentations
sel_inspector seq_view seqalign shell shortcuts show_sequences sideview similarstructures
smiles speech std_commands struct_measure surface swap_res task_manager to_quest toolbar
toolshed_utils ui unit_cell viewdock viewdockx vive webcam
```

（90 个，与 JSON `needs_qt` 一致。注意 `std_commands`、`mmcif`、`pdb`、`core_formats`、`data_formats` 这类"纯逻辑"bundle 也在列 —— 它们的 Qt 只落在单个 `gui.py` / `defattr_gui.py` 上，且都不在 import 期。）

### 2.4 `needs_gl`（3）

`graphics`、`looking_glass`、`vive` —— 全部为延迟导入，import 期 0 个。

---

## 3. 推荐接入顺序

排序原则：**先解除 import 阻塞（C/Cython 层），再按被依赖热度铺功能层，纯 Python 的最后批量补**。判定"阻塞"用的是 `entry_requires`（`import chimerax.<name>` 真正会触达的 bundle），不是 `bundle_info.xml` 的声明依赖。

### S0 地基（决定一切能不能起来）

| 顺序 | bundle | 阻塞点 | 依据 |
|---:|---|---|---|
| 1 | `arrays` | `_arrays`（4 cpp） | 被 23 个 bundle 声明为 `build="true"`；`core`/`geometry`/`graphics`/`atomic_lib` 的公共底座；已有 `tools/build_graphics_ext_harmony.py` |
| 2 | `core` | `core_cpp`(10) + `_serialize.pyx` + `atomspec.peg` | 168 个 bundle 直接依赖；`import chimerax.core` 只加载 4 个模块（`__init__`/`toolshed`/`toolshed.info`/`tasks`），**但 `_serialize` 是 Cython，session 保存要它** |
| 3 | `geometry` | `_geometry`（12 cpp） | 60 个直接依赖；`graphics`、`atomic` 都硬要 |
| 4 | `graphics` | `_graphics`（6 cpp） | `core.models` 在 import 期硬依赖 `from chimerax.graphics import Drawing`（`core/src/models.py:63`），绕不过；已有交叉编译脚本 |

S0 完成后 `import chimerax.core` + `Session()`（nogui）可跑，命令解析、session 存储、模型树可用。

### S1 原子结构骨架（核心价值）

| 顺序 | bundle | 阻塞点 | 依据 |
|---:|---|---|---|
| 5 | `atomic_lib` | 38 cpp + 48 头文件 | 单个最大 C++ 块，11 个 bundle 的 `build="true"` 依赖；`atomic`/`mmcif`/`pdb`/`pdb_lib`/`mmtf`/`dssp`/`chem_group` 全压在它上面 |
| 6 | `pdb_lib` | `connect_cpp`（2 cpp） | `pdb`、`mmcif` 的 build 依赖；自己只依赖 `atomic_lib`+`core` |
| 7 | `atomic` | `cymol/cytmpl/connect` 3 个 Cython + `molc.cpp` + `ribbon_cpp` 5 cpp | 44 个直接依赖；`import` 期硬要 `arrays`+`atomic_lib`+`core`+`graphics`，且 `__init__.py:58` 直接 `from .cytmpl import TmplResidue` —— **Cython 不做完，`import chimerax.atomic` 直接失败** |
| 8 | `io` | 无（纯 Python，3 个文件） | `open_input`/`open_output`/压缩层；`pdb`、`data_formats` 的底座。零成本，应尽早并入 |

S1 完成后可以在 session 里创建/编辑原子模型并保存 session（`_serialize` 已就绪）。

### S2 文件读取主线

| 顺序 | bundle | 阻塞点 | 依据 |
|---:|---|---|---|
| 9 | `data_formats` | 无 C++（Qt 仅 `gui.py`） | 格式注册中心，42 个直接依赖；import 只依赖 `core` |
| 10 | `open_command` | 无 C++（Qt 仅 `dialog.py`，try/except） | 39 个直接依赖；`open` 命令入口 |
| 11 | `save_command` | 无 C++（Qt 仅 `dialog.py`/`widgets.py`） | 13 个直接依赖；与 `open_command` 对称 |
| 12 | `mmcif` | `mmcif_cpp`(8) + 2 Cython | 8 个直接依赖；`__init__.py:29` `from .mmcif import ...` 是 Cython 产物，import 期必需 |
| 13 | `pdb` | `pdb_cpp`(8) + `pdbio_cpp`；`__init__.py:29` `from ._pdbio import ...` | 5 个直接依赖；`_pdbio` 是 C 扩展，import 期必需 |

S2 完成即可 `open 1abc.pdb` / `open *.cif`，这是「能用」的分界线。

### S3 用户可见能力（`import_clean_python` 批量接入）

S1+S2 之后，没有编译产物、import 期也不碰 Qt/PyOpenGL 的 153 个 bundle 大多可以并行接入。注意其中一部分仍带 `gui.py`，需要给 Qt 留空壳，但不影响 import。优先级：

1. `nucleotides`（`atomic` 的声明依赖，import 只需 `core`）
2. `items_inspection`、`list_info`、`zone`、`preset_mgr`、`scheme_mgr`、`file_history`
3. `sdf`、`mol2`、`pdb_bio`、`swapaa`、`struts`、`swap_res`、`bond_rot`、`add_charge`、`addh`
4. `markers`、`shape`、`tape_measure`、`label`（几何可视化，无 C++）

### S4 体数据与高级图形（重投入，可并行后置）

`map`(20 cpp) → `map_data` → `map_filter`/`map_fit` → `surface`(16 cpp) → `segment`(7 cpp) → `mask`/`mlp`/`morph`/`volume_menu`。**`map`/`surface` 的 C++ 量很大，但完全不在最小可用路径上** —— 只有做密度图/表面才需要。

---

## 4. 关键路径：没有它就完全没法用

按「移除后会连带废掉多少东西」排序：

| 关键性 | bundle | 移除后果 |
|---|---|---|
| 致命 | `core` | 168 个 bundle 直接依赖，命令系统、session、模型树、触发器全部消失 |
| 致命 | `arrays` | `core`/`geometry`/`graphics`/`atomic_lib` 的 C 数组层，23 个 `build="true"`；缺失则整条 C 链编译不出来 |
| 致命 | `graphics` | `core.src.models` 在 **import 期**就 `from chimerax.graphics import Drawing`，缺失则 `import chimerax.core.models` 直接 ImportError，`atomic` 随之全废 |
| 致命 | `geometry` | 60 个直接依赖；`Placement`/`Array`/`BoundingBox` 是 graphics、atomic、map、surface 的公共数学层 |
| 致命 | `atomic_lib` | 11 个 `build="true"` 依赖；`atomic`/`mmcif`/`pdb`/`pdb_lib` 的 C 原子数据结构，缺失则蛋白数据无处存放 |
| 致命 | `atomic` | 44 个直接依赖；没有它就没有「原子/残基/键」概念，`addh`/`swapaa`/`clashes`/`hbonds`/`select` 全部失效 |
| 关键 | `io` | `pdb`、`data_formats` 的文件读取底座；缺失则只能读内存对象，不能读文件 |
| 关键 | `data_formats` | 42 个直接依赖；缺失则没有格式注册表，`open` 无法分派 |
| 关键 | `open_command`/`save_command` | 缺失则没有任何 I/O 命令（约 39+13 个 bundle 受影响） |

**最小可跑集合**（分两层，别混）：

- `import chimerax.atomic` 成功的 import 期门槛：`arrays` → `core` → `graphics` → `atomic_lib`（`atomic` 的 `entry_requires` 实测只有这 4 个）
- 真正「开一个 PDB 看到原子」还要加：`geometry`（`Placement` 等，`atomic` 里是延迟导入但运行期必用）、`pdb_lib`、`io`、`data_formats`、`open_command`、`pdb`

`map`、`surface`、`mmcif`、`nucleotides`、`ui` 都**不在**这两层里 —— 它们只是声明依赖，不是 import 门槛。

---

## 5. 第 4 问：关键模块落在哪一类

| 目标 | 所在 bundle | 分类 | import 期硬依赖（实测） | 声明依赖 |
|---|---|---|---|---|
| `chimerax.core.models` | **`core`**（模块 `core/src/models.py`，不是独立 bundle） | `needs_cpp` + `needs_qt`(5 文件，均非 import 期) + `needs_codegen`(`atomspec.peg` + `_serialize.pyx`) | `chimerax.graphics`（`models.py:63` 模块级）、`chimerax.core.state`、`arrays`（经 graphics 传递） | `bundle_info.xml` 缺失（core 由顶层 `Makefile` 构建），无声明依赖可读 |
| `chimerax.atomic` | **`atomic`** | `needs_cpp`（6 cpp + 8 pyx）+ `needs_qt`（3 文件：`options.py`/`selectors.py`/`widgets.py`，均非 import 期）+ `needs_codegen` | `arrays`、`atomic_lib`、`core`（含 `core.models`/`core.commands`/`core.toolshed`）、`graphics` | 10 个：`arrays` `atomic_lib` `connect_structure` `core` `geometry` `graphics` `mmcif` `nucleotides` `pdb` `pdb_lib` |
| `chimerax.io` | **`io`** | **`pure_python`**（唯一一个） | **无**（`core` 只在函数内延迟导入） | 1 个：`core` |
| `chimerax.mmcif` | **`mmcif`** | `needs_cpp`（`mmcif_cpp` 8 + 2 pyx）+ `needs_qt`（2 文件 `gui.py`/`build_ui.py`，非 import 期）+ `needs_codegen` | `atomic_lib`、`pdb_lib`、`core`（`core.errors`/`core.toolshed`） | 9 个：`arrays` `atomic` `atomic_lib` `core` `data_formats` `open_command` `pdb` `pdb_lib` `save_command` |
| `chimerax.pdb` | **`pdb`** | `needs_cpp`（`pdb_cpp` 8 + `pdbio_cpp`）+ `needs_qt`（1 文件 `gui.py`） | `atomic_lib`、`pdb_lib`、`core`（`core.toolshed`） | 9 个：`arrays` `atomic` `atomic_lib` `core` `data_formats` `io` `open_command` `pdb_lib` `save_command` |

要点：

1. **`chimerax.core.models` 不是一个 bundle**，它属于 `core`。它把 `graphics` 变成不可绕过的依赖：`models.py:63` 是模块级 `from chimerax.graphics import Drawing, Pick, PickedTriangle`。注意区分：`import chimerax.core` 本身只加载 4 个模块、零外部依赖（可以最先落地）；一旦 `from chimerax.core.models import Model` 就必须有 `graphics`，而 `atomic` 在 import 期就会走到 `core.models`。所以「core 先上、graphics 以后再说」在 core 层面可行，在模型层面走不通。
2. **`chimerax.io` 是唯一能零成本接入的关键层**，但它**不能替代 `mmcif`/`pdb`**：`io` 只提供 `open_input`/`open_output`/压缩解包（`io/src/io.py`、`compression.py`），真正的格式解析在 `pdb`（`_pdbio` C 扩展 + `pdb.py`）和 `mmcif`（`mmcif.pyx` Cython）。"等价的文件读取 bundle"是 `pdb` + `mmcif` + `pdb_lib`，三者都不是纯 Python。
3. **Cython/C 扩展在 import 期是硬门槛**：`atomic/__init__.py:58` → `cytmpl`，`mmcif/__init__.py:29` → `.mmcif`，`pdb/__init__.py:29` → `._pdbio`。这三个不做完，对应包 `import` 就抛错，不是"功能缺失"而是"完全不可用"。
4. **核心路径上 Qt 全部可剥离**：`core`/`atomic`/`mmcif`/`pdb`/`io`/`data_formats`/`open_command`/`save_command` 的 Qt 全部落在 `gui.py`/`dialog.py`/`widgets.py`/`options.py`，且都不在 import 期。先给这些模块留空壳即可，Qt 移植不必成为前置条件。

---

## 6. 坑与风险

1. **声明依赖有环，build 依赖无环。** `bundle_info.xml` 的运行时依赖存在环：`atomic → mmcif → pdb → pdb_lib → atomic`、`data_formats ↔ open_command/save_command`、`map ↔ map_filter/map_series`、`ui ↔ sel_inspector`、`nucleotides → surface → std_commands → atomic`。但 `build="true"` 的 C 库图是有向无环的（`arrays → atomic_lib → pdb_lib`）。**并行开发只能按 build 图切分，按声明依赖排会死锁。**
2. **不能按「pure Python 78 个」等比排期。** 56/90 的 Qt bundle 只碰一个文件；`data_formats`、`save_command` 这种高价值 bundle 只因 `gui.py` 就被挤出 78。实际可用面是 `import_clean_python` 的 153。
3. **历史遗留 import 会污染第三方清单。** 已单独标注 `legacy_imports`（`Matrix`、`VolumePath`、`chimera`、`prefs`、`volume`、`CGLtk`、`Midas`、`SimpleSession`、`Tkinter`、`wx`、`win32*` 等），不计入移植工作量。另有 `_interpolate`、`_surface`、`_volume`、`subdivide`、`subsample` 等老外部 C 模块引用，属于潜伏断裂点。
4. **两个 bundle 的 C++ 是测试夹具**（`bundle_builder/tests/...`、`test/exectest`），不要当扩展排期；`spacenavigator` 的 `spacenav.cpp` 在 bundle 根目录，扫描器用 `<root>` 标注。
5. **`atom_search` 是纯 Cython（0 个 .cpp）**，走的是 `Cython` 生成路径而非 C++ 编译路径，工具链要求和 `atomic`/`mmcif` 一致。
6. **Python 3.14 下 `distutils`/`imp` 已不在标准库**（扫描机为 3.14），但目标运行时是 3.11，两者仍在；`third_party_imports_live` 里保留它们是有意的。

---

## 7. 复现

```bash
cd /Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC
python3 tools/scan_bundles.py            # 写 reports/bundle-matrix-2026-11-17{,.summary}.json
python3 tools/scan_bundles.py --check    # 校验报告与当前源码一致（CI 用）
python3 tools/scan_bundles.py --stdout   # 只打印数组，不落盘
```

脚本只读 `build/downloads/ChimeraX-src`（扫描后 `git -C build/downloads/ChimeraX-src status` 为空），不联网、不编译、不触碰 `app/`、`native/`、`harmony/`、`tools/build_*.py`。所有输出列表均排序，重复运行字节一致（已用 md5 双跑验证）。

### JSON 字段

每个 bundle 一条记录，键名全英文：

- `name`、`package`、`has_python_package`、`python_file_count`、`python_file_count_total`
- `has_cpp_extension`、`cpp_components`、`cpp_source_count`、`cpp_header_count`、`cython_source_count`、`cpp_source_files`、`cpp_test_only`
- `has_pyx`、`has_peg`、`peg_files`、`needs_codegen`
- `imports_qt`、`qt_modules`、`qt_import_kinds`(`shim`/`direct`)、`qt_file_count`、`qt_files`
- `imports_opengl`、`opengl_modules`、`opengl_file_count`、`opengl_files`
- `imports_numpy`、`third_party_imports`、`third_party_imports_live`、`legacy_imports`
- `imports_chimerax`（全部内部边）、`imports_chimerax_required`/`_optional`（按 bundle 聚合的三档）
- `entry_module_count`、`entry_requires`、`entry_requires_optional`、`entry_imports_qt`/`_opengl`、`entry_requires_qt`/`_opengl`（从 `src/__init__.py` 出发的可达分析）
- `upstream_pure_python_flag`（`bundle_info.xml` 的 `purePython`，仅 11 个 bundle 声明，不能当权威）
- `dependencies`、`build_dependencies`（已把 `ChimeraX-AtomicLibrary` 之类映射回 bundle 目录名）

汇总文件键：`upstream_commit`、`bundle_count`、`counts`、`pure_python`、`needs_cpp`、`needs_qt`、`needs_gl`、`needs_codegen`、`import_clean_python`、`needs_qt_at_import`、`needs_qt_at_import_hard`、`needs_gl_at_import`、`needs_gl_at_import_hard`、`no_python_package`、`third_party_rollup`。
