#define _XOPEN_SOURCE 700
#include "bootstrap.h"
#include <dlfcn.h>
#include <limits.h>
#include <locale.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <wchar.h>
#if defined(__APPLE__) && !defined(CX_BOOTSTRAP_LIBRARY)
#include <mach-o/dyld.h>
#endif
#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

/* Uses only public CPython 3.11 entry points, resolved from the PRIVATE runtime.
 * No Python headers, host Python linking, application modules or data are included.
 * The legacy setters are deliberately limited to the upstream's Python 3.11 ABI.
 */
typedef struct {
    const char *(*version)(void);
    int (*initialized)(void);
    void (*set_home)(const wchar_t *);
    void (*set_program)(const wchar_t *);
    int (*main)(int, wchar_t **);
} PythonAPI;
static atomic_flag invoked = ATOMIC_FLAG_INIT;
/* Keep Python loaded and these strings alive for the entire process. Extensions
 * can retain Python references after Py_Main returns; unloading is unsafe. */
static void *python_handle;
static wchar_t *persistent_home;
static wchar_t *persistent_program;

static int fail(const char *code, const char *message) {
    fprintf(stderr, "CX_HARMONY_%s: %s\n", code, message);
    return 69;
}

static int join_path(char *out, size_t capacity, const char *root, const char *relative) {
    int length = snprintf(out, capacity, "%s/%s", root, relative);
    return length >= 0 && (size_t)length < capacity;
}

/* Decode valid UTF-8 independently of Python's preinitialization and host locale.
 * HarmonyOS/macOS wchar_t represent full Unicode scalar values. Non-UTF-8 POSIX
 * filenames are explicitly rejected instead of silently changing their bytes. */
_Static_assert(WCHAR_MAX >= 0x10ffff, "32-bit wchar_t is required");
static wchar_t *decode_utf8(const char *text) {
    size_t bytes = strlen(text);
    if (bytes > (SIZE_MAX / sizeof(wchar_t)) - 1) { return NULL; }
    wchar_t *result = calloc(bytes + 1, sizeof(*result));
    if (!result) { return NULL; }
    size_t used = 0;
    const unsigned char *p = (const unsigned char *)text;
    while (*p) {
        uint32_t value;
        int remaining;
        uint32_t minimum;
        if (*p < 0x80) { value = *p++; remaining = 0; minimum = 0; }
        else if (*p >= 0xc2 && *p <= 0xdf) { value = *p++ & 0x1f; remaining = 1; minimum = 0x80; }
        else if (*p >= 0xe0 && *p <= 0xef) { value = *p++ & 0x0f; remaining = 2; minimum = 0x800; }
        else if (*p >= 0xf0 && *p <= 0xf4) { value = *p++ & 0x07; remaining = 3; minimum = 0x10000; }
        else { free(result); return NULL; }
        for (int i = 0; i < remaining; ++i) {
            if ((*p & 0xc0) != 0x80) { free(result); return NULL; }
            value = (value << 6) | (*p++ & 0x3f);
        }
        if (value < minimum || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff)) {
            free(result); return NULL;
        }
        result[used++] = (wchar_t)value;
    }
    return result;
}

static int is_directory(const char *path) {
    struct stat info;
    return stat(path, &info) == 0 && S_ISDIR(info.st_mode);
}

static int qt_paths(const char *root) {
    const char *candidates[] = {
        "lib/python3.11/site-packages/PyQt6/Qt6/plugins",
        "lib/python3.11/site-packages/PySide6/Qt/plugins"
    };
    char plugins[PATH_MAX], platforms[PATH_MAX];
    for (size_t i = 0; i < sizeof(candidates) / sizeof(candidates[0]); ++i) {
        if (!join_path(plugins, sizeof(plugins), root, candidates[i])) { return 0; }
        if (is_directory(plugins)) {
            if (setenv("QT_PLUGIN_PATH", plugins, 1) != 0) { return 0; }
            if (!join_path(platforms, sizeof(platforms), plugins, "platforms")) { return 0; }
            if (is_directory(platforms) && setenv("QT_QPA_PLATFORM_PLUGIN_PATH", platforms, 1) != 0) { return 0; }
            /* Do not force xcb, a scale factor, Chromium switches or QPA backend. */
            return 1;
        }
    }
    return 1;
}

#define LOAD_API(member, symbol, type) do { \
    dlerror(); \
    api.member = (type)dlsym(python_handle, symbol); \
    if (!api.member) { return fail("MISSING_SYMBOL", symbol); } \
} while (0)

