# 2026-11-18：结构读取器与 atomic 模型层进展

## 当前结论

**`chimerax.atomic.AtomicStructure` 可以在设备上创建（`STRUCTURE cx_probe atoms=0`），`chimerax.mmcif` 与 `chimerax.pdb` 的 C++ 读取器已交叉编译并加载；但创建原子（`new_residue`/`new_atom`）仍失败：`Cannot instantiate Python class corresponding to C++ atomstruct::Residue`。**

设备侧 22 项断言保持全过（这一轮未改变应用探针集合）。

## 本轮打通的构建

| 产物 | 说明 |
|---|---|
| `chimerax/mmcif/_mmcif.cpython-311-aarch64-linux-ohos.so` | CIF 读取器（`mmcif_cpp` + `readcif_cpp`） |
| `chimerax/pdb/_pdbio.cpython-311-aarch64-linux-ohos.so` | PDB 读取器（`pdbio_cpp` + `pdb_cpp`） |
| `chimerax/lib/libcxatomstruct.so` | **单一共享支撑库**：arrays + atomstruct + tmpl + element + pyinstance + pdb_connect + readcif + core(logger/ioutil/chutil) |

新工具 `tools/build_atomic_shared_lib_harmony.py`；`build_cython_modules_harmony.py` 与 `build_pdb_ext_harmony.py` 已改为链接该共享库（不再各自静态拷贝），以避免"实例注册表多份"。

## 仍然存在的阻塞（如实记录）

`Cannot instantiate Python class corresponding to C++ N10atomstruct7ResidueE`

- 已排除"多份静态拷贝"这一原因（现在只有一份 `libcxatomstruct.so`）。
- 待查方向：
  1. `pyinstance` 注册发生的时机与模块（可能在 `_ribbons`/`cymol` 初始化里注册 Python 包装类，需确认注册是否在**同一** C++ 库实例上进行）；
  2. 我们编译时用的 `atomstruct` 头/实现是否与 Cython 生成代码里的类型名一致（`__n1` namespace 与 `_LIBCPP_ABI_NAMESPACE`）；
  3. 是否需要在上游 `libatomstruct.so`/`libpyinstance.so` 独立库形态下运行（即恢复上游的多库布局，而不是单库）。

## 附带完成

- `chimerax/pdb_lib/_load_libs.py` 平台 shim（与 atomic_lib 同款），让上游 import 通过。
- `readcif`、`pdb_connect`、`element`、`pyinstance` 的头文件根已按上游 `<xxx/...>` 布局建立符号链接目录。

## 下一步

1. 定位 pyinstance 注册点（读上游 `pyinstance_cpp` 与 `cymol.pyx` 的注册调用），决定是补注册还是拆成上游的多共享库布局。
2. 打通后用 `chimerax.io.open_input` 打开一个最小 PDB 文件，读回原子数与残基数。
3. 把渲染接上 EGL 表面后即可显示结构。
