#!/usr/bin/env python3
"""Build the C modules a bundle declares in its bundle_info.xml.

ChimeraX's bundles list their extension sources in `<CModule>` entries, so the build list is
data rather than guesswork. This tool compiles those sources against the HarmonyOS NDK and
stages the resulting `.so` inside the staged ChimeraX tree.
"""
from __future__ import annotations

import argparse
import json
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
        modules.append({'name': name, 'sources': sources})
    return modules


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, help='bundle directory name, e.g. map')
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
    if args.numpy_include.is_dir():
        flags.append(f'-I{args.numpy_include}')
    linker = [f'-L{runtime_lib}', '-l:libpython3.11.so.1.0',
              '-Wl,-rpath,$ORIGIN/../../../../../lib:$ORIGIN/../../lib', '-Wl,--no-undefined']

    workdir = ROOT / 'build/bundle-cmodule' / args.bundle
    workdir.mkdir(parents=True, exist_ok=True)
    for module in modules:
        objects: list[str] = []
        failed = False
        for relative in module['sources']:
            source = bundle_root / relative
            obj = workdir / (relative.replace('/', '_') + '.o')
            code, output = run([str(clang), *flags, '-c', '-o', str(obj), str(source)])
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
        code, output = run([str(clang), *flags, '-shared', f'-o{artifact}', *objects, *linker])
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
