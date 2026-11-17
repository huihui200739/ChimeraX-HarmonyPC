#!/usr/bin/env python3
"""Cross-compile numpy for HarmonyOS (aarch64-linux-ohos) against the private runtime.

Only the pinned sdist is used; there is no network access and no host-wheel
substitution. The result is a directory of extension modules plus the numpy
Python package, importable by the packaged CPython runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SDK = Path('/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native')
VERSION = '1.26.4'
SHA256 = '2a02aba9ed12e4ac4eb3ea9421c420301a0c6460d9830d74a9df87efa4912010'


def sha256(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, default=DEFAULT_SDK)
    parser.add_argument('--host-python', type=Path,
                        default=ROOT / 'build/host-python/cpython-3.11.17-macos-aarch64-none/bin/python3.11')
    parser.add_argument('--archive', type=Path, default=ROOT / f'build/downloads/numpy-{VERSION}.tar.gz')
    parser.add_argument('--output', type=Path, default=ROOT / f'build/numpy-{VERSION}-ohos')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    report_path = args.report or ROOT / f'reports/numpy-{day}.json'
    report: dict = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'version': VERSION, 'target': 'aarch64-linux-ohos',
                    'host_executed': False, 'commands': []}
    compiler = args.sdk / 'llvm/bin/clang'
    sysroot = args.sdk / 'sysroot'
    try:
        if sha256(args.archive) != SHA256:
            raise RuntimeError('numpy sdist checksum does not match the pinned value')
        work = Path(tempfile.mkdtemp(prefix='numpy-ohos-', dir='/tmp')) / 'numpy'
        with tarfile.open(args.archive) as bundle:
            bundle.extractall(work.parent, filter='data')
        source = work.parent / f'numpy-{VERSION}'
        build_dir = work.parent / 'build-out'
        build_dir.mkdir()
        common = f'--target=aarch64-linux-ohos --sysroot={sysroot}'
        env = {key: value for key, value in os.environ.items()
               if key not in ('CFLAGS', 'LDFLAGS', 'CC', 'CXX', 'CPP')}
        env.update({
            'CC': f'{compiler} {common}',
            'CXX': f'{args.sdk}/llvm/bin/clang++ {common}',
            'LDSHARED': f'{compiler} {common} -shared',
            'AR': f'{args.sdk}/llvm/bin/llvm-ar',
            'RANLIB': f'{args.sdk}/llvm/bin/llvm-ranlib',
            'CFLAGS': '-O2 -fPIC -fstack-protector-strong',
            'LDFLAGS': '-Wl,-z,relro,-z,now',
            '_PYTHON_HOST_PLATFORM': 'linux-aarch64',
            'NPY_DISABLE_SVML': '1',
            'NPY_BLAS_ORDER': '',
            'NPY_LAPACK_ORDER': '',
            'NPY_BLAS_LIBS': '',
            'NPY_LAPACK_LIBS': '',
            'NPY_ATLAS': '',
            'PYTHONNOUSERSITE': '1',
            # numpy 1.26 uses stdlib distutils; the shim lacks msvccompiler.
            'SETUPTOOLS_USE_DISTUTILS': 'stdlib',
        })
        command = [str(args.host_python), 'setup.py', f'build_ext', f'--build-lib={build_dir}',
                   f'--build-temp={build_dir / "temp"}', '-j', str(args.jobs)]
        report['commands'].append({'argv': command, 'cwd': str(source)})
        log = build_dir.parent / 'numpy-build.log'
        with log.open('w') as stream:
            result = subprocess.run(command, cwd=source, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=3600)
        report['log'] = str(log)
        if result.returncode != 0:
            tail = log.read_text(errors='replace').splitlines()[-30:]
            raise RuntimeError('numpy build failed:\n' + '\n'.join(tail))
        target = args.output
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(build_dir / 'numpy', target / 'numpy')
        for extra in ('numpy.libs',):
            candidate = build_dir / extra
            if candidate.is_dir():
                shutil.copytree(candidate, target / extra)
        modules = sorted(p.name for p in (target / 'numpy/core').glob('*.ohos*.so'))
        report.update({'output': str(target), 'extension_modules': modules,
                       'files': sum(1 for _ in target.rglob('*') if _.is_file()),
                       'status': 'numpy_cross_compiled_not_target_tested'})
    except Exception as error:  # noqa: BLE001 - report the failure
        report['status'] = 'numpy_build_failed'
        report['error'] = str(error)[:4000]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(report['status'], report.get('error', '')[:500])
    return 0 if report['status'] == 'numpy_cross_compiled_not_target_tested' else 1


if __name__ == '__main__':
    raise SystemExit(main())
