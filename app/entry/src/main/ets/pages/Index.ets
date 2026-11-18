import { fileIo as fs } from '@kit.CoreFileKit';
import { zlib } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import native, { RuntimeReport, ExpressionReport, ExtractReport, ScriptReport, GLReport } from 'libchimerax_native.so';

// Keep in sync with the packaged rawfile name: a stale copy in the sandbox
// would otherwise be reused after the runtime contents change.
const ARCHIVE = 'cx-runtime-v4.zip';
const RUNTIME_DIR = 'cx-generic-runtime';
// The store name carries the packaged archive size, so a new payload always
// extracts into a fresh directory instead of reusing stale content.


// Runs a real ChimeraX command: the command is registered in the (global)
// command table exactly like a bundle would, then executed through
// chimerax.core.commands.run with a minimal Session.
const COMMAND_SCRIPT = `
import io, sys
from chimerax.core.session import Session
from chimerax.core.commands import CmdDesc, StringArg, register, run

# Reuse the persistent session created by the native bootstrap; creating a new
# one here would shadow it and lose tools/toolshed.
try:
    session
except NameError:
    class _NullUI:
        is_gui = False
        def __getattr__(self, name):
            return lambda *args, **kwargs: None
    session = Session("ChimeraX", silent=True, minimal=True)
    session.ui = _NullUI()
calls = []

def _cx_probe(session, value):
    calls.append(value)
    return "cxprobe:" + value

register("cxprobe", CmdDesc(required=[("value", StringArg)],
                            synopsis="harmony adaptation probe command"), _cx_probe)
result = run(session, "cxprobe hello-harmony")
print("%s|%s|%s" % (result, len(calls), calls[0]))
`;


// Two genuine ChimeraX built-ins registered by the core bundle: toolshed list
// executes, and devel dump exercises CmdDesc argument validation.
const BUILTIN_SCRIPT = `
from chimerax.core.commands import run
summary = []
try:
    run(session, "toolshed list")
    summary.append("toolshed-list:ok")
except Exception as error:
    summary.append("toolshed-list:" + type(error).__name__ + ":" + str(error)[:40])
try:
    run(session, "devel dump /nonexistent/cx-probe.txt")
    summary.append("devel-dump:no-error")
except Exception as error:
    summary.append("devel-dump:" + str(error).split(":")[0])
print("|".join(summary) + "|tools=%s|toolshed=%s|state=%s" % (
    hasattr(session, "tools"), hasattr(session, "toolshed"), globals().get("_cx_state", "?")))
`;


