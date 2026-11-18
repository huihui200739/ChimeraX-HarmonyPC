/*
 * snippets/qt-ohos/QtUtils.ets
 *
 * 目标位置: app/entry/src/main/ets/qability/QtUtils.ets  (新文件)
 *
 * 上游 templates 版本还注册了 'LocalStorage' 与 'QEmbeddedComponentCreator'
 * (templates/entry/src/main/ets/qability/QtUtils.ets)。这两项只在 Qt Quick /
 * QEmbeddedComponent 场景被 Qt 侧按名字抓取；ChimeraX 是 Widgets 应用，不加载
 * QML，因此 modulesFactories 返回空表即可 —— makeJsModulesFactoriesMap()
 * (qohosjsmain.cpp:852) 对空对象是安全的循环零次。
 *
 * 若后续要跑 Qt Quick(比如某个 bundle 用 QQuickWidget)，再按 templates 补齐：
 *   factories['LocalStorage'] = getLocalStorageTsInterface;
 *   factories['QEmbeddedComponentCreator'] = getQEmbeddedComponentCreatorTsInterface;
 */

export default class QtUtils {
  static getModulesFactoriesMapForQt(): object {
    return {};
  }
}
