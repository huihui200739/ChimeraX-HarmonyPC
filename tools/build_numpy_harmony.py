#!/usr/bin/env python3
"""Cross-compile numpy 1.26.4 for HarmonyOS with meson.

The pinned sdist is configured through a meson cross file:

* clang from the HarmonyOS SDK with the OHOS sysroot,
* ``exe_wrapper`` runs configure probes on the target through hdc,
* ``longdouble_format`` is declared explicitly (cross builds cannot run the
  format probe on the build machine),
* extension modules are linked against the private libpython with a relative
  rpath, because the target loader only resolves CPython symbols through an
  object's own NEEDED entries.

No host wheel and no network access are used.
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
TRIPLE = 'aarch64-linux-ohos'


def sha256(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def cross_file(sdk: Path, runtime_lib: Path, hdc: Path, target: str) -> str:
    cc = sdk / 'llvm/bin/clang'
    cxx = sdk / 'llvm/bin/clang++'
    sysroot = sdk / 'sysroot'
    common = f'--target={TRIPLE} --sysroot={sysroot}'
    wrapper = Path('/tmp/cx-meson-device-run.sh')
    wrapper.write_text(f'''#!/bin/sh
HDC="{hdc}"
BIN="$1"
shift
"$HDC" -t {target} file send "$BIN" /data/local/tmp/cx-meson-probe >/dev/null 2>&1 || exit 1
"$HDC" -t {target} shell "chmod 755 /data/local/tmp/cx-meson-probe" >/dev/null 2>&1
"$HDC" -t {target} shell "/data/local/tmp/cx-meson-probe $*"
''')
    wrapper.chmod(0o755)
    return f'''[binaries]
c = '{cc}'
cpp = '{cxx}'
ar = '{sdk}/llvm/bin/llvm-ar'
strip = '{sdk}/llvm/bin/llvm-strip'
ranlib = '{sdk}/llvm/bin/llvm-ranlib'
pkg-config = 'false'
pkgconfig = 'false'
exe_wrapper = '{wrapper}'

[host_machine]
system = 'linux'
cpu_family = 'aarch64'
cpu = 'aarch64'
endian = 'little'

[properties]
needs_exe_wrapper = true
# aarch64 Linux/OHOS uses IEEE binary128 long double; the probe cannot run here.
longdouble_format = 'IEEE_QUAD_LE'

[built-in options]
c_args = ['--target={TRIPLE}', '--sysroot={sysroot}', '-O2', '-fPIC']
cpp_args = ['--target={TRIPLE}', '--sysroot={sysroot}', '-O2', '-fPIC']
c_link_args = ['--target={TRIPLE}', '--sysroot={sysroot}', '-shared',
               '-L{runtime_lib}', '-l:libpython3.11.so.1.0',
               '-Wl,-rpath,$ORIGIN/../../../lib']
cpp_link_args = ['--target={TRIPLE}', '--sysroot={sysroot}', '-shared',
                 '-L{runtime_lib}', '-l:libpython3.11.so.1.0',
                 '-Wl,-rpath,$ORIGIN/../../../lib']
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, default=DEFAULT_SDK)
    parser.add_argument('--host-python', type=Path,
                        default=ROOT / 'build/host-python/cpython-3.11.17-macos-aarch64-none/bin/python3.11')
    parser.add_argument('--archive', type=Path, default=ROOT / f'build/downloads/numpy-{VERSION}.tar.gz')
    parser.add_argument('--runtime-lib', type=Path,
                        default=ROOT / 'build/cpython-3.11.18/ohos-aarch64-with-libffi-linked/runtime/lib')
    parser.add_argument('--target', default='127.0.0.1:5555')
    parser.add_argument('--output', type=Path, default=ROOT / f'build/numpy-{VERSION}-ohos-wheel')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    report_path = args.report or ROOT / f'reports/numpy-{day}.json'
    report: dict = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'version': VERSION, 'target': TRIPLE, 'builder': 'meson',
                    'host_executed': False, 'target_executed': False}
    hdc = Path('/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc')
    try:
        if sha256(args.archive) != SHA256:
            raise RuntimeError('numpy sdist checksum does not match the pinned value')
        work = Path(tempfile.mkdtemp(prefix='numpy-meson-'))
        with tarfile.open(args.archive) as bundle:
            bundle.extractall(work, filter='data')
        source = work / f'numpy-{VERSION}'
        cross = work / 'cx-cross.ini'
        cross.write_text(cross_file(args.sdk, args.runtime_lib, hdc, args.target))
        wheel_dir = work / 'wheels'
        wheel_dir.mkdir()
        env = dict(os.environ)
        env['PATH'] = f'{args.host_python.parent}:/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native/build-tools/cmake/bin:' + env.get('PATH', '')
        command = [str(args.host_python), '-m', 'pip', 'wheel', '--no-build-isolation', '--no-deps',
                   '-w', str(wheel_dir), f'-Csetup-args=--cross-file={cross}',
                   '-Csetup-args=-Dblas=none', '-Csetup-args=-Dlapack=none', '.']
        log = work / 'numpy-build.log'
        with log.open('w') as stream:
            result = subprocess.run(command, cwd=source, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=5400)
        report['log'] = str(log)
        wheels = sorted(wheel_dir.glob('numpy-*.whl'))
        if result.returncode != 0 or not wheels:
            tail = log.read_text(errors='replace').splitlines()[-25:]
            raise RuntimeError('numpy meson build failed:\n' + '\n'.join(tail))
        wheel = wheels[-1]
        args.output.mkdir(parents=True, exist_ok=True)
        destination = args.output / wheel.name
        shutil.copy2(wheel, destination)
        report.update({'wheel': str(destination), 'wheel_sha256': sha256(destination),
                       'cross_file': cross.read_text(),
                       'status': 'numpy_cross_compiled_not_target_tested'})
    except Exception as error:  # noqa: BLE001 - report the failure
        report['status'] = 'numpy_build_failed'
        report['error'] = str(error)[:4000]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(report['status'], report.get('wheel', ''), report.get('error', '')[:400])
    return 0 if report['status'] == 'numpy_cross_compiled_not_target_tested' else 1


if __name__ == '__main__':
    raise SystemExit(main())