// Builds a real AtomicStructure with atoms through chimerax.atomic, which exercises
// the C++ atomstruct layer, the pyinstance registry and the shared support library.
const MODEL_SCRIPT = `
import numpy
from chimerax.atomic import AtomicStructure
structure = AtomicStructure(session, name="cx_app_model")
residue = structure.new_residue("UNL", "A", 1)
coords = numpy.array([[0.0, 0.0, 0.0], [1.5, 0.0, 0.0]], dtype=numpy.float64)
names = ["C1", "N1"]
elements = ["C", "N"]
for index, name in enumerate(names):
    atom = structure.new_atom(name, elements[index])
    atom.coord = coords[index]
    residue.add_atom(atom)
print("atoms=%d|residues=%d|names=%s" % (structure.num_atoms, structure.num_residues,
      ",".join(a.name for a in structure.atoms)))
`;

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
  @State numpyResult: string = '';
  @State numpyCore: string = '';
  @State commandsProbe: string = '';
  @State sessionProbe: string = '';
  @State commandResult: string = '';
  @State commandText: string = 'cxprobe ui-command';
  @State commandOutput: string = '';
  @State builtinResult: string = '';
  @State graphicsResult: string = '';
  @State glStatus: string = '';
  @State atomicResult: string = '';
  @State glStackResult: string = '';
  @State modelResult: string = '';
  @State failed: string = '';

  aboutToAppear(): void {
    this.bootstrap();
  }

  private filesDir(): string {
    return AppStorage.get<string>('cxFilesDir') ?? '';
  }

  private executeCommand(): void {
    const report: ScriptReport = native.runChimeraCommand(this.commandText);
    this.commandOutput = (report.ok ? report.output : report.error).trim();
  }

  private executePythonSample(): void {
    const report: ScriptReport = native.runScript(
      'print(session.app_name, len(session.triggers.trigger_names()))');
    this.commandOutput = (report.ok ? report.output : report.error).trim();
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
      const store = `${files}/cx-runtime-${packed.byteLength}`;
      const runtimeDir = `${store}/${RUNTIME_DIR}`;
      const ready = fs.accessSync(`${runtimeDir}/lib/python3.11/os.py`) &&
        fs.accessSync(`${runtimeDir}/lib/python3.11/chimerax/version.py`) &&
        fs.accessSync(`${runtimeDir}/lib/python3.11/numpy/__init__.py`);
      if (!ready) {
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
      const numpy: ExpressionReport = native.runExpression(
        '"%s|%s|%s" % (__import__("numpy").__version__,' +
        ' str(__import__("numpy").sqrt(16.0)), str(__import__("numpy").arange(5).sum()))');
      this.numpyResult = numpy.ok ? numpy.value : numpy.error;
      const numpyCore: ExpressionReport = native.runExpression(
        '__import__("numpy.core._multiarray_umath", fromlist=["x"]).__file__');
      this.numpyCore = numpyCore.ok ? numpyCore.value : numpyCore.error;
      const session: ExpressionReport = native.runExpression(
        '(lambda s: "%s|%s|%s" % (type(s).__name__, str(s.logger is not None),' +
        ' str(len(s.triggers.trigger_names()))))(' +
        '__import__("chimerax.core.session", fromlist=["x"]).Session("ChimeraX", silent=True, minimal=True))');
      this.sessionProbe = session.ok ? session.value : session.error;
      const commands: ExpressionReport = native.runExpression(
        '"%s|%s|%s" % (__import__("chimerax.core.colors", fromlist=["x"]).__name__,' +
        ' __import__("chimerax.core.session", fromlist=["x"]).__name__,' +
        ' __import__("chimerax.core.commands", fromlist=["x"]).__name__)');
      this.commandsProbe = commands.ok ? commands.value : commands.error;
      const command: ScriptReport = native.runScript(COMMAND_SCRIPT);
      this.commandResult = command.ok ? command.output.trim() : command.error;
      const builtin: ScriptReport = native.runScript(BUILTIN_SCRIPT);
      this.builtinResult = (builtin.ok ? builtin.output : builtin.error).trim();
      const graphics: ExpressionReport = native.runExpression(
        '(lambda g, n: "%s|%s" % (g.__name__,' +
        ' str(g.count_value(n.array([1, 2, 5, 5, 5, 9], dtype="uint8"), 5))))(' +
        '__import__("chimerax.graphics._graphics", fromlist=["x"]), __import__("numpy"))');
      this.graphicsResult = graphics.ok ? graphics.value : graphics.error;
      const atomic: ExpressionReport = native.runExpression(
        '"%s|%s|%s" % (__import__("chimerax.atomic", fromlist=["x"]).__name__,' +
        ' __import__("chimerax.atomic", fromlist=["x"]).Atom.__name__,' +
        ' __import__("chimerax.atomic", fromlist=["x"]).AtomicStructure.__name__)');
      this.atomicResult = atomic.ok ? atomic.value : atomic.error;
      const glStack: ExpressionReport = native.runExpression(
        '"%s|%s|%s" % (__import__("OpenGL").__version__,' +
        ' __import__("chimerax.graphics.opengl", fromlist=["x"]).__name__,' +
        ' str(hasattr(__import__("chimerax.core.models", fromlist=["x"]), "Model")))');
      this.glStackResult = glStack.ok ? glStack.value : glStack.error;
      const model: ScriptReport = native.runScript(MODEL_SCRIPT);
      this.modelResult = (model.ok ? model.output : model.error).trim();
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
      let polls = 0;
      const poll = setInterval(() => {
        polls += 1;
        try {
          const gl: GLReport = native.glStatus();
          if (gl.status.length > 0) {
            this.glStatus = gl.status;
          }
        } catch (error) {
          this.glStatus = 'gl-status-error';
        }
        if (polls >= 10 || this.glStatus.startsWith('ready:')) {
          clearInterval(poll);
        }
      }, 800);
    } catch (error) {
      this.failed = (error as Error).message ?? JSON.stringify(error);
      this.status = '失败';
      hilog.error(0x3802, 'ChimeraX', 'CX_BOOTSTRAP_ERROR %{public}s', this.failed);
    }
  }

  build() {
    Scroll() {
      Column({ space: 8 }) {
      Text('ChimeraX · Harmony PC').fontSize(24).fontWeight(FontWeight.Bold).fontColor('#FFFFFF')
      Text('应用内嵌私有 CPython 运行环境（通用运行层，非完整应用）').fontSize(12).fontColor('#C9D6E5')
      Divider().color('#3E5C80')
      Row() {
        Text('状态').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.status).id('cx-status').fontSize(13).fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('core API').fontSize(12).fontColor('#C9D6E5').width(80)
        Text((this.commandsProbe.length > 0 ? this.commandsProbe : '—') + ' | ' +
             (this.sessionProbe.length > 0 ? this.sessionProbe : '—')).id('cx-commands')
          .fontSize(9).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Text('触发器').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.triggerResult.length > 0 ? this.triggerResult : '—').id('cx-trigger')
          .fontSize(11).fontColor('#FFFFFF').layoutWeight(1)
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
        Text('numpy').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.numpyResult.length > 0 ? this.numpyResult : '—').id('cx-numpy')
          .fontSize(11).fontColor('#FFFFFF').layoutWeight(1)
      }.width('100%')
      Row() {
        Text('_umath').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.numpyCore.length > 0 ? this.numpyCore : '—').id('cx-numpyc')
          .fontSize(10).fontColor('#B9C8D8').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row({ space: 6 }) {
        TextInput({ text: this.commandText, placeholder: '输入 ChimeraX 命令，例如 cxprobe ui-command' })
          .id('cx-cmd-input').height(32).fontSize(11).layoutWeight(1)
          .onChange((value: string) => { this.commandText = value; })
          .onSubmit(() => this.executeCommand())
        Button('执行命令').id('cx-cmd-run').height(32).fontSize(11)
          .onClick(() => this.executeCommand())
        Button('Python').id('cx-cmd-py').height(32).fontSize(11)
          .onClick(() => this.executePythonSample())
      }.width('100%')
      Text(this.commandOutput.length > 0 ? this.commandOutput : '（输出）')
        .id('cx-cmd-output').fontSize(11).fontColor('#D7E3F0').width('100%').maxLines(4)
      Row() {
        Text('命令执行').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.commandResult.length > 0 ? this.commandResult : '—').id('cx-command-run')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      XComponent({ id: 'cx-gl-surface', type: XComponentType.SURFACE, libraryname: 'chimerax_native' })
        .id('cx-gl-surface').width('100%').height(150).backgroundColor('#16212F')
      Row() {
        Text('GL 表面').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.glStatus.length > 0 ? this.glStatus : '—').id('cx-gl-status')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Text('模型层').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.modelResult.length > 0 ? this.modelResult : '—').id('cx-model')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Text('GL 栈').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.glStackResult.length > 0 ? this.glStackResult : '—').id('cx-glstack')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Text('atomic').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.atomicResult.length > 0 ? this.atomicResult : '—').id('cx-atomic')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Text('graphics').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.graphicsResult.length > 0 ? this.graphicsResult : '—').id('cx-graphics')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      Row() {
        Text('内置命令').fontSize(13).fontColor('#C9D6E5').width(80)
        Text(this.builtinResult.length > 0 ? this.builtinResult : '—').id('cx-builtin')
          .fontSize(10).fontColor('#FFFFFF').layoutWeight(1).maxLines(3)
      }.width('100%')
      if (this.failed.length > 0) {
        Text(this.failed).id('cx-error').fontSize(12).fontColor('#FFB4A2').width('100%')
      }
      Text(this.prefix).fontSize(10).fontColor('#7F93A8').width('100%')
    }
      .width('100%').padding(20)
    }
    .width('100%').height('100%').backgroundColor('#1E3A5F').scrollBar(BarState.Auto)
  }
}
