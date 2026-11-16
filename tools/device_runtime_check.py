#!/usr/bin/env python3
"""Run the private CPython runtime on a HarmonyOS target and record the result.

Pushes the packaged runtime payload to the target, extracts it under
/data/local/tmp, executes the launcher's own runtime check plus a probe that
imports the native extensions (including _ctypes/libffi), and writes a report.
No application modules, Qt bindings or research data are involved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HDC = Path('/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc')
DEFAULT_TARGET = '127.0.0.1:5555'
DEVICE_ROOT = '/data/local/tmp/cx-runtime-check'

PROBE = '''import json, sys
out = {"python": sys.version.split()[0], "platform": sys.platform}
try:
    import _ctypes, ctypes
    libc = ctypes.CDLL("libc.so", use_errno=True)
    out["ctypes_module"] = getattr(_ctypes, "__file__", "").split("/")[-1]
    out["ctypes_ffi_call"] = hasattr(_ctypes, "call_function") or hasattr(_ctypes, "CFuncPtr")
    out["libc_strlen"] = libc.strlen(b"chimerax-on-harmony")
except Exception as error:
    out["ctypes_error"] = f"{type(error).__name__}: {error}"
try:
    import math, json as _json, zlib, hashlib, binascii
    out["stdlib_probe"] = [math.sqrt(16.0), len(_json.dumps({"a": 1})), len(zlib.compress(b"x" * 100)),
                           hashlib.sha256(b"cx").hexdigest()[:8], binascii.hexlify(b"\\x01\\x02").decode()]
except Exception as error:
    out["stdlib_error"] = f"{type(error).__name__}: {error}"
print(json.dumps(out, ensure_ascii=False))
'''


def run(command: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hdc', type=Path, default=DEFAULT_HDC)
    parser.add_argument('--target', default=DEFAULT_TARGET)
    parser.add_argument('--payload', type=Path,
                        default=ROOT / 'build/runtime-payload/cx-generic-runtime-3.11.18-with-libffi-aarch64-ohos.tar.gz')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    report_path = args.report or ROOT / f'reports/device-runtime-{day}.json'
    hdc = [str(args.hdc), '-t', args.target]
    report: dict = {
        'schema_version': 1,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'generic_runtime_device_check_no_application',
        'target': args.target,
        'payload': {'path': str(args.payload), 'bytes': args.payload.stat().st_size,
                    'sha256': hashlib.sha256(args.payload.read_bytes()).hexdigest()},
        'checks': [], 'commands': [],
    }

    def record(name: str, passed: bool, detail: str) -> None:
        report['checks'].append({'name': name, 'passed': bool(passed), 'detail': detail[:800]})

    try:
        info = run(hdc + ['shell', 'param get const.product.model'])
        report['device'] = {
            'model': info.stdout.strip(),
            'system': run(hdc + ['shell', 'param get const.ohos.apiversion']).stdout.strip(),
            'cpu': run(hdc + ['shell', 'param get const.product.cpu.abilist']).stdout.strip(),
            'uname': run(hdc + ['shell', 'uname', '-a']).stdout.strip(),
        }
        run(hdc + ['shell', f'rm -rf {DEVICE_ROOT} && mkdir -p {DEVICE_ROOT}'])
        sent = run(hdc + ['file', 'send', str(args.payload), f'{DEVICE_ROOT}/runtime.tar.gz'])
        report['commands'].append(sent.stdout.strip()[-300:])
        record('Runtime payload transferred', sent.returncode == 0, sent.stdout.strip()[-300:])
        extract = run(hdc + ['shell', f'cd {DEVICE_ROOT} && tar xzf runtime.tar.gz 2>&1 | head -5'])
        report['extract'] = extract.stdout.strip()
        root_path = f'{DEVICE_ROOT}/cx-generic-runtime'
        listing = run(hdc + ['shell', f'ls {root_path}'])
        record('Runtime extracted on the target', 'bin' in listing.stdout, listing.stdout.strip())

        check = run(hdc + ['shell', f'cd {root_path} && ./bin/ChimeraX --cx-runtime-root {root_path} --cx-runtime-check'])
        report['runtime_check_raw'] = check.stdout.strip()
        payload = {}
        for line in check.stdout.strip().splitlines():
            line = line.strip()
            if line.startswith('{'):
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
        report['runtime_check'] = payload
        record('Launcher runtime check reports CPython',
               payload.get('implementation') == 'cpython' and 'version' in payload,
               str(payload)[:400])
        record('Runtime reports isolated UTF-8 mode',
               bool(payload.get('isolated')) and bool(payload.get('utf8')), str(payload)[:200])

        target_main = f'{root_path}/lib/python3.11/chimerax/core/__main__.py'
        local_probe = Path('/tmp/cx_device_probe.py')
        local_probe.write_text(PROBE)
        run(hdc + ['shell', f'mkdir -p {root_path}/lib/python3.11/chimerax/core'])
        run(hdc + ['file', 'send', str(local_probe), target_main])
        probe = run(hdc + ['shell', f'cd {root_path} && ./bin/ChimeraX --cx-runtime-root {root_path}'])
        report['probe_raw'] = probe.stdout.strip()[-800:]
        probe_payload = {}
        for line in probe.stdout.strip().splitlines():
            line = line.strip()
            if line.startswith('{'):
                try:
                    probe_payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
            elif 'ImportError' in line:
                probe_payload.setdefault('errors', []).append(line.strip()[:300])
        report['probe'] = probe_payload
        record('Native extensions import on the target',
               'ctypes_error' not in probe_payload and 'stdlib_error' not in probe_payload,
               str(probe_payload)[:400])
        record('_ctypes calls into libc through libffi', probe_payload.get('libc_strlen') == 19,
               str(probe_payload.get('libc_strlen')))
        record('Standard library probe returns expected values',
               probe_payload.get('stdlib_probe') == [4.0, 8, 12, '2c1179ae', '0102'],
               str(probe_payload.get('stdlib_probe')))
        run(hdc + ['shell', f'rm -rf {root_path}/lib/python3.11/chimerax'])
        leftovers = run(hdc + ['shell', f'ls {root_path}/lib/python3.11/chimerax 2>&1'])
        record('Probe module removed after the check', 'No such file' in leftovers.stdout or
               leftovers.returncode != 0, leftovers.stdout.strip())
    except Exception as error:  # noqa: BLE001 - the report must capture the failure
        report['error'] = f'{type(error).__name__}: {error}'

    passed = sum(1 for item in report['checks'] if item['passed'])
    report['result'] = {'passed': passed, 'failed': len(report['checks']) - passed}
    report['status'] = 'device_runtime_verified' if report['checks'] and passed == len(report['checks']) else 'device_runtime_incomplete'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['result'], ensure_ascii=False), report['status'], report_path)
    return 0 if report['status'] == 'device_runtime_verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
