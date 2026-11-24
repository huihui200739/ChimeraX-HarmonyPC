# 2026-11-17：ChimeraX 官方 Python 包在鸿蒙应用中运行

## 当前结论

**真实的 ChimeraX v1.11.1 Python 包已随应用打包并在模拟器上运行：应用内 `import chimerax.version` 读出 `v1.11.1`，`chimerax.core.errors`（`UserError`）与 `chimerax.core.logger`（`Logger`）导入成功，设备断言 9/9 全部通过。**

仍未包含 Qt/PyQt 绑定、`chimerax.core.session` 等依赖 GUI 的模块与科研数据。

## 做法

1. **上游源码**：按 `upstream.lock.json` 锁定提交 `60235d30…`（标签 `v1.11.1`）克隆 `RBVI/ChimeraX`，只用其 Python 包源码，不做整体上游构建。
2. **`tools/stage_chimerax_python.py`**：由上游 `buildinfo.py.in` 模板生成 `chimerax/version.py`（真实版本、提交、日期、分支、版权），复制 core bundle 源码到 `build/chimerax-python/chimerax/`（含 `core/`）。不使用占位版本号。
3. **打包**：`tools/package_app_runtime.py` 把该包写入运行环境 ZIP 的 `lib/python3.11/chimerax/`，随应用 rawfile 一起分发。
4. **设备读取**：页面新增 `ChimeraX`、`core`、`诊断` 三行，分别读回版本、core 模块与 `sys.prefix`/运行时目录状态。

## 这一轮在设备上修掉的问题（都是真机才暴露的）

| 现象 | 根因 | 修复 |
|---|---|---|
| `chimerax` 导入失败，运行时目录里没有该包 | 应用沙箱里的运行环境 ZIP 副本被复用，安装新 HAP 后仍是旧归档 | 归档文件名带版本号（`cx-runtime-v4.zip`），每次启动重写副本 |
| 提取后仍缺文件 | `@ohos.zlib.decompressFile` 未落地全部条目 | 自写原生 ZIP 解包器（zlib inflate + 中央目录解析），`extractArchive` N-API |
| 原生解包报 `cannot write …` | 目录创建函数漏掉最后一段 | `MakeDirs` 末尾补 `mkdir` |
| `rpath`/`sys.path` 之前指向解压目录里的扩展 | 数据目录 ELF 不可 dlopen | 扩展走应用原生库目录，`sys.path` 指向它 |

## 产物与证据

- HAP：`build/hap/entry-default-unsigned.hap`（32 MB，未签名 debug）
- 设备收据：`reports/device-app-2026-11-17.json`（9 项断言 + UI 读回值）
- ChimeraX 包暂存记录：`reports/chimerax-python-2026-11-17.json`（62 个文件、真实提交）
- 运行环境打包记录：`reports/app-runtime-2026-11-17.json`

## 边界与下一步

- 只证明"真实 ChimeraX Python 包可在鸿蒙应用内导入并取版本"；`chimerax.core.session`、`chimerax.ui`、Qt 相关模块仍未接入。
- 缺少的纯 Python 依赖（如 `sortedcontainers`）会在导入 `chimerax.core.colors/commands` 时暴露，后续按需引入并核验许可证。
- 下一步：引入 core 的 session/命令子系统最小依赖集，逐步逼近可执行的 ChimeraX 命令通道。
