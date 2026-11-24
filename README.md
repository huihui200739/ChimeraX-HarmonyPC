# ChimeraX × HarmonyOS PC

在 OpenHarmony 6.1.1 / API 24（aarch64）上运行 UCSF ChimeraX v1.11.1。应用用 ArkUI 提供界面，内嵌 CPython 3.11.18 和 ChimeraX 引擎；不是桌面 Qt 版的完整替代。上游版本与文件指纹见 [upstream.lock.json](upstream.lock.json)。

![模拟器中的 ArkUI 界面、蛋白卡通和密度等值面](reports/viewport-protein-density-v2-2026-11-24.jpeg)

*历史界面截图（2026-11-24），用于展示适配效果，不是当前 HAP 的验收证据。*

## 仓库地址

| 位置 | 地址 |
| --- | --- |
| AtomGit（镜像） | <https://atomgit.com/2501_93573368/ohos_ChimeraX> |
| GitHub（开发源） | <https://github.com/huihui200739/ChimeraX-HarmonyPC> |

两份源码逐字节一致（tree `94f8778`）。

## 能力分级

按迁移难度分三档；状态只写已完成或已覆盖的部分，未覆盖项单列。

### T0 基础能力

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 引擎启动 | 已达成 | HAP 内启动 CPython 3.11.18 与 ChimeraX 引擎，创建会话与命令表 |
| 示例结构读取 | 已达成 | 官方 PDB、mmCIF、SDF 样例经原版读取器载入 |
| 结构显示 | 已达成 | 官方渲染器绘制彩色蛋白卡通与密度等值面 |

### T1 主要能力

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 视图交互 | 已达成 | 拖动、缩放、选择高亮在模拟器验收中通过 |
| 图像导出 | 已达成 | 渲染帧导出为 PNG |
| 面板与命令 | 部分覆盖 | ArkUI 模型、结构、体积/表面、链序列和日志面板；部分命令可用 |
| 结构保存 | 待复验 | 当前版包含 PDB `save` 修复，尚未对新 HAP 完成设备验收 |

### T2 增强能力

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 原生 Qt 窗口 | 未覆盖 | 运行时拒绝 Qt 插件所需的 JS 求值，当前走 ArkUI 外壳 |
| 桌面 GUI 与插件 | 未覆盖 | 桌面版插件体系与完整命令兼容性尚未逐项验证 |
| 实体设备 | 未覆盖 | 现有验收均在模拟器完成 |

## 验收状态

上一版 HAP 的模拟器验收为 **50/50**；当前 HAP 已构建，但模拟器安装因空间不足（`9568288`）未通过，未执行后续设备断言。详见 [验收记录](docs/PGC-VALIDATION-2026-11-21.md)。

## 快速开始

```bash
git clone https://atomgit.com/2501_93573368/ohos_ChimeraX.git
cd ohos_ChimeraX
bash scripts/verify.sh --local       # 本地单元测试，无需 DevEco 或设备
bash scripts/verify.sh --build-only  # 使用仓库内运行时构建 HAP
bash scripts/verify.sh               # 本地测试 + 构建 + 模拟器验收
```

环境要求、HAP 安装与常见问题见 [OpenHarmony 中文指南](README.OpenHarmony_CN.md)；技术设计与历史记录见 [文档索引](docs/README.md)。

## 目录

| 路径 | 内容 |
| --- | --- |
| `app/` | DevEco 工程、ArkUI 页面、N-API 桥与打包所需原生库、运行时 |
| `harmony/`、`patches/`、`*.lock.json` | 平台源码、适配补丁与版本哈希锁定 |
| `vendor/`、`snippets/` | 兼容垫片与探针样例 |
| `scripts/`、`tools/`、`tests/` | 验证入口、构建与诊断工具、单元测试 |
| `docs/`、`reports/` | 设计说明、阶段总结与验收证据 |

## 许可证

见 [UCSF ChimeraX Non-Commercial Software License Agreement](LICENSE.md)。商业使用需另行签订协议；分发上游软件或其衍生改动前须核对许可范围，并在条款要求时取得 UCSF 书面许可。此仓库不代表 UCSF 官方发布。
