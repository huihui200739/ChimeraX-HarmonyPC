# 2026-11-17：`chimerax.atomic` C++ 扩展交叉编译

## 当前结论

**上游 `ChimeraX-Atomic` 的纯 C++ 组件已全部用 HarmonyOS SDK clang 交叉编过，并放进暂存包树：`_ribbons`、`molc`（ctypes 共享库），外加 atomic 运行时依赖的 `chimerax.geometry._geometry`。三个产物都是 `AArch64` / `NEEDED libpython3.11.so.1.0` / `RUNPATH $ORIGIN/../lib`，链接时通过 `-Wl,--no-undefined`，符号完全闭合。`cymol`/`cytmpl`/`connect` 三个 Cython 组件没编——本机没有 Cython，且不允许联网装，原因写在下面。**

只做了本机构建 + 本地 ELF/符号检查；**没有用 hdc、没有开模拟器**，设备侧导入验收仍由主线负责。工具：`tools/build_atomic_ext_harmony.py`；报告：`reports/atomic-ext-2026-11-17.json`。

## 先纠正一处事实：atomic 到底有几个子扩展

任务里写的 `_molc` / `_object` / `_atomstruct` / `_geometry` 这组名字在钉住的这版上游（commit `60235d303c18f72c6ebd45a620b540ba84825994`）里**不存在**。`src/bundles/atomic/bundle_info.xml` 实际声明的是：

| 组件 | 声明 | 源文件 | 产物形态 |
|---|---|---|---|
| `_ribbons` | `CModule`，`usesNumpy="true"` | `ribbon_cpp/{normals,parse,ribbons,spline,xsection}.cpp` | CPython 扩展，`PyInit__ribbons` |
| `molc` | `CLibrary` | `atomic_cpp/molc.cpp`（180 KB，导出 `EXPORT` C 函数） | 共享库，被 `chimerax/atomic/molc.py` 用 ctypes 打开 |
| `cymol` | `CModule` | `atomic_cpp/cymol.pyx` | Cython 生成后再编译 |
| `cytmpl` | `CModule` | `atomic_cpp/cytmpl.pyx` | Cython |
| `connect` | `CModule` | `atomic_cpp/connect.pyx` + `Library pdbconnect` | Cython + 需 PDBLibrary |

`_atomstruct` / `element` / `pyinstance` 也不是扩展模块，而是 `ChimeraX-AtomicLibrary` 里的 `CLibrary`（`libatomstruct.so` 等）；`_geometry` 属于 `ChimeraX-Geometry` 包。所以本次按真实结构编，不按名字编。

## 编过的（3/3 纯 C++ 组件）

| 模块 | 暂存路径 | bytes | sha256 |
|---|---|---|---|
| `_ribbons` | `build/chimerax-python/chimerax/atomic/_ribbons.cpython-311-aarch64-linux-ohos.so` | 2456072 | `0f99cc13e2cbe6259009e744fddcfdff14276f88cb72443342118a0ea0f94d56` |
| `libmolc` | `build/chimerax-python/chimerax/atomic/libmolc.so` | 2654352 | `b05567f466610796dbe6643b46dfe8dafd8f77ba9c165e3c28fa909b6d5ba2b0` |
| `_geometry` | `build/chimerax-python/chimerax/geometry/_geometry.cpython-311-aarch64-linux-ohos.so` | 709248 | `84a90b29d727d5c4a159fa76e8799e817ecb3e54ac88a621ddfdf16d10ac10c8` |

- 暂存目录里**只写 `.so`**，不碰任何 `.py`（`chimerax/atomic/` 原来没有 Python 源码，本次也没往里面拷 `.py`）。
- `libmolc.so` 放 `chimerax/atomic/libmolc.so` 而不是 `lib/` 子目录，是因为 `chimerax/atomic/molc.py` 的 `ctypes_open()` 先按 `os.path.dirname(__file__)/libmolc.so` 找，找不到才回退 `lib/libmolc.so`。放包根目录命中第一条。
- `_geometry` 属于 `chimerax.geometry`，落在 `chimerax/geometry/`（任务里把它列为 atomic 子扩展，实际归属不同，按正确归属放置）。
- 干净重建两次，sha256 完全一致，构建可复现；全量 64 个目标文件、约 37 秒。

