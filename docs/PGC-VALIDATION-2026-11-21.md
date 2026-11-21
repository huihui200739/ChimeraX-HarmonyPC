# PGC 验证记录（2026-11-21）

本文件记录当前可交付形态的能力边界与验证方式，供验收方核对。

## 一、环境

| 项 | 值 |
|---|---|
| 设备 | HarmonyOS PC 模拟器（2in1，aarch64），`127.0.0.1:5555` |
| 系统 | OpenHarmony 6.1.1 / API 24 |
| 上游 | UCSF ChimeraX v1.11.1（`60235d3`） |
| 引擎 | 私有 CPython 3.11.18（`Clang 15.0.4` 构建） |
| 包名 | `com.example.chimeraxharmony` |
| HAP | `build/hap/entry-default-unsigned.hap` ≈155 MB |

## 二、验证方式

```bash
python3 -m unittest discover -s tests      # 132 个本地用例
python3 tools/device_app_check.py         # 27 项设备断言，收据写入 reports/
bash scripts/verify.sh                    # 以上两件事的封装（加构建）
```

## 三、通过项（设备实测）

1. 私有 CPython 3.11.18 启动并暴露 ChimeraX v1.11.1
2. EGL 上下文被 ChimeraX 接管，GLES 在原生表面上应答
3. `chimerax.core` / `commands` / `session` / `toolshed` 可用
4. atomic 模型层可建结构（`AtomicStructure`、残基、链）
5. 真实 PDB（1322 原子）与 SDF（48 原子）可读
6. 结构可视化：按元素着色、成键、球体着色、景深、视图旋转/缩放/重置
7. 打开/保存往返（`saved=4`）
8. 52 条命令注册，命令面板可列可执行
9. 14 个 bundle C 扩展加载（`map-ext:ok`）
10. 原版图标、菜单栏与工具栏

## 四、未通过项（含精确定位）

| 项 | 状态 | 卡点 |
|---|---|---|
| ChimeraX 官方渲染器出图 | ✗ | ctypes GL 门面全链路可用（程序创建/着色器编译/链接均成功），但 `lighting_block` 不在活动块中：`translate_shader_to_gles()` 未做真正的 GLSL 330→ES 300 方言翻译 |
| Qt 原生窗口 | ✗ | 运行时拒绝对 Qt 插件所需的表达式求值（`LocalStorage.makeNewLocalStorage()`），四条路径日志见 `docs/qt-status-2026-11-18-final.md` |
| `_surface` 三角化 | 降级 | GLU 用桩实现，封盖三角形为空；其余网格计算（连通性/法线/面积）真实可用 |
| 依赖 UI 部件的命令（如 `mlp`） | ✗ | 无 GUI 的最小会话缺少 UI 对象（`register_available_commands`） |

## 五、结论

当前形态是**引擎可用 + 结构可视化可用 + 界面接近原版**的适配版本（T0/T1 能力见 README）。
"官方渲染器出图"与"Qt 原生窗口"是两项已定位但尚未完成的独立工程。
