#!/usr/bin/env python3
"""Build the C modules a bundle declares in its bundle_info.xml.

ChimeraX's bundles list their extension sources in `<CModule>` entries, so the build list is
data rather than guesswork. This tool compiles those sources against the HarmonyOS NDK and
stages the resulting `.so` inside the staged ChimeraX tree.
"""
from __future__ import annotations

import argparse
import json
import subprocess as _sp
import tempfile
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SDK = Path('/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native')
TRIPLE = 'aarch64-linux-ohos'
EXT_SUFFIX = '.cpython-311-aarch64-linux-ohos.so'
# Header trees the bundle sources include as <arrays/...>, <atomstruct/...> and friends.
INCLUDE_LINKS = {
    'arrays': 'arrays/_arrays',
    'atomstruct': 'atomic_lib/atomic_cpp/atomstruct_cpp',
    'element': 'atomic_lib/atomic_cpp/element_cpp',
    'pyinstance': 'atomic_lib/atomic_cpp/pyinstance_cpp',
    'pysupport': 'core/core_cpp/pysupport',
    'logger': 'core/core_cpp/logger',
    'chutil': 'core/core_cpp/chutil',
    'ioutil': 'core/core_cpp/ioutil',
    'map': 'map/_map',
}
# C++ support that every extension links against; arrays marshals Python<->numpy.
SHARED_SOURCES = ('arrays/_arrays/pythonarray.cpp',
                  'arrays/_arrays/rcarray.cpp',
                  'arrays/_arrays/refcount.cpp')


def run(cmd: list[str], timeout: int = 1800) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def parse_libraries(bundle_root: Path) -> list[dict]:
    """Bundles can declare a CLibrary that their C modules link against."""
    info = bundle_root / 'bundle_info.xml'
    tree = ET.parse(info)
    libraries = []
    for node in tree.iter('CLibrary'):
        sources = [child.text.strip() for child in node
                   if child.tag == 'SourceFile' and child.text]
        includes = [child.text.strip() for child in node
                    if child.tag == 'IncludeDir' and child.text]
        libraries.append({'name': node.get('name'), 'sources': sources, 'includes': includes})
    return libraries