int cx_harmony_bootstrap(const char *root, int argc, char *const argv[], int runtime_check) {
    char resolved[PATH_MAX], path[PATH_MAX], program[PATH_MAX];
    if (!root || argc < 1 || !argv || !argv[0]) { return fail("BAD_ARGUMENTS", "runtime root and argv are required"); }
    if (atomic_flag_test_and_set(&invoked)) { return fail("ALREADY_INVOKED", "only one interpreter invocation per process is supported"); }
    if (!realpath(root, resolved) || !is_directory(resolved)) { return fail("RUNTIME_ROOT", "runtime root is not an accessible directory"); }
    if (!join_path(path, sizeof(path), resolved, "lib/python3.11/encodings/__init__.py")) { return fail("PATH_TOO_LONG", "standard library path exceeds the platform limit"); }
    if (access(path, R_OK) != 0) { return fail("STDLIB_MISSING", "private lib/python3.11/encodings/__init__.py is required"); }
    const char *names[] = {"lib/libpython3.11.so.1.0", "lib/libpython3.11.so"};
    for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
        if (!join_path(path, sizeof(path), resolved, names[i])) { return fail("PATH_TOO_LONG", "Python library path exceeds the platform limit"); }
        python_handle = dlopen(path, RTLD_NOW | RTLD_GLOBAL);
        if (python_handle) { break; }
    }
    if (!python_handle) {
        const char *error = dlerror();
        return fail("PYTHON_LOAD", error ? error : "private CPython 3.11 library cannot be loaded");
    }
    PythonAPI api;
    LOAD_API(version, "Py_GetVersion", const char *(*)(void));
    const char *version = api.version();
    if (!version || strncmp(version, "3.11.", 5) != 0) { return fail("PYTHON_ABI", "expected CPython 3.11; host or mismatched Python is not accepted"); }
    LOAD_API(initialized, "Py_IsInitialized", int (*)(void));
    if (api.initialized()) { return fail("PYTHON_INITIALIZED", "refusing to reconfigure an existing interpreter"); }
    LOAD_API(set_home, "Py_SetPythonHome", void (*)(const wchar_t *));
    LOAD_API(set_program, "Py_SetProgramName", void (*)(const wchar_t *));
    LOAD_API(main, "Py_Main", int (*)(int, wchar_t **));
    if (!join_path(program, sizeof(program), resolved, "bin/ChimeraX")) { return fail("PATH_TOO_LONG", "program path exceeds the platform limit"); }
    /* Decoding and locale setup are done before Python initialization. */
    setlocale(LC_ALL, "");
    persistent_home = decode_utf8(resolved);
    persistent_program = decode_utf8(program);
    if (!persistent_home || !persistent_program) { return fail("DECODE", "cannot decode private runtime paths"); }
    if (!qt_paths(resolved)) { return fail("QT_PATH", "cannot configure private plugin directories"); }
    int debug = 0;
    for (int i = 1; i < argc; ++i) {
        if (!argv[i]) { return fail("BAD_ARGUMENTS", "argv contains a null element"); }
        if (strcmp(argv[i], "--debug") == 0) { debug = 1; }
    }
    const char *args_check[] = {
        "-I", "-X", "utf8", "-c",
        "import json,sys; print(json.dumps(dict(check='cx_harmony_runtime',implementation=sys.implementation.name,version=sys.version,prefix=sys.prefix,executable=sys.executable,isolated=bool(sys.flags.isolated),utf8=bool(sys.flags.utf8_mode))))"
    };
    const char *args_app[] = {"-I", "-X", "utf8", "-X", "faulthandler", "-m", "chimerax.core"};
    const char **extra = runtime_check ? args_check : args_app;
    int extra_count = (int)(runtime_check ? sizeof(args_check) / sizeof(args_check[0]) : sizeof(args_app) / sizeof(args_app[0]));
    /* Runtime checks never import the application or forward app arguments. */
    int app_count = runtime_check ? 0 : argc - 1;
    int debug_count = !runtime_check && debug ? 2 : 0;
    if (argc > INT_MAX - extra_count - debug_count - 1) { return fail("ARGUMENT_COUNT", "too many arguments"); }
    int count = 1 + extra_count + debug_count + app_count;
    wchar_t **wide = calloc((size_t)count + 1, sizeof(*wide));
    if (!wide) { return fail("MEMORY", "argument allocation failed"); }
    int used = 0;
    wide[used++] = decode_utf8(program);
    if (debug_count) {
        wide[used++] = decode_utf8("-X");
        wide[used++] = decode_utf8("dev");
    }
    for (int i = 0; i < extra_count; ++i) { wide[used++] = decode_utf8(extra[i]); }
    for (int i = 0; i < app_count; ++i) { wide[used++] = decode_utf8(argv[i + 1]); }
    int decoded = 1;
    for (int i = 0; i < count; ++i) { if (!wide[i]) { decoded = 0; } }
    if (!decoded) {
        for (int i = 0; i < count; ++i) { if (wide[i]) { free(wide[i]); } }
        free(wide);
        return fail("DECODE", "cannot decode application arguments");
    }
    api.set_home(persistent_home);
    api.set_program(persistent_program);
    int status = api.main(count, wide);
    for (int i = 0; i < count; ++i) { free(wide[i]); }
    free(wide);
    return status;
}

