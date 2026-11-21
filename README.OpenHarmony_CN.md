# ChimeraX × OpenHarmony PC 适配（中文说明）

UCSF ChimeraX v1.11.1 的 OpenHarmony 6.1.1 / API 24（aarch64）移植。

## 形态

ArkTS 应用外壳 + 内嵌私有 CPython 3.11.18 运行 ChimeraX 引擎；界面复刻原版（原版图标/菜单/工具栏）。

## 能力

- **T0 完全可用**：引擎启动、numpy、52 条命令、PDB/SDF 读取、结构可视化、交互、打开/保存、原版外观
- **T1 可用但有降级**：14 个 bundle C 扩展（`_surface` 用 GLU 桩）、示例结构内置
- **T2 尚不可用**：官方渲染器出图（需 GLSL 330→ES 300 翻译层）、Qt 原生窗口、真实三角化

## 验证

```bash
python3 -m unittest discover -s tests   # 132 用例
python3 tools/device_app_check.py       # 27 项设备断言
bash scripts/verify.sh                  # 构建 + 验证一条命令
```

详细验证记录见 `docs/PGC-VALIDATION-2026-11-21.md`。

## 许可证

遵循上游 UCSF ChimeraX 许可证（学术/商业使用条款见上游 `LICENSE`）。
