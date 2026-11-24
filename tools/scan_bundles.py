#!/usr/bin/env python3
"""Static dependency inventory of the upstream ChimeraX bundles.

Walks ``build/downloads/ChimeraX-src/src/bundles`` (read only, never written)
and classifies every bundle along the axes that decide how hard it is to bring
up on HarmonyOS/OHOS:

* Python-only vs. requiring a compiled extension (C++/Cython)
* Qt binding usage (``Qt.QtCore`` shim or a direct PyQt6/PySide6 import)
* PyOpenGL (``OpenGL.*``) usage
* third-party top-level imports outside the stdlib and ``chimerax.*``
* PEG / Cython sources that need a code-generation step before build
* declared ``<Dependencies>`` from ``bundle_info.xml``

The output is an array of records, one per bundle, in stable name order; every
list inside a record is sorted, so repeated runs produce byte-identical files.
Nothing here compiles, imports ChimeraX, or touches a device.

Usage::

    python3 tools/scan_bundles.py                     # write report + summary
    python3 tools/scan_bundles.py --stdout            # print the array only
    python3 tools/scan_bundles.py --check             # compare, do not write
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / 'build' / 'downloads' / 'ChimeraX-src'
BUNDLE_ROOT = SRC_ROOT / 'src' / 'bundles'
REPORT_PATH = ROOT / 'reports' / 'bundle-matrix-2026-11-17.json'
SUMMARY_PATH = ROOT / 'reports' / 'bundle-matrix-2026-11-17.summary.json'

CPP_EXTS = {'.cpp', '.cxx', '.cc'}
HEADER_EXTS = {'.h', '.hpp', '.hxx'}
PYX_EXTS = {'.pyx', '.pxd', '.pxi'}

# Task-mandated probe set for "this bundle needs Qt bindings".
QT_RE = re.compile(r'\b(PyQt6|PySide6|QtCore|QtWidgets|QtGui|QtOpenGL)\b')
# Statement-anchored so that ``chimerax.graphics.OpenGLContext`` (ChimeraX's own
# shim class) is not misread as a PyOpenGL dependency.
OPENGL_RE = re.compile(
    r'^[ \t]*(?:from[ \t]+(OpenGL(?:\.\w+)*)[ \t]+import|import[ \t]+(OpenGL(?:\.\w+)*))',
    re.MULTILINE,
)
# Modules that get their own dedicated field and must not pollute third-party.
DEDICATED = {'chimerax', 'Qt', 'OpenGL', 'PyQt6', 'PySide6'}
# Dead py2 / Chimera-1.x imports still present in unmaintained code paths. They
# are reported but must not drive porting effort: the code that uses them is
# never reached in ChimeraX 1.11.
LEGACY = {
    # Chimera 1.x module names that still linger in ported code paths.
    'Matrix', 'VolumePath', 'VolumeData', 'VolumeFilter', 'VolumeViewer',
    'Molecule', 'Midas', 'Commands', 'CGLtk', 'SimpleSession', 'Surface',
    'SurfaceCap', 'SurfaceZone', 'Symmetry', 'replyobj', 'chimera', 'prefs',
    'volume', 'Tkinter', 'wx', 'gor', 'selectregion',
    # py2 leftovers
    'StringIO', 'cStringIO', 'xmlrpclib',
    # Windows-only
    'win32', 'win32api', 'win32con', 'win32gui', 'win32process', 'winreg', 'wmi',
    'comtypes',
}

# ``import X`` inside a docstring or comment block is common in this tree; the
# AST pass is authoritative and this is only the fallback for unparsable files.
FALLBACK_IMPORT_RE = re.compile(
    r'^[ \t]*(?:from[ \t]+([A-Za-z_][\w.]*)[ \t]+import|import[ \t]+([A-Za-z_][\w.]*))',
    re.MULTILINE,
)

STDLIB = set(getattr(sys, 'stdlib_module_names', ()))
# Present on every supported CPython < 3.12 as stdlib; keeps the report honest
# when the scanner itself runs on a newer interpreter.
STDLIB |= {
    'abc', 'argparse', 'array', 'asyncio', 'base64', 'binascii', 'bisect', 'builtins',
    'bz2', 'calendar', 'cmath', 'codecs', 'collections', 'colorsys', 'concurrent',
    'configparser', 'contextlib', 'copy', 'csv', 'ctypes', 'curses', 'dataclasses',
    'datetime', 'dbm', 'decimal', 'difflib', 'enum', 'errno', 'faulthandler', 'fcntl',
    'filecmp', 'fileinput', 'fnmatch', 'fractions', 'ftplib', 'functools', 'gc',
    'getpass', 'gettext', 'glob', 'grp', 'gzip', 'hashlib', 'heapq', 'hmac', 'html',
    'http', 'imaplib', 'importlib', 'inspect', 'io', 'ipaddress', 'itertools', 'json',
    'keyword', 'linecache', 'locale', 'logging', 'lzma', 'math', 'mimetypes', 'mmap',
    'multiprocessing', 'netrc', 'numbers', 'operator', 'os', 'pathlib', 'pdb',
    'pickle', 'pkgutil', 'platform', 'plistlib', 'pprint', 'profile', 'pstats',
    'pwd', 'queue', 'quopri', 'random', 're', 'readline', 'reprlib', 'resource',
    'rlcompleter', 'secrets', 'select', 'selectors', 'shlex', 'shutil', 'signal',
    'site', 'smtplib', 'socket', 'socketserver', 'sqlite3', 'ssl', 'stat',
    'statistics', 'string', 'stringprep', 'struct', 'subprocess', 'sys', 'sysconfig',
    'tarfile', 'tempfile', 'termios', 'textwrap', 'threading', 'time', 'timeit',
    'token', 'tokenize', 'traceback', 'tracemalloc', 'types', 'typing', 'unicodedata',
    'unittest', 'urllib', 'uuid', 'venv', 'warnings', 'wave', 'weakref', 'webbrowser',
    'xml', 'xmlrpc', 'zipfile', 'zipimport', 'zlib', 'zoneinfo',
}


def _norm(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', name.lower())


def _bundle_index(names: list[str]) -> dict[str, str]:
    """Map normalised bundle names (and their ``*_lib`` stems) to bundle dirs."""
    exact: dict[str, str] = {}
    stem: dict[str, str] = {}
    for name in names:
        exact.setdefault(_norm(name), name)
        if name.endswith('_lib'):
            stem.setdefault(_norm(name)[:-3], name)
    return {'exact': exact, 'stem': stem}


def resolve_dependency(raw: str, index: dict[str, dict[str, str]],
                       names: list[str]) -> str:
    """Turn a ``ChimeraX-Foo`` dependency name into a bundle directory name."""
    dep = raw.strip()
    if dep.lower().startswith('chimerax-'):
        dep = dep[len('chimerax-'):]
    key = _norm(dep)
    is_lib = key.endswith('library') or key.endswith('lib')
    base = key[:-len('library')] if key.endswith('library') else (
        key[:-3] if key.endswith('lib') else key)
    # "ChimeraX-AtomicLibrary" -> the *_lib bundle; plain names -> the plain one.
    if is_lib and base in index['stem']:
        return index['stem'][base]
    if key in index['exact']:
        return index['exact'][key]
    if base in index['stem']:
        return index['stem'][base]
    if base in index['exact']:
        return index['exact'][base]
    return raw.strip()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


class _ImportVisitor(ast.NodeVisitor):
    """Collect absolute imports, tagging those that run at module import time.

    ChimeraX defers a lot of imports into functions (``def draw(self): from
    chimerax.map import ...``) and guards type-only imports with
    ``if TYPE_CHECKING``. Those do not constrain which bundles must exist for
    ``import chimerax.atomic`` to succeed, so they are recorded separately.
    """

    #: (module, tier, level); tier is "required", "optional" or "deferred".
    def __init__(self) -> None:
        self.records: list[tuple[str, str, int]] = []
        self._deferred = 0
        self._optional = 0

    def _add(self, module: str | None, level: int = 0) -> None:
        if not module or module.startswith('.'):
            return
        if self._deferred:
            tier = 'deferred'
        elif self._optional:
            tier = 'optional'
        else:
            tier = 'required'
        self.records.append((module, tier, level))

    def visit_FunctionDef(self, node: ast.AST) -> None:
        self._deferred += 1
        self.generic_visit(node)
        self._deferred -= 1

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def visit_If(self, node: ast.If) -> None:
        # ``if TYPE_CHECKING: from x import Y`` never executes at runtime.
        test = ast.dump(node.test) if node.test is not None else ''
        if 'TYPE_CHECKING' in test or 'TYPE_CHECKING' in ast.dump(node):
            self._deferred += 1
            for child in node.body:
                self.visit(child)
            self._deferred -= 1
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        # ``try: import chimerax.ui except ImportError:`` at module scope is a
        # soft dependency: the bundle still imports when it is absent.
        self._optional += 1
        self.generic_visit(node)
        self._optional -= 1

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # level > 0 keeps the import inside the bundle; the entry-chain scan
        # follows those, the third-party scan ignores them.
        self._add(node.module, node.level)


def scan_bundle_info(path: Path) -> dict:
    """Read ``package``, ``purePython`` flag and ``<Dependencies>`` declarations."""
    info = {'package': None, 'pure_python_flag': None, 'deps': [], 'build_deps': []}
    text = _read_text(path)
    if not text:
        return info
    tag = re.search(r'<BundleInfo\b([^>]*)>', text)
    head = tag.group(1) if tag else ''
    m = re.search(r'package\s*=\s*"([^"]+)"', head)
    if m:
        info['package'] = m.group(1)
    m = re.search(r'purePython\s*=\s*"([^"]+)"', head)
    if m:
        info['pure_python_flag'] = m.group(1).strip().lower() == 'true'
    block = re.search(r'<Dependencies>(.*?)</Dependencies>', text, re.DOTALL)
    if block:
        for tag in re.finditer(r'<Dependency\b([^>]*)>', block.group(1)):
            attrs = tag.group(1)
            nm = re.search(r'name\s*=\s*"([^"]+)"', attrs)
            if not nm:
                continue
            info['deps'].append(nm.group(1))
            if re.search(r'build\s*=\s*"true"', attrs):
                info['build_deps'].append(nm.group(1))
    info['deps'] = sorted(dict.fromkeys(info['deps']))
    info['build_deps'] = sorted(dict.fromkeys(info['build_deps']))
    return info


def module_roots(rel: str) -> set[str]:
    """Top-level components of a relative path, used to name the owning dir."""
    parts = rel.split('/')
    return {parts[0]} if len(parts) > 1 else set()


def scan_python(bundle: Path, py_files: list[Path]) -> dict:
    qt_hits: set[str] = set()
    qt_kinds: set[str] = set()
    qt_files: set[str] = set()
    gl_hits: set[str] = set()
    gl_files: set[str] = set()
    numpy = False
    third: set[str] = set()
    internal: set[str] = set()
    tops: set[str] = set()
    required: set[str] = set()
    optional: set[str] = set()
    unparsable: list[str] = []

    local = {p.stem for p in py_files}
    for sub in ('src',):
        d = bundle / sub
        if d.is_dir():
            local |= {p.name for p in d.iterdir() if p.is_dir()}
    local |= {'chimerax'}

    for f in py_files:
        text = _read_text(f)
        if not text:
            continue
        for m in QT_RE.finditer(text):
            qt_hits.add(m.group(1))
            qt_files.add(str(f.relative_to(bundle)))
        # Distinguish the ChimeraX Qt shim from a direct bindings import.
        if re.search(r'^[ \t]*(?:from[ \t]+Qt\.[A-Za-z]+|import[ \t]+Qt\b)', text, re.M):
            qt_kinds.add('shim')
        if re.search(r'^[ \t]*(?:from[ \t]+(?:PyQt6|PySide6)\b|import[ \t]+(?:PyQt6|PySide6)\b)',
                     text, re.M):
            qt_kinds.add('direct')

        for m in OPENGL_RE.finditer(text):
            mod = m.group(1) or m.group(2)
            gl_hits.add(mod.split('.')[0])
            gl_files.add(str(f.relative_to(bundle)))

        try:
            with warnings.catch_warnings():
                # Upstream has invalid regex escapes in docstrings; they are noise here.
                warnings.simplefilter('ignore', SyntaxWarning)
                tree = ast.parse(text, filename=str(f))
        except (SyntaxError, ValueError):
            unparsable.append(str(f.relative_to(bundle)))
            for m in FALLBACK_IMPORT_RE.finditer(text):
                mod = m.group(1) or m.group(2)
                if not mod or mod.startswith('.'):
                    continue
                parts = mod.split('.')
                tops.add(parts[0])
                if parts[0] == 'chimerax' and len(parts) > 1:
                    internal.add(parts[1])
        else:
            visitor = _ImportVisitor()
            visitor.visit(tree)
            for mod, tier, level in visitor.records:
                if level:
                    continue
                parts = mod.split('.')
                tops.add(parts[0])
                if parts[0] == 'chimerax' and len(parts) > 1:
                    internal.add(parts[1])
                    if tier == 'required':
                        required.add(parts[1])
                    elif tier == 'optional':
                        optional.add(parts[1])

        for top in tops:
            if not top or top == '_' or top.startswith('_') and top.endswith('_'):
                continue
            if top in DEDICATED or top in STDLIB or top in local:
                continue
            third.add(top)
            if top == 'numpy':
                numpy = True

    return {
        'imports_qt': bool(qt_hits),
        'qt_modules': sorted(qt_hits),
        'qt_import_kinds': sorted(qt_kinds),
        'qt_files': sorted(qt_files),
        'imports_opengl': bool(gl_hits),
        'opengl_modules': sorted(gl_hits),
        'opengl_files': sorted(gl_files),
        'imports_numpy': numpy,
        'third_party_imports': sorted(third),
        'imports_chimerax': sorted(internal),
        # ChimeraX defers most heavy imports into functions. The two sets below
        # decide whether a bundle can be brought up on its own: "required" must
        # exist for ``import chimerax.<name>`` to succeed, "optional" is behind
        # a try/except and only degrades a feature.
        'imports_chimerax_required': sorted(required - {bundle.name}),
        'imports_chimerax_optional': sorted(optional - {bundle.name}),
        'unparsable_python_files': sorted(unparsable),
    }


def _module_key(rel: str) -> str:
    """``foo/bar.py`` -> ``foo.bar``; ``foo/__init__.py`` -> ``foo``."""
    rel = rel.replace('\\', '/')
    if rel.endswith('/__init__.py'):
        rel = rel[:-len('/__init__.py')]
    elif rel == '__init__.py':
        return ''
    else:
        rel = rel[:-len('.py')] if rel.endswith('.py') else rel
    return rel.replace('/', '.')


def _resolve_relative(module_key: str, level: int, module: str | None) -> str | None:
    """Resolve ``from ..a.b import c`` inside a bundle to a bundle module key."""
    parts = module_key.split('.') if module_key else []
    # level 1 means "current package", so drop (level - 1) components.
    if level - 1 > len(parts):
        return None
    base = parts[:len(parts) - (level - 1)] if level > 1 else parts
    if module:
        base = base + module.split('.')
    return '.'.join(base) if base else ''


def scan_entry_chain(bundle: Path, pkg_subdir: str = 'src') -> dict:
    """What ``import chimerax.<name>`` actually pulls in.

    Walks only the modules reachable from ``src/__init__.py`` through
    import-time (unguarded) relative imports. A bundle may contain 30 modules
    yet load 3 of them on import, and that difference decides whether the
    bundle can be staged before its Qt/OpenGL dependencies exist.
    """
    root = bundle / pkg_subdir
    entry = root / '__init__.py'
    if not entry.is_file():
        return {'entry_module_count': 0, 'entry_requires': [],
                'entry_requires_optional': [], 'entry_imports_qt': False,
                'entry_imports_opengl': False, 'entry_requires_qt': False,
                'entry_requires_opengl': False}
    modules = {_module_key(str(p.relative_to(root)).replace('\\', '/')): p
               for p in root.rglob('*.py')}
    seen: set[str] = set()
    required: set[str] = set()
    optional: set[str] = set()
    qt = gl = False          # any tier, reachable at import
    qt_hard = gl_hard = False  # unguarded (required) tier only
    queue = ['']
    while queue:
        key = queue.pop()
        if key in seen or key not in modules:
            continue
        seen.add(key)
        text = _read_text(modules[key])
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', SyntaxWarning)
                tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        visitor = _ImportVisitor()
        visitor.visit(tree)
        for mod, tier, level in visitor.records:
            # Qt/PyOpenGL only matter here when a reachable module imports them
            # at import time; ChimeraX defers nearly all of them into functions.
            if not level and tier != 'deferred':
                root_mod = mod.split('.')[0]
                if root_mod in ('Qt', 'PyQt6', 'PySide6'):
                    qt = True
                    qt_hard = qt_hard or tier == 'required'
                elif root_mod == 'OpenGL':
                    gl = True
                    gl_hard = gl_hard or tier == 'required'
            if level:
                # Stays inside this bundle: follow it as part of the same chain.
                if tier == 'deferred':
                    continue
                target = _resolve_relative(key, level, mod)
                if target is not None:
                    queue.append(target)
                continue
            if mod.startswith('chimerax.'):
                parts = mod.split('.')
                if len(parts) > 1 and parts[1] == bundle.name:
                    # A deferred self-import inside a function does not run at
                    # import time, so it must not extend the chain either.
                    if tier == 'deferred':
                        continue
                    queue.append('.'.join(parts[2:]))
                elif tier == 'required':
                    required.add(parts[1])
                elif tier == 'optional':
                    optional.add(parts[1])
    return {
        'entry_module_count': len(seen),
        'entry_requires': sorted(required - {bundle.name}),
        'entry_requires_optional': sorted(optional - {bundle.name}),
        'entry_imports_qt': qt,
        'entry_imports_opengl': gl,
        'entry_requires_qt': qt_hard,
        'entry_requires_opengl': gl_hard,
    }


def scan_bundle(bundle: Path) -> dict:
    name = bundle.name
    rel_files = sorted(
        str(p.relative_to(bundle)).replace('\\', '/')
        for p in bundle.rglob('*') if p.is_file()
    )

    def pick(exts: set[str]) -> list[str]:
        return [r for r in rel_files if Path(r).suffix in exts]

    cpp_sources = pick(CPP_EXTS)
    cpp_headers = pick(HEADER_EXTS)
    cython = pick(PYX_EXTS)
    peg = [r for r in rel_files if Path(r).suffix == '.peg']
    py_rel = pick({'.py'})
    py_files = [bundle / r for r in py_rel]

    # A .cpp can also sit directly in the bundle root (e.g. spacenavigator).
    cpp_dirs = sorted({r.split('/')[0] if '/' in r else '<root>'
                       for r in cpp_sources + cython})
    # Some bundles only carry C++ as test fixtures (bundle_builder); they are not
    # shipped extensions and must not be prioritised like atomic_lib.
    cpp_test_only = bool(cpp_sources or cython) and all(
        r.startswith('tests/') for r in cpp_sources + cython)

    pkg_dir = bundle / 'src'
    has_pkg = pkg_dir.is_dir() and any(pkg_dir.rglob('*.py'))
    pkg_py = [r for r in py_rel if r.startswith('src/')]
    py_count = len(pkg_py) if has_pkg else len(py_rel)

    info = {'package': None, 'pure_python_flag': None, 'deps': [], 'build_deps': []}
    for candidate in ('bundle_info.xml', 'bundle_info.xml.in'):
        p = bundle / candidate
        if p.is_file():
            info = scan_bundle_info(p)
            break

    py = scan_python(bundle, py_files)
    entry = scan_entry_chain(bundle)

    has_cpp = bool(cpp_sources or cython)
    record = {
        'name': name,
        'package': info['package'] or (f'chimerax.{name}' if has_pkg else None),
        'has_python_package': has_pkg,
        'python_file_count': py_count,
        'python_file_count_total': len(py_rel),
        'has_cpp_extension': has_cpp,
        'cpp_components': cpp_dirs,
        'cpp_source_count': len(cpp_sources),
        'cpp_header_count': len(cpp_headers),
        'cython_source_count': len(cython),
        'cpp_source_files': sorted(cpp_sources + cython),
        'cpp_test_only': cpp_test_only,
        'has_pyx': bool(cython),
        'has_peg': bool(peg),
        'peg_files': sorted(peg),
        'imports_qt': py['imports_qt'],
        'qt_modules': py['qt_modules'],
        'qt_import_kinds': py['qt_import_kinds'],
        'qt_file_count': len(py['qt_files']),
        'qt_files': py['qt_files'],
        'imports_opengl': py['imports_opengl'],
        'opengl_modules': py['opengl_modules'],
        'opengl_file_count': len(py['opengl_files']),
        'opengl_files': py['opengl_files'],
        'imports_numpy': py['imports_numpy'],
        'third_party_imports': py['third_party_imports'],
        'imports_chimerax': py['imports_chimerax'],
        'imports_chimerax_required': py['imports_chimerax_required'],
        'imports_chimerax_optional': py['imports_chimerax_optional'],
        # Reachability from src/__init__.py: what ``import chimerax.<name>`` costs.
        'entry_module_count': entry['entry_module_count'],
        'entry_requires': entry['entry_requires'],
        'entry_requires_optional': entry['entry_requires_optional'],
        'entry_imports_qt': entry['entry_imports_qt'],
        'entry_imports_opengl': entry['entry_imports_opengl'],
        'entry_requires_qt': entry['entry_requires_qt'],
        'entry_requires_opengl': entry['entry_requires_opengl'],
        'legacy_imports': [m for m in py['third_party_imports'] if m in LEGACY],
        'third_party_imports_live': [m for m in py['third_party_imports'] if m not in LEGACY],
        'upstream_pure_python_flag': info['pure_python_flag'],
        'dependencies': [],
        'build_dependencies': [],
        'needs_codegen': bool(peg or cython),
        'unparsable_python_files': py['unparsable_python_files'],
    }
    return record


def classify(records: list[dict]) -> dict:
    """Build the three dependency classes plus the easy-port set."""
    pure = [r['name'] for r in records
            if not r['has_cpp_extension'] and not r['imports_qt'] and not r['imports_opengl']]
    needs_cpp = sorted(
        (r for r in records if r['has_cpp_extension']),
        key=lambda r: (-(r['cpp_source_count'] + r['cython_source_count']), r['name']),
    )
    needs_qt = sorted((r for r in records if r['imports_qt']), key=lambda r: r['name'])
    needs_gl = sorted((r for r in records if r['imports_opengl']), key=lambda r: r['name'])
    return {
        'pure_python': sorted(pure),
        'needs_cpp': [
            {
                'name': r['name'],
                'cpp_source_count': r['cpp_source_count'],
                'cpp_header_count': r['cpp_header_count'],
                'cython_source_count': r['cython_source_count'],
                'components': r['cpp_components'],
            }
            for r in needs_cpp
        ],
        'needs_qt': [r['name'] for r in needs_qt],
        'needs_gl': [r['name'] for r in needs_gl],
        # Derived tier (beyond the three required classes): no compiled source and
        # nothing Qt/PyOpenGL reached by ``import chimerax.<name>``. These bundles
        # can be staged before any Qt/PyOpenGL work lands, even if they ship a GUI
        # module that is only imported when a tool window opens.
        'import_clean_python': sorted(
            r['name'] for r in records
            if not r['has_cpp_extension']
            and not r['entry_imports_qt'] and not r['entry_imports_opengl']),
        'needs_qt_at_import': sorted(r['name'] for r in records if r['entry_imports_qt']),
        'needs_qt_at_import_hard': sorted(r['name'] for r in records if r['entry_requires_qt']),
        'needs_gl_at_import': sorted(r['name'] for r in records if r['entry_imports_opengl']),
        'needs_gl_at_import_hard': sorted(r['name'] for r in records if r['entry_requires_opengl']),
        'needs_codegen': sorted(r['name'] for r in records if r['needs_codegen']),
        'no_python_package': sorted(r['name'] for r in records if not r['has_python_package']),
        'third_party_rollup': sorted({m for r in records for m in r['third_party_imports']}),
    }


def collect(bundle_root: Path = BUNDLE_ROOT) -> tuple[list[dict], dict]:
    bundles = sorted((p for p in bundle_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    names = [b.name for b in bundles]
    index = _bundle_index(names)
    records = []
    for bundle in bundles:
        rec = scan_bundle(bundle)
        for candidate in ('bundle_info.xml', 'bundle_info.xml.in'):
            p = bundle / candidate
            if p.is_file():
                info = scan_bundle_info(p)
                break
        else:
            info = {'deps': [], 'build_deps': []}
        # Resolution needs every bundle name, so it happens here, not in scan_bundle.
        rec['dependencies'] = sorted({resolve_dependency(d, index, names) for d in info['deps']})
        rec['build_dependencies'] = sorted(
            {resolve_dependency(d, index, names) for d in info['build_deps']})
        records.append(rec)
    return records, classify(records)


def build_summary(records: list[dict], classes: dict) -> dict:
    rev = None
    head = SRC_ROOT / '.git'
    if head.exists():
        try:
            import subprocess
            rev = subprocess.run(
                ['git', '-C', str(SRC_ROOT), 'rev-parse', 'HEAD'],
                capture_output=True, text=True, timeout=10, check=False,
            ).stdout.strip() or None
        except OSError:
            rev = None
    return {
        'upstream_commit': rev,
        'bundle_count': len(records),
        'counts': {
            'has_python_package': sum(r['has_python_package'] for r in records),
            'has_cpp_extension': sum(r['has_cpp_extension'] for r in records),
            'imports_qt': sum(r['imports_qt'] for r in records),
            'imports_opengl': sum(r['imports_opengl'] for r in records),
            'imports_numpy': sum(r['imports_numpy'] for r in records),
            'pure_python': len(classes['pure_python']),
            'import_clean_python': len(classes['import_clean_python']),
            'needs_qt_at_import': len(classes['needs_qt_at_import']),
            'needs_qt_at_import_hard': len(classes['needs_qt_at_import_hard']),
            'needs_gl_at_import': len(classes['needs_gl_at_import']),
            'needs_codegen': len(classes['needs_codegen']),
        },
        **classes,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--bundle-root', type=Path, default=BUNDLE_ROOT)
    ap.add_argument('--json', type=Path, default=REPORT_PATH)
    ap.add_argument('--summary', type=Path, default=SUMMARY_PATH)
    ap.add_argument('--stdout', action='store_true', help='print the array, write nothing')
    ap.add_argument('--check', action='store_true',
                    help='compare with the on-disk report instead of writing')
    args = ap.parse_args(argv)

    if not args.bundle_root.is_dir():
        print(f'error: bundle root not found: {args.bundle_root}', file=sys.stderr)
        return 2

    records, classes = collect(args.bundle_root)
    payload = json.dumps(records, indent=2, sort_keys=False) + '\n'
    summary = json.dumps(build_summary(records, classes), indent=2, sort_keys=False) + '\n'

    if args.stdout:
        sys.stdout.write(payload)
        return 0
    if args.check:
        same = args.json.is_file() and args.json.read_text(encoding='utf-8') == payload
        print('report up to date' if same else 'report differs from a fresh scan')
        return 0 if same else 1

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(payload, encoding='utf-8')
    args.summary.write_text(summary, encoding='utf-8')

    c = classes
    print(f'bundles                    : {len(records)}')
    print(f'pure python (no cpp/qt/gl) : {len(c["pure_python"])}')
    print(f'needs cpp extension        : {len(c["needs_cpp"])}')
    print(f'needs qt                   : {len(c["needs_qt"])}')
    print(f'needs opengl               : {len(c["needs_gl"])}')
    print(f'needs codegen (pyx/peg)    : {len(c["needs_codegen"])}')
    print(f'report  -> {args.json.relative_to(ROOT) if args.json.is_relative_to(ROOT) else args.json}')
    print(f'summary -> {args.summary.relative_to(ROOT) if args.summary.is_relative_to(ROOT) else args.summary}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