def parse_modules(bundle_root: Path) -> list[dict]:
    info = bundle_root / 'bundle_info.xml'
    tree = ET.parse(info)
    modules = []
    for node in tree.iter('CModule'):
        name = node.get('name')
        sources = [child.text.strip() for child in node
                   if child.tag == 'SourceFile' and child.text]
        if not sources:
            continue
        includes = [child.text.strip() for child in node
                    if child.tag == 'IncludeDir' and child.text]
        libraries = [child.text.strip() for child in node
                     if child.tag == 'Library' and child.text]
        lib_dirs = [child.text.strip() for child in node
                    if child.tag == 'LibraryDir' and child.text]
        modules.append({'name': name, 'sources': sources, 'includes': includes,
                        'libraries': libraries, 'lib_dirs': lib_dirs})
    return modules


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, help='bundle directory name, e.g. map')
    parser.add_argument('--exclude', nargs='*', default=[],
                        help='source file names to skip (e.g. GLU-dependent tessellation)')
    parser.add_argument('--source', type=Path,
                        default=ROOT / 'build/downloads/ChimeraX-src/src/bundles')
    parser.add_argument('--sdk', type=Path, default=DEFAULT_SDK)
    parser.add_argument('--cpython', type=Path,
                        default=ROOT / 'build/cpython-3.11.18/ohos-aarch64-with-libffi-linked')
    parser.add_argument('--packages', type=Path, default=ROOT / 'build/chimerax-python')
    parser.add_argument('--numpy-include', type=Path,
                        default=ROOT / 'build/chimerax-python/numpy/core/include')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()

    bundle_root = args.source / args.bundle
    modules = parse_modules(bundle_root)
    day = datetime.now(timezone.utc).date().isoformat()
    report: dict = {'schema_version': 1,
                    'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'bundle': args.bundle, 'modules': [m['name'] for m in modules],
                    'products': [], 'failures': []}
    report_path = args.report or ROOT / f'reports/bundle-cmodule-{args.bundle}-{day}.json'

    clang = args.sdk / 'native/../native/llvm/bin/clang++'
    if not clang.exists():
        clang = args.sdk / 'llvm/bin/clang++'
    sysroot = args.sdk / 'sysroot'
    py_include = args.cpython / 'include/python3.11'
    if not (py_include / 'Python.h').is_file():
        py_include = ROOT / 'app/entry/src/main/cpp/python-include'
    runtime_lib = args.cpython / 'lib'
    if not (runtime_lib / 'libpython3.11.so.1.0').is_file():
        runtime_lib = args.cpython / 'runtime/lib'
    if not (runtime_lib / 'libpython3.11.so.1.0').is_file():
        candidates = list((ROOT / 'build').rglob('libpython3.11.so.1.0'))
        runtime_lib = candidates[0].parent if candidates else runtime_lib
    include_root = ROOT / 'build/bundle-cmodule/include'
    include_root.mkdir(parents=True, exist_ok=True)
    src_root = args.source.parent / 'bundles'
    for name, relative in INCLUDE_LINKS.items():
        target = src_root / relative
        link = include_root / name
        if link.is_symlink() or link.exists():
            link.unlink()
        if target.is_dir():
            link.symlink_to(target)
    flags = [f'--target={TRIPLE}', f'--sysroot={sysroot}', '-std=c++17', '-O2', '-fPIC',
             f'-I{py_include}', f'-I{bundle_root}', f'-I{include_root}']
    # Bundles such as alignment_algs keep public headers under src/include.
    for extra in (bundle_root / 'src/include', bundle_root / 'src'):
        if extra.is_dir():
            flags.append(f'-I{extra}')
    # HarmonyOS has no usable GLU tessellator at run time, so replace the cap triangulation in
    # _surface with an inlined ear-clipping implementation before compiling.
    if args.bundle == 'surface':
        patch = ROOT / 'vendor/surface_glu/cap_triangulate.inc'
        target = bundle_root / '_surface' / 'triangulate.cpp'
        if patch.is_file() and target.is_file():
            text = target.read_text()
            if 'CX_EARCUT' not in text:
                start_marker = ('static void triangulate_polygon(Loops &loops, float normal[3],\n'
                                '\t\t\t\tPolygon_Data &polygon_data)\n{\n')
                end_marker = '  gluTessEndPolygon(tess);\n  gluDeleteTess(tess);\n}\n'
                try:
                    start = text.index(start_marker)
                    end = text.index(end_marker, start) + len(end_marker)
                    target.write_text(text[:start] + patch.read_text() + '\n' + text[end:])
                except ValueError:
                    pass
    glu_stub = ROOT / 'vendor/surface_glu'
    if (glu_stub / 'GL/glu.h').is_file():
        # HarmonyOS has no desktop GLU; the stub keeps _surface linkable.
        flags.append(f'-I{glu_stub}')
    if args.numpy_include.is_dir():
        flags.append(f'-I{args.numpy_include}')
    shared_lib_dir = args.packages / 'chimerax/lib'
    if not (shared_lib_dir / 'libcxatomstruct.so').is_file():
        # The shared support library ships as an app native library, not inside the payload.
        candidate = ROOT / 'app/entry/libs/arm64-v8a/chimerax/lib'
        if (candidate / 'libcxatomstruct.so').is_file():
            shared_lib_dir = candidate
    linker = [f'-L{runtime_lib}', '-l:libpython3.11.so.1.0']
    if (shared_lib_dir / 'libcxatomstruct.so').is_file():
        # atomstruct/pyinstance registries live in one shared library; linking the same
        # sources per extension would give each copy its own registry.
        linker += [f'-L{shared_lib_dir}', '-lcxatomstruct']
    linker += ['-Wl,-rpath,$ORIGIN/../../../../../lib:$ORIGIN/../../lib:$ORIGIN/../lib',
               '-Wl,--no-undefined']

    workdir = ROOT / 'build/bundle-cmodule' / args.bundle
    workdir.mkdir(parents=True, exist_ok=True)

    ar = args.sdk / 'llvm/bin/llvm-ar'
    library_products: dict[str, Path] = {}
    shared_objects_extra: list[str] = []
    stub_source = glu_stub / 'glu_stub.cpp'
    if stub_source.is_file():
        stub_obj = workdir / 'glu_stub.o'
        code, output = run([str(clang), *flags, '-c', '-o', str(stub_obj), str(stub_source)])
        if code == 0:
            shared_objects_extra.append(str(stub_obj))
        else:
            report['failures'].append({'glu_stub': output[-1000:]})
    for library in parse_libraries(bundle_root):
        if not library['sources']:
            continue
        objects = []
        broken = False
        library_flags = list(flags)
        for include in library['includes']:
            library_flags.append(f'-I{bundle_root / include}')
        for relative in library['sources']:
            source = bundle_root / relative
            obj = workdir / ('lib_' + relative.replace('/', '_') + '.o')
            code, output = run([str(clang), *library_flags, '-c', '-o', str(obj), str(source)])
            if code != 0:
                report['failures'].append({'library': library['name'], 'source': relative,
                                           'stderr': output[-2000:]})
                broken = True
                break
            objects.append(str(obj))
        if broken:
            continue
        archive = workdir / ('lib%s.a' % library['name'])
        run([str(ar), 'rcs', str(archive), *objects])
        library_products[library['name']] = archive
    for module in modules:
        objects: list[str] = []
        failed = False
        module_flags = list(flags)
        for include in module.get('includes', []):
            module_flags.append(f'-I{bundle_root / include}')
        for relative in module['sources']:
            if Path(relative).name in args.exclude:
                continue
            source = bundle_root / relative
            if source.suffix == '.pyx':
                # Cython runs on the build host and only emits C++; compile that instead.
                generated_dir = workdir / 'cython'
                generated_dir.mkdir(parents=True, exist_ok=True)
                generated = generated_dir / (source.stem + '.cpp')
                host_python = ROOT / 'build/host-python/cpython-3.11.17-macos-aarch64-none/bin/python3.11'
                if not host_python.is_file():
                    host_python = Path(sys.executable)
                cython_include = [f'-I{bundle_root}', f'-I{bundle_root / "src"}',
                                  f'-I{ROOT / "build/chimerax-python/numpy/core/include"}']
                cy = _sp.run([str(host_python), '-m', 'cython', '-3', '--cplus',
                              *cython_include, '-o', str(generated), str(source)],
                             capture_output=True, text=True)
                if cy.returncode != 0:
                    report['failures'].append({'module': module['name'],
                                               'source': relative,
                                               'cython_stderr': (cy.stderr or '')[-1500:]})
                    failed = True
                    break
                source = generated
            obj = workdir / (relative.replace('/', '_') + '.o')
            code, output = run([str(clang), *module_flags, '-c', '-o', str(obj), str(source)])
            if code != 0:
                report['failures'].append({'module': module['name'], 'source': relative,
                                           'stderr': output[-3000:]})
                failed = True
                break
            objects.append(str(obj))
        if not failed and SHARED_SOURCES:
            for relative in SHARED_SOURCES:
                source = src_root / relative
                if not source.is_file():
                    continue
                obj = workdir / (relative.replace('/', '_') + '.o')
                code, output = run([str(clang), *flags, '-c', '-o', str(obj), str(source)])
                if code != 0:
                    report['failures'].append({'module': module['name'],
                                               'source': relative,
                                               'stderr': output[-3000:]})
                    failed = True
                    break
                objects.append(str(obj))
        if failed:
            continue
        staged_dir = args.packages / 'chimerax' / args.bundle
        staged_dir.mkdir(parents=True, exist_ok=True)
        artifact = staged_dir / (module['name'] + EXT_SUFFIX)
        module_linker = list(linker)
        for name in module.get('libraries', []):
            product = library_products.get(name)
            if product is not None:
                module_linker.append(str(product))
        code, output = run([str(clang), *module_flags, '-shared', f'-o{artifact}', *objects,
                            *shared_objects_extra, *module_linker])
        if code != 0:
            report['failures'].append({'module': module['name'], 'link_stderr': output[-4000:]})
            continue
        report['products'].append({'module': module['name'], 'path': str(artifact),
                                   'bytes': artifact.stat().st_size})
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'products': len(report['products']),
                      'failures': len(report['failures']),
                      'report': str(report_path)}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
