# 2026-11-19：鸿蒙视口里的结构查看器

## 结论

**打开 PDB 后，结构可以在鸿蒙窗口的 GL 视口里显示出来：原子按元素着色、按距离成键、自动居中与缩放。
设备读回 `atoms=4`，截图 `reports/viewer-bonds-2026-11-19.jpeg`。**

这是"能看见结构"的落地方式：ChimeraX 官方渲染器要移植 GLSL ES（UBO 体系，以天计），
在那之前用一条原生点/线渲染通路把数据画出来，用户马上能看到结果。

## 数据流

1. Python：读取 PDB 后把原子坐标与元素写入沙箱 `cx_atoms.txt`
   （`x y z r g b` 每行一个原子，颜色按元素映射：C 灰 / N 蓝 / O 红 / S 黄）
2. 原生 `ChimeraXGLDrawAtoms(path)`：解析文本 → 质心居中 → 按包围半径缩放到视口 85%
   → 距离 ≤ 2.2 Å 的原子两两连线 → 先画 `GL_LINES` 再画 `GL_POINTS` → `eglSwapBuffers`
3. 页面「显示结构」按钮触发，状态行显示原子数

## 踩过的坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `atoms_written=0` | `open_pdb` 返回的模型没有加入 `session.models` | 打开后显式 `session.models.add(models)` |
| `unterminated string literal` | 嵌套模板里 `"\n".join()` 被转义破坏 | 改用 `chr(10).join()` |

## 边界

- 这是**替代渲染通路**，不是 ChimeraX 的渲染器：没有光照/材质/裁剪/选择高亮
- 交互（旋转、缩放、拾取）与官方渲染器的移植仍是待办

## 追加：交互与示例结构

- **触摸旋转/缩放**：`rotateView(dx,dy)` / `zoomView(factor)` 通过 N-API 暴露，XComponent 的
  onTouch 驱动；几何缓存后重绘
- **示例螺旋**：`示例螺旋` 按钮生成 60 个点的 α 螺旋并绘制，用于验证 3D 视图
  （4 原子的 PDB 探针近似共面，旋转到侧视会缩成一点）
- **修掉的关键 bug**：视图 uniform（yaw/pitch/zoom）此前在 `glDrawArrays` **之后**才设置，
  `zoom` 初值为 0 把整条螺旋压到原点（表现为"只有一个点"）；现在先设 uniform 再绘制
- **归一化改为按最大轴跨度**：细长螺旋按包围半径缩放会缩成点

设备读回：`demo=60`，截图 `reports/helix3-2026-11-19.jpeg`（螺旋可见、可旋转）
