/*
 * snippets/qt-ohos/EntryAbility.ets
 *
 * 目标位置: app/entry/src/main/ets/entryability/EntryAbility.ets  (整文件替换)
 * 依赖:      snippets/qt-ohos/QAbilityStage.ets ->
 *            app/entry/src/main/ets/qabilitystage/QAbilityStage.ets
 *            snippets/qt-ohos/libqohos.d.ts + oh-package.json5 ->
 *            app/entry/src/main/qt/
 *
 * 事实依据(上游 Qt 6.12.0 源码, 只读引用):
 *   build/qt/src/qtbase/src/plugins/platforms/ohos/qohosjsmain.cpp:1369
 *     handleAbilityOnWindowStageCreate() -> loadWindowStageContentPage()
 *   build/qt/src/qtbase/src/plugins/platforms/ohos/qohosjsmain.cpp:1312
 *     loadWindowStageContentPage() 自己算 XComponent id、自己 loadContent("pages/MainWindowNativeNode")
 *
 * 也就是说: 窗口页由 libqohos.so 拉起, Ability 必须把生命周期原样转交给它,
 * 自己不要再调 stage.loadContent()。现有 Index.ets(GL 探针页)不参与 Qt 路径。
 */

import { UIAbility, AbilityConstant, Want, common } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';
import qpa from 'libqohos.so';
import QAbilityStage from '../qabilitystage/QAbilityStage';

const LOG_DOMAIN: number = 0x3802;
const LOG_TAG: string = 'ChimeraX';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    // 既有约定: 页面通过 AppStorage 取沙箱目录。Qt 路径下 HOME==filesDir,
    // 但探针页/脚本仍用它拼路径, 保留。
    AppStorage.setOrCreate<string>('cxFilesDir', this.context.filesDir);
    hilog.info(LOG_DOMAIN, LOG_TAG, 'CX_QT_ONCREATE want=%{public}s', JSON.stringify(want.parameters));
    // 顺序不能反: setupQtApplication 必须在任何 qpa.handleAbilityOn* 之前跑完,
    // 它负责 QOhosAppContext::init + 设置 QT_QPA_PLATFORM/QT_PLUGIN_PATH 等环境变量。
    QAbilityStage.initQtAppContextIfNeeded(this.context.getApplicationContext());
    qpa.handleAbilityOnCreate(this, want, launchParam);
  }

  onDestroy(): void | Promise<void> {
    hilog.info(LOG_DOMAIN, LOG_TAG, 'CX_QT_ONDESTROY');
    return qpa.handleAbilityOnDestroy(this);
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    hilog.info(LOG_DOMAIN, LOG_TAG, 'CX_QT_WINDOWSTAGE_CREATE');
    // 不调用 windowStage.loadContent(): XComponent 页由 libqohos.so 加载。
    qpa.handleAbilityOnWindowStageCreate(this, windowStage);
  }

  onWindowStageRestore(windowStage: window.WindowStage): void {
    qpa.handleAbilityOnWindowStageRestore(this, windowStage);
  }

  onWindowStageDestroy(): void {
    hilog.info(LOG_DOMAIN, LOG_TAG, 'CX_QT_WINDOWSTAGE_DESTROY');
    qpa.handleAbilityOnWindowStageDestroy(this);
  }

  onNewWant(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    hilog.info(LOG_DOMAIN, LOG_TAG, 'CX_QT_ONNEWWANT want=%{public}s', JSON.stringify(want.parameters));
    qpa.handleAbilityOnNewWant(this, want, launchParam);
  }

  onForeground(): void {
    qpa.handleAbilityOnForeground(this);
  }

  onBackground(): void {
    qpa.handleAbilityOnBackground(this);
  }

  onPrepareToTerminate(): boolean {
    return qpa.handleAbilityOnPrepareToTerminate(this);
  }

  onPrepareToTerminateAsync(): Promise<boolean> {
    return qpa.handleAbilityOnPrepareToTerminateAsync(this);
  }

  onContinue(wantParam: Record<string, Object>):
    AbilityConstant.OnContinueResult | Promise<AbilityConstant.OnContinueResult> {
    return qpa.handleAbilityOnContinue(this, wantParam);
  }
}

/* 若主线需要保留 native/CPython 探针入口(libchimerax_native.so 的 initializeRuntime),
 * 它和 Qt 路径互斥: 同一进程里 Py_InitializeEx 只能有一次, 而 Qt 路径的 CPython
 * 由 libchimeraxqt.so 的 main() 初始化。二者同时启用会出现
 * "Py_InitializeEx failed" 或段错误。取舍见 README 第 6 节。 */
