# 2026-11-17：numpy 1.26.4 交叉编译成功并在鸿蒙应用中运行

## 当前结论

**ChimeraX 锁定的 numpy 1.26.4 已为 aarch64-linux-ohos 交叉编译，并随应用打包：设备上 `numpy.__version__ = 1.26.4`、`numpy.sqrt(16.0) = 4.0`、`numpy.arange(5).sum() = 10`；numpy 的扩展模块从应用原生库目录加载（`/data/storage/el1/bundle/libs/arm64/numpy/core/_multiarray_umath...so`）。设备断言 12/12 全部通过。**

## 交叉编译路线（meson）

`tools/build_numpy_harmony.py` 用 meson 交叉文件取代了 numpy 1.26 的 distutils 路径（后者会忽略 clang 的 `--target`，产出 darwin 目标文件）。关键点：

| 配置 | 作用 |
|---|---|
| `[binaries]` 指向 SDK 的 clang/clang++/llvm-ar/llvm-strip | 真实 OHOS 目标编译 |
| `exe_wrapper = /tmp/cx-meson-device-run.sh` | configure 阶段的探测程序**通过 hdc 在模拟器上运行** |
| `longdouble_format = 'IEEE_QUAD_LE'` | 交叉构建无法运行格式探测，aarch64 上是 binary128 |
| `-Dblas=none -Dlapack=none` | 不引入不存在的 BLAS/LAPACK |
| `c_link_args` 追加 `-l:libpython3.11.so.1.0` 与 `$ORIGIN/../../../lib` | 让扩展带 NEEDED 与相对 rpath（鸿蒙加载器只按 NEEDED 解析 CPython 符号） |

产物：`build/numpy-1.26.4-ohos-wheel/numpy-1.26.4-cp311-cp311-macosx_27_0_arm64.whl`
（wheel 标签沿用构建机平台，内部 `.so` 经 `llvm-readelf` 确认为 **AArch64 ELF**，NEEDED `libpython3.11.so.1.0` + `libc.so`，RUNPATH `$ORIGIN/../../../lib`；暂存时把文件名后缀改写为 `*.cpython-311-aarch64-linux-ohos.so`。）

## 设备上新增的两个限制与对策

1. **数据目录里的 ELF 不可 `dlopen`**：numpy 的扩展放在解压目录会报 `No error information`。对策：把 numpy 的 19 个 `.so` 按包结构复制到应用原生库目录（`libs/arm64/numpy/...`），Python 包本身仍随运行环境归档分发。
2. **子模块名与原生库同名冲突**：最初"按 basename 兜底"的查找器把 `numpy._typing` 误解析到标准库 `_typing.so`。对策：查找器改为按**完整点分路径**映射（`numpy.core._multiarray_umath` → `libs/arm64/numpy/core/_multiarray_umath*.so`），不再按 basename 猜测。

## 证据

- 设备收据：`reports/device-app-2026-11-17.json`（12 项断言，含 numpy 版本与 `_umath` 实际加载路径）
- numpy 构建记录：`reports/numpy-2026-11-17.json`（含 meson 交叉文件全文与 wheel SHA-256）
- numpy 暂存记录：`reports/numpy-2026-11-17-cross.json`

## 边界与下一步

- 仍是模拟器验收；wheel 标签非 OHOS wheel 标签（只用于本工程打包，不是可发布 wheel）。
- `chimerax.core.colors/commands` 在主机侧仍无法导入（暂存的 numpy 面向 OHOS），需在**设备上**逐个验证；下一步把命令子系统的导入与最小命令执行放到设备探针里。
