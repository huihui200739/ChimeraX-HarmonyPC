# 2026-11-18：Qt 窗口路径的最终状态（证据封存）

## 结论

**Qt 窗口在这台模拟器上起不来。** 工程侧该做的都做了，卡点已定位到"ArkTS 传给插件的对象在 Qt 的
JS 状态里读不到字段"这一层，并且**已有两条独立证据**：

| 尝试 | 设备日志 | 结果 |
|---|---|---|
| 默认预编译插件 | `QNapi: exception: global expression doesn't start with known module path: 'LocalStorage.makeNewLocalStorage()'` | JS 崩溃 |
| 我们重编的插件（`LocalStorageProvider` 接管） | `falling back to script evaluation of "LocalStorage.makeNewLocalStorage()"` | 三条交底路径全未命中，回落 eval |
| 交底 `modulesFactories.LocalStorage` | `loadJsModuleViaEtsFactoryOrFail(..., loading napi module 'LocalStorage' via ets factory)` → `Error: Need object` | 工厂被调到，但返回值被判非对象 |
| 交底 `localStorage: new LocalStorage()` 实例 | `falling back to script evaluation ...` | 连 `Has("localStorage")` 都没命中 |

## 根因判断

ArkTS（静态编译）把传给 napi 的对象字面量编成类实例，字段在 napi 的 `Has/Get` 与枚举下不可见；
而 Qt 插件完全依赖"按名取属性 + 枚举工厂表"。所以：
- 页面线程 `napi_run_script` 一切正常（9/9 表达式通过）
- Qt 自己的 JS 状态里，同一个 `LocalStorage` 既取不到字段、也不认 eval

## 已交付的工程产物（保留，不删）

- `libqohos.so` 自建版本：`build/qt/ohos-plugin/libqohos.so`（4.02 MB，NEEDED 与官方逐条一致），
  补丁 `patches/qt-ohos/0102-ohos-no-eval-localstorage-handoff.patch`
- 独立构建脚手架：`docs/qt-ohos-standalone-build/`（实测可复现逐字节相同的 .so）
- Qt 模式 ArkTS/native 全套：`QAbilityStage`/`QtUtils`/`MainWindowNativeNode`/`qt_launcher.cpp`
- 部署工具：`tools/stage_qt_deploy.py`（17 个原生库 + PySide6 绑定）

## 如果还要继续（给下一个接手的人）

最小验证顺序：
1. 在 ArkTS 里用 `Object.defineProperty` 或 `Map` 显式构造一个**可枚举**对象，再交给 `setupQtApplication`
2. 或改插件侧：`adopt()` 放宽到 `napi_get_all_property_names` 枚举
3. 或在 `runQtChildProcess`（无 UI）路径下先验证 Qt 核心能跑，再回到窗口路径

## 对照：探针模式（无 Qt）

`python3 tools/device_app_check.py` → **26/26 断言通过**，这是当前可交付形态。