#ifndef CX_BOOTSTRAP_LIBRARY
static int default_root(char *root, size_t capacity) {
    char executable[PATH_MAX];
#if defined(__APPLE__)
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) != 0) { return 0; }
#else
    ssize_t size = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
    if (size < 0 || (size_t)size >= sizeof(executable) - 1) { return 0; }
    executable[size] = '\0';
#endif
    char resolved[PATH_MAX];
    if (!realpath(executable, resolved)) { return 0; }
    for (int i = 0; i < 2; ++i) {
        char *slash = strrchr(resolved, '/');
        if (!slash) { return 0; }
        if (slash == resolved) { slash[1] = '\0'; break; }
        *slash = '\0';
    }
    if (strlen(resolved) + 1 > capacity) { return 0; }
    strcpy(root, resolved);
    return 1;
}


/* HarmonyOS resolves extension modules with the loader's global scope only, so a
 * dlopen'ed libpython stays invisible to later extension loads. Re-executing once
 * with the private libpython preloaded puts CPython into that global scope using
 * the loader's own mechanism; nothing is installed system-wide. */
static int preload_reexec(const char *root, char **argv) {
    if (getenv("CX_HARMONY_PRELOADED")) { return 0; }
    char python[PATH_MAX], libs[PATH_MAX];
    if (!join_path(python, sizeof(python), root, "lib/libpython3.11.so.1.0")) { return 0; }
    if (access(python, R_OK) != 0) { return 0; }
    if (!join_path(libs, sizeof(libs), root, "lib")) { return 0; }
    const char *previous_paths = getenv("LD_LIBRARY_PATH");
    size_t length = strlen(libs) + (previous_paths ? strlen(previous_paths) + 2 : 1);
    char *paths = malloc(length);
    if (!paths) { return 0; }
    snprintf(paths, length, "%s%s%s", libs, previous_paths && *previous_paths ? ":" : "",
             previous_paths && *previous_paths ? previous_paths : "");
    setenv("LD_PRELOAD", python, 1);
    setenv("LD_LIBRARY_PATH", paths, 1);
    setenv("CX_HARMONY_PRELOADED", "1", 1);
    free(paths);
    execv(argv[0], argv);
    return 0; /* Fall through: the dlopen path still works without preloading. */
}

int main(int argc, char **argv) {
    const char *root = NULL;
    int runtime_check = 0, index = 1;
    for (; index < argc; ++index) {
        if (strcmp(argv[index], "--") == 0) { ++index; break; }
        if (strcmp(argv[index], "--cx-runtime-root") == 0) {
            if (++index >= argc) { return fail("BAD_ARGUMENTS", "--cx-runtime-root requires a directory"); }
            root = argv[index];
        } else if (strcmp(argv[index], "--cx-runtime-check") == 0) {
            runtime_check = 1;
        } else if (strcmp(argv[index], "--cx-help") == 0) {
            puts("ChimeraX Harmony startup adapter (not a complete application).\n"
                 "Options: --cx-runtime-root DIR --cx-runtime-check --cx-help\n"
                 "Application options follow these options or --. No device is contacted.");
            return 0;
        } else { break; }
    }
    char inferred[PATH_MAX];
    if (!root) {
        if (!default_root(inferred, sizeof(inferred))) { return fail("RUNTIME_ROOT", "cannot derive private runtime; specify --cx-runtime-root"); }
        root = inferred;
    }
    preload_reexec(root, argv);
    int application_argc = 1 + argc - index;
    char **application_argv = calloc((size_t)application_argc + 1, sizeof(*application_argv));
    if (!application_argv) { return fail("MEMORY", "argument allocation failed"); }
    application_argv[0] = argv[0];
    for (int i = 1; i < application_argc; ++i) { application_argv[i] = argv[index + i - 1]; }
    int status = cx_harmony_bootstrap(root, application_argc, application_argv, runtime_check);
    free(application_argv);
    return status;
}
#endif