### 编译/链接参数

```
clang++ --target=aarch64-linux-ohos --sysroot=<SDK>/sysroot -std=c++11 -O2 -fPIC -shared
        -I<py>/source/Include -I<py>/objects -Ibuild/atomic-ext/include
        -Ibuild/chimerax-python/numpy/core/include
        -L<py>/runtime/lib -l:libpython3.11.so.1.0
        -Wl,-rpath,$ORIGIN/../lib -Wl,--no-undefined
```

`build/atomic-ext/include/` 是符号链接根目录，把上游的包含路径还原成 ChimeraX 的写法（和 `build_graphics_ext_harmony.py` 的 `arrays` 处理同一套路）：

```
arrays      -> src/bundles/arrays/_arrays
atomstruct  -> src/bundles/atomic_lib/atomic_cpp/atomstruct_cpp
element     -> src/bundles/atomic_lib/atomic_cpp/element_cpp
pyinstance  -> src/bundles/atomic_lib/atomic_cpp/pyinstance_cpp
pysupport   -> src/bundles/core/core_cpp/pysupport
logger      -> src/bundles/core/core_cpp/logger
chutil      -> src/bundles/core/core_cpp/chutil
ioutil      -> src/bundles/core/core_cpp/ioutil
```

依赖栈（`libatomstruct` 那一套）在这个工作区里没有现成 `.so`，也不在本次范围内单独出库，所以**按 `_graphics` 的先例把它们直接编进每个产物**：`arrays` 的 `pythonarray.cpp rcarray.cpp refcount.cpp`、`atomstruct` 22 个 cpp、`atomstruct/tmpl` 13 个 cpp、`element/Element.cpp`、`pyinstance/PythonInstance.cpp`、core 的 `logger/chutil/ioutil` 6 个 cpp。这样产物自包含，只依赖运行时里的 `libpython3.11.so.1.0`，不会在设备上因为缺 `libarrrays.so`/`libatomstruct.so` 报 symbol not found。

## 跳过的（4 项，未伪造成功）

| 扩展 | 原因 | 需要什么才能编 |
|---|---|---|
| `cymol` | `.pyx` 源；上游不附带生成好的 C++；本机 `import Cython` 失败、pip 缓存无 Cython、不允许联网装 | Cython ≥ 3.0，`cython --cplus atomic_cpp/cymol.pyx` 生成后按 `_ribbons` 同样方式交叉编译 |
| `cytmpl` | 同上（同目录 `.pxd` 依赖 `cydecl.pxd`/`cycoord.pxd`，也必须由 Cython 展开） | 同上 |
| `connect` | Cython 源，另外还链接 ChimeraX-PDBLibrary 的 `pdbconnect`，该库在本工作区也没交叉编译过 | Cython + 交叉编译好的 `libpdbconnect.so` |
| `_load_libs`（`atomic_lib`） | 只在 `libatomstruct.so`/`libelement.so` 作为独立 `.so` 存在时才有意义；本次是静态编入，暂不需要 | 把依赖栈拆成 `chimerax/atomic_lib/lib/*.so` 再补 |

顺带说明：`molobject.py` 会 `import chimerax.arrays`「先加载 libarrrays」——本次 `libmolc.so` 自带 arrays 实现，这条前置在符号层面已无必要，但 Python 侧仍是 `import`，不影响导入。

## 本地检查证据

ELF（`llvm-readelf -h -d`，三个产物结果一致）：

```
Class:   ELF64
Type:    DYN (Shared object file)
Machine: AArch64
0x000000000000001d (RUNPATH)  Library runpath: [$ORIGIN/../lib]
0x0000000000000001 (NEEDED)   Shared library: [libpython3.11.so.1.0]
0x0000000000000001 (NEEDED)   Shared library: [libc++_shared.so]
0x0000000000000001 (NEEDED)   Shared library: [libc.so]
```

