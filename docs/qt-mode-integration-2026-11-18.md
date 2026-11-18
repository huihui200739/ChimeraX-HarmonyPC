# 2026-11-18：Qt 窗口模式的代码与部署已进工程

## 当前结论

**`libqohos` 交接代码、`libchimeraxqt.so`（导出 `main`）、Qt 6.12 运行时与 PySide6 绑定
全部进入 HAP（147 MB），探针模式仍 26/26 全过；Qt 窗口模式通过沙箱标志文件切换，可随时验证。**

## 集成内容

| 项 | 位置 | 说明 |
|---|---|---|
| Ability 双模式 | `app/entry/src/main/ets/entryability/EntryAbility.ets` | 读取沙箱 `qt-mode.flag`：有 → 走 `qpa.handleAbilityOn*`（Qt 自己 loadContent `pages/MainWindowNativeNode`）；无 → 现有探针页 |
| Qt 窗口页 | `app/entry/src/main/ets/pages/MainWindowNativeNode.ets` | 文件名由 Qt C++ 写死，不能改名 |
| 启动参数与工厂表 | `app/entry/src/main/ets/qabilitystage/QAbilityStage.ets`、`qability/QtUtils.ets` | `setupQtApplication({appContext, modulesFactories, appName, appArgs, abilityClassName, _unusedQChildProcess})` |
| 类型声明 | `app/entry/src/main/qt/libqohos.d.ts` + `oh-package.json5` | `import qpa from 'libqohos.so'` |
| 应用入口 .so | `app/entry/src/main/cpp/qt_launcher.cpp` | 导出 `main`，内部拉起 CPython（Qt 要求 `dlsym(handle,"main")`） |
| 部署 | `tools/stage_qt_deploy.py` | 拷 `libqohos.so`、11 个 `libQt6*.so`、`libc++_shared.so`、PySide6 绑定到 `app/entry/libs/arm64-v8a`（17 个文件） |

## 编译期踩的坑（都修了）

1. `OH_LOG_VPrint` 在本 SDK 的 hilog 头里不存在 → 改成 `vsnprintf` + `OH_LOG_Print`
2. ArkTS 禁止无类型对象字面量（`arkts-no-untyped-obj-literals`）→ 用显式声明类型
3. ArkTS 禁止索引签名（`arkts-no-indexed-signatures`）→ 空工厂表用声明类实例
4. `object` 不能赋给 `Record<string, Function>` → 对齐 `libqohos.d.ts` 的参数类型

## 证据

- 设备收据：`reports/device-app-2026-11-18.json`（26/26，探针模式）
- 部署清单：`reports/qt-deploy-2026-11-18.json`（copied=17，missing=0）
- 交接说明（子代理）：`snippets/qt-ohos/README.md`、`docs/qt-glue-2026-11-18.md`

## 下一步（Qt 窗口真正起来）

1. 页面点「启用 Qt 窗口模式」→ 重启应用 → 看日志：
   - `CX_QT_MODE true`、`setupQtApplication` 相关输出
   - 失败特征：`Could not find the Qt platform plugin "ohos"`、`dlopen() failed`、`unsupported OHOS version`
2. `qt_launcher.cpp` 目前是 probe 阶段（起窗口并打印 `platformName`/`Qt 版本`）
3. probe 通过后接到 `chimerax.ui.gui_start()`，让 ChimeraX 主窗口接管
