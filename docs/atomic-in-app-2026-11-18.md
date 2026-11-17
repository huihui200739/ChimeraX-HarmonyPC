# 2026-11-18：`chimerax.atomic` 在鸿蒙应用中导入成功

## 当前结论

**应用内 `import chimerax.atomic` 成功，读回 `chimerax.atomic|Atom|AtomicStructure`；设备断言 22/22。** 这标志着 C++/Cython 原子层在鸿蒙上可用，是"能加载结构"的前置条件。

## 打通的链条（每一步都踩过真实错误）

| 步骤 | 真实报错 | 处理 |
|---|---|---|
| `atomic_lib` 导入 | `cannot import name '_load_libs'` | 上游该模块负责 dlopen 每个静态库；本移植把库源码静态编进扩展，故提供**平台 shim** `_load_libs.py`（`load_lib()` 返回 `static:<name>`，不是伪造功能） |
| `cymol` 导入 | `No module named 'chimerax.atomic.cymol'` | 用 Cython 0.29.37 在宿主生成 C，再用 SDK clang 交叉编译（`tools/build_cython_modules_harmony.py`） |
| `cymol` 链接 | `tmpl::find_template_residue ... symbol not found` | 把 `atomstruct_cpp/tmpl/*.cpp` 加入静态链接集合 |
| `cymol` 链接 | `logger::_log ... symbol not found` | 把 `core_cpp/logger|ioutil|chutil` 加入静态链接集合 |
| `cymol` 导入 | `No module named 'tinyarray'` | 交叉编译 tinyarray 1.2.5（`tools/build_tinyarray_harmony.py`）；注意其模块名是 `PyInit_tinyarray`，文件名必须是 `tinyarray...so` |
| `chimerax.atomic` 导入 | `Unable to find 'lib/libmolc' shared library` | `molc.py` 用 ctypes 从包目录加载；数据目录 ELF 不可 dlopen → 补 `molc.py` 平台钩子：优先查 `CX_NATIVE_LIB_DIR/chimerax/atomic`（由原生引导设置） |

## 头文件组织（跨 bundle 的真实依赖）

ChimeraX 的 C++ 头用 `<atomstruct/Atom.h>`、`<chutil/CString.h>`、`<pysupport/convert.h>` 这类路径，需要在 include 根下建同名符号链接目录：
`build/atomic-include/{atomstruct,element,pyinstance,chutil,logger,ioutil,pysupport}` → 对应上游 `*_cpp` 目录。

## 产物

- `_ribbons`（2.46 MB）、`libmolc.so`（2.65 MB）、`_geometry`（0.71 MB）—— 见 `reports/atomic-ext-2026-11-17.json`
- `cymol`、`cytmpl` —— 见 `reports/cython-modules-2026-11-18.json`
- `tinyarray` —— 见 `reports/tinyarray-2026-11-18.json`
- 设备收据：`reports/device-app-2026-11-17.json`（22 项断言）

## 边界与下一步

- `connect`（`.pyx`，依赖 pdbconnect）与 `mmcif`/`pdb` 的 C 扩展尚未编译，因此"打开真实结构文件"还没打通。
- 下一步：补这些扩展 → 用 `chimerax.atomic` 构造 `AtomicStructure` → 接 graphics 渲染到已建立的 EGL 表面。
