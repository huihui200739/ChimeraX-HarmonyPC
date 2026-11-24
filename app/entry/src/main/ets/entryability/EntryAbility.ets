import { UIAbility, AbilityConstant, Want } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import native from 'libchimerax_native.so';
import qpa from 'libqohos.so';
import QAbilityStage from '../qabilitystage/QAbilityStage';

// Qt mode is switched by a marker file in the sandbox, so the same HAP can be used
// for the CPython probe page and for the native Qt window.
const QT_MODE_FLAG = 'qt-mode.flag';

export default class EntryAbility extends UIAbility {
  private qtMode: boolean = false;

  private detectQtMode(): boolean {
    try {
      const path = this.context.filesDir + '/' + QT_MODE_FLAG;
      return fs.accessSync(path);
    } catch (error) {
      return false;
    }
  }

  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    AppStorage.setOrCreate<string>('cxFilesDir', this.context.filesDir);
    this.qtMode = this.detectQtMode();
    hilog.info(0x3802, 'ChimeraX', 'CX_QT_MODE %{public}s', String(this.qtMode));
    if (this.qtMode) {
      QAbilityStage.initQtAppContextIfNeeded(this.context.getApplicationContext());
      qpa.handleAbilityOnCreate(this, want, launchParam);
    }
  }

  onDestroy(): void {
    try {
      native.finalizeRuntime();
    } catch (error) {
      hilog.warn(0x3802, 'ChimeraX', 'CX_FINALIZE_ERROR %{public}s', (error as Error).message);
    }
  }

  onWindowStageCreate(stage: window.WindowStage): void {
    if (this.qtMode) {
      // libqohos computes the XComponent id and loads pages/MainWindowNativeNode itself.
      qpa.handleAbilityOnWindowStageCreate(this, stage);
      return;
    }
    stage.loadContent('pages/Index', (error) => {
      if (error.code) {
        hilog.error(0x3802, 'ChimeraX', 'CX_LOAD_CONTENT_ERROR %{public}s', JSON.stringify(error));
      }
    });
  }
}
