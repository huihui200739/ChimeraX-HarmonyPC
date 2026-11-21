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
11. **ChimeraX 官方渲染器出图**：`View.image_rgba()` 返回 512×512 RGBA 帧，
    非背景像素 `lit=26803/262144`，帧经 base64 → PixelMap 显示在 ArkUI 视口
    （截图 `reports/molecule-render-final.jpeg`）；结构目前渲染为黑色剪影

## 四、未通过项（含精确定位）

| 项 | 状态 | 卡点 |
|---|---|---|
| 结构绘制的光照着色 | ✗ | 结构以黑色剪影显示；同一 shader 下用 vertex_colors 的探针三角形着色正常，怀疑 lighting UBO 数据为零 |
| Qt 原生窗口 | ✗ | 运行时拒绝对 Qt 插件所需的表达式求值（`LocalStorage.makeNewLocalStorage()`），四条路径日志见 `docs/qt-status-2026-11-18-final.md` |
| `_surface` 三角化 | 降级 | GLU 用桩实现，封盖三角形为空；其余网格计算（连通性/法线/面积）真实可用 |
| 依赖 UI 部件的命令（如 `mlp`） | ✗ | 无 GUI 的最小会话缺少 UI 对象（`register_available_commands`） |

## 五、2026-11-22 渲染线突破记录

官方渲染器出图需要连续修复五个缺陷（缺一不可）：

1. `glAttachShader` 未委托门面 → 程序链接后没有着色器
2. `vertex_colors` 必须是 uint8 0-255（float alpha=1.0 被判为全透明）
3. `vendor/graphics/_cxgl_sigs.py` 未随包分发 → 门面没有签名表
4. 参数必须按声明类型逐位转换（统一包 `c_int` 会让 `c_long`/`c_void_p` 失配）
5. 缓冲区/属性/统一变量调用必须走门面（PyOpenGL 返回 0 → VBO/IBO 无效 → 绘制被跳过）

## 六、结论

当前形态是**引擎可用 + 结构可视化可用 + 界面接近原版**的适配版本（T0/T1 能力见 README）。
"官方渲染器出图"与"Qt 原生窗口"是两项已定位但尚未完成的独立工程。
