# 2026-11-17：运行环境首次在鸿蒙设备上真实运行

## 当前结论

**私有 CPython 3.11.18 运行环境已在鸿蒙 PC 模拟器（OpenHarmony-6.1.1.125 / API 24 / aarch64 / 2in1）上真实启动：解释器自报 cpython 3.11.18、隔离模式与 UTF-8 模式均为真；54 个原生扩展可导入，`_ctypes` 通过 libffi 调用 `libc.so` 的 `strlen` 返回 19；math/json/zlib/hashlib/binascii 计算正确。设备检查 8 项断言全部通过。**

这仍是通用运行环境层面的设备验证，**不含 Qt、Python Qt 绑定、原应用模块、科研数据或可安装 HAP**。模拟器此前被另一工程占用，本轮该工程已推送并清理、释放设备后才进行设备测试。

## 本轮发现并修复的真实缺陷

设备首次运行暴露了本地交叉编译阶段无法发现的符号可见性问题：

- 现象：解释器可以启动，但导入任何扩展都失败，报
  `ImportError: Error relocating .../math.cpython-311-aarch64-linux-ohos.so: PyModuleDef_Init: symbol not found`
  与 `_ctypes ... _Py_CheckFunctionResult: symbol not found`。
- 原因：`libpython3.11.so.1.0` 在设备上是通过适配器 `dlopen(RTLD_GLOBAL)` 载入的；鸿蒙加载器不会把这些符号放进后续扩展模块解析所用的全局作用域（`LD_LIBRARY_PATH` 无效，`LD_PRELOAD` 有效，可复现区分）。
- 修复：启动适配器在解析出私有运行根目录后，**自我重新执行一次**，把 `<root>/lib/libpython3.11.so.1.0` 放进 `LD_PRELOAD`、`<root>/lib` 放进 `LD_LIBRARY_PATH`，并用 `CX_HARMONY_PRELOADED` 防重入；未安装任何系统级文件，未改系统设置。改动 `harmony/bootstrap.c`（`preload_reexec`），启动器仍只使用 CPython 公开入口。
- 另一路尝试（把启动器直接链接到 `libpython3.11.so.1.0`，`--python-lib-dir` 选项并校验 `NEEDED`）已保留在 `tools/build_harmony_local.py`，但单独使用不能解决该问题，因此不作为主路径。

## 设备验证内容

| 断言 | 结果 |
|---|---|
| 运行环境归档传输到设备 | 通过 |
| 归档在设备上解包 | 通过 |
| 启动器 `--cx-runtime-check` 报告 CPython | `cpython` / `3.11.18 (main, Nov 9 2026, 21:48:32)` |
| 隔离模式与 UTF-8 | `isolated=true`、`utf8=true` |
| 原生扩展可导入 | 通过（无 ImportError） |
| `_ctypes` 经 libffi 调用 `libc.so` | `strlen("chimerax-on-harmony") = 19` |
| 标准库计算 | `math.sqrt(16)=4.0`、`json` 8 字节、`zlib` 12 字节、`sha256("cx")` 前 8 位 `2c1179ae`、`binascii.hexlify(b"\x01\x02")` = `0102` |
| 探针模块清理 | 通过（设备上已删除） |

收据：`reports/device-runtime-2026-11-17.json`（含设备型号、系统版本、归档 SHA-256、原始输出）。

## 产物

- 修复后的运行目录：`build/cpython-3.11.18/ohos-aarch64-with-libffi-v2/runtime`
- 归档：`build/runtime-payload/cx-generic-runtime-3.11.18-with-libffi-v2-aarch64-ohos.tar.gz`
- 清单重签：`tools/restamp_runtime_manifest.py`（适配器源码变更后重算 915 个文件哈希与链接）

## 边界

- 未包含 Qt、PyQt 绑定、`chimerax.*` 应用模块或科研数据；启动器默认入口 `-m chimerax.core` 仍会因缺少应用模块而报 `ModuleNotFoundError`，这是预期行为而非缺陷。
- 未生成 HAP、未签名、未上架。
- 该设备验证只覆盖通用运行环境；窗口、Qt 界面、文件对话框、键鼠与剪贴板等仍待验证。
