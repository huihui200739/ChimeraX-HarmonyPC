# ChimeraX 鸿蒙 PC 适配 — 构建与验证说明

本仓库把 UCSF ChimeraX v1.11.1 接入 HarmonyOS PC（2in1）：上游版本按 commit 固定，适配以平台源码与补丁维护，
再用 ArkUI 外壳承载界面，经 N-API 把内嵌 CPython 与 ChimeraX 引擎接进 HAP。

- 上游：`RBVI/ChimeraX` @ `60235d3`（v1.11.1，见 [upstream.lock.json](upstream.lock.json)）
- 许可证：UCSF 非商业许可（见 [LICENSE](LICENSE)），分发前须核对条款
- 目标设备类型：`2in1`（鸿蒙 PC）

## 获取源码

```bash
git clone https://atomgit.com/2501_93573368/ohos_ChimeraX.git
cd ohos_ChimeraX
```

GitHub 开发源为 <https://github.com/huihui200739/ChimeraX-HarmonyPC>，两份内容逐字节一致。

## 环境

| 组件 | 版本/路径 |
| --- | --- |
| 主机 | macOS + DevEco Studio（默认 `/Applications/DevEco-Studio.app`） |
| HarmonyOS SDK | OpenHarmony 6.1.1 / API 24（aarch64，native 工具链） |
| Python | 3.10+（工具与测试） |
| hdc | DevEco SDK `default/openharmony/toolchains/hdc` |
| 设备 | API 24、arm64 的 2in1 模拟器，默认目标 `127.0.0.1:5555` |
| 磁盘 | 跟踪文件约 210 MB（含原生库与运行时归档），另需构建空间 |

工程路径不要带中文：Hvigor 对中文目录支持不稳定。

## 能力分级（T0 / T1 / T2）

按迁移能力分三档，详细状态与证据见 [项目首页](README.md) 和 [验收记录](docs/PGC-VALIDATION-2026-11-21.md)。

### T0 基础能力：启动、读取与渲染

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 引擎启动 | 已达成 | HAP 内启动 CPython 3.11.18 与 ChimeraX 引擎，建立会话与命令表 |
| 结构读取 | 已达成 | 官方 PDB、mmCIF、SDF 样例经原版读取器载入 |
| 结构显示 | 已达成 | 官方渲染器绘制彩色蛋白卡通与密度等值面 |
| 视图交互 | 已达成 | 拖动、缩放、选择高亮在模拟器验收中通过 |
| 图像导出 | 已达成 | 渲染帧导出为 PNG |

### T1 主要能力：面板、命令与保存

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| ArkUI 面板 | 部分覆盖 | 模型、结构、体积/表面、链序列、日志面板 |
| 原版命令 | 部分覆盖 | 核心命令集与部分 bundle 命令已注册并通过设备断言 |
| 表面计算 | 部分覆盖 | `_surface` 耳切封盖在正方形探针上验证，非任意输入 |
| PDB 保存 | 已接入未验证 | `save` 修复已合并，当前 HAP 尚未完成设备复验 |

### T2 增强能力：桌面完整兼容

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 原生 Qt 窗口 | 未覆盖 | 运行时拒绝 Qt 插件所需的 JS 求值，当前走 ArkUI 外壳 |
| 桌面 GUI 与插件 | 未覆盖 | 插件体系与全量命令兼容性未逐项验证 |
| 实体设备验收 | 未覆盖 | 现有验收均在模拟器完成 |

## 构建

仓库自带原生库与运行时压缩包，打包不重新交叉编译。

```bash
# 1) 本地单元测试（不需要 DevEco、设备或上游源码）
bash scripts/verify.sh --local

# 2) 构建未签名 debug HAP（产物在 build/hap/）
bash scripts/verify.sh --build-only
```

构建报告写入 `build/reports/`。若要重建 CPython、libffi、扩展模块或运行时归档，
先读 [文档索引](docs/README.md) 中的运行时与扩展构建记录，不要把这步当成从上游源码重建。

## 设备安装与验收

```bash
# 本地测试 + 构建 + 模拟器验收
bash scripts/verify.sh

# 或对已生成的 HAP 单独验收
python3 tools/device_app_check.py --target 127.0.0.1:5555 \
  --hap build/hap/entry-default-unsigned.hap
```

- DevEco 不在默认位置时，设备脚本可用 `--hdc` 指定，或把 `hdc` 加进 `PATH`；打包仍使用默认 DevEco 路径。
- 遇到 `9568288`，先清理模拟器空间；脚本会停止，不会把上一次安装的应用当作本次结果。
- 默认产物是调试用未签名 HAP，不等于可在实体设备安装或对外分发。
- 验收报告与截图写入 `build/reports/`；入库记录在 `reports/`，仅在核对构建与范围后手动更新。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `hvigorw` / `ohpm` 找不到 | 确认 DevEco 在默认路径，或用 DevEco 自带工具链 |
| 安装报 `9568288` | 模拟器空间不足，清理后重装，再重新执行验收 |
| 设备列表为空 | 先启动模拟器，`hdc list targets` 确认连接，再用 `--target` 指定 |
| 界面显示但命令无效 | 属 T1/T2 未覆盖范围，对照首页能力分级与验收记录 |
| 打包长时间无输出 | 首次构建需解压运行时归档，属正常；失败时看 `build/reports/` 的报告 |

## 目录

| 路径 | 用途 |
| --- | --- |
| `app/` | DevEco 工程、ArkUI/N-API 入口及打包所需原生库和运行时 |
| `harmony/`、`patches/` | 平台源码与适配补丁 |
| `*.lock.json` | 上游、运行时、libffi 的版本与补丁锁定（说明见 [AGENTS.md](AGENTS.md)） |
| `vendor/`、`snippets/` | 兼容垫片、依赖与探针样例 |
| `scripts/`、`tools/`、`tests/` | 验证入口、构建/诊断工具、单元测试 |
| `docs/`、`reports/` | 设计说明、历史验收报告与截图 |
| `build/` | 构建输出与新报告，不入库 |
