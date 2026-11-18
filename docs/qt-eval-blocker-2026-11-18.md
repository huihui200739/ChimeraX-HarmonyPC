# 2026-11-18：Qt OHOS 插件在模拟器上的硬阻塞（如实记录）

## 现象

Qt 窗口模式已完整接入并跑到最后一步，但停在 Qt 插件自身的一次 JS 求值上：

```
CX_QT_STAGE_ONCREATE
CX_QT_SETUP start appName=libchimeraxqt.so
setupQtApplication() - Shared libraries directory: /data/storage/el1/bundle/libs/arm64
CX_QT_MODE true
QNapi: exception: global expression doesn't start with known module path: 'LocalStorage.makeNewLocalStorage()'
```

崩溃栈指向 `libqohos.so`（`qohosjsmain.cpp:1322` 的 `jsState.eval<QNapi::Object>("LocalStorage.makeNewLocalStorage()")`），
随后 JS 崩溃，进程退出。

## 已经排除的可能

| 假设 | 结果 |
|---|---|
| 插件没被加载 | 已加载：`qohosjsmain Init begin/end`、`setupQtApplication` 正常执行、`CX_QT_MODE true` |
| 应用入口 .so 缺失/无 `main` | 已就位：`libchimeraxqt.so` 导出 `main`，`sharedLibraryName` 打印正确 |
| 平台插件找不到 | 不是：错误发生在 `loadContent` 之前，插件已运行 |
| 表达式本身写法过时（`makeNewLocalStorage` 已废弃） | 已把 `.so` 里的字符串等长替换成 `(()=>new LocalStorage())`，报错**仍是同一条**"global expression..." |
| ArkTS 静态运行时开关 | 已在 `app/build-profile.json5` 设 `"arkTSVersion": "1.1"`，报错不变 |

结论：**当前设备运行时（OpenHarmony 6.1.1 / API 24 模拟器）禁止 `napi_run_script` 求值任意全局表达式**，
而 Qt 6.12 的 OHOS 插件正是用这个机制构造 `LocalStorage`。这与插件版本无关，是运行时策略。

## 可行出路（按成本排序）

1. **重编 `libqohos.so`，把那次 `eval` 换成不依赖 eval 的路径**（我们已有 qtbase 6.12 源码与
   OHOS 交叉工具链，预编译包证明可编）。改动点集中在 `qohosjsmain.cpp:1322` 与
   `render/qohoswindowproxydatafactory.cpp:88`，可改为由 ArkTS 侧创建 `LocalStorage` 后通过
   `appStartupObj` 传入。预计 4–8 小时（含配置、编译 qtbase OHOS 目标、替换插件、部署验证）。
2. **换设备/换运行时**：真实鸿蒙 PC（非模拟器）或更高 API 版本的运行时是否放开 eval，需要实测。
3. **ArkUI 复刻界面**（不依赖 Qt）：界面元素可 1:1 复刻，但行为细节与控件体系不同，工作量大。

## 现状

- Qt 模式代码全部保留在工程内，由沙箱 `qt-mode.flag` 开关控制，不删。
- 探针模式（无 Qt）仍然 26/26 全过，是当前可交付的形态。
- `tools/patch_qohos_localstorage.py` 与 `tools/stage_qt_deploy.py` 保留（等重编插件后可继续用）。
