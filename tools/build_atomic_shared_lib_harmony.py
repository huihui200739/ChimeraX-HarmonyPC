#!/usr/bin/env python3
"""Build one shared C++ support library for the atomic/reader extensions.

ChimeraX's C++ layers keep per-type instance registries (pyinstance). Linking the
same sources into every extension gives each copy its own registry, so Python
cannot wrap a C++ Residue/Atom ("Cannot instantiate Python class corresponding to
C++ atomstruct::Residue"). This tool builds a single shared library that all the
extensions link against instead.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SDK = Path('/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native')
TRIPLE = 'aarch64-linux-ohos'


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
    report_path = args.report or ROOT / f'reports/atomic-shared-lib-{day}.json'
    report: dict = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'target': TRIPLE}
    bundles = args.source / 'src/bundles'
    sources: list[Path] = []
    for pattern in ('arrays/_arrays/*.cpp',
                    'atomic_lib/atomic_cpp/atomstruct_cpp/*.cpp',
                    'atomic_lib/atomic_cpp/atomstruct_cpp/tmpl/*.cpp',
                    'atomic_lib/atomic_cpp/element_cpp/*.cpp',
                    'atomic_lib/atomic_cpp/pyinstance_cpp/*.cpp',
                    'pdb_lib/connect_cpp/*.cpp',
                    'mmcif/mmcif_cpp/*.cpp',
                    'mmcif/mmcif_cpp/readcif_cpp/*.cpp',
                    'core/core_cpp/logger/*.cpp',
                    'core/core_cpp/ioutil/*.cpp',
                    'core/core_cpp/chutil/*.cpp'):
        sources.extend(sorted(bundles.glob(pattern)))
    sources = [path for path in sources if path.name != 'load_libs.cpp']
    includes = [
        args.cpython / 'source/Include', args.cpython / 'objects',
        args.packages / 'numpy/core/include',
        ROOT / 'build/atomic-include', ROOT / 'build/pdb-include',
        ROOT / 'build/graphics-ext/include',
        bundles / 'atomic_lib/atomic_cpp', bundles / 'atomic_lib/atomic_cpp/atomstruct_cpp',
        bundles / 'pdb/pdb_cpp', bundles / 'pdb/pdbio_cpp',
        bundles / 'mmcif/mmcif_cpp', bundles / 'mmcif/mmcif_cpp/readcif_cpp',
    ]
    try:
        target = args.packages / 'chimerax' / 'lib' / 'libcxatomstruct.so'
        target.parent.mkdir(parents=True, exist_ok=True)
        command = [str(args.sdk / 'llvm/bin/clang++'), f'--target={TRIPLE}',
                   f'--sysroot={args.sdk / "sysroot"}', '-std=c++11', '-O2', '-fPIC', '-shared', '-w',
                   *[f'-I{path}' for path in includes],
                   '-o', str(target), *[str(path) for path in sources],
                   f'-L{args.cpython / "runtime/lib"}', '-l:libpython3.11.so.1.0',
                   "-Wl,-rpath,$ORIGIN/../lib", '-Wl,--no-undefined']
        built = subprocess.run(command, capture_output=True, text=True)
        if built.returncode != 0:
            raise RuntimeError(built.stderr[-3000:])
        report.update({'path': str(target), 'bytes': target.stat().st_size,
                       'sha256': sha256(target), 'sources': len(sources),
                       'status': 'atomic_shared_lib_cross_compiled_not_target_tested'})
    except Exception as error:  # noqa: BLE001 - report the failure
        report['status'] = 'atomic_shared_lib_build_failed'
        report['error'] = str(error)[:3500]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(report['status'], report.get('path', ''))
    if report['status'].endswith('failed'):
        print(report.get('error', '')[-800:])
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
