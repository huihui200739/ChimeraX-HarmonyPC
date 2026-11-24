# OpenHarmony PC 构建与验证指南

当前版本与支持范围以 [项目首页](README.md) 和 [设备验收记录](docs/PGC-VALIDATION-2026-11-21.md) 为准。

## 环境

| 项目 | 要求 |
| --- | --- |
| 主机 | 当前打包脚本面向 macOS，使用 `/Applications/DevEco-Studio.app` 下的 DevEco 工具 |
| 本地测试 | Python 3.10+、Bash；不需要 DevEco、模拟器或上游源码目录 |
| 设备验收 | OpenHarmony 6.1.1 / API 24、aarch64 的 2-in-1 模拟器；默认目标 `127.0.0.1:5555` |

## 获取与构建

仓库入口为 [GitHub](https://github.com/huihui200739/ChimeraX-HarmonyPC)；目前没有已核实的 AtomGit 镜像。请在有使用权限的前提下获取仓库。

```bash
git clone https://github.com/huihui200739/ChimeraX-HarmonyPC.git
cd ChimeraX-HarmonyPC
bash scripts/verify.sh --local
bash scripts/verify.sh --build-only
```

打包使用仓库内已有的原生库和运行时 ZIP，不重新交叉编译。HAP 位于 `build/hap/`；构建报告默认写到 `build/reports/`。若要重建运行时，先读 [文档索引](docs/README.md) 中的运行时和扩展构建记录，不要把仅构建 HAP 误当成从上游源码重建。

## 模拟器安装与验收

```bash
bash scripts/verify.sh
```

如果已生成 HAP，可单独验收，并显式指定设备：

```bash
python3 tools/device_app_check.py --target 127.0.0.1:5555 \
  --hap build/hap/entry-default-unsigned.hap
```

- 使用非默认 DevEco 安装位置时，可给设备脚本传 `--hdc`，它也会尝试从 `PATH` 查找 `hdc`；打包仍使用上述默认 DevEco 路径。
- 遇到 `9568288`，先检查模拟器磁盘容量；脚本会停止，不会误验上一次已安装的应用。
- 默认生成的是调试用未签名 HAP，不等于可以在实体设备上安装或对外分发。
- 验收报告默认写到 `build/reports/`，设备截图与报告同名、扩展名为 `.jpeg`。入库记录在 `reports/`，仅在核对构建与范围后手动更新。

## 目录

| 路径 | 用途 |
| --- | --- |
| `app/` | DevEco 工程、ArkUI/N-API 入口及打包所需原生库和运行时 |
| `harmony/`、`patches/`、`*.lock.json` | 平台源码、适配补丁、版本与哈希锁定 |
| `vendor/`、`snippets/` | 兼容垫片、依赖和探针样例 |
| `scripts/`、`tools/`、`tests/` | 验证入口、构建/诊断工具、单元测试 |
| `docs/`、`reports/` | 设计说明、历史验收报告、筛选过的证据与截图 |
| `build/` | 构建输出、下载缓存和新报告，不入库 |
