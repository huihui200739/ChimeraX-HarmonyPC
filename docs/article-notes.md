# 写适配文章用的素材清单

> 面向"把 UCSF ChimeraX 完整适配到鸿蒙 PC"这篇技术文章。按叙事顺序排列：
> 为什么难以移植 → 如何破局 → 现在能做什么 → 还差什么。

## 一、开篇可用的成品图（建议做头图）

| 图 | 说明 |
|---|---|
| `reports/viewport-protein-density-v2-2026-11-24.jpeg` | **头图首选**。完整界面：结构信息面板、体积/表面面板、日志面板、模型面板，视口内 **橙色螺旋卡通蛋白 + 灰色密度等值面**，768×768，`lit=36498/589824` |
| `reports/molecule-768-2026-11-23.jpeg` | 官方渲染器绘制整条 RAS 蛋白卡通表示（无可视面板，纯渲染质量展示） |
| `reports/molecule-lighting-2026-11-22.jpeg` | 早期"彩色分子"里程碑（512²） |

## 二、技术难度：三个"不可能"与破解方式

### 1. 图形栈：PyOpenGL 在 OHOS 上静默返回 0
- 现象：`glGenBuffers` 等返回 0，VBO 无效，绘制被跳过
- 破局：`vendor/graphics/_cxgl.py` —— ctypes 直连 `libGLESv3.so`，把 PyOpenGL 的调用重定向到门面
- 配图：`reports/big-update-2026-11-22-official-render-geometry.jpeg`（诊断面板：`calls=glAttachShader:6,glBindBuffer:114…`）

### 2. 渲染链路上七个串联缺陷（文章技术核心）
1. `glAttachShader` 未委托 → 程序链接后没有着色器
2. `vertex_colors` 必须是 uint8（float alpha=1.0 被判全透明）
3. `_cxgl_sigs.py` 签名表从未随包分发
4. 参数统一包 `c_int` → `c_long`/`c_void_p` 全部失配
5. 缓冲区/属性/统一变量走 PyOpenGL → 返回 0
6. 渲染前未 `view.draw()`；FBO 存储调用未委托
7. `AtomsDrawing.colors` 未填充（原子球用 `colors` 而非 `vertex_colors`）

### 3. 私有 CPython + C++ 扩展
- 交叉编译 15 个 bundle C 扩展；C 层通过 ctypes 加载共享库（`libcxatomstruct.so`）
- GLU 缺失 → 自写耳切三角化桩（`vendor/surface_glu/glu_stub.cpp`）
- 外部依赖垫片：`vendor/distro/distro.py`（mmCIF 读取需要）

## 三、现在能做什么（每项都有设备读数）

| 能力 | 设备证据 |
|---|---|
| 引擎启动 | `CPython 3.11.18` / `ChimeraX v1.11.1` / `Session\|True\|16` |
| 命令系统 | 81 条单字命令；`mlp`/`coulombic`/`morph`/`dssp`/`rmsd`/`align`/`zone` 实测可产出结果 |
| 结构读取 | PDB 1322 原子、mmCIF、SDF |
| 官方渲染 | 768² 彩色卡通蛋白（`lit=36498/589824`） |
| 选择反馈 | `sel=120\|models=2`、`hl=1`、`selpaint=120`（画面可见） |
| 体积等值面 | 合成密度 → marching cubes → `vol=6; surf=2` → 进入渲染帧 |
| 图像导出 | `ImagePacker` → PNG，`png=93742` |
| 界面面板 | 模型面板、结构信息、体积/表面、日志、命令行补全、菜单五项 |

## 四、还差什么（诚实收尾，体现工程判断）

| 缺口 | 根因（已定位） |
|---|---|
| Qt 原生窗口 | 运行时拒绝对 Qt 插件所需的 JS 表达式求值（四条路径有日志，见 `docs/qt-status-2026-11-18-final.md`） |
| `save` 结构导出 | `_pdbio` 捕获 `pyinstance::PyAttrError`，实际抛 `NoPyAttrError`（C++ 异常层级不一致），进程 abort |
| ~~`_surface` 耳切~~ | **已修复**：构建时用内联耳切实现替换 `gluTess*`，设备实测正方形 → 2 个三角形（`tess=2`） |
| 更多工具面板 | Sequence / Rotamers 尚未实现 |

## 五、可复现命令

```bash
python3 -m unittest discover -s tests    # 137 个本地用例
python3 tools/device_app_check.py        # 47/48 项设备断言（收据在 reports/）
bash scripts/verify.sh                   # 一次跑完
```

## 六、数据规模

- payload 5767 文件，HAP ≈ 158 MB
- 渲染帧 768×768（可调），PNG 导出约 90–100 KB
- 每轮改造耗时：构建 ≈13–20 min + 设备验证 ≈4 min
