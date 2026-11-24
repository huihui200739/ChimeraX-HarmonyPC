# 2026-11-18：真实原子模型在鸿蒙应用内创建成功

## 当前结论

**应用内用 `chimerax.atomic` 构建出真实结构：读回 `atoms=2|residues=1|names=C1,N1`（两个原子、一个残基、坐标可读）。设备断言 23/23。**

这是"能加载/编辑/显示真实结构"的核心前提，之前卡在
`Cannot instantiate Python class corresponding to C++ atomstruct::Residue`。

## 根因与修复（关键）

`molc.py` 通过 ctypes 调 `libmolc.so` 里的 `structure_new_residue` 创建 C++ 对象，
而 `Residue.set_py_class(...)` 是在 `cymol.so` 里注册的。两份二进制各自持有
`PythonInstance<C>::_py_class` 静态成员 → 创建时读到的是**未注册的那一份**，于是报无法实例化。

修复：把所有 C++ 支撑代码（arrays + atomstruct + tmpl + element + pyinstance +
pdb_connect + readcif + core logger/ioutil/chutil）编成**唯一共享库**
`chimerax/lib/libcxatomstruct.so`，`cymol`/`cytmpl`/`_ribbons`/`libmolc`/`_pdbio`/`_mmcif`
全部链接它（`-lcxatomstruct` + rpath `$ORIGIN/../lib:$ORIGIN/../lib/chimerax/lib`），
注册与创建因此落在同一份静态成员上。

诊断链条（每一步都是真报错）：
`_load_libs` 缺失 → Cython 模块交叉编译 → `tmpl`/`logger`/`readcif`/`pdb_connect`/`element`/`pyinstance` 缺符号 → 静态拷贝导致注册表重复 → 单共享库 → 成功。

## 平台 shim 现在写进 staging

`tools/stage_chimerax_python.py` 现在**自动生成** `atomic_lib/_load_libs.py`、
`pdb_lib/_load_libs.py`，并给 `molc.py` 打 `CX_NATIVE_LIB_DIR` 优先查找补丁
（数据目录 ELF 不可 dlopen）。此前这些是手工补的，重跑 staging 会被清掉——已经不会了。

## 证据

- 设备收据：`reports/device-app-2026-11-18.json`（23 项断言，含 `cx-model`）
- 共享库构建：`reports/atomic-shared-lib-2026-11-18.json`
- 读取器构建：`reports/pdb-ext-2026-11-18.json`、`reports/cython-modules-2026-11-18.json`

## 边界与下一步

- 原子/残基已可创建与读回，但**还没有渲染**（下一步把 `chimerax.graphics` 接到 EGL 表面）。
- 文件打开路径（`chimerax.io.open_input` + `_mmcif`/`_pdbio`）尚未端到端验证。
