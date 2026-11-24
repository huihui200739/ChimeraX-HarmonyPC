# 2026-11-09：鸿蒙 PC 通用运行环境适配

> 此文保留当日早先的 53 扩展基线记录，不是当前增强版状态。最新已在独立目录补齐 libffi / `_ctypes`，54 个扩展、89 项本地测试通过；见[最新运行依赖进度](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/libffi-runtime-2026-11-09.md)。基线记录中的 `_ctypes` 缺失和 69 项测试是当时结果。

## 本轮范围与结论

继续限于通用安装准备、启动环境和界面兼容性的基础工作。没有编译、导入或运行原应用模块，没有处理专业功能、相关数据或研究流程。

**已实际交叉编译 CPython 3.11.18 的鸿蒙 AArch64 共享运行库、53 个通用原生扩展，并整理为应用私有目录。启动程序和可嵌入引导库也已放入目录。** 这不是完整应用，也不是已经通过鸿蒙运行验收的解释器。

**模拟器留给另一个项目。本轮未执行设备连接、上传、应用启动、停止或重启操作。** 没有修改 SDK、系统 Python 或其他项目。

## 具体适配

1. **固定来源**：使用 CPython 官方仓库提交 `26badd80b6dc7786cd8fb63c3608a31f04754219`，对应源码版本 `3.11.18`。缓存归档经 SHA-256 校验。该校验值是本地记录的 GitHub 归档校验值，不冒称 python.org 发行压缩包的官方校验值。
2. **明确平台标识**：允许 `linux-ohos` 配置，并依编译器的 `__OHOS__` 宏生成 `aarch64-linux-ohos` 扩展标识；不将鸿蒙误标为 GNU/glibc 目标。当前只支持小端 AArch64 LP64。
3. **修正语言接口检测**：SDK 的 `libintl.h` 存在但没有所需 gettext 函数声明。独立编译检查失败后才关闭这组原生接口，不降低编译检查要求，不伪造接口实现。标准库纯 Python 的 gettext 内容仍保留。
4. **修正普通网络模块的构建检测**：上游对 CAN 常量的探测使用了与实际头文件检测不同的包含顺序，导致配置结果矛盾。补丁统一探测上下文，不虚构常量、不改 SDK；`_socket` 现已编译出来。这不是网络运行或系统 CAN 支持验收。
5. **限制编译占用**：除了 `make` 最多 2 个任务，还限制了上游扩展编译的独立线程池，避免其自动按全部处理器数量启动。主机构建关闭字节码写入，源码与输出分离。
6. **私有目录与可重复打包**：保留来源、补丁、配置、文件摘要和 CPython 许可证；校验符号链接。已有有效目录只验证复用，不偷偷覆盖。归档内容逐文件核验，并已连续打包复查两次。

## 实际产物

私有运行目录：

`/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/build/cpython-3.11.18/ohos-aarch64/runtime`

主要内容：

- `bin/ChimeraX`：本工程的通用启动适配器，不是完整原应用。
- `lib/libpython3.11.so.1.0` 与相对符号链接：真实交叉编译运行库。
- `lib/libcx_harmony_bootstrap.so`：后续原生窗口生命周期接入可用的引导接口；目前未接入 Qt Ability。
- `lib/python3.11/`：来自固定 CPython 源码的标准库及 53 个已编译扩展，包括 `_socket`、`_json`、`_struct`、`unicodedata`、`math`、`select`、`zlib` 等。
- `runtime-manifest.json` 与许可证：来源、摘要、缺失项及未进行设备验证的声明。

文件摘要记录 913 个普通文件，合计 41,124,667 字节；另有清单自身与相对符号链接。上游示例扩展 `xxlimited`、`xxlimited_35` 不放入目录。

仅供后续设备测试使用的通用运行环境归档：

`/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/build/runtime-payload/cx-generic-runtime-3.11.18-aarch64-ohos.tar.gz`

