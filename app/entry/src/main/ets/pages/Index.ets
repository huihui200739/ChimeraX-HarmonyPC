import { fileIo as fs } from '@kit.CoreFileKit';
import { zlib } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import native, { RuntimeReport, ExpressionReport } from 'libchimerax_native.so';

const ARCHIVE = 'cx-runtime.zip';
const RUNTIME_DIR = 'cx-generic-runtime';

@Entry
@Component
struct Index {
  @State status: string = '准备中…';
  @State version: string = '';
  @State prefix: string = '';
  @State mathResult: string = '';
  @State ctypesResult: string = '';
  @State stdlibResult: string = '';
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
      if (!fs.accessSync(archivePath)) {
        const packed: Uint8Array = getContext(this).resourceManager.getRawFileContentSync(`rawfile/${ARCHIVE}`);
        const file = fs.openSync(archivePath, fs.OpenMode.CREATE | fs.OpenMode.WRITE_ONLY | fs.OpenMode.TRUNC);
        fs.writeSync(file.fd, packed.buffer as ArrayBuffer);
        fs.closeSync(file);
      }
      const runtimeDir = `${files}/${RUNTIME_DIR}`;
      if (!fs.accessSync(`${runtimeDir}/lib/python3.11/os.py`)) {
        this.status = '解包运行环境…';
        await zlib.decompressFile(archivePath, files);
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
      if (this.failed.length > 0) {
        Text(this.failed).id('cx-error').fontSize(12).fontColor('#FFB4A2').width('100%')
      }
      Blank()
      Text(this.prefix).fontSize(10).fontColor('#7F93A8').width('100%')
    }
    .width('100%').height('100%').padding(24).backgroundColor('#1E3A5F')
  }
}
