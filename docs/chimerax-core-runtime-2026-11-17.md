# 2026-11-17：ChimeraX core 触发器在鸿蒙应用中真实派发

## 当前结论

**在鸿蒙模拟器的 HAP 内，真实 ChimeraX v1.11.1 的 `chimerax.core.triggerset.TriggerSet` 完成了 添加触发器 → 注册处理函数 → 激活 的完整链路，读回 `cx_app_probe|fired`；同时 `sortedcontainers 2.4.0`（纯 Python 依赖）已随包分发。设备断言 10/10 全部通过。**

仍缺 `numpy`（`chimerax.core.colors`/`commands` 的硬依赖），因此命令解释器尚未跑通。

## 本轮改动

1. `tools/stage_chimerax_python.py` 现在会把 `sortedcontainers-2.4.0` 的纯 Python 模块一并暂存（wheel 来自 PyPI，记录 SHA-256 与许可证文件），保证 `chimerax.core` 的依赖可复现。
2. 页面新增"触发器"行：在应用内创建 `TriggerSet`、注册 handler、激活触发器并读回结果。
3. `tools/device_app_check.py` 增加对应断言。

## numpy 交叉编译：已尝试，未成功（如实记录）

新增 `tools/build_numpy_harmony.py`（固定 sdist `1.26.4`，SHA-256 `2a02aba9…`），三处调整后仍失败：

1. 宿主 Python 的 setuptools distutils shim 缺 `distutils.msvccompiler` → 改用 stdlib distutils（`SETUPTOOLS_USE_DISTUTILS=stdlib`）。
2. sdist 需要 Cython 生成部分源文件 → 在宿主 3.11 环境装 `cython 0.29.37`。
3. **关键失败**：`numpy.distutils` 忽略 `CC="clang --target=aarch64-linux-ohos ..."`，把 `.so` 编成了 `*-darwin.so`（产物 19 个文件、0 个目标模块）。

结论：numpy 1.26 的 distutils 交叉编译路径不适用于本工具链。下一步应改用 numpy 2.x 的 **meson 交叉文件**（`--cross-file`）或对 1.26 施加 OHOS 工具链补丁，并把 `_PYTHON_HOST_PLATFORM`/`CC` 的传递方式改为 meson 的 `[binaries]` 段。

## 证据

- 设备收据：`reports/device-app-2026-11-17.json`（10 项断言，含 `cx-trigger` 读回）
- ChimeraX 包暂存：`reports/chimerax-python-2026-11-17.json`（71 个文件，含 sortedcontainers）
- 依赖记录：`reports/sortedcontainers-2026-11-17.json`
- numpy 失败记录：`reports/numpy-2026-11-17.json`（含完整构建日志路径与产物清单）

## 边界

- 触发器链路只是 ChimeraX core 的纯 Python 部分；不涉及 session、命令、模型或 GUI。
- numpy 未就绪，`chimerax.core.colors/commands` 仍无法导入。
