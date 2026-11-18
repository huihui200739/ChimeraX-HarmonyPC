/*
 * snippets/qt-ohos/qt_launcher.cpp
 *
 * 目标位置: app/entry/src/main/cpp/qt_launcher.cpp  (新文件, 由主线加入 CMake)
 * 产物:     entry/libs/arm64-v8a/libchimeraxqt.so
 *           —— 就是 QAbilityStage.ets 里 APP_LIBRARY_NAME 的那个名字。
 *
 * 为什么必须有这个 .so(硬结论, 来自上游源码):
 *   qohosjsmain.cpp:286  openLibraryWithMainFunctionOrFail()
 *     dlopen("<bundleCodeDir>/libs/arm64/<appName>", RTLD_LAZY)
 *     dlsym(handle, "main")            <-- 找不到 main 直接 abort
 *   然后 makeQtThreadWithMainFuncLauncher() 在一个专门的 Qt 线程里调用 main(argc, argv)。
 *
 *   结论: Qt for HarmonyOS 的"应用"= 一个导出 main() 的 .so。Python 不能直接当
 *   appName:
 *     - libpython3.11.so 没有导出 main;
 *     - runQtChildProcess() 那一路(qohosnouichildprocess.cpp)同样要求
 *       <libs>/<libraryName> 里有一个带 main 的 .so, 只是跑在无 UI 子进程里。
 *   所以 Python 只能以两种形态出现, 本文件实现第一种:
 *     A. 被嵌入(本文, 进程内 CPython + PySide6, 共用 Qt 的 QPA/native window)  <-- 选它
 *     B. 被 spawn 成子进程(需要 OHOS 上 fork/exec 自己的 python 二进制, 且拿不到
 *        ArkUI 的 native window; 仅适合 no-UI 计算)
 *
 * 本文件的三条硬约束:
 *   1. main 必须导出为动态符号。CMAKE 里别加 -fvisibility=hidden, 或用下面的
 *      __attribute__((visibility("default")))(已加)。
 *   2. Py_InitializeEx 必须在这个线程里跑一次, 且早于 PySide6 的 QApplication。
 *   3. 不要 setenv QT_QPA_PLATFORM / QT_PLUGIN_PATH —— setupQtApplicationImpl()
 *      (qohosjsmain.cpp:1698) 已经设好(QT_QPA_PLATFORM=ohos,
 *      QT_QPA_PLATFORM_PLUGIN_PATH/QT_PLUGIN_PATH=<bundleCodeDir>/libs/arm64,
 *      HOME=<filesDir>, TMPDIR=<tempDir>, 并且 chdir 到 filesDir)。
 *      这里再改只会把 Qt 指到不存在的目录。
 */

#include <Python.h>

#include <dirent.h>
#include <dlfcn.h>
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <string>
#include <vector>

#include <hilog/log.h>

