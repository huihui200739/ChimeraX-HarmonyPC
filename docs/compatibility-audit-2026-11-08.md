# 2026-11-08 通用兼容性审查

## 1. 范围与当前状态

仅分析通用构建元数据、启动器构建配置及平台基础设施；检测程序不导入 ChimeraX，不读取数据、不运行上游测试或专业模块。

阶段状态：

- [x] 找到并核实官方源代码入口。
- [x] 选定可复查的版本基线，记录元数据哈希。
- [x] 盘点本机 SDK、连接目标和运行环境。
- [x] 编译并在目标临时运行独立的通用原生检测程序，核验清理结果。
- [x] 编写独立空白 Qt 窗口检查程序；本机实际执行被缺少运行环境阻断。
- [ ] 在目标落实适用的 Python、Qt 和 Python Qt 绑定。
- [ ] 在目标打开 Qt 空白窗口并验收通用交互。
- [ ] 上游应用的通用安装包、启动入口及空白界面验收。
- [ ] 实体鸿蒙 PC 验收。

**没有“适配完成”“应用已启动”或“界面已通过”的结论，也没有生成替代应用冒充移植成果。**

## 2. 上游身份与版本基线

官方仓库：https://github.com/RBVI/ChimeraX

选定版本：`v1.11.1`；固定提交：`60235d303c18f72c6ebd45a620b540ba84825994`。这只是本次选用的已存在版本标签，不声称是最新分发版本。提交时间为 2026-01-23（UTC）。

只在读取时获取公开构建元数据，交付目录没有复制上游源码、模块或数据集。源文件 Git blob SHA 与 SHA-256 记录在：

`/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/upstream.lock.json`

## 3. 许可证需要先行核实

上游 `License.md` 标为自定义非商业许可，包含用途及分发限制。公开源代码不能直接推断为可自由修改并对外发布的 MIT/Apache 授权。后续商用、发布修改版或上传分发包前，应向权利人核实适用授权；本记录不构成法律意见。本次没有分发原软件或修改版。

原始条款：https://github.com/RBVI/ChimeraX/blob/60235d303c18f72c6ebd45a620b540ba84825994/License.md

## 4. 通用构建链发现

| 固定版本中的配置 | 直接观察 | 影响 |
|---|---|---|
| `mk/detectOS.make` | 识别 Linux、Darwin、Windows；Linux 用 uname 和发行版参数继续分支 | 当前目标的 uname 返回 Linux，会进入 Linux 分支，而不是得到原生鸿蒙支持 |
| `mk/config.make` | Python 主次版本固定为 3.11 | 本机 Python 3.14 不能自动代替原应用的 Python ABI |
| `prereqs/PyQt/Makefile` | 默认 Qt 基线 6.9.2 | 不可直接套用别的 Qt 主次版本的鸿蒙说明后宣称完成 |
| `prereqs/PyQt/Makefile.wheel.qt6` | Linux ARM64 使用 manylinux 平台标签，并依赖 PyQt6 和 WebEngine | CPU 相同不证明 wheel、插件、系统窗口与加载环境适用 |
| `src/apps/ChimeraX/Makefile` | 启动器连接 Python，安装和动态库路径按既有平台处理 | 增加安装包外壳不能替代运行时和启动器适配 |

以上仅为源代码静态观察，没有执行上游构建或测试。各文件的固定提交链接见版本校验记录。

## 5. Qt 官方说明的适用边界

本次查到的官方 Qt 6.12 文档列有 HarmonyOS 6.0/6.1、ARM64 和其相应 SDK，并将支持标为技术预览。它提供平台移植方向，但不证明上游默认 Qt 6.9.2 已具备相同支持，也不证明 PyQt6/PySide6 或 Qt WebEngine 在当前目标上可用。不要混淆 Qt C++ 平台支持与 Python 绑定支持。本次未尝试跨版本替换。

官方文档：https://doc.qt.io/qt-6/harmonyos.html

## 6. 真实环境与运行结果

完整证据：

- `/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/environment-2026-11-08.json`
- `/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/native-loader-2026-11-08.json`
- `/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/qt-host-2026-11-08.json`

目标明确报告 `model=emulator`，`device_type=2in1`，`architecture=aarch64`，`system_version=OpenHarmony-6.1.1.125`，API 24。这是模拟器，不是实体鸿蒙 PC。

当前 SDK 成功编译自有 C 检测程序，启用 `-Wall -Wextra -Werror`。通过 hdc 临时发送并执行，收到可解析的 JSON；随后删除该唯一名称的临时文件，并核验文件不存在。未安装 HAP、未启动 ChimeraX、未改变现有应用或系统设置。

独立检测程序在自己的默认加载环境中：

- 成功加载查询的 `libc.so.6`、`libEGL.so`、`libGLESv3.so`。
- 未成功加载查询的 `libGL.so.1`、Python 3.11、Qt6 Core/Gui/Widgets/WebEngine 库名。
- `command -v python3` 无输出；这只说明当前 PATH 未观察到该命令。

**限制：**未遍历应用私有目录，不能断言整台设备没有 Python 或 Qt。某个库名可加载也不能证明完整 ABI 兼容。EGL/GLES 可加载不等于桌面 OpenGL 上下文、系统窗口或 Qt 界面可用；未测试图形上下文。单个原生程序可执行不等于应用可启动。

开发机的 Qt 空白窗口检查实际以退出码 2 阻断：当前 Python 无 PyQt6。报告明确为 `blocked_missing_runtime`，没有转成通过结果，也没有尝试以假界面替代原应用。

## 7. 下一阶段验收顺序

1. 明确实际设备版本与授权范围，并确定目标 Python/Qt/Python 绑定的来源和版本组合。
2. 先做独立通用运行环境加载验证；原生运行库与 Python 扩展须来自适用目标平台，不以主机结果代替。
3. 在目标执行空白 Qt 窗口检查，人工验收中文输入、键鼠、尺寸、缩放、菜单和文件选择器。
4. 必要时分别验证空白桌面 OpenGL 上下文和通用内嵌页面运行环境，不加载项目数据。
5. 前述条件具备后，才进入原应用通用启动入口、安装/卸载和打包环节。
6. 实体鸿蒙 PC 上独立记录验收结果。始终不扩展到专业科研功能或相关数据流程。
