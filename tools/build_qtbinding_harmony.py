#!/usr/bin/env python3
"""Cross-compile a QtCore Python binding for HarmonyOS (aarch64-linux-ohos).

Three independent evidence tracks, each recorded with its exact command, return
code and stderr tail so that a failure is attributable to one layer instead of
being reported as a vague "the binding does not build":

1. ``inspect_qt`` — what the official Qt 6.12.0 HarmonyOS prebuilt actually
   offers: version, header/lib paths, and whether every ``DT_NEEDED`` of
   ``libQt6Core.so`` is resolvable from the HarmonyOS sysroot.
2. ``abi_probe`` — a hand-written CPython extension that calls real QtCore
   (``QString``/``QJsonDocument``/``QVersionNumber``) compiled with the SDK
   clang against the private cross-built CPython.  This isolates the C++ ABI
   question from the binding-generator question.
3. ``pyside`` — the actual PySide6 route: build the shiboken6 generator for the
   host, then use it to generate and cross-compile the QtCore binding.  This is
   the layer that decides whether the ChimeraX UI can stay Qt.

Nothing is executed on a device, and no host Qt is ever linked into the output:
the host is only allowed to contribute *build tools* (cmake/ninja, the
shiboken6 generator binary), never libraries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SDK = Path('/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native')
TRIPLE = 'aarch64-linux-ohos'
SUFFIX = 'cpython-311-aarch64-linux-ohos.so'

ABI_PROBE = '''// ABI probe: can the cross-built CPython 3.11 load a C++ extension that links
// the official Qt 6.12.0 HarmonyOS arm64 build (libQt6Core.so)?
#include <Python.h>
#include <QtCore/QByteArray>
#include <QtCore/QCoreApplication>
#include <QtCore/QJsonDocument>
#include <QtCore/QJsonObject>
#include <QtCore/QString>
#include <QtCore/QVersionNumber>

static PyObject *probe_qt_version(PyObject *, PyObject *) {
    return PyUnicode_FromString(qVersion());
}

static PyObject *probe_json_roundtrip(PyObject *, PyObject *) {
    QJsonObject obj;
    obj.insert(QStringLiteral("bind"), QStringLiteral("QtCore"));
    obj.insert(QStringLiteral("qt"), QString::fromLatin1(QT_VERSION_STR));
    const QByteArray doc = QJsonDocument(obj).toJson(QJsonDocument::Compact);
    return PyUnicode_FromString(doc.constData());
}

static PyObject *probe_version_match(PyObject *, PyObject *) {
    const QVersionNumber header = QVersionNumber::fromString(QStringLiteral(QT_VERSION_STR));
    const QVersionNumber runtime = QVersionNumber::fromString(QString::fromLatin1(qVersion()));
    return PyBool_FromLong(header == runtime);
}

static PyMethodDef methods[] = {
    {"qt_version", probe_qt_version, METH_NOARGS, "runtime Qt version reported by libQt6Core"},
    {"json_roundtrip", probe_json_roundtrip, METH_NOARGS, "QJsonDocument round trip"},
    {"version_match", probe_version_match, METH_NOARGS, "header version == library version"},
    {nullptr, nullptr, 0, nullptr},
};

static PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT, "_qtcore_abi_probe",
    "Qt6Core ABI probe for aarch64-linux-ohos", -1, methods,
    nullptr, nullptr, nullptr, nullptr,
};

PyMODINIT_FUNC PyInit__qtcore_abi_probe(void) {
    return PyModule_Create(&moduledef);
}
'''

WIDGETS_PROBE = '''// Widget-surface probe: forces the linker to bind every Qt class family that
// ChimeraX's UI actually uses (QAction/QMenuBar/QDockWidget/QGraphicsView/
// QTableWidget/QTreeWidget/QSplitter/QStatusBar) from the official Qt 6.12.0
// HarmonyOS arm64 prebuilt.  Nothing is constructed: this answers the
// link/ABI question, not the runtime question.
#include <Python.h>
#include <QtGui/QAction>
#include <QtWidgets/QDockWidget>
#include <QtWidgets/QGraphicsScene>
#include <QtWidgets/QGraphicsView>
#include <QtWidgets/QMainWindow>
#include <QtWidgets/QMenuBar>
#include <QtWidgets/QSplitter>
#include <QtWidgets/QStatusBar>
#include <QtWidgets/QTableWidget>
#include <QtWidgets/QToolBar>
#include <QtWidgets/QTreeWidget>

#if defined(__GNUC__)
#  define PROBE_USED __attribute__((used))
#else
#  define PROBE_USED
#endif

// Each function calls the real member so the symbol lands in the dynamic symbol
// table; the linker cannot drop them because they are extern "C".
extern "C" PROBE_USED void qtw_probe_action(QAction *a, QObject *o) {
    QObject::connect(a, &QAction::triggered, o, [](){});
}
extern "C" PROBE_USED void qtw_probe_mainwindow(QMainWindow *w, QWidget *c) {
    w->setCentralWidget(c); w->menuBar()->addMenu(QStringLiteral("m"));
    w->statusBar()->showMessage(QStringLiteral("s")); w->addToolBar(QStringLiteral("t"));
}
extern "C" PROBE_USED void qtw_probe_splitter(QSplitter *s, QDockWidget *d, QWidget *w) {
    s->setSizes(QList<int>{1, 2}); d->setWidget(w);
}
extern "C" PROBE_USED void qtw_probe_models(QTableWidget *t, QTreeWidget *r) {
    t->setRowCount(1); r->setHeaderLabel(QStringLiteral("h"));
}
extern "C" PROBE_USED void qtw_probe_view(QGraphicsView *v, QGraphicsScene *s) {
    v->setScene(s);
}

static PyMethodDef methods[] = {{nullptr, nullptr, 0, nullptr}};
static PyModuleDef moduledef = {PyModuleDef_HEAD_INIT, "_qtwidgets_probe", nullptr, -1,
                                methods, nullptr, nullptr, nullptr, nullptr};
PyMODINIT_FUNC PyInit__qtwidgets_probe(void) { return PyModule_Create(&moduledef); }
'''

TARGET_CMAKE = '''# Toolchain for building the PySide6 QtCore binding against the official
# Qt 6.12.0 HarmonyOS prebuilt and the private cross-built CPython 3.11.
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(OHOS TRUE)

set(CMAKE_C_COMPILER   "{sdk}/llvm/bin/clang")
set(CMAKE_CXX_COMPILER "{sdk}/llvm/bin/clang++")
set(CMAKE_SYSROOT      "{sdk}/sysroot")
set(CMAKE_FIND_ROOT_PATH "{sdk}/sysroot" "{qt}" "{cpython}")

set(CMAKE_C_FLAGS_INIT   "--target={triple} --sysroot={sdk}/sysroot -fPIC")
set(CMAKE_CXX_FLAGS_INIT "--target={triple} --sysroot={sdk}/sysroot -fPIC -std=c++17")

# Host programs must never be taken from the target root.
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
'''


def sha256(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def tail(text: str, limit: int) -> str:
    text = (text or '').strip()
    return text[-limit:] if len(text) > limit else text


class Recorder:
    """Runs one build step and stores a compact, reproducible record of it."""

    def __init__(self) -> None:
        self.steps: list[dict] = []

    def run(self, name: str, argv: list[str], cwd: Path | None = None,
            timeout: int = 1800, env: dict | None = None) -> dict:
        started = datetime.now(timezone.utc)
        record: dict = {'name': name, 'command': ' '.join(argv), 'cwd': str(cwd or ROOT)}
        try:
            result = subprocess.run(argv, cwd=str(cwd or ROOT), capture_output=True,
                                    text=True, timeout=timeout, env=env)
            record.update(returncode=result.returncode,
                          stdout_tail=tail(result.stdout, 1500),
                          stderr_tail=tail(result.stderr, 3000))
            record['status'] = 'ok' if result.returncode == 0 else 'failed'
        except subprocess.TimeoutExpired:
            record.update(returncode=None, status='timeout',
                          error=f'exceeded {timeout}s')
        except FileNotFoundError as error:
            record.update(returncode=None, status='not_runnable', error=str(error)[:400])
        record['elapsed_s'] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
        self.steps.append(record)
        return record


def read_qconfig_version(qt: Path) -> dict:
    header = qt / 'include/QtCore/qconfig.h'
    found: dict = {}
    if not header.exists():
        return found
    text = header.read_text(errors='replace')
    for key in ('QT_VERSION_STR', 'QT_VERSION_MAJOR', 'QT_VERSION_MINOR', 'QT_VERSION_PATCH'):
        match = re.search(rf'#define\s+{key}\s+("?[^"\n]+"?)', text)
        if match:
            found[key] = match.group(1).strip('"')
    return found


def dump_needed(sdk: Path, library: Path) -> list[str]:
    readelf = sdk / 'llvm/bin/llvm-readelf'
    result = subprocess.run([str(readelf), '-d', str(library)], capture_output=True, text=True)
    return re.findall(r'\(NEEDED\)\s+Shared library: \[([^\]]+)\]', result.stdout)


def dump_runpath(sdk: Path, library: Path) -> list[str]:
    readelf = sdk / 'llvm/bin/llvm-readelf'
    result = subprocess.run([str(readelf), '-d', str(library)], capture_output=True, text=True)
    return re.findall(r'\((?:RUNPATH|RPATH)\)\s+Library r(?:un)?path: \[([^\]]+)\]',
                      result.stdout)


def resolve_needed(sdk: Path, cpython: Path, names: list[str]) -> dict:
    """Search the same three roots the linker would be given, in that order."""
    roots = {
        'sysroot': sdk / f'sysroot/usr/lib/{TRIPLE}',
        'python_runtime': cpython / 'runtime/lib',
        # libc++_shared.so is a clang runtime, not part of the stable NDK sysroot.
        'clang_runtime': sdk / f'llvm/lib/{TRIPLE}',
    }
    resolved: dict = {}
    for name in names:
        hits = [label for label, root in roots.items() if (root / name).exists()]
        resolved[name] = hits or ['UNRESOLVED']
    return resolved


def inspect_qt(report: dict, qt: Path, sdk: Path, cpython: Path, rec: Recorder) -> None:
    core_so = qt / 'lib/libQt6Core.so'
    include_core = qt / 'include/QtCore'
    info = {
        'root': str(qt),
        'version': read_qconfig_version(qt),
        'include_dirs': {
            'qt_include': str(qt / 'include'),
            'qtcore_include': str(include_core),
            'qtcore_private': str(include_core / '6.12.0/QtCore/private'),
        },
        'lib_dir': str(qt / 'lib'),
        'core_so': {'path': str(core_so),
                    'bytes': core_so.stat().st_size if core_so.exists() else None,
                    'sha256': sha256(core_so) if core_so.exists() else None},
        'qtcore_header_count': len(list(include_core.glob('*'))) if include_core.exists() else 0,
        'platform_plugin': str(qt / 'plugins/platforms/libqohos.so'),
        'platform_plugin_present': (qt / 'plugins/platforms/libqohos.so').exists(),
    }
    if core_so.exists():
        needed = dump_needed(sdk, core_so)
        info['needed'] = needed
        info['runpath'] = dump_runpath(sdk, core_so)
        info['needed_resolution'] = resolve_needed(sdk, cpython, needed)
        unresolved = [n for n, hits in info['needed_resolution'].items() if hits == ['UNRESOLVED']]
        info['unresolved'] = unresolved
        info['needed_all_resolvable'] = not unresolved
    report['qt_prebuilt'] = info

    # A pure record of the tool invocation so the report is self-describing.
    rec.run('readelf_libQt6Core', [str(sdk / 'llvm/bin/llvm-readelf'), '-d', str(core_so)])


def build_abi_probe(report: dict, qt: Path, sdk: Path, cpython: Path, out: Path,
                    rec: Recorder) -> None:
    probe_dir = ROOT / 'build/qtbind/probe'
    probe_dir.mkdir(parents=True, exist_ok=True)
    source = probe_dir / 'abi_probe.cpp'
    source.write_text(ABI_PROBE)
    target = probe_dir / f'_qtcore_abi_probe.{SUFFIX}'
    clang = sdk / 'llvm/bin/clang++'
    py_include = cpython / 'source/Include'
    py_objects = cpython / 'objects'
    runtime_lib = cpython / 'runtime/lib'
    argv = [
        str(clang), f'--target={TRIPLE}', f'--sysroot={sdk}/sysroot',
        '-std=c++17', '-O2', '-fPIC', '-shared',
        f'-I{py_include}', f'-I{py_objects}',
        f'-I{qt}/include', f'-I{qt}/include/QtCore', '-DQT_CORE_LIB',
        '-o', str(target), str(source),
        f'-L{qt}/lib', '-lQt6Core',
        f'-L{runtime_lib}', '-l:libpython3.11.so.1.0',
        "-Wl,-rpath,$ORIGIN/../lib",
    ]
    record = rec.run('abi_probe_compile', argv)
    entry = {'module': '_qtcore_abi_probe', 'path': str(target), 'compile': record}
    if record['status'] == 'ok' and target.exists():
        entry['bytes'] = target.stat().st_size
        entry['sha256'] = sha256(target)
        entry['needed'] = dump_needed(sdk, target)
        entry['needed_resolution'] = resolve_needed(sdk, cpython, entry['needed'])
        # Every Qt symbol the extension imports must be exported by libQt6Core.so.
        # readelf appends the version tag (@Qt_6) on the consumer side only, so the
        # comparison has to be done on the bare mangled name.
        readelf = sdk / 'llvm/bin/llvm-readelf'
        undef = subprocess.run([str(readelf), '--dyn-syms', str(target)],
                               capture_output=True, text=True).stdout
        qt_undef = sorted({m.split('@', 1)[0]
                           for m in re.findall(r'UND\s+(\S+)', undef)
                           if m.startswith('_ZN')})
        exports = subprocess.run([str(readelf), '--dyn-syms', str(qt / 'lib/libQt6Core.so')],
                                 capture_output=True, text=True).stdout
        exported = {line.split()[-1].split('@', 1)[0]
                    for line in exports.splitlines() if re.match(r'^\s*\d+:', line)
                    and line.split()[-2] != 'UND'}
        missing = [s for s in qt_undef if s not in exported]
        entry['cxx_undefined_count'] = len(qt_undef)
        entry['cxx_unresolved_in_libQt6Core'] = missing
        entry['abi_linkable'] = not missing
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, out / target.name)
        entry['staged_to'] = str(out / target.name)
    report['abi_probe'] = entry


def build_widgets_probe(report: dict, qt: Path, sdk: Path, cpython: Path, out: Path,
                        rec: Recorder) -> None:
    """Link the Qt Widgets surface ChimeraX actually imports, not just QtCore."""
    probe_dir = ROOT / 'build/qtbind/probe'
    probe_dir.mkdir(parents=True, exist_ok=True)
    source = probe_dir / 'widgets_probe.cpp'
    source.write_text(WIDGETS_PROBE)
    target = probe_dir / f'_qtwidgets_probe.{SUFFIX}'
    clang = sdk / 'llvm/bin/clang++'
    argv = [
        str(clang), f'--target={TRIPLE}', f'--sysroot={sdk}/sysroot',
        '-std=c++17', '-O2', '-fPIC', '-shared',
        f'-I{cpython}/source/Include', f'-I{cpython}/objects',
        f'-I{qt}/include', f'-I{qt}/include/QtCore', f'-I{qt}/include/QtGui',
        f'-I{qt}/include/QtWidgets',
        '-DQT_CORE_LIB', '-DQT_GUI_LIB', '-DQT_WIDGETS_LIB',
        '-o', str(target), str(source),
        f'-L{qt}/lib', '-lQt6Widgets', '-lQt6Gui', '-lQt6Core',
        f'-L{cpython}/runtime/lib', '-l:libpython3.11.so.1.0',
        "-Wl,-rpath,$ORIGIN/../lib",
    ]
    record = rec.run('widgets_probe_compile', argv)
    entry: dict = {'module': '_qtwidgets_probe', 'path': str(target), 'compile': record}
    if record['status'] == 'ok' and target.exists():
        entry['bytes'] = target.stat().st_size
        entry['sha256'] = sha256(target)
        entry['needed'] = dump_needed(sdk, target)
        # Every Qt symbol imported across QtCore/Gui/Widgets must be exported by
        # at least one of the three prebuilt libraries.
        readelf = sdk / 'llvm/bin/llvm-readelf'
        undef = subprocess.run([str(readelf), '--dyn-syms', str(target)],
                               capture_output=True, text=True).stdout
        imported = sorted({m.split('@', 1)[0] for m in re.findall(r'UND\s+(\S+)', undef)
                           if m.startswith('_ZN')})
        exported: set[str] = set()
        for lib in ('libQt6Core.so', 'libQt6Gui.so', 'libQt6Widgets.so'):
            text = subprocess.run([str(readelf), '--dyn-syms', str(qt / 'lib' / lib)],
                                  capture_output=True, text=True).stdout
            for line in text.splitlines():
                fields = line.split()
                if re.match(r'^\s*\d+:', line) and len(fields) >= 8 and fields[6] != 'UND':
                    exported.add(fields[-1].split('@', 1)[0])
        missing = [s for s in imported if s not in exported]
        entry['qt_cxx_imported_count'] = len(imported)
        entry['qt_cxx_unresolved'] = missing
        entry['widgets_surface_linkable'] = not missing
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, out / target.name)
    report['widgets_probe'] = entry


def probe_host_qt(report: dict, qt: Path) -> dict:
    """A CMake-based Qt build needs HOST tools: moc/rcc/uic + Qt6CoreTools.

    The official HarmonyOS prebuilt is a target-only package: it carries headers
    and target libraries but no host Qt tools, so ``find_package(Qt6 Core)``
    cannot complete on the build machine.  Record exactly what is missing
    instead of reporting a bare "configure failed".
    """
    # QT_HOST_PATH wins; otherwise probe the usual macOS install locations.
    candidates: list[Path] = []
    env_host_path = os.environ.get('QT_HOST_PATH', '').strip()
    if env_host_path:
        candidates += [Path(env_host_path), Path(env_host_path) / 'lib/cmake']
    candidates += [
        ROOT / 'build/qt/host-qt-6.12.0',
        ROOT / 'build/qt/host-qt-6.12.0/lib/cmake',
        Path('/opt/homebrew/opt/qt/lib/cmake'),
        Path('/opt/homebrew/lib/cmake'),
        Path('/usr/local/opt/qt/lib/cmake'),
        Path('/usr/local/lib/cmake'),
    ]
    host_prefix: Path | None = None
    for candidate in candidates:
        if (candidate / 'Qt6CoreTools/Qt6CoreToolsConfig.cmake').exists():
            # <prefix>/lib/cmake -> <prefix>; a bare <prefix> stays as is.
            host_prefix = (candidate.parent.parent if candidate.name == 'cmake'
                           else candidate)
            break
    def _host_tool(name: str) -> str | None:
        for rel in (f'bin/{name}', f'libexec/{name}', f'libexec/{name}.app/Contents/MacOS/{name}'):
            if host_prefix is not None and (host_prefix / rel).exists():
                return str(host_prefix / rel)
        return shutil.which(name)
    probe = {
        'qt_host_path_env': env_host_path,
        'resolved_host_prefix': str(host_prefix) if host_prefix else None,
        'moc': _host_tool('moc'),
        'rcc': _host_tool('rcc'),
        'uic': _host_tool('uic'),
        'qt6coretools_config': (str(host_prefix / 'lib/cmake/Qt6CoreTools/Qt6CoreToolsConfig.cmake')
                                if host_prefix else None),
        'moc_on_path': shutil.which('moc') or shutil.which('moc-qt6') or None,
        'target_package_has_qt6coretools': (qt / 'lib/cmake/Qt6CoreTools').exists(),
        'target_package_has_moc': any((qt / rel / 'moc').exists()
                                      for rel in ('bin', 'libexec')),
        'host_qt_available': host_prefix is not None,
    }
    host_version = None
    if host_prefix is not None:
        conf = host_prefix / 'lib/cmake/Qt6/Qt6ConfigVersionImpl.cmake'
        if conf.exists():
            match = re.search(r'PACKAGE_VERSION "([^"]+)"', conf.read_text(errors='replace'))
            host_version = match.group(1) if match else None
    probe['host_qt_version'] = host_version
    probe['blocker'] = None if probe['host_qt_available'] else (
        'no host Qt 6.x installation: shiboken6/CMake needs Qt6::Core and the host '
        'tools (moc/rcc/uic) at build time; the HarmonyOS prebuilt supplies neither')
    report['host_qt'] = probe
    return probe


def locate_sdist_roots(src: Path) -> dict:
    """Find the pieces of a pyside-setup tree regardless of archive nesting."""
    candidates = [src] + [p for p in src.glob('pyside-setup*') if p.is_dir()]
    roots: dict = {}
    for candidate in candidates:
        if (candidate / 'sources/shiboken6/CMakeLists.txt').exists():
            roots['setup'] = candidate
            roots['shiboken6'] = candidate / 'sources/shiboken6'
            roots['pyside6'] = candidate / 'sources/pyside6'
            qtcore = candidate / 'sources/pyside6/PySide6/QtCore'
            roots['qtcore_typesystem'] = qtcore if qtcore.exists() else None
            break
    return roots


# The shiboken6 generator has no supported way to make libclang PARSE with a
# cross target: --compiler-argument only feeds include-path discovery, while the
# translation unit keeps the HOST triple.  For HarmonyOS that means libc++ sees
# host predefines and dies with "unknown rune table for this platform" and
# "use of undeclared identifier 'strtoll_l'".  Apply a minimal, idempotent
# patch that forwards the target/define flags into the parse itself.
GENERATOR_PATCH_ANCHOR = """    std::transform(headerPaths.cbegin(), headerPaths.cend(),
                   std::back_inserter(result), HeaderPath::includeOption);
    return result;
}"""

GENERATOR_PATCH_BODY = """    std::transform(headerPaths.cbegin(), headerPaths.cend(),
                   std::back_inserter(result), HeaderPath::includeOption);

    // HarmonyOS patch (build_qtbinding_harmony.py): parse with the same target
    // triple and predefines that were used for include-path discovery.
    // Upstream only *reports* the mismatch ("targeting <host>, (cross build)")
    // but never passes the triple to clang_parseTranslationUnit2(), so libclang
    // falls back to the HOST triple.  OHOS libc++ then fails with
    //   __locale:548: unknown rune table for this platform
    //   locale:763:   use of undeclared identifier 'strtoll_l'
    // because  _LIBCPP_PROVIDES_DEFAULT_RUNE_TABLE  needs __OHOS_FAMILY__ and
    // the musl xlocale support header needs __OHOS__.
    if (isCrossCompilation()) {
        QByteArrayList forwarded;
        for (const QString &argument : std::as_const(_compilerArguments)) {
            if (argument.startsWith(QLatin1StringView("--target="))
                || argument.startsWith(QLatin1StringView("-D"))) {
                forwarded.append(argument.toUtf8());
            }
        }
        result = forwarded + result;
    }
    return result;
}"""


def patch_generator_sources(setup_root: Path) -> dict:
    """Apply the generator patch idempotently; report what happened."""
    target = (setup_root / 'sources/shiboken6_generator/ApiExtractor/clangparser'
                         / 'compilersupport.cpp')
    if not target.exists():
        return {'status': 'missing', 'path': str(target)}
    text = target.read_text()
    if 'HarmonyOS patch (build_qtbinding_harmony.py)' in text:
        return {'status': 'already_patched', 'path': str(target)}
    if GENERATOR_PATCH_ANCHOR not in text:
        return {'status': 'anchor_not_found', 'path': str(target)}
    backup = target.with_suffix('.cpp.orig')
    if not backup.exists():
        backup.write_text(text)
    target.write_text(text.replace(GENERATOR_PATCH_ANCHOR, GENERATOR_PATCH_BODY, 1))
    return {'status': 'patched', 'path': str(target), 'backup': str(backup)}


def patch_runpath(path: Path, new_runpath: str) -> dict:
    """Rewrite DT_RUNPATH in place, with the standard library only.

    The value is written into .dynstr at its existing offset.  A shorter value
    is fine (the remainder becomes unreachable padding); a longer one cannot be
    done in place, so it is refused rather than corrupting the file.  This is
    what makes the device-side RUNPATH ($ORIGIN/../lib) possible without
    patchelf, which is not installed on this machine.
    """
    import struct
    data = bytearray(path.read_bytes())
    if data[:6] != b'\x7fELF\x02\x01':
        return {'path': str(path), 'status': 'not_elf64_le'}
    e_phoff, = struct.unpack_from('<Q', data, 0x20)
    e_phentsize, e_phnum = struct.unpack_from('<HH', data, 0x36)
    loads: list[tuple[int, int, int]] = []
    dyn_off = dyn_size = None
    for index in range(e_phnum):
        off = e_phoff + index * e_phentsize
        p_type, = struct.unpack_from('<I', data, off)
        p_offset, p_vaddr, _paddr, p_filesz = struct.unpack_from('<QQQQ', data, off + 8)
        if p_type == 1:
            loads.append((p_vaddr, p_offset, p_filesz))
        elif p_type == 2:
            dyn_off, dyn_size = p_offset, p_filesz
    if dyn_off is None:
        return {'path': str(path), 'status': 'no_pt_dynamic'}

    def vaddr_to_offset(vaddr: int) -> int | None:
        for base, offset, size in loads:
            if base <= vaddr < base + size:
                return offset + (vaddr - base)
        return None

    strtab = runpath = None
    pos = dyn_off
    while pos < dyn_off + dyn_size:
        tag, value = struct.unpack_from('<QQ', data, pos)
        if tag == 0:
            break
        if tag == 5:
            strtab = value
        elif tag == 29:
            runpath = value
        pos += 16
    if runpath is None or strtab is None:
        return {'path': str(path), 'status': 'no_dt_runpath'}
    base = vaddr_to_offset(strtab)
    if base is None:
        return {'path': str(path), 'status': 'unmapped_strtab'}
    base += runpath
    old_end = data.index(b'\0', base)
    old = data[base:old_end].decode('utf-8', 'replace')
    encoded = new_runpath.encode()
    if len(encoded) > old_end - base:
        return {'path': str(path), 'status': 'new_runpath_too_long', 'was': old}
    data[base:base + len(encoded)] = encoded
    data[base + len(encoded)] = 0
    path.write_bytes(data)
    return {'path': str(path), 'status': 'patched', 'was': old, 'now': new_runpath}


def stage_clang_package(sdk: Path, build: Path) -> dict:
    """Two build-time shims around the OpenHarmony SDK's LLVM install.

    The SDK ships a working host ``libclang.dylib`` and clang-c headers, but its
    ``LLVMExports.cmake`` references static libraries it does not ship, so
    ``find_package(Clang CONFIG)`` aborts.  It also puts an older
    ``libc++.1.0.dylib`` in ``llvm/lib`` which, if that directory lands on
    ``DYLD_LIBRARY_PATH``, shadows the host libc++ and breaks host Qt.

    So: (1) a minimal ``ClangConfig.cmake`` and (2) a directory containing only
    a symlink to libclang, used for the generator's wrapper script.
    """
    shim = build / 'clang-shim'
    shim.mkdir(parents=True, exist_ok=True)
    libclang = sdk / 'llvm/lib/libclang.dylib'
    (shim / 'ClangConfig.cmake').write_text(f"""# Minimal Clang package for shiboken6 (generated by build_qtbinding_harmony.py).
