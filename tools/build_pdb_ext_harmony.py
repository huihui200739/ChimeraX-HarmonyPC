#!/usr/bin/env python3
"""Cross-compile the PDB reader extension (chimerax.pdb._pdbio) for HarmonyOS."""
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
SUFFIX = 'cpython-311-aarch64-linux-ohos.so'


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
    report_path = args.report or ROOT / f'reports/pdb-ext-{day}.json'
    report: dict = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'target': TRIPLE}
    bundles = args.source / 'src/bundles'
    clang = args.sdk / 'llvm/bin/clang++'
    # Support code comes from the single shared library (instance registries must
    # stay unique), so only the reader-specific sources are compiled here.
    targets = {
        'pdb/_pdbio': [*(bundles / 'pdb/pdbio_cpp').glob('*.cpp'),
                       *(bundles / 'pdb/pdb_cpp').glob('*.cpp')],
        'mmcif/_mmcif': [*(bundles / 'mmcif/mmcif_cpp').glob('*.cpp')],
    }
    includes = [
        args.cpython / 'source/Include', args.cpython / 'objects',
        args.packages / 'numpy/core/include',
        ROOT / 'build/atomic-include', ROOT / 'build/pdb-include',
        bundles / 'pdb/pdb_cpp', bundles / 'pdb/pdbio_cpp',
        bundles / 'mmcif/mmcif_cpp', bundles / 'mmcif/mmcif_cpp/readcif_cpp',
        bundles / 'atomic_lib/atomic_cpp', bundles / 'atomic_lib/atomic_cpp/atomstruct_cpp',
        ROOT / 'build/graphics-ext/include',
    ]
    try:
        results = []
        for module, sources in targets.items():
            if not sources:
                raise RuntimeError(f'no C++ sources found for {module}')
            target = args.packages / 'chimerax' / (module + '.' + SUFFIX)
            target.parent.mkdir(parents=True, exist_ok=True)
            command = [str(clang), f'--target={TRIPLE}', f'--sysroot={args.sdk / "sysroot"}',
                       '-std=c++11', '-O2', '-fPIC', '-shared', '-w',
                       *[f'-I{path}' for path in includes],
                       '-o', str(target), *[str(path) for path in sources],
                       f'-L{args.packages / "chimerax/lib"}', '-lcxatomstruct',
                       f'-L{args.cpython / "runtime/lib"}', '-l:libpython3.11.so.1.0',
                       '-Wl,-rpath,$ORIGIN/../lib:$ORIGIN/../lib/chimerax/lib']
            built = subprocess.run(command, capture_output=True, text=True)
            if built.returncode != 0:
                raise RuntimeError(module + ':\n' + built.stderr[-2000:])
            results.append({'module': module, 'path': str(target),
                            'bytes': target.stat().st_size, 'sha256': sha256(target),
                            'sources': len(sources)})
        report.update({'modules': results,
                       'status': 'reader_extensions_cross_compiled_not_target_tested'})
    except Exception as error:  # noqa: BLE001 - report the failure
        report['status'] = 'pdb_extension_build_failed'
        report['error'] = str(error)[:3500]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(report['status'], report.get('path', ''))
    if report['status'].endswith('build_failed'):
        print(report.get('error', '')[-600:])
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
