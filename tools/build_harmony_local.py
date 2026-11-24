#!/usr/bin/env python3
"""Cross-compile startup adapters locally. Never contact or run a device."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SDK = Path('/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native')


def run(argv: list[str]) -> dict:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=90, check=False)
        return {'argv': argv, 'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'argv': argv, 'returncode': None, 'error': str(exc), 'stdout': '', 'stderr': ''}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, default=DEFAULT_SDK)
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    parser.add_argument('--report', type=Path, default=ROOT / f'reports/local-build-{day}.json')
    parser.add_argument('--python-lib-dir', type=Path,
                        help='private runtime lib directory; links the launcher against libpython so '
                             'extension modules resolve CPython symbols on the target')
    args = parser.parse_args(argv)
    sdk = args.sdk.resolve()
    compiler = sdk / 'llvm/bin/clang'
    readelf = sdk / 'llvm/bin/llvm-readelf'
    output = ROOT / 'build/harmony-local'
    output.mkdir(parents=True, exist_ok=True)
    report_path = args.report
    report = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'generic_startup_adapter_cross_compile_only', 'device_contacted': False,
              'upstream_app_launched': False, 'target_python_validated': False,
              'target_ui_validated': False, 'port_validated': False, 'artifacts': [], 'commands': []}
    try:
        if not compiler.is_file() or not readelf.is_file() or not (sdk / 'sysroot').is_dir():
            raise RuntimeError('Native SDK compiler, ELF inspection tool and sysroot are required')
        common = [str(compiler), '--target=aarch64-linux-ohos', f'--sysroot={sdk / "sysroot"}',
                  '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-fPIC',
                  '-fvisibility=hidden', '-fstack-protector-strong',
                  '-Wl,-z,relro,-z,now', '-Wl,--no-undefined', str(ROOT / 'harmony/bootstrap.c'), '-ldl']
        launcher_flags = ['-Wl,-rpath,$ORIGIN/../lib']
        python_scope = None
        if args.python_lib_dir:
            lib_dir = args.python_lib_dir.resolve()
            candidates = sorted(lib_dir.glob('libpython3.11.so.*'))
            if not candidates:
                raise RuntimeError('private libpython shared object is missing from --python-lib-dir')
            python_scope = candidates[-1].name
            launcher_flags += ['-Wl,--no-as-needed', f'-L{lib_dir}', f'-l:{python_scope}',
                               '-Wl,--no-undefined']
        artifacts = [('ChimeraX', launcher_flags),
                     ('libcx_harmony_bootstrap.so', ['-shared', '-DCX_BOOTSTRAP_LIBRARY',
                      '-Wl,-soname,libcx_harmony_bootstrap.so', '-Wl,-rpath,$ORIGIN'])]
        for name, flags in artifacts:
            destination = output / name
            temporary = output / (name + '.new')
            build = run(common + flags + ['-o', str(temporary)])
            report['commands'].append(build)
            if build['returncode'] != 0:
                raise RuntimeError(f'Cross-compilation failed for {name}')
            inspect = run([str(readelf), '--file-header', '--program-headers', '--dynamic', '--dyn-syms', str(temporary)])
            report['commands'].append(inspect)
            if inspect['returncode'] != 0 or 'AArch64' not in inspect['stdout']:
                raise RuntimeError(f'Not a verified AArch64 ELF artifact: {name}')
            if name.endswith('.so') and 'cx_harmony_bootstrap' not in inspect['stdout']:
                raise RuntimeError('Shared bootstrap API was not exported')
            if name == 'ChimeraX' and python_scope and python_scope not in inspect['stdout']:
                raise RuntimeError('The launcher was not linked against the private libpython')
            temporary.replace(destination)
            report['artifacts'].append({'path': str(destination), 'bytes': destination.stat().st_size,
                        'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
                        'kind': 'native_startup_adapter_not_complete_application'})
        report['source_sha256'] = hashlib.sha256((ROOT / 'harmony/bootstrap.c').read_bytes()).hexdigest()
        report['header_sha256'] = hashlib.sha256((ROOT / 'harmony/bootstrap.h').read_bytes()).hexdigest()
        report['status'] = 'local_cross_compile_passed'
        report['missing_components'] = ['target CPython integration and target-side validation (not inspected by this adapter-only build)',
                 'target Qt and Python bindings', 'Qt HarmonyOS Ability/lifecycle integration',
                 'application contents and installable signed package']
    except RuntimeError as exc:
        report.update(status='blocked_local_build', error=str(exc))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"{report['status']}: {report_path}")
    return 0 if report['status'] == 'local_cross_compile_passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
