# 2026-11-09：通用运行环境补齐 libffi / ctypes

## 当前结论

**已补齐私有 libffi，并在独立构建配置中编译出 CPython `_ctypes`：通用原生扩展从 53 个增至 54 个。89 项独立本地测试通过。**

这仍是通用运行依赖的本地交叉编译成果，**没有在鸿蒙设备运行 Python、导入 `_ctypes` 或验证回调**；不是完整应用、Qt 窗口或 HAP 安装验收。本轮未导入原应用或使用专业功能、数据与研究流程。

另一项目仍处于活动状态，尚未确认释放模拟器。本轮不连接、不上传、不启动或关闭任何设备应用，不改共享 SDK、系统 Python 或其他工程。

## 实际修改

1. **新增独立 libffi 构建工具**：固定 `3.8.0` 官方发行源码归档，实际下载摘要与官方 GitHub 发行资产的 SHA-256 字段一致。版本由归档中的 `configure` 再次核验；README 首行仍写旧版本，未将其当成版本依据。来源、标签对象和提交记录在 [来源锁定文件](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/libffi-sources.lock.json)。构建工具只使用本地缓存，不自行联网。
2. **补充平台识别**：该归档的 `config.sub` 尚不接受 `linux-ohos`。最小补丁仅增加识别，不冒称 GNU/glibc ABI，不修改 SDK 或替换系统库。
3. **构建私有静态依赖**：使用鸿蒙 SDK 的 `aarch64-linux-ohos` 目标，开启位置无关编译，最多 2 个编译任务。保留上游默认的闭包/静态跳板配置，没有为运行测试关闭系统安全检查。静态归档内 8 个对象均经本地 AArch64 ELF 检查；另有只链接、不执行的普通接口检查。
4. **新增 `with-libffi` 运行环境配置**：与原有 `baseline` 使用不同源码准备目录、对象目录、运行目录和报告。引用前逐文件校验依赖摘要及编译器身份，过滤主机头文件/库路径。基线默认行为不变。
5. **验证实际 `_ctypes` 链接**：确认 `ffi_call`、`ffi_prep_cif`、`ffi_closure_alloc`、`ffi_closure_free`、`ffi_prep_closure_loc` 在生成模块中有导出定义，不把未解析引用算成链接完成。该模块 ELF 依赖仅记录 `libc.so`，不额外依赖共享 `libffi.so`。这不证明目标加载命名空间、内存映射策略或实际回调可用。
6. **许可证、目录和归档核验**：运行目录包含 libffi 许可证。原基线运行目录、原归档和原报告均保留，按旧摘要复核未变；增强版归档两次生成摘要一致。

## 当前产物

- 私有依赖目录：`/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/build/libffi-3.8.0/ohos-aarch64/prefix`
- 增强版运行目录：`/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/build/cpython-3.11.18/ohos-aarch64-with-libffi/runtime`
- 增强版归档：`/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/build/runtime-payload/cx-generic-runtime-3.11.18-with-libffi-aarch64-ohos.tar.gz`

运行清单记录 915 个普通文件，合计 41,676,537 字节，不含清单自身与相对符号链接。归档包含清单，因此是 916 个普通文件及 1 个符号链接。

压缩后 **17,190,473 字节**；SHA-256：

```text
9c1d61293846bb3153853037e56abb3731f7927239aaee002419c7eab6ae2271
```

归档只含通用 CPython 运行环境、通用启动适配器及许可证，不含 Qt、Python Qt 绑定、原应用模块或科研数据；不是 HAP，也未发布。`_sysconfigdata` 保留交叉编译时的配置路径，不承诺在设备上重新编译扩展或安装任意第三方包。

## 检查结果与边界

| 检查 | 已确认 | 尚不能说明 |
|---|---|---|
| libffi 构建 | 目标静态归档与只链接检查通过 | 未在目标调用或验证回调 |
| CPython 扩展 | 54 个通用扩展生成；本次扩展编译失败列表为空 | 仍不是完整标准库 |
| 增量复查 | 依赖与运行目录均校验后复用 | 不承诺含构建时间的重新链接结果逐字节相同 |
| 本地测试 | 89 项通过；0 失败、0 错误、0 跳过、无资源警告 | 含明确标注的独立合成夹具，不是设备/应用测试 |
| 基线保留 | 原运行清单、libpython 和归档与此前记录一致 | 未因此增加基线设备验证结论 |
| 归档重复核验 | 两次生成摘要一致，内容逐文件匹配 | 不是安装包验收 |
| 鸿蒙运行 / Qt / HAP | 均未验证 | 不得标记为完整移植完成 |

仍缺少的可选扩展：

`_bz2`, `_curses`, `_curses_panel`, `_dbm`, `_gdbm`, `_hashlib`, `_lzma`, `_sqlite3`, `_ssl`, `_tkinter`, `_uuid`, `nis`, `readline`, `spwd`。

其中 `_sqlite3` 当前被配置禁用，其余具体分类见构建报告。`_ssl` / `_hashlib` 仍未提供，不能宣称标准库 TLS 或全部摘要算法可用。没有通过关闭证书校验、忽略依赖错误或使用主机二进制来填补缺失项。

## 本地复查方法（不使用模拟器）

```sh
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/build_libffi_harmony.py'
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/build_cpython_harmony.py' --profile with-libffi
python3 '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/package_generic_runtime.py' \
  --runtime '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/build/cpython-3.11.18/ohos-aarch64-with-libffi/runtime' \
  --output '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/build/runtime-payload/cx-generic-runtime-3.11.18-with-libffi-aarch64-ohos.tar.gz' \
  --report '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/runtime-archive-with-libffi-2026-11-09.json'
python3 -m unittest discover -s '/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tests' -v
```

前两项会重新配置并做增量编译；已有目录来源或文件摘要不符时停止并保留现场，不自动清空。默认 `build_cpython_harmony.py` 仍选择旧基线；增强版必须显式选择 `--profile with-libffi`。默认归档命令也仍针对基线，因此增强版须显式传递上面的路径。

## 证据与后续

- [libffi 构建工具](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/tools/build_libffi_harmony.py)
- [libffi 平台识别补丁](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/patches/0003-libffi-ohos-triplet.patch)
- [libffi 本地构建报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/libffi-local-2026-11-09.json)
- [增强版 CPython 构建报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/cpython-local-with-libffi-2026-11-09.json)
- [增强版归档报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/runtime-archive-with-libffi-2026-11-09.json)
- [重复归档报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/runtime-archive-with-libffi-repeat-2026-11-09.json)
- [89 项本地测试报告](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/unit-tests-with-libffi-2026-11-09.json)
- [基线保留核验](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/baseline-preservation-with-libffi-2026-11-09.json)
- [设备测试暂缓记录](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/reports/device-test-deferred-with-libffi-2026-11-09.json)
- [此前 53 扩展基线的阶段记录](/Users/huihui/Documents/鸿蒙pc适配/ChimeraX-HarmonyPC/docs/runtime-adaptation-2026-11-09.md)

下一阶段仍需：补齐剩余通用依赖；落实 Qt 与 Python Qt 绑定、HarmonyOS Ability/主线程生命周期；在确认模拟器释放后进行独立通用运行检查；随后验证空白窗口、缩放、字体与键鼠。签名安装、卸载和实体 PC 验收均未完成。原应用的修改及分发授权问题仍需单独核实。
