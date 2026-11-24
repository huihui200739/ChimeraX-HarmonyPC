#!/usr/bin/env python3
"""Build the ChimeraX HarmonyOS HAP from an ASCII-only staging path.

hvigor rejects project paths containing non-ASCII characters, so the app tree is
staged under a temporary ASCII directory, built there with the installed DevEco
toolchain, and the resulting package is copied back into build/hap/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEVECO = Path('/Applications/DevEco-Studio.app/Contents')


def run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stdout + result.stderr).strip().splitlines()[-25:]
        raise RuntimeError('\n'.join(tail))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=ROOT / 'app')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/hap')
    parser.add_argument('--report', type=Path, default=None)
    parser.add_argument('--keep-stage', action='store_true')
    args = parser.parse_args()
    day = datetime.now(timezone.utc).date().isoformat()
    report_path = args.report or ROOT / f'build/reports/hap-build-{day}.json'
    report: dict = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'scope': 'harmony_app_entry_build', 'steps': []}
    stage = Path(tempfile.mkdtemp(prefix='cx-hap-', dir='/tmp')) / 'app'
    try:
        shutil.copytree(args.app, stage,
                        ignore=shutil.ignore_patterns('build', '.hvigor', 'oh_modules', '.cxx'))
        (stage / 'hvigor').mkdir(exist_ok=True)
        report['stage'] = str(stage)
        run([str(DEVECO / 'tools/ohpm/bin/ohpm'), 'install', '--all'], cwd=stage)
        report['steps'].append('ohpm install')
        built = run([str(DEVECO / 'tools/hvigor/bin/hvigorw'), '--mode', 'module',
                     '-p', 'product=default', '-p', 'module=entry@default', '-p', 'buildMode=debug',
                     'assembleHap', '--no-daemon'], cwd=stage)
        report['steps'].append('hvigor assembleHap')
        report['build_tail'] = built.stdout.strip().splitlines()[-6:]
        outputs = list((stage / 'entry/build').rglob('*.hap'))
        if not outputs:
            raise RuntimeError('No HAP was produced')
        args.output.mkdir(parents=True, exist_ok=True)
        artifacts = []
        for hap in outputs:
            destination = args.output / hap.name
            shutil.copy2(hap, destination)
            artifacts.append({'path': str(destination), 'bytes': destination.stat().st_size,
                              'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()})
        report['artifacts'] = artifacts
        report['status'] = 'hap_built'
    except Exception as error:  # noqa: BLE001 - the report keeps the failure
        report['status'] = 'hap_build_failed'
        report['error'] = str(error)
    finally:
        if not args.keep_stage:
            shutil.rmtree(stage.parent, ignore_errors=True)
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(report['status'], json.dumps(report.get('artifacts', []), ensure_ascii=False))
    if report['status'] != 'hap_built':
        print(report.get('error', ''))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