- 压缩后 16,959,203 字节。
- SHA-256：`57668296daa2d09578bfbb8b5d4084d6173e476a91ddf5197eca6cb6eabcb38e`。
- **不是 HAP，不包含原应用或 Qt，也不是可交付的完整安装包。未发布或分发。**

## 验证结果与边界

| 检查 | 本轮真实结果 | 尚不能说明什么 |
|---|---|---|
| 本地交叉编译 | CPython 运行库、53 个扩展、启动器和引导库产出并通过 AArch64 ELF 检查 | 不能说明设备可加载或接口完整可用 |
| 已有运行目录复用 | 输入来源及全部文件摘要验证后复用，保留原产物 | 不承诺含构建时间的 CPython 重新链接后逐字节相同 |
| 运行目录依赖 | 本地 ELF 记录为运行库依赖 `libc.so`，扩展另涉及 `libz.so` | 不证明设备默认加载命名空间开放这些库 |
| 主机真实引导 | macOS CPython 3.11.17，中文/空格目录、隔离模式和 UTF-8 检查通过 | 不是鸿蒙 CPython 3.11.18 运行结果 |
| 本地测试 | 69 项通过，0 失败、0 错误、0 跳过 | 测试含明确标注的合成夹具，不是上游功能测试或设备测试 |
| 归档核验 | 字节摘要与相对链接校验通过，重复生成一致 | 不是安装或应用启动验收 |
| 鸿蒙运行、Qt 窗口、HAP | 均未验证 | 不得表述为完整移植完成 |

主机构建解释器是 3.11.17，目标源码是 3.11.18。固定源码的 `configure` 实际检查主机解释器的主/次版本 `3.11`；没有修改或冒充版本来绕过检查。

## 明确缺失的部分

下列可选扩展尚未提供：

`_bz2`, `_ctypes`, `_curses`, `_curses_panel`, `_dbm`, `_gdbm`, `_hashlib`, `_lzma`, `_sqlite3`, `_ssl`, `_tkinter`, `_uuid`, `nis`, `readline`, `spwd`。

其中 `_ctypes` 因目标 libffi 头文件缺失未编译成功，其余具体分类见构建报告。上游 `make` 可能在可选扩展失败时仍返回成功，因此本工程额外读取扩展构建总结，并强制检查一组通用必需模块，不能只看退出码宣称标准库完整。

仍需完成：目标运行检查；缺失通用依赖的补齐；Qt、Python Qt 绑定与 HarmonyOS Ability/主线程生命周期接入；通用窗口、缩放、字体和键鼠检查；签名安装包及安装/卸载验证；实体 PC 验收。原应用修改版的发布授权问题仍需独立核实。

## 本地复查（均不使用设备）

以下命令只使用工程内已有源码缓存和独立主机解释器，不自动下载、不安装全局组件：

```sh
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/build_cpython_harmony.py'
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/package_generic_runtime.py'
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/check_host_embedding.py' \
  --python-home '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/build/host-python/cpython-3.11.17-macos-aarch64-none'
python3 -m unittest discover -s '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tests' -v
```

源码与补丁检查发现未知改动时会保留文件并停止，而不是清理用户文件。最初失败尝试的对象文件、旧运行目录和生成的字节码已保存在本工程的 `build/` 下，不改动其他项目。

## 文件与证据

- [通用运行环境构建工具](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/build_cpython_harmony.py)
- [运行环境归档工具](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/package_generic_runtime.py)
- [CPython 平台与构建检测补丁](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/patches/0002-cpython311-ohos-triplet.patch)
- [源码来源与摘要](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/runtime-sources.lock.json)
- [补丁前后摘要](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/runtime-patch.lock.json)
- [本地交叉编译报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/cpython-local-2026-11-09.json)
- [归档核验报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/runtime-archive-2026-11-09.json)
- [本地测试报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/unit-tests-2026-11-09.json)
- [主机真实引导报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/host-embedding-2026-11-09.json)

所有通过结论均限于报告实际记录的层次；本轮报告的设备接触、目标运行和完整移植验证标志仍为 `false`。
