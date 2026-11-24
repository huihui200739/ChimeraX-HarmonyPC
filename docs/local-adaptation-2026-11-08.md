# 第二轮：本地源码与启动适配（2026-11-08）

## 本轮执行边界

用户说明另一个窗口正在使用模拟器。因此本轮不连接设备、不调用 hdc、不启动/关闭模拟器、不安装或卸载应用。第一轮的模拟器报告仅保留为历史记录，不代表本轮重新验收。全部改动与构建均在当前独立工程中完成。

## 实际完成的适配代码

### 1. 显式鸿蒙目标选择与构建配置

补丁：

`/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/patches/0001-harmony-platform.patch`

基线仍是固定的上游提交 `60235d303c18f72c6ebd45a620b540ba84825994`。补丁只涉及三个通用构建文件和一个新增的通用构建配置：

- 显式 `CX_TARGET_PLATFORM=harmonyos` 选择 `HarmonyOS / HarmonyArm64`，不把开发机 macOS 或目标系统的 Linux 内核视为平台兼容证明。
- 默认 `host` 分支保留原有平台行为；目标拼写错误和未配置的架构明确报错，不回退到宿主机。
- 使用原生 SDK 的 Clang、sysroot、归档工具和目标三元组；不沿用宿主机编译器、Linux gold 链接器或 manylinux 预编译包。
- 安装目录候选改为私有的 `ChimeraX.harmony/bin`、`lib` 布局，而非 macOS `.app/Contents` 布局。
- 不把 GLES 伪装成桌面 OpenGL；图形后端仍需单独落实。
- 完整上游构建仍被明确阻断，避免现有安装配方在开发机运行目标 Python 或抓取不适用的二进制依赖。此补丁没有宣称完整交叉构建已经可用。

补丁已在本地的固定版本通用元数据副本中应用并验证。应用工具会校验原始文件和补丁哈希，发现用户改动或已有新增文件时停止，不覆盖。

校验记录：

`/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/platform-patch.lock.json`

### 2. 私有运行环境启动适配器

源文件：

- `/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/harmony/bootstrap.c`
- `/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/harmony/bootstrap.h`

它是真正可编译的启动代码，不是绘制一个替代界面的空壳：

- 从自身安装位置推导私有运行目录，或接受明确指定的运行目录。
- 从私有目录加载 CPython 3.11，检查 ABI 和标准库，不回退到系统/开发机 Python。
- 使用公开 CPython 3.11 入口，保留原应用 `chimerax.core` 入口、应用参数、`--debug` 和退出状态。
- 正确处理 UTF-8 中文、空格和非 BMP 字符路径；无效 UTF-8 明确报错，不悄悄改写路径。
- 设置隔离模式和 UTF-8 模式；不将当前工作目录作为安装目录。
- 识别常见的私有 PyQt6/PySide6 插件目录，但不强制 xcb、固定缩放比例或 Chromium 特殊开关。
- 提供仅检查 Python 标准库的 `--cx-runtime-check`，不会导入应用。
- 同一实现可编译为启动程序，或导出 `cx_harmony_bootstrap` 的动态库供后续平台应用集成；一个进程仅支持一次调用，需由调用方落实主线程和生命周期约束。

使用的是针对 CPython 3.11 的公开旧式初始化入口。Python 官方已将部分 setter 标为弃用，因此实现会拒绝其他主次版本，不把这套代码当成可直接适配 Python 3.12+ 的通用方案。后续升级应迁移到新的初始化配置接口。

### 3. 本地构建产物

- `/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/build/harmony-local/ChimeraX`
- `/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/build/harmony-local/libcx_harmony_bootstrap.so`

两个文件均使用当前鸿蒙 SDK 交叉编译，并经 SDK 的 ELF 工具确认是 AArch64 目标文件；启用警告即错误及未定义链接符号检查。**它们只是启动适配层，不含 Python、Qt、原应用模块或安装包，不应作为可运行的完整 ChimeraX 交付。**

构建报告：

`/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/local-build-2026-11-08.json`

## 本轮验证与证据边界

1. 本地单元与集成测试共 40 项通过，覆盖平台选择、宿主分支保留、目录、参数、调试选项、退出状态、私有插件路径、缺失运行库与版本不匹配处理。
2. 参数行为测试使用明确标注的合成 CPython API 库，不冒充真实解释器。
3. 另外单独使用真实的 **macOS CPython 3.11.17** 检查公开入口、私有 Python home、中文/空格路径、隔离和 UTF-8 模式，实际通过。此运行时仅装在本工程 build 目录，没有更改系统默认 Python、PATH 或注册全局命令；只执行标准库检查，没有导入上游应用。
4. 该主机测试不代表目标平台 Python 已可用。测试用的 3.11.17 不作为正式目标运行时版本建议或部署包。
5. 本轮没有目标运行、GUI 或安装验收；未提供任何新的“鸿蒙启动成功”结论。

证据：

- `/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/tests-local-2026-11-08.json`
- `/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/host-embedding-2026-11-08.json`
- `/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/platform-patch-2026-11-08.json`

## 本地复现（均不使用模拟器）

交叉编译启动适配器：

```sh
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/build_harmony_local.py'
```

或：

```sh
make -f '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/harmony/Makefile'
```

已有固定版本源码时，先只检查补丁；需要应用时才增加 `--apply`。以下路径是本工程本地元数据缓存，不是完整上游源码：

```sh
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/apply_platform_patch.py' \
  --source-root '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/build/upstream-baseline'
```

不运行上游测试，只运行独立兼容性测试：

```sh
python3 -m unittest discover \
  -s '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tests' -v
```

## 还没有完成的部分

- 目标平台适用的 CPython 3.11、标准库和扩展模块；本次产物没有附带这些内容。
- 目标 Qt、Python Qt 绑定与必要的通用界面组件。
- HarmonyOS 的 Qt Ability 接入、窗口事件与主线程生命周期；裸 ELF 可编译不能代替原生窗口接入。
- 完整应用构建、原生签名安装包、实际安装/卸载和界面验收。
- 实体鸿蒙 PC 验收，以及修改版发布授权核实。

后续继续以上通用平台工作，不扩展到专业功能、相关数据或研究流程。

## 一手资料

- Python 3.11 初始化公开接口：https://docs.python.org/3.11/c-api/init.html
- Python 3.11 初始化配置及预初始化边界：https://docs.python.org/3.11/c-api/init_config.html
- Qt 的鸿蒙平台说明：https://doc.qt.io/qt-6/harmonyos.html
- 本次固定的上游通用构建配置：见版本校验记录和补丁校验记录。
