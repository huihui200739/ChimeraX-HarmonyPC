#!/usr/bin/env python3
"""Cross-compile the ChimeraX atomic C++ extension modules for HarmonyOS.

The upstream ``ChimeraX-Atomic`` bundle (pinned at
``build/downloads/ChimeraX-src``) declares five compiled components:

* ``_ribbons``  (CModule, ribbon_cpp/*.cpp)  -> chimerax.atomic._ribbons
* ``molc``      (CLibrary, atomic_cpp/molc.cpp, ctypes-loaded)
* ``cymol``     (CModule from atomic_cpp/cymol.pyx)
* ``cytmpl``    (CModule from atomic_cpp/cytmpl.pyx)
* ``connect``   (CModule from atomic_cpp/connect.pyx)

The three ``*.pyx`` components are Cython sources: they only become compilable
after ``cython --cplus`` generation, which needs a Cython interpreter that is not
present on this machine, so the tool lists them as skipped instead of pretending
to build them.

The C++ components need the ChimeraX C++ library stack that upstream ships as
shared libraries (``libatomstruct``/``libelement``/``libpyinstance`` plus the
core ``logger``/``chutil``/``ioutil`` and the ``arrays`` marshalling code).  In
the same spirit as ``tools/build_graphics_ext_harmony.py`` that stack is compiled
straight into each produced object file, so every artifact is self contained and
only needs ``libpython3.11.so.1.0`` from the runtime directory.

Nothing is executed on the build machine and no device/simulator tooling is
used: the tool only compiles, links, stages the ``.so`` files and inspects them
with ``llvm-readelf``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SDK = Path('/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native')
TRIPLE = 'aarch64-linux-ohos'
SUFFIX = 'cpython-311-aarch64-linux-ohos.so'
EXPECTED_MACHINE = 'AArch64'
EXPECTED_NEEDED = 'libpython3.11.so.1.0'
EXPECTED_RUNPATH = '$ORIGIN/../lib'

#: Absolute include roots exposed to the sources under their ChimeraX names
#: (``<arrays/pythonarray.h>``, ``<atomstruct/Atom.h>``, ...).
INCLUDE_LINKS = {
    'arrays': 'src/bundles/arrays/_arrays',
    'atomstruct': 'src/bundles/atomic_lib/atomic_cpp/atomstruct_cpp',
    'element': 'src/bundles/atomic_lib/atomic_cpp/element_cpp',
    'pyinstance': 'src/bundles/atomic_lib/atomic_cpp/pyinstance_cpp',
    'pysupport': 'src/bundles/core/core_cpp/pysupport',
    'logger': 'src/bundles/core/core_cpp/logger',
    'chutil': 'src/bundles/core/core_cpp/chutil',
    'ioutil': 'src/bundles/core/core_cpp/ioutil',
}

ARRAYS_MARSHALLING = ('src/bundles/arrays/_arrays/pythonarray.cpp',
                      'src/bundles/arrays/_arrays/rcarray.cpp',
                      'src/bundles/arrays/_arrays/refcount.cpp')

CORE_SUPPORT = ('src/bundles/core/core_cpp/logger/logger.cpp',
                'src/bundles/core/core_cpp/chutil/IOFile.cpp',
                'src/bundles/core/core_cpp/chutil/cmp_nocase.cpp',
                'src/bundles/core/core_cpp/ioutil/GetOpt.cpp',
                'src/bundles/core/core_cpp/ioutil/pstream.cpp',
                'src/bundles/core/core_cpp/ioutil/tokenize.cpp')

ATOMSTRUCT_TMPL = tuple(
    'src/bundles/atomic_lib/atomic_cpp/atomstruct_cpp/tmpl/%s.cpp' % name
    for name in ('Atom', 'Bond', 'CoordSet', 'Molecule', 'Residue', 'TemplateCache',
                 'amino', 'camino', 'findres', 'general', 'ions', 'namino', 'nucleic'))

ATOMSTRUCT = tuple(
    'src/bundles/atomic_lib/atomic_cpp/atomstruct_cpp/%s.cpp' % name
    for name in ('Atom', 'AtomTypes', 'AtomicStructure', 'Bond', 'Chain', 'ChangeTracker',
                 'CompSS', 'CoordSet', 'MolResId', 'PBGroup', 'PBManager', 'Point',
                 'Pseudobond', 'Residue', 'Ring', 'RingCalc', 'Sequence', 'Structure',
                 'StructureSeq', 'destruct', 'search', 'seq_assoc'))

PYINSTANCE = ('src/bundles/atomic_lib/atomic_cpp/pyinstance_cpp/PythonInstance.cpp',)
ELEMENT = ('src/bundles/atomic_lib/atomic_cpp/element_cpp/Element.cpp',)

RIBBON_CPP = tuple('src/bundles/atomic/ribbon_cpp/%s.cpp' % name
                   for name in ('normals', 'parse', 'ribbons', 'spline', 'xsection'))

GEOMETRY_CPP = tuple('src/bundles/geometry/_geometry/%s.cpp' % name
                     for name in ('bounds', 'closepoints', 'cylinderrot', 'distances',
                                  'distancespy', 'fill_ring', 'geometry', 'intercept',
                                  'matrix', 'spline', 'transform', 'vector_ops'))

#: Pure C++ components.  ``stage`` is the path relative to the package tree that
#: receives the artifact; ``needs_atomstruct`` pulls in the atomic library stack.
MODULES = (
    {
        'name': '_ribbons',
        'bundle': 'atomic',
        'package': 'chimerax/atomic',
        'kind': 'cpython_extension',
        'sources': RIBBON_CPP,
        'extra': ARRAYS_MARSHALLING + CORE_SUPPORT + ATOMSTRUCT + ATOMSTRUCT_TMPL
                 + PYINSTANCE + ELEMENT,
        'stage': 'chimerax/atomic/_ribbons.%s' % SUFFIX,
        'module_init': 'PyInit__ribbons',
    },
    {
        'name': 'libmolc',
        'bundle': 'atomic',
        'package': 'chimerax/atomic',
        'kind': 'shared_library',
        'sources': ('src/bundles/atomic/atomic_cpp/molc.cpp',),
        'extra': ARRAYS_MARSHALLING + CORE_SUPPORT + ATOMSTRUCT + ATOMSTRUCT_TMPL
                 + PYINSTANCE + ELEMENT,
        # chimerax/atomic/molc.py resolves "libmolc" as <package dir>/libmolc.so.
        'stage': 'chimerax/atomic/libmolc.so',
        'module_init': None,
    },
    {
        'name': '_geometry',
        'bundle': 'geometry',
        'package': 'chimerax/geometry',
        'kind': 'cpython_extension',
        'sources': GEOMETRY_CPP,
        'extra': ARRAYS_MARSHALLING,
        'stage': 'chimerax/geometry/_geometry.%s' % SUFFIX,
        'module_init': 'PyInit__geometry',
    },
)

#: Compiled components declared by the bundle that this tool cannot build yet.
SKIPPED = (
    {
        'extension': 'cymol',
        'bundle': 'atomic',
        'declaration': 'CModule name="cymol" (atomic_cpp/cymol.pyx, usesNumpy)',
        'reason': 'Cython source: no generated C++ checked in and no Cython interpreter '
                  'available offline on this host (import Cython fails, no local wheel, '
                  'network installs are out of scope).',
        'unblocks_with': 'Cython >= 3.0 (cython --cplus atomic_cpp/cymol.pyx) then the same '
                         'clang cross-compile + atomstruct stack link as _ribbons.',
    },
    {
        'extension': 'cytmpl',
        'bundle': 'atomic',
        'declaration': 'CModule name="cytmpl" (atomic_cpp/cytmpl.pyx, usesNumpy)',
        'reason': 'Cython source: same blocker as cymol (no Cython code generation offline).',
        'unblocks_with': 'Cython >= 3.0 code generation, then cross-compile like _ribbons.',
    },
    {
        'extension': 'connect',
        'bundle': 'atomic',
        'declaration': 'CModule name="connect" (atomic_cpp/connect.pyx) + Library pdbconnect',
        'reason': 'Cython source; additionally links the ChimeraX-PDBLibrary pdbconnect '
                  'library, which is not cross-compiled in this workspace either.',
        'unblocks_with': 'Cython code generation plus a cross-compiled libpdbconnect.so.',
    },
    {
        'extension': '_load_libs',
        'bundle': 'atomic_lib',
        'declaration': 'CModule name="_load_libs" (atomic_lib/atomic_cpp/load_libs.cpp)',
        'reason': 'Not part of chimerax.atomic; it is only useful once libatomstruct.so / '
                  'libelement.so exist as separate shared libraries. Here the atomic stack '
                  'is compiled directly into each atomic artifact, so no dynamic loader '
                  'shim is needed yet.',
        'unblocks_with': 'Split the stack into chimerax/atomic_lib/lib/*.so and build '
                         '_load_libs afterwards.',
    },
)


def sha256(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def obj_name(source: Path) -> str:
    return str(source).replace('/', '_').replace(' ', '_') + '.o'


def run(argv: list[str], timeout: int = 900) -> tuple[int, str]:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return result.returncode, (result.stderr or '') + (result.stdout or '')


def verify_elf(readelf: Path, artifact: Path) -> dict:
    """Check machine type, the python NEEDED entry and the runtime RUNPATH."""
    code, output = run([str(readelf), '-h', '-d', str(artifact)], timeout=120)
    machine = needed = runpath = None
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith('Machine:'):
            machine = stripped.split(':', 1)[1].strip()
        elif '(NEEDED)' in line and 'Shared library:' in line:
            name = line.split('[', 1)[-1].rstrip(']')
            if name == EXPECTED_NEEDED:
                needed = name
        elif '(RUNPATH)' in line or '(RPATH)' in line:
            if '[' in line:
                runpath = line.split('[', 1)[-1].rstrip(']')
    checks = {
        'readelf_returncode': code,
        'machine': machine,
        'machine_is_aarch64': machine == EXPECTED_MACHINE,
        'needed_libpython': needed == EXPECTED_NEEDED,
        'runpath': runpath,
        'runpath_ok': runpath == EXPECTED_RUNPATH,
        'elf_type_shared': 'DYN (Shared object file)' in output,
    }
    checks['ok'] = bool(checks['machine_is_aarch64'] and checks['needed_libpython']
                        and checks['runpath_ok'] and checks['elf_type_shared'])
    return checks


CTYPES_CALL = re.compile(r"c_(?:property|function|array_function|varlen_property)\(\s*"
                         r"['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]")


def exported_symbols(readelf: Path, artifact: Path) -> set[str]:
    code, output = run([str(readelf), '--dyn-syms', str(artifact)], timeout=120)
    if code != 0:
        return set()
    names = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 8 and parts[6] != 'UND':
            names.add(parts[7].split('@')[0])
    return names


def audit_ctypes_symbols(readelf: Path, artifact: Path, bundles: Path,
                         bundle: str) -> dict:
    """Every C function chimerax.atomic reaches through ctypes must be exported.

    Names built by string concatenation in Python (``'set_' + name``,
    ``'structure_session_' + suffix``) are matched by exported symbol prefix,
    which is reported separately so the heuristic stays visible.
    """
    python_dir = bundles / bundle / 'src'
    wanted: dict[str, str] = {}
    for path in sorted(python_dir.glob('*.py')):
        for match in CTYPES_CALL.finditer(path.read_text()):
            wanted.setdefault(match.group(1), path.name)
    exported = exported_symbols(readelf, artifact)
    exact, prefixed, missing = [], [], []
    for name, origin in sorted(wanted.items()):
        if name in exported:
            exact.append(name)
        elif any(symbol.startswith(name) for symbol in exported):
            prefixed.append(name)
        else:
            missing.append({'name': name, 'referenced_in': origin})
    return {'artifact': artifact.name, 'references': len(wanted),
            'exact_matches': len(exact), 'prefix_matches': prefixed,
            'missing': missing, 'ok': not missing}


def audit_attribute_table(source: Path, table_source: str, python_dir: str,
                          attribute: str) -> dict:
    """Compare the C method table of a module with what the Python layer uses.

    Two usage styles are collected: ``<module>.<name>`` attribute access and
    ``from .<module> import a, b, c`` re-exports.
    """
    table = source / table_source
    declared = set(re.findall(r'\{\s*const_cast<char\*>\("([A-Za-z_][A-Za-z0-9_]*)"\)',
                              table.read_text())) if table.exists() else set()
    used: dict[str, str] = {}
    attribute_call = re.compile(re.escape(attribute) + r'\.([A-Za-z_][A-Za-z0-9_]*)')
    import_call = re.compile(r'from\s+[\w.]*' + re.escape(attribute) + r'\s+import\s+(.+)')
    for path in sorted((source / python_dir).glob('*.py')):
        text = path.read_text()
        for match in attribute_call.finditer(text):
            used.setdefault(match.group(1), path.name)
        for match in import_call.finditer(text):
            statement = match.group(1).replace('(', ' ').replace(')', ' ').replace('\\', ' ')
            for item in statement.split(','):
                parts = item.split()
                # "name" or "name as alias": the imported symbol is the first token.
                if parts and parts[0] not in ('import', 'as'):
                    used.setdefault(parts[0], path.name)
    missing = [{'name': n, 'referenced_in': f} for n, f in sorted(used.items())
               if n not in declared]
    return {'table_source': table_source, 'declared': len(declared),
            'referenced': len(used), 'missing': missing, 'ok': not missing}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, default=ROOT / 'build/downloads/ChimeraX-src')
    parser.add_argument('--sdk', type=Path, default=DEFAULT_SDK)
    parser.add_argument('--cpython', type=Path,
                        default=ROOT / 'build/cpython-3.11.18/ohos-aarch64-with-libffi-linked')
    parser.add_argument('--packages', type=Path, default=ROOT / 'build/chimerax-python')
    parser.add_argument('--workdir', type=Path, default=ROOT / 'build/atomic-ext')
    parser.add_argument('--report', type=Path, default=None)
    parser.add_argument('--modules', nargs='*', default=None,
                        help='subset of module names to build (default: all pure C++ ones)')
    args = parser.parse_args()
    day = datetime.now(timezone.utc).date().isoformat()
    report_path = args.report or ROOT / f'reports/atomic-ext-{day}.json'

    clang = args.sdk / 'llvm/bin/clang++'
    readelf = args.sdk / 'llvm/bin/llvm-readelf'
    sysroot = args.sdk / 'sysroot'
    py_include = args.cpython / 'source/Include'
    py_objects = args.cpython / 'objects'
    runtime_lib = args.cpython / 'runtime/lib'
    numpy_include = args.packages / 'numpy/core/include'
    include_root = args.workdir / 'include'
    obj_dir = args.workdir / 'obj'

    report: dict = {
        'schema_version': 1,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'tool': rel(Path(__file__)),
        'target': TRIPLE,
        'host_executed': False,
        'device_tooling_used': False,
        'bundle': 'ChimeraX-Atomic',
        'upstream_commit': None,
        'inputs': {},
        'include_root': {},
        'products': [],
        'skipped': list(SKIPPED),
        'compile_failures': [],
        'link_failures': [],
        'verification': [],
        'symbol_audit': [],
    }

    try:
        # ---- 1. validate every input individually -------------------------
        inputs = {
            'clang': clang, 'llvm_readelf': readelf, 'sysroot': sysroot,
            'python_include': py_include / 'Python.h', 'pyconfig': py_objects / 'pyconfig.h',
            'numpy_include': numpy_include / 'numpy/arrayobject.h',
            'libpython': runtime_lib / 'libpython3.11.so.1.0',
        }
        report['inputs'] = {name: {'path': str(path), 'exists': path.exists()}
                            for name, path in inputs.items()}
        sources = set()
        for module in MODULES:
            sources.update(module['sources'])
            sources.update(module['extra'])
        source_paths = {str(args.source / name): (args.source / name).exists()
                        for name in sorted(sources)}
        report['inputs']['sources'] = {
            'count': len(source_paths),
            'missing': [p for p, ok in source_paths.items() if not ok],
        }
        missing = [name for name, path in inputs.items() if not path.exists()]
        if source_paths and report['inputs']['sources']['missing']:
            missing.append('%d source file(s)' % len(report['inputs']['sources']['missing']))
        if missing:
            raise RuntimeError('missing build inputs: ' + ', '.join(missing))

        commit_file = args.source / '.git/HEAD'
        if (args.source / '.git').is_dir():
            code, out = run(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], timeout=60)
            if code == 0:
                report['upstream_commit'] = out.strip()
        elif commit_file.exists():
            report['upstream_commit'] = commit_file.read_text().strip()

        # ---- 2. include root with the ChimeraX header names ----------------
        include_root.mkdir(parents=True, exist_ok=True)
        for name, relative in INCLUDE_LINKS.items():
            target = args.source / relative
            if not target.exists():
                raise RuntimeError(f'missing include tree for {name}: {target}')
            link = include_root / name
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(target)
            report['include_root'][name] = {'link': str(link), 'target': str(target),
                                            'ok': link.resolve().is_dir()}

        flags = [f'--target={TRIPLE}', f'--sysroot={sysroot}', '-std=c++11', '-O2', '-fPIC',
                 f'-I{py_include}', f'-I{py_objects}', f'-I{include_root}',
                 f'-I{numpy_include}']
        # --no-undefined makes an unresolved atomstruct/arrays symbol a hard build
        # failure instead of a load-time crash on the device.
        linker = [f'-L{runtime_lib}', '-l:libpython3.11.so.1.0',
                  '-Wl,-rpath,$ORIGIN/../lib', '-Wl,--no-undefined']
        report['compile_flags'] = flags
        report['link_flags'] = linker

        # ---- 3. compile objects once, reuse across modules -----------------
        obj_dir.mkdir(parents=True, exist_ok=True)
        signature = args.workdir / 'flags.txt'
        signature_text = ' '.join(flags) + '\n'
        if signature.exists() and signature.read_text() != signature_text:
            for stale in obj_dir.glob('*.o'):
                stale.unlink()
        signature.write_text(signature_text)

        object_cache: dict[str, Path | None] = {}

        def compile_source(source: Path) -> Path | None:
            key = str(source)
            if key in object_cache:
                return object_cache[key]
            target = obj_dir / obj_name(source)
            if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
                object_cache[key] = target
                return target
            started = time.time()
            code, output = run([str(clang), *flags, '-c', '-o', str(target), str(source)])
            if code != 0:
                report['compile_failures'].append({
                    'source': str(source), 'returncode': code,
                    'seconds': round(time.time() - started, 2),
                    'stderr': output[-4000:]})
                object_cache[key] = None
                return None
            object_cache[key] = target
            return target

        wanted = set(args.modules) if args.modules else {m['name'] for m in MODULES}
        for module in MODULES:
            if module['name'] not in wanted:
                report['skipped'].append({
                    'extension': module['name'], 'bundle': module['bundle'],
                    'declaration': 'selected out via --modules',
                    'reason': 'requested subset skipped this run',
                    'unblocks_with': 'rerun without --modules'})
                continue
            entry: dict = {'name': module['name'], 'bundle': module['bundle'],
                           'kind': module['kind'], 'module_init': module['module_init'],
                           'staged_path': module['stage']}
            started = time.time()
            objects = []
            broken = []
            for name in list(module['sources']) + list(module['extra']):
                source = args.source / name
                built = compile_source(source)
                if built is None:
                    broken.append(name)
                else:
                    objects.append(str(built))
            entry['source_count'] = len(objects)
            entry['compile_seconds'] = round(time.time() - started, 2)
            if broken:
                entry.update(status='compile_failed', broken_sources=broken[:20])
                report['products'].append(entry)
                continue

            artifact = args.workdir / 'out' / Path(module['stage']).name
            artifact.parent.mkdir(parents=True, exist_ok=True)
            code, output = run([str(clang), *flags, '-shared', f'-o{artifact}', *objects,
                                *linker], timeout=1800)
            if code != 0:
                report['link_failures'].append({
                    'module': module['name'], 'returncode': code,
                    'stderr': output[-6000:]})
                entry.update(status='link_failed')
                report['products'].append(entry)
                continue

            # ---- 4. stage the artifact, never touching Python sources ------
            staged = args.packages / module['stage']
            staged.parent.mkdir(parents=True, exist_ok=True)
            if staged.suffix != '.so':
                raise RuntimeError(f'refusing to stage non-.so file: {staged}')
            shutil.copy2(artifact, staged)
            entry.update(status='built', path=str(artifact), staged=str(staged),
                         bytes=staged.stat().st_size, sha256=sha256(staged))
            checks = verify_elf(readelf, staged)
            report['verification'].append({'module': module['name'], 'path': str(staged),
                                           **checks})
            entry['verify_ok'] = checks['ok']
            if module['name'] == 'libmolc':
                report['symbol_audit'].append(audit_ctypes_symbols(
                    readelf, staged, args.source / 'src/bundles', 'atomic'))
            elif module['name'] == '_ribbons':
                report['symbol_audit'].append(audit_attribute_table(
                    args.source, 'src/bundles/atomic/ribbon_cpp/ribbons.cpp',
                    'src/bundles/atomic/src', '_ribbons'))
            elif module['name'] == '_geometry':
                report['symbol_audit'].append(audit_attribute_table(
                    args.source, 'src/bundles/geometry/_geometry/geometry.cpp',
                    'src/bundles/geometry/src', '_geometry'))
            report['products'].append(entry)

        built = [p for p in report['products'] if p['status'] == 'built']
        verified = [v for v in report['verification'] if v['ok']]
        if built and len(verified) == len(built):
            report['status'] = 'atomic_extensions_cross_compiled_not_target_tested'
        elif built:
            report['status'] = 'atomic_extensions_built_with_verification_gaps'
        else:
            report['status'] = 'atomic_extension_build_failed'
    except Exception as error:  # noqa: BLE001 - report the failure
        report['status'] = 'atomic_extension_build_failed'
        report['error'] = str(error)[:4000]

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(report['status'])
    for product in report['products']:
        if product['status'] == 'built':
            print(f"  {product['name']}: {product['staged']} "
                  f"({product['bytes']} B, sha256 {product['sha256'][:16]}..., "
                  f"verify={'ok' if product.get('verify_ok') else 'GAP'})")
        else:
            print(f"  {product['name']}: {product['status']}")
    if report['compile_failures']:
        print('  compile failures:', [Path(f['source']).name
                                     for f in report['compile_failures']])
    if report['link_failures']:
        print('  link failures:', [f['module'] for f in report['link_failures']])
    if report.get('error'):
        print('  error:', report['error'])
    return 0 if report['status'] in ('atomic_extensions_cross_compiled_not_target_tested',
                                     'atomic_extensions_built_with_verification_gaps') else 1


if __name__ == '__main__':
    raise SystemExit(main())