namespace {

constexpr const char *kLogDomainTag = "ChimeraXQt";
constexpr unsigned int kLogDomain = 0x3802;

void logInfo(const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    OH_LOG_VPrint(LOG_APP, kLogDomain, kLogDomainTag, LOG_INFO, fmt, args);
    va_end(args);
}

void logError(const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    OH_LOG_VPrint(LOG_APP, kLogDomain, kLogDomainTag, LOG_ERROR, fmt, args);
    va_end(args);
}

bool fileExists(const std::string &path)
{
    struct stat st = {};
    return ::stat(path.c_str(), &st) == 0;
}

bool dirExists(const std::string &path)
{
    struct stat st = {};
    return ::stat(path.c_str(), &st) == 0 && S_ISDIR(st.st_mode);
}

/* 本 .so 所在目录 = <bundleCodeDir>/libs/arm64。PySide6 部署在
 * libs/arm64-v8a/PySide6(见 build/qtbind/out/deploy-manifest.txt),
 * 设备上即 <bundleCodeDir>/libs/arm64/PySide6, 所以这个目录必须进 sys.path。 */
std::string selfLibDir()
{
    Dl_info info = {};
    if (::dladdr(reinterpret_cast<void *>(&selfLibDir), &info) == 0 || info.dli_fname == nullptr) {
        return {};
    }
    std::string path = info.dli_fname;
    const auto slash = path.find_last_of('/');
    return slash == std::string::npos ? std::string() : path.substr(0, slash);
}

std::string dirName(const std::string &path)
{
    const auto slash = path.find_last_of('/');
    return slash == std::string::npos ? std::string(".") : path.substr(0, slash);
}

/* 把 <filesDir>/cx-runtime-<size>/cx-generic-runtime 这种 glob 展开成真实目录,
 * 取 mtime 最新的一个(现有 Index.ets 探针页按 archive 大小命名 store 目录,
 * 名字在编译期未知, 所以在运行时解析)。 */
std::vector<std::string> expandRuntimeGlob(const std::string &pattern)
{
    std::vector<std::string> result;
    const std::string parent = dirName(pattern);
    if (!dirExists(parent)) {
        return result;
    }

    DIR *dir = ::opendir(parent.c_str());
    if (dir == nullptr) {
        return result;
    }

    const std::string suffix = "/cx-generic-runtime";
    struct Candidate
    {
        std::string path;
        time_t mtime;
    };
    std::vector<Candidate> candidates;

    while (dirent *entry = ::readdir(dir)) {
        const std::string name = entry->d_name;
        if (name == "." || name == "..") {
            continue;
        }
        if (name.rfind("cx-runtime-", 0) != 0) {
            continue;
        }
        const std::string candidate = parent + "/" + name + suffix;
        if (!fileExists(candidate + "/lib/python3.11/os.py")) {
            continue;
        }
        struct stat st = {};
        if (::stat(candidate.c_str(), &st) != 0) {
            continue;
        }
        candidates.push_back({candidate, st.st_mtime});
    }
    ::closedir(dir);

    std::sort(candidates.begin(), candidates.end(), [](const Candidate &a, const Candidate &b) {
        return a.mtime > b.mtime;
    });
    for (const auto &candidate : candidates) {
        result.push_back(candidate.path);
    }
    return result;
}

struct LaunchArgs
{
    std::string filesDir;
    std::string runtimeGlob;
    std::string bootstrap;
    std::string stage = "probe"; // probe | real
};

LaunchArgs parseArgs(int argc, char **argv)
{
    LaunchArgs args;
    for (int i = 1; i < argc; ++i) {
        const std::string current = argv[i] ? argv[i] : "";
        const auto next = [&]() -> std::string {
            return (i + 1 < argc && argv[i + 1]) ? std::string(argv[++i]) : std::string();
        };
        if (current == "--cx-files-dir") {
            args.filesDir = next();
        } else if (current == "--cx-runtime-glob") {
            args.runtimeGlob = next();
        } else if (current == "--cx-bootstrap") {
            args.bootstrap = next();
        } else if (current == "--cx-stage") {
            args.stage = next();
        }
    }
    return args;
}

/* 探针页(阶段 1): 只证明 "Qt 平台插件 + ArkUI XComponent + PySide6" 这条链通了。
 * 不加载 ChimeraX, 失败面最小。 */
const char *kProbeScript = R"PY(
import os, sys, traceback

def cxqt_log(message):
    print('CXQT ' + str(message), flush=True)

code = 0
try:
    cxqt_log('prefix=%s' % sys.prefix)
    cxqt_log('PYTHONHOME=%s' % os.environ.get('PYTHONHOME', '?'))
    cxqt_log('QT_QPA_PLATFORM=%s' % os.environ.get('QT_QPA_PLATFORM', '?'))
    cxqt_log('QT_PLUGIN_PATH=%s' % os.environ.get('QT_PLUGIN_PATH', '?'))
    from PySide6 import QtCore
    cxqt_log('pyside6=%s qt=%s' % (QtCore.__version__, QtCore.qVersion()))
    from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QWidget, QVBoxLayout
    app = QApplication(sys.argv)
    cxqt_log('qpa_platform=%s' % app.platformName())
    window = QMainWindow()
    window.setWindowTitle('ChimeraX / Qt on HarmonyOS')
    window.resize(900, 640)
    central = QWidget()
    layout = QVBoxLayout(central)
    layout.addWidget(QLabel('Qt for HarmonyOS: window pipeline is live.'))
    layout.addWidget(QLabel('platformName=' + app.platformName()))
    layout.addWidget(QLabel('Qt=' + QtCore.qVersion() + ' PySide6=' + QtCore.__version__))
    layout.addWidget(QLabel('PYTHONHOME=' + os.environ.get('PYTHONHOME', '(none)')))
    window.setCentralWidget(central)
    window.show()
    cxqt_log('window_shown')
    code = app.exec()
    cxqt_log('exec_returned=%d' % code)
except BaseException:
    cxqt_log('PROBE_FAILED')
    traceback.print_exc()
    code = 70
# SystemExit 必须在 try 之外抛, 否则会被上面的 except BaseException 吞掉。
sys.exit(code)
)PY";

