# OpenHarmony PC 构建与验证指南

当前版本与支持范围以 [项目首页](README.md) 和 [设备验收记录](docs/PGC-VALIDATION-2026-11-21.md) 为准。

## 仓库

| 位置 | 地址 |
| --- | --- |
| AtomGit（镜像，推荐国内访问） | <https://atomgit.com/2501_93573368/ohos_ChimeraX> |
| GitHub（开发源） | <https://github.com/huihui200739/ChimeraX-HarmonyPC> |

## 环境

| 项目 | 要求 |
| --- | --- |
| 主机 | 当前打包脚本面向 macOS，使用 `/Applications/DevEco-Studio.app` 下的 DevEco 工具 |
| 本地测试 | Python 3.10+、Bash；不需要 DevEco、模拟器或上游源码目录 |
| 设备验收 | OpenHarmony 6.1.1 / API 24、aarch64 的 2-in-1 模拟器；默认目标 `127.0.0.1:5555` |
| 磁盘 | 仓库含原生库与运行时归档，克隆约 210 MB 跟踪文件，另需构建输出空间 |

请在有使用权限的前提下获取仓库（见上方两个地址，内容一致）。

## 编译运行

### 1. 克隆并自检

```bash
git clone https://atomgit.com/2501_93573368/ohos_ChimeraX.git
cd ohos_ChimeraX
bash scripts/verify.sh --local
```

`--local` 只跑单元测试，不需要 DevEco、设备或上游源码；失败时按输出里的用例名定位。

### 2. 打包 HAP

```bash
bash scripts/verify.sh --build-only
```

打包使用仓库内已有的原生库和运行时 ZIP，**不重新交叉编译**；HAP 生成在 `build/hap/`，构建报告写到 `build/reports/`。

若要重建 CPython、libffi、扩展模块或运行时归档，先读 [文档索引](docs/README.md) 中的运行时与扩展构建记录，不要把“只构建 HAP”当成“从上游源码重建”。

### 3. 安装到模拟器并验收

```bash
bash scripts/verify.sh
```

或对已生成的 HAP 单独验收：

```bash
python3 tools/device_app_check.py --target 127.0.0.1:5555 \
  --hap build/hap/entry-default-unsigned.hap
```

- DevEco 不在默认位置时，给设备脚本传 `--hdc`；它也会从 `PATH` 查找 `hdc`，打包仍使用默认 DevEco 路径。
- 遇到 `9568288`，先检查模拟器磁盘容量；脚本会停止，不会误验上一次已安装的应用。
- 默认产物是调试用未签名 HAP，不等于可在实体设备安装或对外分发。
- 验收报告写到 `build/reports/`，截图与报告同名、扩展名 `.jpeg`；入库记录在 `reports/`，仅在核对构建与范围后手动更新。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `hvigorw` / `ohpm` 找不到 | 确认 DevEco 安装在默认路径，或改用 DevEco 内的工具链 |
| 安装报 `9568288` | 模拟器空间不足，清理后重装；不要跳过验收继续后续断言 |
| 设备列表为空 | 先启动模拟器，`hdc list targets` 确认连接，再用 `--target` 指定实际地址 |
| 界面显示但命令无效 | 属 T1/T2 未覆盖范围，参照首页能力分级与验收记录 |

## 目录

| 路径 | 用途 |
| --- | --- |
| `app/` | DevEco 工程、ArkUI/N-API 入口及打包所需原生库和运行时 |
| `harmony/`、`patches/`、`*.lock.json` | 平台源码、适配补丁、版本与哈希锁定 |
| `vendor/`、`snippets/` | 兼容垫片、依赖和探针样例 |
| `scripts/`、`tools/`、`tests/` | 验证入口、构建/诊断工具、单元测试 |
| `docs/`、`reports/` | 设计说明、历史验收报告、筛选过的证据与截图 |
| `build/` | 构建输出、下载缓存和新报告，不入库 |