#
# The OpenHarmony SDK ships a usable host libclang.dylib plus the clang-c
# headers, but its LLVMExports.cmake references static libraries
# (libLLVMDemangle.a, ...) that the SDK does not ship, so
# find_package(Clang CONFIG) aborts before anything is built.
#
# shiboken consumes exactly three things:
#   * LLVM_PACKAGE_VERSION -> becomes -D LLVM_VERSION=<major>, which drives
#     clang_typedefs.h's "#if LLVM_VERSION >= 22" branch
#   * ${{CLANG_INCLUDE_DIRS}} -> clangparser includes clang-c/Index.h
#   * imported target "libclang" WITH IMPORTED_CONFIGURATIONS, because
#     setup_clang() reads IMPORTED_LOCATION_${{IMPORTED_CONFIGURATIONS}}

set(Clang_VERSION "15.0.4")
set(Clang_FOUND TRUE)
set(LLVM_PACKAGE_VERSION "15.0.4")
set(CLANG_INCLUDE_DIRS "{sdk}/llvm/include")
set(CLANG_LIBRARY_DIRS "{sdk}/llvm/lib")

if(NOT TARGET libclang)
  add_library(libclang SHARED IMPORTED)
  set_target_properties(libclang PROPERTIES
    IMPORTED_CONFIGURATIONS RELEASE
    IMPORTED_LOCATION_RELEASE "{libclang}"
    IMPORTED_LOCATION         "{libclang}"
    INTERFACE_INCLUDE_DIRECTORIES "{sdk}/llvm/include")
