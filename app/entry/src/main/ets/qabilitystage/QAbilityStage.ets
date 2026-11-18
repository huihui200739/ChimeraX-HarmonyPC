/*
 * snippets/qt-ohos/QAbilityStage.ets
 *
 * 目标位置: app/entry/src/main/ets/qabilitystage/QAbilityStage.ets  (新文件)
 * module.json5 的 "module"."srcEntry" 必须指向它 (见 patches/qt-ohos/0001-*).
 *
 * 上游依据:
 *   qohosjsmain.cpp:1626 setupQtApplicationImpl() 读 appStartupObj 的
 *     appContext{bundleCodeDir,cacheDir,filesDir,preferencesDir,tempDir,
 *                 databaseDir,distributedFilesDir,resourceDir}
 *     resourceDir 缺省回落 bundleCodeDir + "/entry/resources/resfile"
 *     modulesFactories (object, 值必须是 function)
 *     appArgs (Array<string>, 覆盖 Want 里的启动参数)
 *     appName  <-- 就是 dlopen 的名字, 不是 sharedLibraryName
 *     abilityClassName (只接受 "QAbility")
 *   qohosjsmain.cpp:1678 s_appSharedLibName = appStartupObj["appName"]
 *   qohosjsmain.cpp:1683 s_appSharedLibsDirPath = bundleCodeDir + "/libs/arm64"
 *   qohosjsmain.cpp:1698-1711 Qt 自己 setenv QT_QPA_PLATFORM=ohos 等, 不要在外面抢着设
 */

import AbilityStage from '@ohos.app.ability.AbilityStage';
import Want from '@ohos.app.ability.Want';
import { common } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import qpa from 'libqohos.so';
import QtUtils from '../qability/QtUtils';

const LOG_DOMAIN: number = 0x3802;
const LOG_TAG: string = 'ChimeraX';

/* 必须是 entry/libs/arm64-v8a/ 里那个导出 main() 的 .so 文件名。
 * 不要写成 libqohos.so —— 那是 QPA/napi 模块本身。 */
export const APP_LIBRARY_NAME: string = 'libchimeraxqt.so';

/* Qt 只认 "QAbility" (qohosjsmain.cpp:1728 abilityClassNameToQtRunModeMap)。 */
const QT_ABILITY_CLASS_NAME: string = 'QAbility';

export default class QAbilityStage extends AbilityStage {
  private static initCalled: boolean = false;

  /* appArgs -> 应用 .so 的 main(argc, argv)。
   * 这是把 ArkTS 侧算出来的路径交给 C++ 的唯一干净通道(setupQtApplication 前后
   * 环境变量已被 Qt 覆盖, 不要指望靠 setenv 传递)。 */
  private static buildAppArgs(appContext: common.ApplicationContext): Array<string> {
    return [
      '--cx-files-dir', appContext.filesDir,
      // 现有 Index.ets 探针页解包出来的通用运行层(带尺寸后缀的 store 目录)。
      // launcher 会自己 glob <filesDir>/cx-runtime-*/cx-generic-runtime。
      '--cx-runtime-glob', `${appContext.filesDir}/cx-runtime-*/cx-generic-runtime`,
      '--cx-bootstrap', 'chimerax_qt_bootstrap.py',
    ];
  }

  private static initQtAppContextImpl(
    appContext: common.ApplicationContext, abilityClassName: string): void {
    if (QAbilityStage.initCalled) {
      return;
    }
    QAbilityStage.initCalled = true;
    hilog.info(LOG_DOMAIN, LOG_TAG, 'CX_QT_SETUP start appName=%{public}s', APP_LIBRARY_NAME);
    // The parameter type comes from libqohos.d.ts (QtApplicationSetupParams).
    qpa.setupQtApplication({
      appContext: appContext,
      modulesFactories: QtUtils.getModulesFactoriesMapForQt(),
      appName: APP_LIBRARY_NAME,
      appArgs: QAbilityStage.buildAppArgs(appContext),
      abilityClassName: abilityClassName,
      // 该字段 Qt 侧命名即 _unusedQChildProcess, 仅用于让 hvigor 保留
      // QChildProcess(.ets) 不被摇树; 非子进程模式随便给个对象。
      // Hand over a constructed instance: ArkTS compiles arrow functions into closure
      // objects, so napi_typeof reports an object rather than a function. The rebuilt
      // plugin accepts an instance directly (it only checks for "setOrCreate").
      localStorage: new LocalStorage(),
      _unusedQChildProcess: QtUtils.getModulesFactoriesMapForQt()
    });
  }

  public static initQtAppContextIfNeeded(appContext: common.ApplicationContext): void {
    QAbilityStage.initQtAppContextImpl(appContext, QT_ABILITY_CLASS_NAME);
  }

  onCreate(): void {
    hilog.info(LOG_DOMAIN, LOG_TAG, 'CX_QT_STAGE_ONCREATE');
    qpa.handleAbilityStageOnCreate(this);
  }

  onNewProcessRequest(want: Want): string {
    QAbilityStage.initQtAppContextIfNeeded(this.context.getApplicationContext());
    const key: string = qpa.handleAbilityStageOnNewProcessRequest(this, want);
    hilog.info(LOG_DOMAIN, LOG_TAG, 'CX_QT_STAGE_NEWPROCESS key=%{public}s', key);
    return key;
  }

  onAcceptWant(want: Want): string {
    QAbilityStage.initQtAppContextIfNeeded(this.context.getApplicationContext());
    const key: string = qpa.handleAbilityStageOnAcceptWant(this, want);
    hilog.info(LOG_DOMAIN, LOG_TAG, 'CX_QT_STAGE_ACCEPTWANT key=%{public}s', key);
    return key;
  }

  onDestroy(): void {
    hilog.info(LOG_DOMAIN, LOG_TAG, 'CX_QT_STAGE_ONDESTROY');
    qpa.handleAbilityStageOnDestroy(this);
  }
}
