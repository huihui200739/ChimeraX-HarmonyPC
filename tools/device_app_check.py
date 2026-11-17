#!/usr/bin/env python3
"""Install the ChimeraX Harmony HAP on a target, launch it and read the runtime state.

The page reports the embedded CPython version and three probe results; this tool
verifies those through the UI hierarchy instead of trusting logs alone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HDC = Path('/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc')
BUNDLE = 'com.example.chimeraxharmony'


def run(argv: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hdc', type=Path, default=DEFAULT_HDC)
    parser.add_argument('--target', default='127.0.0.1:5555')
    parser.add_argument('--hap', type=Path, default=ROOT / 'build/hap/entry-default-unsigned.hap')
    parser.add_argument('--report', type=Path, default=None)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    day = datetime.now(timezone.utc).date().isoformat()
    report_path = args.report or ROOT / f'reports/device-app-{day}.json'
    hdc = [str(args.hdc), '-t', args.target]
    report: dict = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'scope': 'harmony_app_entry_with_embedded_runtime', 'target': args.target,
                    'hap': {'path': str(args.hap), 'bytes': args.hap.stat().st_size,
                            'sha256': hashlib.sha256(args.hap.read_bytes()).hexdigest()},
                    'checks': []}

    def record(name: str, passed: bool, detail: str = '') -> None:
        report['checks'].append({'name': name, 'passed': bool(passed), 'detail': str(detail)[:600]})

    def dump() -> tuple[str, dict[str, str]]:
        remote = '/data/local/tmp/cx-app-layout.json'
        run(hdc + ['shell', 'uitest', 'dumpLayout', '-b', BUNDLE, '-p', remote, '-a'])
        run(hdc + ['file', 'recv', remote, '/tmp/cx-app-layout.json'])
        path = Path('/tmp/cx-app-layout.json')
        if not path.is_file():
            return '', {}
        text = path.read_text(errors='replace')
        values: dict[str, str] = {}
        for match in re.finditer(r'"id":"([^"]+)"[^}]*?"text":"((?:[^"\\]|\\.)*)"', text):
            values[match.group(1)] = match.group(2)
        return text, values

    try:
        install = run(hdc + ['install', '-r', str(args.hap)], timeout=600)
        record('HAP installs', install.returncode == 0, (install.stdout + install.stderr)[-300:])
        run(hdc + ['shell', 'aa', 'force-stop', BUNDLE])
        start = run(hdc + ['shell', 'aa', 'start', '-a', 'EntryAbility', '-b', BUNDLE])
        record('Application starts', start.returncode == 0, (start.stdout + start.stderr)[-200:])
        values: dict[str, str] = {}
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            _, values = dump()
            if values.get('cx-status') in ('运行环境就绪', '失败'):
                break
            time.sleep(5)
        report['ui'] = values
        record('Runtime reports a ready state', values.get('cx-status') == '运行环境就绪',
               values.get('cx-status', 'no status'))
        record('Embedded CPython reports its version', 'cpython' in values.get('cx-version', '').lower()
               or '3.11' in values.get('cx-version', ''), values.get('cx-version', ''))
        record('math.sqrt evaluates inside the app', values.get('cx-math') == '4.0', values.get('cx-math', ''))
        record('ctypes reaches libc through libffi', values.get('cx-ctypes') == '19', values.get('cx-ctypes', ''))
        stdlib = values.get('cx-stdlib', '')
        record('Standard library probe matches', '2c1179ae' in stdlib, stdlib)
        record('Genuine ChimeraX version module loads',
               values.get('cx-chimerax', '').startswith('v1.'), values.get('cx-chimerax', ''))
        core = values.get('cx-core', '')
        numpy = values.get('cx-numpy', '')
        record('numpy imports and computes in the app',
               numpy.startswith('1.26.4|4.0|10'), numpy)
        core_path = values.get('cx-numpyc', '')
        record('numpy extension loads from the application native library directory',
               'libs' in core_path and '_multiarray_umath' in core_path, core_path)
        record('ChimeraX trigger dispatch runs in the app',
               'cx_app_probe' in values.get('cx-trigger', '') and 'fired' in values.get('cx-trigger', ''),
               values.get('cx-trigger', ''))
        record('ChimeraX core modules import in the app',
               core.startswith('chimerax.core.errors|UserError|Logger'), core)
        screenshot = run(hdc + ['shell', 'snapshot_display', '-f', '/data/local/tmp/cx-app.jpeg'])
        if screenshot.returncode == 0:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            run(hdc + ['file', 'recv', '/data/local/tmp/cx-app.jpeg',
                       str(ROOT / 'reports' / 'device-app-2026-11-17.jpeg')])
    except Exception as error:  # noqa: BLE001 - report the failure
        report['error'] = f'{type(error).__name__}: {error}'

    passed = sum(1 for item in report['checks'] if item['passed'])
    report['result'] = {'passed': passed, 'failed': len(report['checks']) - passed}
    report['status'] = 'app_runtime_verified' if report['checks'] and passed == len(report['checks']) else 'app_runtime_incomplete'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['result'], ensure_ascii=False), report['status'], report_path)
    return 0 if report['status'] == 'app_runtime_verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