/* 真实路径(阶段 2): 用 PySide6 起 QApplication, 再让 ChimeraX 的 ui 接管主窗口。
 * 关键点: QApplication 只能有一个, 必须由这里创建, 不能让 chimerax.ui 再建一个。 */
const char *kRealScript = R"PY(
import os, sys, traceback

def cxqt_log(message):
    print('CXQT ' + str(message), flush=True)

code = 0
try:
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    cxqt_log('qpa_platform=%s' % app.platformName())
    from chimerax.core.session import Session
    session = Session('ChimeraX')
    session.ui.gui_start()          # 建 MainWindow; 事件循环由 ui 自己跑
    cxqt_log('gui_start_returned')
except BaseException:
    cxqt_log('REAL_STAGE_FAILED')
    traceback.print_exc()
    code = 71
sys.exit(code)
)PY";

int runPython(const std::string &runtimeDir, const LaunchArgs &args, const std::string &libsDir)
{
    /* 1) 解释器 home: 现有 chimerax_native.cpp 用的就是 Py_SetPythonHome + Py_InitializeEx(0),
     *    CPython 3.11 依然支持, 保持一致。 */
    const std::wstring wideHome(runtimeDir.begin(), runtimeDir.end());
    Py_SetPythonHome(const_cast<wchar_t *>(wideHome.c_str()));

    std::string pythonPath = runtimeDir + "/lib/python3.11";
    pythonPath += ":";
    pythonPath += libsDir; // PySide6/ 在这个目录下
    ::setenv("PYTHONPATH", pythonPath.c_str(), 1);
    ::setenv("PYTHONHOME", runtimeDir.c_str(), 1);
    /* PyOpenGL: 只有 EGL 可用, 没有 GLX/CGL。 */
    ::setenv("PYOPENGL_PLATFORM", "egl", 1);
    /* shiboken 的调试输出很有用, 默认开 info 便于定位 import 失败。 */
    if (::getenv("SHIBOKEN_DEBUG") == nullptr) {
        ::setenv("SHIBOKEN_DEBUG", "1", 1);
    }

    Py_InitializeEx(0);
    if (!Py_IsInitialized()) {
        logError("CXQT_PY_INIT_FAILED");
        return 64;
    }

    PyObject *sysPath = PySys_GetObject("path"); // borrowed
    if (sysPath != nullptr && libsDir.size() > 0) {
        PyObject *entry = PyUnicode_FromString(libsDir.c_str());
        if (entry != nullptr) {
            PyList_Insert(sysPath, 0, entry);
            Py_DECREF(entry);
        }
    }

    const char *script = (args.stage == "real") ? kRealScript : kProbeScript;
    logInfo("CXQT_PY_RUN stage=%s runtime=%s libs=%s",
            args.stage.c_str(), runtimeDir.c_str(), libsDir.c_str());

    const int result = PyRun_SimpleString(script);
    if (result != 0) {
        logError("CXQT_PY_SCRIPT_FAILED rc=%d", result);
    }
    if (Py_FinalizeEx() < 0) {
        logError("CXQT_PY_FINALIZE_FAILED");
    }
    return result == 0 ? 0 : 65;
}

/* 没有运行层时 Qt 依然要有窗口 —— 否则无法区分"胶水坏了"和"载荷没解包"。 */
int showFatalWindowWithoutPython(const std::string &message)
{
    logError("CXQT_NO_RUNTIME %s", message.c_str());
    return 66;
}

} // namespace

/* Qt 用 dlsym(handle, "main") 取它, 必须是导出符号。 */
extern "C" __attribute__((visibility("default"))) int main(int argc, char **argv)
{
    const LaunchArgs args = parseArgs(argc, argv);
    const std::string libsDir = selfLibDir();

    logInfo("CXQT_MAIN argc=%d filesDir=%s libs=%s", argc,
            args.filesDir.c_str(), libsDir.c_str());

    std::vector<std::string> runtimeDirs;
    if (!args.runtimeGlob.empty()) {
        runtimeDirs = expandRuntimeGlob(args.runtimeGlob);
    }
    if (runtimeDirs.empty() && ::getenv("CXQT_RUNTIME_DIR") != nullptr) {
        runtimeDirs.push_back(::getenv("CXQT_RUNTIME_DIR"));
    }
    if (runtimeDirs.empty()) {
        return showFatalWindowWithoutPython(
            "no cx-runtime-*/cx-generic-runtime found under filesDir; "
            "run the CPython probe page once to unpack it");
    }

    return runPython(runtimeDirs.front(), args, libsDir);
}
