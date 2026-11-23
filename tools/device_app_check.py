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

    def dump_scrolling(required: list[str], rounds: int = 16) -> dict[str, str]:
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
            run(hdc + ['shell', 'uitest', 'uiInput', 'swipe', '1000', '1300', '1000', '950', '250'])
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
        # Top-of-page first: the command bar lives there, and clicking needs its rect.
        for _ in range(3):
            run(hdc + ['shell', 'uitest', 'uiInput', 'swipe', '1000', '600', '1000', '1500', '200'])
            time.sleep(0.5)
        dump()
        ui_command = _rect_from_dump('cx-cmd-run')
        ui_python = _rect_from_dump('cx-cmd-py')
        ui_output = ''
        if ui_command:
            run(hdc + ['shell', 'uitest', 'uiInput', 'click', str(ui_command[0]), str(ui_command[1])])
            time.sleep(4)
            ui_output = dump()[1].get('cx-cmd-output', '')
        ui_python_output = ''
        if ui_python:
            run(hdc + ['shell', 'uitest', 'uiInput', 'click', str(ui_python[0]), str(ui_python[1])])
            time.sleep(4)
            ui_python_output = dump()[1].get('cx-cmd-output', '')
        values = dump_scrolling(['cx-status', 'cx-command-run', 'cx-builtin', 'cx-graphics', 'cx-atomic', 'cx-glstack', 'cx-render', 'cx-gl-render', 'cx-model', 'cx-open', 'cx-trigger', 'cx-commands', 'cx-model-rows', 'cx-cmd-suggest', 'cx-log-rows', 'cx-selection-state', 'cx-builtin', 'cx-graphics'])
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
        # Interactive command channel results were captured at the top of the page.
        output = ui_output
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
        cx_render = values.get('cx-render', '')
        report['chimerax_render'] = cx_render
        record('ChimeraX adopts the native EGL context and GLES answers on it',
               # The adopted native context is verified through the raw GLES library;
               # PyOpenGL's entry points are the remaining gap (recorded below).
               # Adoption is the verified half; PyOpenGL's framebuffer path is still
               # open (documented in docs/gles2-binding-2026-11-18.md).
               # The probe prefixes diagnostic stats, so look for the marker anywhere.
               'context=EGLContext-adopted' in cx_render
               and ('view=64x64' in cx_render or 'raw=OpenGL ES' in cx_render),
               cx_render)
        render = values.get('cx-gl-render', '')
        # The official renderer must actually produce non-background pixels, not just a frame.
        import re as _re
        cached = _re.search(r'cached=(\d+)/(\d+)', cx_render)
        lit = int(cached.group(1)) if cached else 0
        record('ChimeraX own renderer draws geometry into the captured frame',
               cached is not None and lit > 1000, 'cached=%s' % (cached.group(0) if cached else 'none'))

        # Model Panel parity: the panel exists and lists the open model with its atom count.
        rows_text = values.get('cx-model-rows', '')
        # A row is "<id>|<name>|<atoms>|<residues>", rendered with the pipes replaced by spaces.
        panel_ok = 'cx-model-refresh' in values and len(re.findall(r'\d+', rows_text)) >= 3
        record('Model Panel lists the open models', panel_ok,
               rows_text[:80])

        # Command completion parity: typing a prefix offers registered command names.
        suggest_text = values.get('cx-cmd-suggest', '')
        # The row shows the first matches, so check the prefix and that several names are offered.
        record('The command line offers completion from the registered commands',
               '补全' in suggest_text and len(suggest_text.split()) >= 4,
               suggest_text[:80])

        # Log panel parity: the command that the checker typed above must appear in the log.
        log_text = values.get('cx-log-rows', '')
        record('The Log panel records executed commands', 'cxprobe' in log_text, log_text[:80])

        # Selection linkage: the shell selects atoms during start-up and reports the result.
        selection_text = values.get('cx-selection-state', '')
        report['selection_output'] = selection_text
        select_match = re.search(r'sel=(\d+)', selection_text)
        # Highlight channel: the selected atoms must reach the drawing that the renderer paints.
        hl_match = re.search(r'hl=(\d+)', cx_render)
        record('Selection reaches the highlight channel of the drawings',
               hl_match is not None and int(hl_match.group(1)) >= 1,
               'hl=%s' % (hl_match.group(1) if hl_match else 'none'))

        record('Selecting atoms updates the selection manager',
               select_match is not None and int(select_match.group(1)) > 0,
               selection_text[:80])

        # Compiled-extension matrix: at least six bundle C modules must import on device.
        match = re.search(r'cmods=(\d+)/(\d+)', values.get('cx-builtin', ''))
        record('Compiled bundle extensions import on device',
               match is not None and int(match.group(1)) >= 6,
               match.group(0) if match else 'none')

        # A real bundle command (mlp) must run to completion against the loaded protein.
        # Core command set: colouring, selection, display state, DSSP and camera commands run.
        core_ok = all(marker in cx_render for marker in
                      ('color=ok', 'select=ok', 'view=ok', 'turn=ok', 'zoom=ok', 'dssp=ok'))
        # Computation commands: RMSD, structural alignment and zone selection all complete.
        compute_ok = all(marker in cx_render for marker in
                         ('rmsd=ok', 'align=ok', 'zone=ok'))
        # Bundle subcommands that need domain input still prove the command system: the error is a
        # domain error from the command body, not "Unknown command".
        seg_ok = ('segmentation:UserError:No segmentations specified' in cx_render)
        record('Bundle subcommands parse and reach their implementation', seg_ok,
               'segmentation subcommand reached its body' if seg_ok else 'not reached')

        record('RMSD, align and zone commands compute on device', compute_ok,
               'rmsd/align/zone=%s' % ('ok' if compute_ok else 'failed'))

        record('The core command set executes on device', core_ok,
               'color/select/view/turn/zoom/dssp=%s' % ('ok' if core_ok else 'failed'))

        record('The morph bundle command interpolates between two structures',
               'morph=ok' in cx_render,
               'morph=%s' % ('ok' if 'morph=ok' in cx_render else 'failed'))

        record('The coulombic bundle command assigns charges and colours the surface',
               'coulombic=ok' in cx_render,
               'coulombic=%s' % ('ok' if 'coulombic=ok' in cx_render else 'failed'))

        record('The mlp bundle command computes a lipophilicity map',
               'mlp=ok' in cx_render, 'mlp=%s' % ('ok' if 'mlp=ok' in cx_render else 'failed'))

        record('A GLSL program renders on the device GPU',
               render.startswith('triangle:') and render.split(':')[1].split(',')[0] != '0', render)
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
        python_output = ui_python_output
        record('The Python sample runs from the UI',
               'ChimeraX' in python_output and any(ch.isdigit() for ch in python_output), python_output)
        report['python_output'] = python_output
        # Protein-command probe: the model-info button opens the bundled protein and runs the
        # bundle commands against it. Its output lands in the viewer status row.
        info_box = None
        for _ in range(4):
            dump()
            info_box = _rect_from_dump('cx-info-run')
            if info_box:
                break
            run(hdc + ['shell', 'uitest', 'uiInput', 'swipe', '1000', '1200', '1000', '900', '200'])
            time.sleep(0.6)
        # The demo button copies the real protein into the sandbox; the command probe then opens
        # that file instead of the four-atom test structure.
        real_box = _rect_from_dump('cx-real-run')
        if real_box:
            run(hdc + ['shell', 'uitest', 'uiInput', 'click', str(real_box[0]), str(real_box[1])])
            time.sleep(14)
        info_output = ''
        if info_box:
            run(hdc + ['shell', 'uitest', 'uiInput', 'click', str(info_box[0]), str(info_box[1])])
            # Opening a 1300-atom protein and running commands on it takes a while.
            time.sleep(60)
            dump()
            info_output = dump()[1].get('cx-viewer-status', '')
        report['info_probe_output'] = info_output
        record('Bundle commands run against the opened protein',
               'mlp' in info_output and 'Unknown command' not in info_output, info_output)

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
