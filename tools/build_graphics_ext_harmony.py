#!/usr/bin/env python3
"""Cross-compile the ChimeraX graphics C++ extensions for HarmonyOS.

Builds two CPython extension modules from the pinned upstream tree:

* ``chimerax.arrays._arrays``  (array marshalling shared by the C++ code)
* ``chimerax.graphics._graphics`` (image accumulate/blend, mesh edges, counts)

HarmonyOS has no GLX/NSOpenGL swap-interval call, so a small platform stub
provides the two symbols the module table references and reports "not applied".
Sources are compiled with the SDK clang against the private runtime; nothing is
executed on the build machine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SDK = Path('/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native')
TRIPLE = 'aarch64-linux-ohos'
SUFFIX = 'cpython-311-aarch64-linux-ohos.so'

STUB = '''// HarmonyOS has no GLX/NSOpenGL swap-interval entry point; ChimeraX only needs
// the symbol to exist and report that the request was not applied.
#include <Python.h>

extern "C" PyObject *set_linux_swap_interval(PyObject *s, PyObject *args, PyObject *keywds) {
  static const char *kwlist[] = {"swap_interval", nullptr};
  int interval = 0;
  if (!PyArg_ParseTupleAndKeywords(args, keywds, "i", const_cast<char **>(kwlist), &interval)) {
    return nullptr;
  }
  Py_RETURN_FALSE;
}

extern "C" PyObject *set_mac_swap_interval(PyObject *s, PyObject *args, PyObject *keywds) {
  static const char *kwlist[] = {"swap_interval", nullptr};
  int interval = 0;
  if (!PyArg_ParseTupleAndKeywords(args, keywds, "i", const_cast<char **>(kwlist), &interval)) {
    return nullptr;
  }
  Py_RETURN_FALSE;
}
'''


def sha256(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'build/downloads/ChimeraX-src')
    parser.add_argument('--sdk', type=Path, default=DEFAULT_SDK)
    parser.add_argument('--cpython', type=Path,
                        default=ROOT / 'build/cpython-3.11.18/ohos-aarch64-with-libffi-linked')
    parser.add_argument('--packages', type=Path, default=ROOT / 'build/chimerax-python')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()
    day = datetime.now(timezone.utc).date().isoformat()
    report_path = args.report or ROOT / f'reports/graphics-ext-{day}.json'
    bundles = args.source / 'src/bundles'
    arrays_src = bundles / 'arrays/_arrays'
    graphics_src = bundles / 'graphics/_graphics'
    include_root = ROOT / 'build/graphics-ext/include'
    stub = ROOT / 'build/graphics-ext/src/swap_interval_ohos.cpp'
    report: dict = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'target': TRIPLE, 'host_executed': False, 'modules': []}
    clang = args.sdk / 'llvm/bin/clang++'
    sysroot = args.sdk / 'sysroot'
    py_include = args.cpython / 'source/Include'
    py_objects = args.cpython / 'objects'
    numpy_include = args.packages / 'numpy/core/include'
    runtime_lib = args.cpython / 'runtime/lib'
    try:
        for required in (clang, py_include / 'Python.h', py_objects / 'pyconfig.h',
                         numpy_include / 'numpy/arrayobject.h', runtime_lib / 'libpython3.11.so.1.0'):
            if not required.exists():
                raise RuntimeError(f'missing build input: {required}')
        include_root.mkdir(parents=True, exist_ok=True)
        link = include_root / 'arrays'
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(arrays_src)
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(STUB)

        common = [str(clang), f'--target={TRIPLE}', f'--sysroot={sysroot}', '-std=c++11', '-O2',
                  '-fPIC', '-shared', f'-I{py_include}', f'-I{py_objects}', f'-I{include_root}',
                  f'-I{numpy_include}']
        linker = [f'-L{runtime_lib}', '-l:libpython3.11.so.1.0', "-Wl,-rpath,$ORIGIN/../lib"]

        arrays_cpp = [arrays_src / name for name in
                      ('load_arrays.cpp', 'pythonarray.cpp', 'rcarray.cpp', 'refcount.cpp')]
        arrays_out = args.packages / 'chimerax/arrays' / f'_arrays.{SUFFIX}'
        graphics_out = args.packages / 'chimerax/graphics' / f'_graphics.{SUFFIX}'
        arrays_out.parent.mkdir(parents=True, exist_ok=True)
        graphics_out.parent.mkdir(parents=True, exist_ok=True)

        graphics_cpp = [graphics_src / name for name in
                        ('blend_rgba.cpp', 'count.cpp', 'graphics.cpp', 'mesh_edges.cpp')]
        jobs = [
            ('_arrays', common + [f'-o{arrays_out}'] + [str(p) for p in arrays_cpp] + linker),
            # The graphics module shares the array marshalling objects, so they are
            # compiled into it as well; otherwise the loader reports missing symbols.
            ('_graphics', common + [f'-o{graphics_out}'] + [str(p) for p in graphics_cpp]
             + [str(stub)] + [str(p) for p in arrays_cpp] + linker),
        ]
        for name, argv in jobs:
            result = subprocess.run(argv, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f'{name} compile failed:\n' + result.stderr[-1500:])
            target = arrays_out if name == '_arrays' else graphics_out
            report['modules'].append({'module': name, 'path': str(target),
                                      'bytes': target.stat().st_size,
                                      'sha256': sha256(target)})
        report['status'] = 'graphics_extensions_cross_compiled_not_target_tested'
    except Exception as error:  # noqa: BLE001 - report the failure
        report['status'] = 'graphics_extension_build_failed'
        report['error'] = str(error)[:3000]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(report['status'], [Path(m['path']).name for m in report['modules']])
    if report['status'] != 'graphics_extensions_cross_compiled_not_target_tested':
        print(report.get('error', ''))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
