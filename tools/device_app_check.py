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

    def _rect_from_dump(node_id: str):
        text = Path('/tmp/cx-app-layout.json').read_text(errors='replace') if Path('/tmp/cx-app-layout.json').is_file() else ''
        match = re.search(r'\{[^{}]*"id":"' + node_id + r'"[^{}]*\}', text)
        if not match:
            return None
        bounds = re.search(r'"(?:bounds|rect)":"?\[?(\d+),(\d+)\]\[?(\d+),(\d+)\]', match.group(0))
        if not bounds:
            numbers = re.findall(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', match.group(0))
            if numbers:
                x1, y1, x2, y2 = (int(v) for v in numbers[0])
                return ((x1 + x2) // 2, (y1 + y2) // 2)
            return None
        x1, y1, x2, y2 = (int(v) for v in bounds.groups())
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    def dump_scrolling(required: list[str], rounds: int = 6) -> dict[str, str]:
        """Scroll from the top to the bottom, merging every dump.

        The page is a Scroll, so a single dump only reports the visible rows; the
        probe rows must be collected across the whole scroll range.
        """
        # back to the top first
        for _ in range(3):
            run(hdc + ['shell', 'uitest', 'uiInput', 'swipe', '1000', '600', '1000', '1500', '200'])
            time.sleep(0.8)
        values = {k: v for k, v in dump()[1].items() if v not in ('', '—')}
        for _ in range(rounds):
            if all(key in values for key in required):
                break
            run(hdc + ['shell', 'uitest', 'uiInput', 'swipe', '1000', '1400', '1000', '700', '300'])
            time.sleep(1.2)
            values.update({k: v for k, v in dump()[1].items() if v not in ('', '—')})
        return values

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
        values = dump_scrolling(['cx-status', 'cx-command-run', 'cx-builtin', 'cx-graphics', 'cx-atomic', 'cx-glstack', 'cx-model', 'cx-open', 'cx-trigger', 'cx-commands', 'cx-builtin', 'cx-graphics'])
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
        commands = values.get('cx-commands', '')
        core_api = values.get('cx-commands', '')
        session_part = core_api.split('|', 3)[-1] if '|' in core_api else ''
        record('A minimal ChimeraX Session can be constructed in the app',
               'Session|True|' in core_api and session_part.strip().isdigit()
               or ('Session|True|' in core_api and any(ch.isdigit() for ch in core_api.split('Session')[-1])),
               core_api)
        record('ChimeraX command subsystem imports in the app',
               'chimerax.core.commands' in commands, commands)
        record('ChimeraX trigger dispatch runs in the app',
               'cx_app_probe' in values.get('cx-trigger', '') and 'fired' in values.get('cx-trigger', ''),
               values.get('cx-trigger', ''))
        record('ChimeraX core modules import in the app',
               core.startswith('chimerax.core.errors|UserError|Logger'), core)
        # Interactive command channel: press the command button, then the Python sample.
        dump()
        command_box = _rect_from_dump('cx-cmd-run')
        python_box = _rect_from_dump('cx-cmd-py')
        output = ''
        if command_box:
            run(hdc + ['shell', 'uitest', 'uiInput', 'click', str(command_box[0]), str(command_box[1])])
            time.sleep(4)
            values = dump()[1]
            output = values.get('cx-cmd-output', '')
        builtin = values.get('cx-builtin', '')
        graphics = values.get('cx-graphics', '')
        gl = values.get('cx-gl-status', '')
        record('An EGL/GLES surface is created inside the app', gl.startswith('xcomponent') or gl.startswith('ready:'), gl)
        report['gl_status'] = gl
        atomic = values.get('cx-atomic', '')
        glstack = values.get('cx-glstack', '')
        model = values.get('cx-model', '')
        opened = values.get('cx-open', '')
        record('A real PDB file is opened by the C++ reader in the app',
               opened.startswith('models=1|atoms=4|residues=1'), opened)
        record('A real AtomicStructure with atoms is built in the app',
               model.startswith('atoms=2|residues=1|names=C1,N1'), model)
        record('PyOpenGL and the graphics Python layer load in the app',
               glstack.startswith('3.') and 'chimerax.graphics.opengl' in glstack, glstack)
        record('The ChimeraX atomic layer imports in the app',
               atomic.startswith('chimerax.atomic|Atom|AtomicStructure'), atomic)
        record('The graphics C++ extension loads and runs in the app',
               graphics.startswith('chimerax.graphics._graphics|3'), graphics)
        record('Core built-in commands run in the app',
               builtin.startswith('toolshed-list:ok') and 'devel-dump:Missing or invalid' in builtin,
               builtin)
        record('The persistent session keeps its tools and toolshed',
               'tools=True' in builtin and 'toolshed=True' in builtin, builtin)
        a = 'cx-builtin'
        report[a] = builtin
        record('ChimeraX command syntax runs from the UI',
               'cxprobe:ui-command' in output, output)
        report['command_output'] = output
        if python_box:
            run(hdc + ['shell', 'uitest', 'uiInput', 'click', str(python_box[0]), str(python_box[1])])
            time.sleep(4)
            values = dump()[1]
            python_output = values.get('cx-cmd-output', '')
        else:
            python_output = ''
        record('The Python sample runs from the UI',
               'ChimeraX' in python_output and any(ch.isdigit() for ch in python_output), python_output)
        report['python_output'] = python_output
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