导出符号抽查：`_ribbons` 有 `PyInit__ribbons`、`geometry_new` 等；`libmolc.so` 有 `structure_atoms`、`_atom_name_tuple` 等 `EXPORT` 函数；`_geometry` 有 `PyInit__geometry`。

链接器加了 `-Wl,--no-undefined`，因此「少编进某个 atomstruct/arrays 目标文件」会直接变成构建失败，而不是设备上的加载期崩溃。

Python↔C 符号对账（工具内自动做，写进 report 的 `symbol_audit`）：

- `libmolc.so`：Python 侧 ctypes 引用 335 个符号，332 个精确命中，3 个是字符串拼接（`set_` / `structure_session_` / `pseudobond_global_manager_session_`）按前缀命中，**缺失 0**。
- `_ribbons`：C 方法表声明 25 个，`ribbon.py` 引用 25 个，**缺失 0**。
- `_geometry`：C 方法表声明 40 个，`chimerax/geometry/src/*.py` 引用 37 个（含 `from ._geometry import look_at as c_look_at` 这类别名），**缺失 0**。

## 怎么复现

```
python3 tools/build_atomic_ext_harmony.py
# 可选：--source --sdk --cpython --packages --workdir --report --modules _ribbons
```

工具会逐项校验输入（clang / llvm-readelf / sysroot / Python.h / pyconfig.h / numpy 头 / libpython / 每个 cpp 是否存在），列出缺哪个；编译或链接失败时把 stderr 截进 `reports/atomic-ext-<date>.json` 的 `compile_failures`/`link_failures`；成功时算 sha256 并跑 ELF 校验。目标文件缓存在 `build/atomic-ext/obj/`（flag 变了会自动清空重建）。

## 下一个阻塞点

1. **`chimerax/atomic` 包还缺 Python 源码**。`tools/stage_chimerax_python.py` 只 stage `core`/`arrays`/`graphics`，而且每次运行会 `rmtree(chimerax/)` —— 也就是说现在这份 `chimerax/atomic/*.so` 会被下一次 staging 直接删掉。需要主线把 `atomic`、`atomic_lib`（以及 `geometry`）的 `src/` 一起纳入 staging，并把 `.so` 复制挪到 staging 之后。
2. **Cython 组件（`cymol`/`cytmpl`/`connect`）没有编**。`chimerax/atomic/__init__.py` 及 `molc.py`/`molobject.py` 的部分路径依赖 `cymol`（Cython 版的 `Atom`/`Residue` 对象）。要么允许联网装 Cython 生成一次 C++、把生成物纳入工作区；要么明确走纯 ctypes 路径（上游 `molc.py` + `molobject.py` 那套，理论上不需要 `cymol`，但需要在设备上确认导入链）。
3. **`libpython3.11.so.1.0` 必须出现在 `chimerax/lib/`**（rpath 是 `$ORIGIN/../lib`，即从 `chimerax/atomic/` 往上到 `chimerax/lib`）。这是主线打包布局的事，本地只做了 ELF 声明检查。
4. **依赖栈是静态编入的，存在两份 `pyinstance` 注册表**：`libmolc.so` 和 `_ribbons*.so` 各自带一份 `atomstruct`/`pyinstance`。两边只通过裸指针交换对象，正常路径没问题；若设备上出现「Python 实例查不到 / 类型识别不对」这类现象，就该按上游布局拆成 `libatomstruct.so`、`libelement.so`、`libpyinstance.so`、`libarrrays.so` 共享库 + `_load_libs`，再让两个模块动态链接。
5. **设备验收未做**（本任务明确禁止 hdc/模拟器）：`import chimerax.atomic`、`Atom`/`Residue` 属性读写、ribbon 绘制三条断言要由主线在设备上跑。
