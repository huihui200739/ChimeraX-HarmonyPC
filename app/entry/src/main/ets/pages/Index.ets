import { fileIo as fs } from '@kit.CoreFileKit';
import { zlib } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import native, { RuntimeReport, ExpressionReport, ExtractReport } from 'libchimerax_native.so';

// Keep in sync with the packaged rawfile name: a stale copy in the sandbox
// would otherwise be reused after the runtime contents change.
const ARCHIVE = 'cx-runtime-v4.zip';
const RUNTIME_DIR = 'cx-generic-runtime';
// Bump when the packaged runtime changes; a fresh directory avoids partial states.
const RUNTIME_STORE = 'cx-runtime-store-v4';

@Entry
@Component
struct Index {
  @State status: string = '准备中…';
  @State version: string = '';
  @State prefix: string = '';
  @State mathResult: string = '';
  @State ctypesResult: string = '';
  @State stdlibResult: string = '';
  @State chimeraxVersion: string = '';
  @State chimeraxCore: string = '';
  @State diagnostic: string = '';
  @State triggerResult: string = '';
  @State failed: string = '';

  aboutToAppear(): void {
    this.bootstrap();
  }

  private filesDir(): string {
    return AppStorage.get<string>('cxFilesDir') ?? '';
  }

  private async bootstrap(): Promise<void> {
    try {
      const files = this.filesDir();
      if (files.length === 0) {
        this.failed = '应用沙箱目录不可用';
        this.status = '失败';
        return;
      }
      this.status = '释放运行环境…';
      const archivePath = `${files}/${ARCHIVE}`;
      const packed: Uint8Array = getContext(this).resourceManager.getRawFileContentSync(`rawfile/cx-runtime.zip`);
      const file = fs.openSync(archivePath, fs.OpenMode.CREATE | fs.OpenMode.WRITE_ONLY | fs.OpenMode.TRUNC);
      fs.writeSync(file.fd, packed.buffer as ArrayBuffer);
      fs.closeSync(file);
      const store = `${files}/${RUNTIME_STORE}`;
      const runtimeDir = `${store}/${RUNTIME_DIR}`;
      if (!fs.accessSync(`${runtimeDir}/lib/python3.11/chimerax/version.py`)) {
        this.status = '解包运行环境…';
        if (!fs.accessSync(store)) {
          fs.mkdirSync(store, true);
        }
        const extracted: ExtractReport = native.extractArchive(archivePath, store);
        if (!extracted.ok) {
          this.failed = extracted.error;
          this.status = '失败';
          return;
        }
      }
      this.status = '初始化 CPython…';
      const report: RuntimeReport = native.initializeRuntime(runtimeDir);
      if (!report.initialized) {
        this.failed = report.error;
        this.status = '失败';
        return;
      }
      this.version = report.version;
      this.prefix = report.prefix;
      const math: ExpressionReport = native.runExpression('__import__("math").sqrt(16.0)');
      this.mathResult = math.ok ? math.value : math.error;
      const ctypes: ExpressionReport = native.runExpression(
        '__import__("ctypes").CDLL("libc.so").strlen(b"chimerax-on-harmony")');
      this.ctypesResult = ctypes.ok ? ctypes.value : ctypes.error;
      const stdlib: ExpressionReport = native.runExpression(
        '__import__("hashlib").sha256(b"cx").hexdigest()[:8]');
      this.stdlibResult = stdlib.ok ? stdlib.value : stdlib.error;
      const trigger: ExpressionReport = native.runExpression(
        '(lambda ts: (ts.add_trigger("cx_app_probe"),' +
        ' ts.add_handler("cx_app_probe", lambda *a: None),' +
        ' ts.activate_trigger("cx_app_probe", "payload"),' +
        ' "%s|fired" % list(ts.trigger_names())[0])[3])(' +
        '__import__("chimerax.core.triggerset", fromlist=["x"]).TriggerSet())');
      this.triggerResult = trigger.ok ? trigger.value : trigger.error;
      const diag: ExpressionReport = native.runExpression(
        '"prefix=%s|has_version=%s|first=%s" % (__import__("sys").prefix,' +
        ' __import__("os").path.exists(__import__("sys").prefix + "/lib/python3.11/chimerax/version.py"),' +
        ' ",".join(sorted(__import__("os").listdir(__import__("sys").prefix + "/lib/python3.11"))[:3]))');
      this.diagnostic = diag.ok ? diag.value : diag.error;
      const chimerax: ExpressionReport = native.runExpression(
        '__import__("chimerax.version").version.version');
      this.chimeraxVersion = chimerax.ok ? chimerax.value : chimerax.error;
      const core: ExpressionReport = native.runExpression(
        '"%s|%s|%s" % (__import__("chimerax.core.errors", fromlist=["x"]).__name__,' +
        ' __import__("chimerax.core.errors", fromlist=["x"]).UserError.__name__,' +
        ' __import__("chimerax.core.logger", fromlist=["x"]).Logger.__name__)');
      this.chimeraxCore = core.ok ? core.value : core.error;
      this.status = '运行环境就绪';
      hilog.info(0x3802, 'ChimeraX', 'CX_RUNTIME_READY %{public}s', this.version);
    } catch (error) {
      this.failed = (error as Error).message ?? JSON.stringify(error);
      this.status = '失败';
      hilog.error(0x3802, 'ChimeraX', 'CX_BOOTSTRAP_ERROR %{public}s', this.failed);
    }
  }

  build() {
    Column({ space: 10 }) {
      Text('ChimeraX · Harmony PC').fontSize(24).fontWeight(FontWeight.Bold).fontColor('#FFFFFF')
      Text('应用内嵌私有 CPython 运行环境（通用运行层，非完整应用）').fontSize(12).fontColor('#C9D6E5')
      Divider().color('#3E5C80')
      Row() {
        Text('状态').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.status).id('cx-status').fontSize(13).fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('Python').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.version.length > 0 ? this.version : '—').id('cx-version').fontSize(12)
          .fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('math.sqrt').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.mathResult.length > 0 ? this.mathResult : '—').id('cx-math').fontSize(12)
          .fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('ctypes/libc').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.ctypesResult.length > 0 ? this.ctypesResult : '—').id('cx-ctypes').fontSize(12)
          .fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('标准库').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.stdlibResult.length > 0 ? this.stdlibResult : '—').id('cx-stdlib').fontSize(12)
          .fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('ChimeraX').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.chimeraxVersion.length > 0 ? this.chimeraxVersion : '—').id('cx-chimerax')
          .fontSize(12).fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('core').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.chimeraxCore.length > 0 ? this.chimeraxCore : '—').id('cx-core')
          .fontSize(12).fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('触发器').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.triggerResult.length > 0 ? this.triggerResult : '—').id('cx-trigger')
          .fontSize(11).fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('诊断').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.diagnostic.length > 0 ? this.diagnostic : '—').id('cx-diag')
          .fontSize(10).fontColor('#B9C8D8').layoutWeight(1)
      }.width('100%')
      if (this.failed.length > 0) {
        Text(this.failed).id('cx-error').fontSize(12).fontColor('#FFB4A2').width('100%')
      }
      Blank()
      Text(this.prefix).fontSize(10).fontColor('#7F93A8').width('100%')
    }
    .width('100%').height('100%').padding(24).backgroundColor('#1E3A5F')
  }
}