endif()
""")
    lib_only = build / 'clang-lib-only'
    lib_only.mkdir(parents=True, exist_ok=True)
    link = lib_only / 'libclang.dylib'
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(libclang)
    return {'clang_dir': str(shim), 'clang_lib_only': str(lib_only),
            'llvm_dir': str(sdk / 'llvm/lib/cmake/llvm')}


def stage_target_python(cpython: Path, build: Path) -> Path:
    """A prefix FindPython accepts for the CROSS-built interpreter.

    The private CPython tree keeps its headers in ``source/Include`` and the
    ABI config in ``objects/pyconfig.h``; CMake needs the usual
    ``include/python3.11`` + ``lib/libpython3.11.so`` layout.  The whole Include
    tree is copied because Python.h pulls in ``cpython/`` and ``internal/``.
    """
    prefix = build / 'target-python-prefix'
    includes = prefix / 'include/python3.11'
    libs = prefix / 'lib'
    includes.mkdir(parents=True, exist_ok=True)
    libs.mkdir(parents=True, exist_ok=True)
    include_src = cpython / 'source/Include'
    for entry in include_src.iterdir():
        target = includes / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)
    shutil.copy2(cpython / 'objects/pyconfig.h', includes / 'pyconfig.h')
    for name in ('libpython3.11.so.1.0', 'libpython3.11.so'):
        if (cpython / 'runtime/lib' / name).exists():
            shutil.copy2(cpython / 'runtime/lib' / name, libs / name)
    if not (libs / 'libpython3.11.so').exists():
        (libs / 'libpython3.11.so').symlink_to('libpython3.11.so.1.0')
    return prefix


def write_target_toolchain(build: Path, sdk: Path, qt: Path, py_prefix: Path) -> Path:
    path = build / 'ohos-aarch64-toolchain.cmake'
    path.write_text(TARGET_CMAKE.format(sdk=sdk, qt=qt, cpython=py_prefix, triple=TRIPLE))
    return path


def build_pyside(report: dict, qt: Path, sdk: Path, cpython: Path, src: Path,
                 build: Path, host_python: Path, rec: Recorder,
                 modules: str = 'Core') -> None:
    """The full PySide6 cross pipeline, in the order that actually works.

        1. host Qt + clang package shims
        2. shiboken6 generator   (host tool)
        3. libshiboken6 + Shiboken module   (target)
        4. PySide6 QtCore                   (target)
    """
    build.mkdir(parents=True, exist_ok=True)
    tool_env = dict(os.environ)
    tool_env['PATH'] = str(host_python.parent) + os.pathsep + tool_env.get('PATH', '')
    host_qt = probe_host_qt(report, qt)
    stage: dict = {'sdist_root': str(src), 'host_python': str(host_python)}
    roots = locate_sdist_roots(src)
    stage['located'] = {k: (str(v) if v else None) for k, v in roots.items()}
    report['pyside'] = stage

    if 'shiboken6' not in roots:
        stage['status'] = 'sdist_not_extracted'
        stage['blocker'] = ('PySide6 source tree not found under build/qtbind/src; '
                           'extract the sdist there first')
        return
    if not host_qt['host_qt_available']:
        stage['status'] = 'blocked_at_host_qt'
        stage['blocker'] = host_qt['blocker']
        return

    host_prefix = Path(host_qt['resolved_host_prefix'])
    clang = stage_clang_package(sdk, build)
    stage['clang_shims'] = clang
    py_prefix = stage_target_python(cpython, build)
    stage['target_python_prefix'] = str(py_prefix)
    toolchain = write_target_toolchain(build, sdk, qt, py_prefix)
    stage['toolchain_file'] = str(toolchain)
    soabi = 'cpython-311-aarch64-linux-ohos'

    cmake = host_python.parent / 'cmake'
    cmake_prefix = [str(cmake)] if cmake.exists() else [str(host_python), '-m', 'cmake']
    # ---- stage 1: host generator -------------------------------------------
    stage['generator_patch'] = patch_generator_sources(roots['setup'])
    gen_build = build / 'shiboken6-generator-host'
    gen_install = build / 'shiboken6-generator-install'
    stage['generator_configure'] = rec.run(
        'shiboken6_generator_configure',
        cmake_prefix + ['-S', str(roots['setup'] / 'sources/shiboken6_generator'),
                        '-B', str(gen_build), '-G', 'Ninja',
                        '-DCMAKE_BUILD_TYPE=Release',
                        f'-DCMAKE_PREFIX_PATH={host_prefix}',
                        f'-DQT_HOST_PATH={host_prefix}',
                        f'-DClang_DIR={clang["clang_dir"]}',
                        f'-DPython_EXECUTABLE={host_python}',
                        f'-DCMAKE_INSTALL_PREFIX={gen_install}'],
        timeout=900, env=tool_env)
    if stage['generator_configure']['status'] == 'ok':
        stage['generator_build'] = rec.run(
            'shiboken6_generator_build',
            cmake_prefix + ['--build', str(gen_build), '--parallel', '8'],
            timeout=2400, env=tool_env)
        if stage['generator_build']['status'] == 'ok':
            stage['generator_install'] = rec.run(
                'shiboken6_generator_install',
                cmake_prefix + ['--install', str(gen_build)], timeout=600, env=tool_env)
    generator_ok = stage.get('generator_install', {}).get('status') == 'ok'
    stage['generator_ready'] = generator_ok
    stage['generator_binary'] = str(gen_install / 'bin/shiboken6')
    if not generator_ok:
        stage['status'] = 'blocked_at_shiboken6_generator'
        stage['blocker'] = ('shiboken6 generator (host tool) could not be produced; '
                            'nothing downstream can be generated without it')
        return
    stage['generator_version'] = rec.run(
        'shiboken6_generator_version', [stage['generator_binary'], '--version'],
        timeout=120, env=tool_env)

    # ---- stage 2: libshiboken6 + Shiboken module, for the target -----------
    sb_build = build / 'shiboken6-target'
    sb_install = build / 'shiboken6-target-install'
    target_common = [
        f'-DCMAKE_TOOLCHAIN_FILE={toolchain}',
        '-DCMAKE_BUILD_TYPE=Release',
        f'-DPython_SOABI={soabi}',
        f'-DPython_ROOT_DIR={py_prefix}',
        f'-DPython_EXECUTABLE={host_python}',
        f'-DPYTHON_EXECUTABLE={host_python}',
        # The generator that shibokenmodule runs is a HOST tool.
        f'-DQFP_PYTHON_HOST_PATH={host_python}',
        f'-DSHIBOKEN_WRAPPER_HOST_CLANG_LIB_PATH={clang["clang_lib_only"]}',
        f'-DClang_DIR={clang["clang_dir"]}',
        f'-DQT_HOST_PATH={host_prefix}',
    ]
    # NOTE: exactly one CMAKE_PREFIX_PATH per configure. Passing a second one
    # later on the same command line makes CMake keep only the last value; that
    # previously hid Shiboken6 from the PySide6 configure step.
    stage['shiboken_configure'] = rec.run(
        'shiboken6_target_configure',
        cmake_prefix + ['-S', str(roots['shiboken6']), '-B', str(sb_build),
                        '-G', 'Ninja', '-DSHIBOKEN_IS_CROSS_BUILD=ON',
                        f'-DCMAKE_INSTALL_PREFIX={sb_install}',
                        f'-DCMAKE_PREFIX_PATH={qt}/lib/cmake;{gen_install};{host_prefix}']
        + target_common,
        timeout=900, env=tool_env)
    if stage['shiboken_configure']['status'] == 'ok':
        stage['shiboken_build'] = rec.run(
            'shiboken6_target_build',
            cmake_prefix + ['--build', str(sb_build), '--parallel', '8'],
            timeout=2400, env=tool_env)
        if stage['shiboken_build']['status'] == 'ok':
            stage['shiboken_install'] = rec.run(
                'shiboken6_target_install',
                cmake_prefix + ['--install', str(sb_build)], timeout=600, env=tool_env)
    if stage.get('shiboken_install', {}).get('status') != 'ok':
        stage['status'] = 'blocked_at_shiboken6_target'
        return
    stage['shiboken6_target_artifacts'] = describe_target_libs(sdk, sb_build)

    # ---- stage 3: PySide6 QtCore, for the target --------------------------
    slug = 'qtcore' if modules == 'Core' else 'qt' + modules.replace(';', '').lower()
    ps_build = build / f'pyside6-{slug}-target'
    ps_install = build / f'pyside6-{slug}-install'
    # The generator must parse as the OHOS target: compiler discovery args plus
    # the OHOS predefines that OHOS libc++ keys off (__OHOS__ selects the musl
    # xlocale support header, __OHOS_FAMILY__ the default rune table).
    generator_flags = [
        '--platform=linux', '--arch=arm64', '--compiler=clang',
        f'--compiler-path={sdk}/llvm/bin/clang++',
        f'--compiler-argument=--target={TRIPLE}',
        f'--compiler-argument=--sysroot={sdk}/sysroot',
        '--compiler-argument=-D__OHOS__=1',
        '--compiler-argument=-D__OHOS_FAMILY__=1',
        '--compiler-argument=-D__MUSL__=1',
        '--compiler-argument=-D_GNU_SOURCE',
        f'--include-paths={qt}/include',
        f'--include-paths={qt}/include/QtCore',
    ]
    stage['generator_extra_flags'] = generator_flags
    # OHOS is bionic like Android: an extension module needs an explicit NEEDED
    # entry for libpython (PySide skips it for POSIX, relying on process symbols).
    py_link = f'-L{py_prefix}/lib -l:libpython3.11.so.1.0'
    stage['pyside_configure'] = rec.run(
        'pyside6_configure',
        cmake_prefix + ['-S', str(roots['pyside6']), '-B', str(ps_build),
                        f'-G', 'Ninja', f'-DMODULES={modules}', '-DPYSIDE_IS_CROSS_BUILD=ON',
                        f'-DSHIBOKEN_GENERATOR_EXTRA_FLAGS={";".join(generator_flags)}',
                        f'-DCMAKE_MODULE_LINKER_FLAGS={py_link}',
                        f'-DCMAKE_SHARED_LINKER_FLAGS={py_link}',
                        '-DCMAKE_INSTALL_RPATH=$ORIGIN/../lib',
                        '-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON',
                        f'-DCMAKE_INSTALL_PREFIX={ps_install}',
                        f'-DCMAKE_PREFIX_PATH={qt}/lib/cmake;{sb_install};{gen_install};{host_prefix}']
        + target_common, timeout=900, env=tool_env)
    if stage['pyside_configure']['status'] == 'ok':
        stage['pyside_build'] = rec.run(
            'pyside6_build',
            cmake_prefix + ['--build', str(ps_build), '--parallel', '8'],
            timeout=3600, env=tool_env)
        if stage['pyside_build']['status'] == 'ok':
            stage['pyside_install'] = rec.run(
                'pyside6_install',
                cmake_prefix + ['--install', str(ps_build)], timeout=600, env=tool_env)
            # PySide bakes the BUILD-machine Qt lib dir into RUNPATH; rewrite it
            # to a relocatable one for the device.
            patches = []
            for pattern in ('*.so*',):
                for so in sorted(ps_install.rglob(pattern)):
                    if so.is_symlink() or not so.is_file():
                        continue
                    result = patch_runpath(so, '$ORIGIN/../lib')
                    if result.get('status') in ('patched', 'new_runpath_too_long'):
                        patches.append(result)
            stage['runpath_patches'] = patches
            stage['pyside_artifacts'] = describe_target_libs(sdk, ps_install)
            stage['symbol_closure'] = verify_symbol_closure(sdk, qt, ps_install, sb_install)
            stage['status'] = 'bindings_cross_compiled'
        else:
            stage['status'] = 'blocked_at_pyside_compile'
            stage['blocker'] = (
                'the shiboken6 generator runs but parses the target sources with '
                'HOST include paths, so it fails on libc++/bionic headers '
                "(e.g. 'features.h' file not found). Pass the OHOS sysroot "
                'include dirs to the generator (--include-paths / '
                '--system-include-paths, or GENERATOR_EXTRA_FLAGS).')
    else:
        stage['status'] = 'blocked_at_pyside_configure'



QT_LIBS = ('libQt6Core.so', 'libQt6Gui.so', 'libQt6Widgets.so', 'libQt6Network.so',
           'libQt6OpenGL.so', 'libQt6OpenGLWidgets.so', 'libQt6PrintSupport.so',
           'libQt6Sql.so', 'libQt6Xml.so', 'libQt6Concurrent.so', 'libQt6Test.so')


def _sidestage_install(build: Path, modules: str) -> Path:
    slug = 'qtcore' if modules == 'Core' else 'qt' + modules.replace(';', '').lower()
    return build / f'pyside6-{slug}-install'


def write_deploy_manifest(qt: Path, sdk: Path, cpython: Path, sb_install: Path,
                          ps_install: Path, out_dir: Path) -> dict:
    """Emit the exact file list a HAP build must stage into libs/arm64-v8a.

    Everything here is a decision we already made the hard way, so it is written
    down once instead of being rediscovered at packaging time.
    """
    py_site = ps_install / 'lib/python3.11/site-packages/PySide6'
    entries: list[dict] = []

    def add(source: Path, dest_name: str, note: str) -> None:
        entries.append({'source': str(source), 'dest': f'libs/arm64-v8a/{dest_name}',
                        'present': source.exists(), 'note': note})

    for name in QT_LIBS:
        add(qt / 'lib' / name, name, 'official Qt 6.12.0 HarmonyOS prebuilt')
    add(qt / 'plugins/platforms/libqohos.so', 'libqohos.so',
        'QPA plugin: without it QApplication cannot be created')
    # Not in the sysroot: ships with the clang runtime only.
    add(sdk / f'llvm/lib/{TRIPLE}/libc++_shared.so', 'libc++_shared.so',
        'NOT in sysroot - must be copied from the SDK clang runtime')
    add(sb_install / 'lib/libshiboken6.abi3.so.6.12', 'libshiboken6.abi3.so.6.12',
        'shiboken6 runtime, cross-built')
    add(ps_install / 'PySide6/libpyside6.abi3.so.6.12', 'libpyside6.abi3.so.6.12',
        'PySide6 runtime, cross-built')
    for so in sorted(py_site.glob('*.abi3.so')):
        add(so, f'PySide6/{so.name}',
            f'{so.stem} binding (.abi3: loadable by CPython 3.11)')

    python_side = []
    for rel in ('__init__.py', '_config.py', '_git_pyside_version.py', 'support',
                'QtAsyncio'):
        candidate = py_site / rel
        if candidate.exists():
            python_side.append({'path': f'PySide6/{rel}', 'source': str(candidate),
                                'kind': 'dir' if candidate.is_dir() else 'file'})

    manifest = {
        'target_lib_dir': 'app/entry/libs/arm64-v8a',
        'runtime_python_dir': 'PySide6 (under the app python site-packages)',
        'native': entries,
        'python_package': python_side,
        'missing': [e for e in entries if not e['present']],
        'runpath_note': ("Every cross-built .so is rewritten to RUNPATH "
                         "$ORIGIN/../lib; the Qt prebuilt keeps "
                         "/usr/local/Qt-6.12.0/lib, so either stage the Qt libs "
                         "next to the Python extension lib dir or patchelf them "
                         "to $ORIGIN."),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'deploy-manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    lines = ['# files for app/entry/libs/arm64-v8a', '']
    for e in entries:
        lines.append(f"{'OK ' if e['present'] else 'MISS'} {e['dest']:<34} <- {e['source']}")
        lines.append(f"     {e['note']}")
    lines += ['', '# python side (PySide6 package)', '']
    for e in python_side:
        lines.append(f"     PySide6/{e['path'].split('PySide6/', 1)[-1]:<28} <- {e['source']}")
    (out_dir / 'deploy-manifest.txt').write_text('\n'.join(lines) + '\n')
    return manifest



def _exported_symbols(sdk: Path, path: Path) -> set[str]:
    readelf = sdk / 'llvm/bin/llvm-readelf'
    text = subprocess.run([str(readelf), '--dyn-syms', str(path)],
                          capture_output=True, text=True).stdout
    out: set[str] = set()
    for line in text.splitlines():
        fields = line.split()
        if re.match(r'^\s*\d+:', line) and len(fields) >= 8 and fields[6] != 'UND':
            out.add(fields[-1].split('@', 1)[0])
    return out


def verify_symbol_closure(sdk: Path, qt: Path, ps_install: Path, sb_install: Path) -> dict:
    """Every C++ symbol a binding imports must be exported by one of its NEEDED libs.

    This is the link-time stand-in for running the GUI on a device: it proves the
    cross-built bindings bind to the prebuilt Qt, our own libpyside6/libshiboken6
    and the SDK's libc++_shared.so with no dangling C++ references.
    """
    qt_syms = set()
    for name in ('libQt6Core.so', 'libQt6Gui.so', 'libQt6Widgets.so'):
        candidate = qt / 'lib' / name
        if candidate.exists():
            qt_syms |= _exported_symbols(sdk, candidate)
    own = set()
    for candidate in (ps_install / 'PySide6/libpyside6.abi3.so.6.12',
                      sb_install / 'lib/libshiboken6.abi3.so.6.12'):
        if candidate.exists():
            own |= _exported_symbols(sdk, candidate)
    libcpp = sdk / f'llvm/lib/{TRIPLE}/libc++_shared.so'
    cpp_syms = _exported_symbols(sdk, libcpp) if libcpp.exists() else set()

    site = ps_install / 'lib/python3.11/site-packages/PySide6'
    results = []
    readelf = sdk / 'llvm/bin/llvm-readelf'
    for so in sorted(site.glob('*.abi3.so')):
        text = subprocess.run([str(readelf), '--dyn-syms', str(so)],
                              capture_output=True, text=True).stdout
        imported = {m.split('@', 1)[0] for m in re.findall(r'UND\s+(\S+)', text)
                    if m.startswith('_ZN')}
        from_qt = {s for s in imported if s in qt_syms}
        from_own = {s for s in imported if s not in from_qt and s in own}
        from_cpp = {s for s in imported if s not in from_qt and s not in from_own
                    and s in cpp_syms}
        missing = sorted(imported - from_qt - from_own - from_cpp)
        results.append({'module': so.name, 'imported': len(imported),
                        'from_qt': len(from_qt), 'from_pyside_shiboken': len(from_own),
                        'from_libcxx_shared': len(from_cpp), 'unresolved': missing,
                        'closure': 'closed' if not missing else 'open'})
    return {'libcxx_shared': str(libcpp), 'modules': results,
            'all_closed': all(r['closure'] == 'closed' for r in results)}

def describe_target_libs(sdk: Path, root: Path) -> list[dict]:
    """Record the ELF facts of every target artefact we produced."""
    readelf = sdk / 'llvm/bin/llvm-readelf'
    out: list[dict] = []
    for so in sorted(root.rglob('*.so*')):
        if so.is_symlink() or not so.is_file():
            continue
        header = subprocess.run([str(readelf), '-h', str(so)],
                                capture_output=True, text=True).stdout
        machine = re.search(r'Machine:\s+(.+)', header)
        entry = {'path': str(so), 'bytes': so.stat().st_size,
                 'machine': machine.group(1).strip() if machine else None,
                 'needed': dump_needed(sdk, so),
                 'runpath': dump_runpath(sdk, so),
                 'sha256': sha256(so)}
        out.append(entry)
    return out
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qt', type=Path,
                        default=ROOT / 'build/qt/prebuilt/harmonyos-arm64')
    parser.add_argument('--sdk', type=Path, default=DEFAULT_SDK)
    parser.add_argument('--cpython', type=Path,
                        default=ROOT / 'build/cpython-3.11.18/ohos-aarch64-with-libffi-linked')
    parser.add_argument('--src', type=Path, default=ROOT / 'build/qtbind/src')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/qtbind/out')
    parser.add_argument('--build', type=Path, default=ROOT / 'build/qtbind/build')
    parser.add_argument('--host-python', type=Path,
                        default=ROOT / 'build/host-python/cpython-3.11.17-macos-aarch64-none/bin/python3.11')
    parser.add_argument('--report', type=Path, default=None)
    parser.add_argument('--modules', default='Core',
                        help='PySide6 modules, no Qt prefix (default: Core; '
                             'use Core;Gui;Widgets for the full UI stack)')
    parser.add_argument('--skip-pyside', action='store_true',
                        help='only run the Qt inspection and the ABI probe')
    args = parser.parse_args()

    day = datetime.now(timezone.utc).date().isoformat()
    report_path = args.report or ROOT / f'reports/qtbinding-{day}.json'
    rec = Recorder()
    report: dict = {
        'schema_version': 1,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'target': TRIPLE,
        'host_executed': False,
        'host_tools_only': ['cmake', 'ninja', 'shiboken6 generator'],
        'qt_root': str(args.qt),
        'sdk': str(args.sdk),
        'cpython': str(args.cpython),
    }

    try:
        clang = args.sdk / 'llvm/bin/clang++'
        for required in (clang, args.qt / 'lib/libQt6Core.so',
                         args.cpython / 'source/Include/Python.h',
                         args.cpython / 'objects/pyconfig.h',
                         args.cpython / 'runtime/lib/libpython3.11.so.1.0'):
            if not required.exists():
                raise RuntimeError(f'missing build input: {required}')

        inspect_qt(report, args.qt, args.sdk, args.cpython, rec)
        build_abi_probe(report, args.qt, args.sdk, args.cpython, args.out, rec)
        build_widgets_probe(report, args.qt, args.sdk, args.cpython, args.out, rec)
        if not args.skip_pyside:
            build_pyside(report, args.qt, args.sdk, args.cpython, args.src,
                         args.build, args.host_python, rec, args.modules)

        abi_ok = (report.get('abi_probe', {}).get('abi_linkable', False)
                  and report.get('widgets_probe', {}).get('widgets_surface_linkable', False))
        pyside = report.get('pyside', {})
        if abi_ok and pyside.get('status') == 'bindings_cross_compiled':
            report['status'] = (f"pyside6_{args.modules.replace(';', '').lower()}"
                                '_cross_compiled_not_target_tested')
        elif abi_ok:
            stage_status = (pyside.get('status') or 'not_attempted')
            if stage_status.startswith('blocked_at_'):
                stage_status = stage_status[len('blocked_at_'):]
            report['status'] = 'abi_linkable_binding_blocked_at_' + stage_status
        else:
            report['status'] = 'abi_probe_failed'
        report['verdict'] = {
            'qt_prebuilt_usable': report.get('qt_prebuilt', {}).get('needed_all_resolvable'),
            'host_qt_ready': report.get('host_qt', {}).get('host_qt_available'),
            'abi_linkable': abi_ok,
            'shiboken_generator_ready': bool(pyside.get('generator_ready')),
            'shiboken_target_built': bool(pyside.get('shiboken6_target_artifacts')),
            'binding_generated': bool(pyside.get('status') == 'bindings_cross_compiled'),
        }
    except Exception as error:  # noqa: BLE001 - the report is the deliverable
        report['status'] = 'qtbinding_build_failed'
        report['error'] = str(error)[:3000]

    try:
        pyside = report.get('pyside') or {}
        if pyside.get('status') == 'bindings_cross_compiled':
            report['deploy_manifest'] = write_deploy_manifest(
                args.qt, args.sdk, args.cpython,
                args.build / 'shiboken6-target-install',
                _sidestage_install(args.build, args.modules), args.out)
    except Exception as error:  # noqa: BLE001 - manifest is informational
        report['deploy_manifest_error'] = str(error)[:500]

    report['steps'] = rec.steps
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(report['status'])
    print('verdict:', json.dumps(report.get('verdict', {}), ensure_ascii=False))
    for step in rec.steps:
        if step['status'] not in ('ok',):
            print(f"  !! {step['name']}: {step['status']}")
            print('    ', (step.get('stderr_tail') or step.get('error') or '')[-600:].replace('\n', '\n     '))
    return 0 if report['status'].startswith(('qtcore_binding', 'abi_linkable')) else 1


if __name__ == '__main__':
    raise SystemExit(main())
