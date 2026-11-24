#!/usr/bin/env python3
"""Cythonise and cross-compile ChimeraX Cython extension modules for HarmonyOS.

Cython runs on the build machine (it only emits C); the generated C is then
compiled with the HarmonyOS SDK clang against the private runtime. Each module
links the static objects it needs, because the target loader resolves symbols
through an object's own dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SDK = Path('/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native')
TRIPLE = 'aarch64-linux-ohos'
SUFFIX = 'cpython-311-aarch64-linux-ohos.so'

MODULES = (
    # (module name, pyx relative to the bundle, extra static sources)
    ('atomic/cymol', 'atomic/atomic_cpp/cymol.pyx', ()),
    ('atomic/cytmpl', 'atomic/atomic_cpp/cytmpl.pyx', ()),
    # Structure readers: they are required for opening real files.
    ('mmcif/mmcif', 'mmcif/src/mmcif.pyx', ()),
    ('pdb/_pdbio', 'pdb/src/_pdbio.pyx', ()),
)


def sha256(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'build/downloads/ChimeraX-src')
    parser.add_argument('--sdk', type=Path, default=DEFAULT_SDK)
    parser.add_argument('--host-python', type=Path,
                        default=ROOT / 'build/host-python/cpython-3.11.17-macos-aarch64-none/bin/python3.11')
    parser.add_argument('--cpython', type=Path,
                        default=ROOT / 'build/cpython-3.11.18/ohos-aarch64-with-libffi-linked')
    parser.add_argument('--packages', type=Path, default=ROOT / 'build/chimerax-python')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()
    day = datetime.now(timezone.utc).date().isoformat()
    report_path = args.report or ROOT / f'reports/cython-modules-{day}.json'
    report: dict = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'target': TRIPLE, 'modules': []}
    bundles = args.source / 'src/bundles'
    clang = args.sdk / 'llvm/bin/clang++'
    sysroot = args.sdk / 'sysroot'
    # Every C++ source ChimeraX compiles into these modules, so the target loader
    # does not need separate shared libraries.
    # All C++ support code lives in one shared library so the per-type instance
    # registries are single (see tools/build_atomic_shared_lib_harmony.py).
    shared_lib_dir = args.packages / 'chimerax/lib'
    static_cpp: list[Path] = []
    py_include = args.cpython / 'source/Include'
    py_objects = args.cpython / 'objects'
    np_include = args.packages / 'numpy/core/include'
    runtime_lib = args.cpython / 'runtime/lib'
    try:
        for module, relative, _extra in MODULES:
            pyx = bundles / relative
            if not pyx.is_file():
                report['modules'].append({'module': module, 'status': 'missing-source'})
                continue
            with tempfile.TemporaryDirectory(prefix='cx-cython-') as work:
                c_file = Path(work) / (Path(relative).stem + '.c')
                cython = subprocess.run(
                    [str(args.host_python), '-m', 'cython', '-3', '--cplus',
                     '-I', str(bundles / 'atomic/atomic_cpp'), '-I', str(np_include),
                     '-o', str(c_file), str(pyx)],
                    capture_output=True, text=True)
                if cython.returncode != 0:
                    report['modules'].append({'module': module, 'status': 'cython-failed',
                                              'error': cython.stderr[-1200:]})
                    continue
                target = args.packages / 'chimerax' / (module + '.' + SUFFIX)
                target.parent.mkdir(parents=True, exist_ok=True)
                compile_cmd = [str(clang), f'--target={TRIPLE}', f'--sysroot={sysroot}',
                               '-std=c++11', '-O2', '-fPIC', '-shared', '-w',
                               f'-I{py_include}', f'-I{py_objects}', f'-I{np_include}',
                               f'-I{bundles / "atomic/atomic_cpp"}',
                               f'-I{ROOT / "build/graphics-ext/include"}',
                               f'-I{ROOT / "build/atomic-include"}',
                               f'-I{ROOT / "build/pdb-include"}',
                               f'-I{bundles / "pdb/pdb_cpp"}',
                               f'-I{bundles / "pdb/pdbio_cpp"}',
                               f'-I{bundles / "mmcif/mmcif_cpp"}',
                               f'-I{bundles / "mmcif/mmcif_cpp/readcif_cpp"}',
                               f'-I{bundles / "atomic_lib"}',
                               '-o', str(target), str(c_file),
                               *[str(path) for path in static_cpp],
                               f'-L{shared_lib_dir}', '-lcxatomstruct',
                               f'-L{runtime_lib}', '-l:libpython3.11.so.1.0',
                               "-Wl,-rpath,$ORIGIN/../lib:$ORIGIN/../lib/chimerax/lib"]
                built = subprocess.run(compile_cmd, capture_output=True, text=True)
                if built.returncode != 0:
                    report['modules'].append({'module': module, 'status': 'compile-failed',
                                              'error': built.stderr[-1500:]})
                    continue
                report['modules'].append({'module': module, 'status': 'built',
                                          'path': str(target), 'bytes': target.stat().st_size,
                                          'sha256': sha256(target)})
        built_modules = [m for m in report['modules'] if m.get('status') == 'built']
        report['status'] = ('cython_modules_cross_compiled_not_target_tested'
                            if built_modules else 'cython_modules_build_failed')
    except Exception as error:  # noqa: BLE001 - report the failure
        report['status'] = 'cython_modules_build_failed'
        report['error'] = str(error)[:3000]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(report['status'], [(m['module'], m.get('status')) for m in report['modules']])
    if report['status'] != 'cython_modules_cross_compiled_not_target_tested':
        for module in report['modules']:
            if module.get('error'):
                print(module['module'], module['error'][-400:])
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
