# OpenHarmony PC 适配验收记录

## 当前构建（2026-11-24）

| 项目 | 记录 |
| --- | --- |
| 适配代码基线 | [`ca3330c`](https://github.com/huihui200739/ChimeraX-HarmonyPC/commit/ca3330cfb285c1710dc8b1d7226a8a60f42f9694) |
| 上游与运行时 | ChimeraX v1.11.1（`60235d3`），CPython 3.11.18；运行时归档标签 `dec0db8c2499` |
| 环境 | OpenHarmony 6.1.1 / API 24，aarch64 2-in-1 模拟器，`127.0.0.1:5555` |
| HAP | `entry-default-unsigned.hap`，158658072 字节 |
| HAP SHA-256 | `aa7f9a5d8a9df6b2663584d09d33f96c95ecee4236a50181df0f270d55b7d112` |
| 结果 | 构建成功；模拟器安装返回空间不足 `9568288`。后续 UI 断言未执行，不能判定当前包通过。 |

证据：[运行时归档](../reports/app-runtime-2026-11-24.json) · [构建记录](../reports/hap-build-2026-11-24.json) · [设备记录](../reports/device-app-2026-11-24.json)。

## 上一版模拟器验收

[`eb33202` 的历史设备记录](https://github.com/huihui200739/ChimeraX-HarmonyPC/blob/eb3320234285413a1423caa246e08363b6a4553c/reports/device-app-2026-11-24.json)记载 **50/50**。覆盖运行时启动、结构读取、官方渲染、密度等值面、选择高亮、PNG 导出和几项面板与命令。`_surface` 耳切封盖探针中，正方形返回两个三角形；这不等于任意输入均已验证。

[界面截图](../reports/viewport-protein-density-v2-2026-11-24.jpeg)是 2026-11-24 的历史示例，展示 ArkUI 界面、蛋白卡通和密度面；未作为当前 HAP 的验收证据。

## 尚未验证

- 当前 HAP 的 PDB `save` 导出：代码和原生库已更新，需安装同一构建后复验。
- Qt 原生窗口：运行时拒绝 Qt 插件所需的 JS 求值，参见 [Qt 限制记录](qt-status-2026-11-18-final.md)。
- 未完成实体鸿蒙 PC 验收或全量桌面插件、命令兼容性验证。

## 复验

```bash
bash scripts/verify.sh --local
bash scripts/verify.sh --build-only
python3 tools/device_app_check.py --target 127.0.0.1:5555
```

新报告默认输出到 `build/reports/`。发布验收记录前，请核对 HAP SHA-256、设备环境和截图归属。
