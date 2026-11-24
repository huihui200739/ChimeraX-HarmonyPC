# 工程约定（给人和 AI 协作者）

## 目标与口径

- 目标：UCSF ChimeraX v1.11.1 的分子结构显示与分析能力在 HarmonyOS PC（API 24 / arm64 / 2in1）上可运行、可复验；不做桌面 Qt 版的等替代上架。
- 状态词只有三个：`已达成`（模拟器实际交互并核对结果）、`部分覆盖`（已接入且部分场景验证）、`未覆盖`（未做或做不了）。
- 验收结论只以 [docs/PGC-VALIDATION-*.md](docs/PGC-VALIDATION-2026-11-21.md) 与 [reports/](reports) 中的记录为准；没有设备证据的改动写“已接入未验证”，不写“完成”。
- 当前版 HAP 若安装失败，不得用上一版的验收结论代替；验收记录必须写明对应的 HAP SHA-256 与设备环境。

## 许可边界

- 上游采用 [UCSF ChimeraX Non-Commercial Software License Agreement](LICENSE)：仅限非商业用途，向第三方分发本体或衍生改动前须取得 The Regents 书面许可。
- 本仓库的适配代码同样受该许可约束；引入新的上游源码、运行时或二进制前，先确认许可是否允许再入库。
- 不把 REW/Olex2 等其它项目的许可条款混用；每个依赖保留自己的许可文件。

## 目录职责

| 目录 | 放什么 | 不放什么 |
| --- | --- | --- |
| `app/` | DevEco 工程：ArkTS 页面、C++ 原生库、打包资源 | 构建产物（`build/`、`.hvigor/`、`oh_modules/`） |
| `harmony/` | 平台源码与 Makefile 片段 | 上游 Python 包 |
| `patches/` | 对上游/平台源码的补丁，编号递增 | 随手改的副本 |
| `vendor/`、`snippets/` | 兼容垫片、依赖与探针样例 | 预编译缓存 |
| `scripts/`、`tools/`、`tests/` | 验证入口、构建与诊断工具、单元测试 | 一次性临时脚本 |
| `docs/` | 设计、阶段总结、验收记录 | 大体积日志 |
| `reports/` | 体量小的验证收据 JSON 与截图 | HAP、运行时归档 |
| `build/` | 本地构建与临时证据（已在 `.gitignore`） | — |

## 锁定文件

| 文件 | 内容 |
| --- | --- |
| `upstream.lock.json` | 上游 ChimeraX 版本、commit 与关键文件指纹 |
| `runtime-sources.lock.json`、`runtime-patch.lock.json` | CPython 运行时源码与补丁 |
| `libffi-sources.lock.json`、`libffi-patch.lock.json` | libffi 源码与补丁 |
| `platform-patch.lock.json` | 平台适配补丁清单 |

新增或修改上述输入时同步更新对应 lock 文件，并让 `bash scripts/verify.sh --local` 通过。

## 改动流程

1. 改 `app/`、`harmony/`、`patches/`；打包所需二进制走 `vendor/` 或 `app/entry/libs`，并在文档里说明来源。
2. 跑 `bash scripts/verify.sh --local`（单元测试）；涉及打包时再跑 `--build-only`。
3. 有设备时跑 `bash scripts/verify.sh`，报告写入 `build/reports/`；确认无误后再挑需要的收据进 `reports/`。
4. 更新 `docs/` 或 `CHANGELOG.md`，说明改动范围和验证状态；README 的能力分级只在状态确实变化时调整。

## 提交规范

- 一个提交只做一件事；文档与代码分开提交。
- 提交信息写清“做了什么 + 验证到哪一步”，不写“完成”“全部通过”这类没有证据的结论。
- 不提交 HAP、运行时 ZIP、日志与大截图；`build/` 一律不入库。
