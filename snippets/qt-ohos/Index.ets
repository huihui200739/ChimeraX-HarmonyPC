/*
 * snippets/qt-ohos/Index.ets
 *
 * 目标位置(名字是硬约束, 不能叫 Index.ets):
 *   app/entry/src/main/ets/pages/MainWindowNativeNode.ets
 *
 * 为什么名字不能改:
 *   qohosjsmain.cpp:1355
 *     const std::string mainWindowNativeNodePagePath = "pages/MainWindowNativeNode";
 *     windowStage.loadContent(mainWindowNativeNodePagePath, localStorage)
 *   页面路径是 C++ 里的字符串常量, 并且 LocalStorage 也由它注入。所以"最小页面"
 *   就是 Qt 要求的那张页, 你自己写的 Index.ets 不会参与 Qt 窗口路径(它可以留着
 *   当探针页, 但 Qt 模式启动时被 loadContent 顶掉)。
 *
 * 契约(三项必须完全一致, 错一项就是空白窗口或 abort):
 *   1. XComponent({ type: XComponentType.NODE, libraryname: 'qohos' })
 *      - NODE 不是 SURFACE: NODE 走 arkui native node 挂载(XComponentRegistry 只
 *        接受 __nnMainWindow_/__nnSubWindow_/__nnFloatWindow_ 前缀, 见
 *        qarkui/qxcomponentregistry.cpp:71-76; RenderXComponent_ 前缀被拒)。
 *      - libraryname 是 napi 模块名 'qohos'(= libqohos.so 的 nm_modname,
 *        qohosjsmain.cpp:1928), 不是 'libqohos.so' 也不是 .so 路径。
 *   2. id 取 LocalStorage 里的 createInfo.xComponentId
 *      Qt 侧算出的值是 "__nnMainWindow_" + qAbilityInstanceId
 *      (render/qxcomponent.cpp:13,57)。
 *   3. onAttach 必须透传: 它触发 handleStartedUiInstance(), Qt 拿到 window stage
 *      后才创建 QWindow。漏了它 = Qt 永远不显示窗口。
 */

interface WindowNativeNodeCreateInfo {
  xComponentId: string;
  onAppear: () => void;
  onAttach: () => void;
  onDisAppear: () => void;
}

@Entry
@Component
struct MainWindowNativeNode {
  @State private createInfo: WindowNativeNodeCreateInfo | undefined = undefined;

  aboutToAppear(): void {
    const localStorage: LocalStorage | undefined = this.getUIContext().getSharedLocalStorage();
    if (localStorage) {
      this.createInfo = localStorage.get<WindowNativeNodeCreateInfo>('createInfo');
    }
  }

  build() {
    Stack() {
      if (this.createInfo !== undefined) {
        XComponent({
          type: XComponentType.NODE,
          id: this.createInfo.xComponentId,
          libraryname: 'qohos'
        })
          .onAttach(this.createInfo.onAttach)
          .onAppear(this.createInfo.onAppear)
          .onDisAppear(this.createInfo.onDisAppear)
          .width('100%')
          .height('100%')
      } else {
        // createInfo 缺失说明没走 qpa.handleAbilityOnWindowStageCreate()。
        // 这条文案出现时去看 CX_QT_WINDOWSTAGE_CREATE 日志是否回调了。
        Text('Qt window stage not provided by libqohos.so')
          .fontSize(14)
          .fontColor('#FFB4A2')
      }
    }
    .width('100%')
    .height('100%')
  }
}
