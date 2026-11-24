# ChimeraX · 鸿蒙 PC 适配

把分子可视化软件 [UCSF ChimeraX](https://github.com/RBVI/ChimeraX) 接入 HarmonyOS PC：上游版本按 commit 固定，
适配以补丁与平台源码维护，再用 ArkUI 外壳承载界面、经 N-API 把 CPython 与 ChimeraX 引擎接进 HAP。

| 项 | 值 |
| --- | --- |
| 上游 | `RBVI/ChimeraX` @ `60235d3`（v1.11.1，见 [upstream.lock.json](upstream.lock.json)），UCSF 非商业许可 |
| 应用工程 | `app/`（HarmonyOS，DevEco/ArkTS + C++ N-API） |
| 运行时 | 内嵌 CPython 3.11.18 与 ChimeraX 引擎（`app/entry/src/main/resources/rawfile/cx-runtime.zip`） |
| 平台源码 | `harmony/`、`patches/`（补丁见 [platform-patch.lock.json](platform-patch.lock.json)） |
| 目标平台 | OpenHarmony 6.1.1 / API 24，arm64，2in1 |

## 适配成果

| 指标 | 状态 |
| --- | --- |
| 引擎与命令体系 | HAP 内启动 CPython 3.11.18 与 ChimeraX 引擎，注册原版命令表并执行内置命令 |
| 结构读取 | 官方 PDB、mmCIF、SDF 样例经原版读取器载入，模型与原子信息可读 |
| 渲染 | 官方渲染器绘制彩色蛋白卡通与密度等值面，支持旋转、缩放与选择高亮帧 |
| 图像导出 | 渲染帧导出为 PNG |

验收记录见 [docs/PGC-VALIDATION-2026-11-21.md](docs/PGC-VALIDATION-2026-11-21.md)，逐批次改动见 [CHANGELOG](CHANGELOG.md)。

## 仓库地址

| 位置 | 地址 |
| --- | --- |
| AtomGit（镜像） | <https://atomgit.com/2501_93573368/ohos_ChimeraX> |
| GitHub（开发源） | <https://github.com/huihui200739/ChimeraX-HarmonyPC> |

两份源码逐字节一致（同一 tree）。

## 能力分级

按社区惯例分三档；未覆盖项单列，不并入完成率。

| 级别 | 含义 | 本仓库覆盖 | 状态 |
| --- | --- | --- | --- |
| 基础 T0 | 能启动、能看、能读文件 | 引擎启动、PDB/mmCIF/SDF 读取、结构显示、蛋白卡通与密度等值面渲染、拖动缩放、选择高亮、PNG 导出 | 已达成（模拟器） |
| 主要 T1 | 面板、命令与保存 | ArkUI 模型/结构/体积/表面/链序列/日志面板，部分命令与表面封盖探针；PDB `save` 修复已合并但未对新 HAP 复验 | 部分覆盖 |
| 增强 T2 | 桌面端完整兼容 | 原生 Qt 窗口、桌面 GUI 与插件完整兼容、实体鸿蒙 PC 验收 | 未覆盖 |

细化说明：

- **T0**：上一版 HAP 模拟器验收 50/50，覆盖运行时启动、结构读取、官方渲染、密度等值面、选择高亮与 PNG 导出。
- **T1**：当前 HAP 已构建，但模拟器安装因空间不足（`9568288`）未通过，后续设备断言未执行；`_surface` 耳切封盖仅在正方形探针上验证。
- **T2**：运行时拒绝 Qt 插件所需的 JS 求值，当前走 ArkUI 外壳；桌面插件体系与全量命令兼容性未逐项验证。

## 目录结构

```
app/         HarmonyOS 工程（entry: ArkTS 页面 + C++ 原生库 + 打包运行时）
harmony/     平台源码与 Makefile 片段
patches/     平台/上游适配补丁
vendor/      libffi 等兼容垫片与依赖
snippets/    Qt 与探针样例
scripts/     验证入口（scripts/verify.sh）
tools/       构建、打包、设备与诊断工具
tests/       单元测试
docs/        设计、阶段总结与验收文档（索引见 docs/README.md）
reports/     小体量验证收据与截图
CHANGELOG.md 逐提交变更记录
AGENTS.md    工程约定（改动流程、证据与提交规范）
```

## 构建

前置：macOS + DevEco Studio（默认 `/Applications/DevEco-Studio.app`）、Python 3.10+、Bash；设备验收另需 API 24 的 2in1 模拟器。

```bash
git clone https://atomgit.com/2501_93573368/ohos_ChimeraX.git
cd ohos_ChimeraX

# 1) 本地单元测试（不需要 DevEco 或设备）
bash scripts/verify.sh --local

# 2) 用仓库内的原生库与运行时构建 HAP
bash scripts/verify.sh --build-only
```

打包使用仓库内已有二进制，不重新交叉编译；HAP 落在 `build/hap/`，构建报告落在 `build/reports/`。
若要重建 CPython、libffi、扩展模块或运行时归档，见 [docs/README.md](docs/README.md) 中的运行时与扩展构建记录。

## 验证

```bash
# 本地测试 + 构建 + 模拟器验收
bash scripts/verify.sh

# 或对已生成的 HAP 单独验收
python3 tools/device_app_check.py --target 127.0.0.1:5555 \
  --hap build/hap/entry-default-unsigned.hap
```

安装失败时（如 `9568288` 空间不足）脚本会停止，不会拿上一次安装的应用充当本次结果。

## 文档

- [README.OpenHarmony_CN.md](README.OpenHarmony_CN.md) — 中文构建、安装与排错指南
- [docs/README.md](docs/README.md) — 文档索引（按主题）
- [docs/PGC-VALIDATION-2026-11-21.md](docs/PGC-VALIDATION-2026-11-21.md) — 当前构建与上一版验收记录
- [AGENTS.md](AGENTS.md) — 工程约定
- [CHANGELOG.md](CHANGELOG.md) — 变更记录

## 许可

上游 ChimeraX 采用 [UCSF ChimeraX Non-Commercial Software License Agreement](LICENSE)：仅限非商业用途，
向第三方分发本体或其衍生改动前须取得 The Regents 书面许可；插件类原创扩展不受此限制。

本仓库的适配代码同样受该许可约束；`vendor/` 下第三方依赖各自保留上游许可。
此仓库不代表 UCSF 官方发布。
