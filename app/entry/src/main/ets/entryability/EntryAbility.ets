import { UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';
import native from 'libchimerax_native.so';

export default class EntryAbility extends UIAbility {
  onCreate(): void {
    AppStorage.setOrCreate<string>('cxFilesDir', this.context.filesDir);
  }

  onDestroy(): void {
    try {
      native.finalizeRuntime();
    } catch (error) {
      hilog.warn(0x3802, 'ChimeraX', 'CX_FINALIZE_ERROR %{public}s', (error as Error).message);
    }
  }

  onWindowStageCreate(stage: window.WindowStage): void {
    stage.loadContent('pages/Index', (error) => {
      if (error.code) {
        hilog.error(0x3802, 'ChimeraX', 'CX_LOAD_CONTENT_ERROR %{public}s', JSON.stringify(error));
      }
    });
  }
}
