#!/usr/bin/env python3
"""Stage the genuine ChimeraX Python package for packaging into the app.

Takes the pinned upstream tree (build/downloads/ChimeraX-src), generates
chimerax/version.py from the upstream buildinfo template with the real commit,
and copies the core bundle sources. Only modules that import without Qt are
exercised on the target; the rest stay in place for later work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPYRIGHT = ('Copyright 2025 Regents of the University of California. '
             'All rights reserved.')


def git(path: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(path), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'build/downloads/ChimeraX-src')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/chimerax-python')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()
    day = datetime.now(timezone.utc).date().isoformat()
    report_path = args.report or ROOT / f'reports/chimerax-python-{day}.json'
    core = args.source / 'src/bundles/core'
    package = args.output / 'chimerax'
    if package.exists():
        shutil.rmtree(package)
    (package / 'core').mkdir(parents=True)
    (package / '__init__.py').write_text('')
    commit = git(args.source, 'rev-parse', 'HEAD')
    date = git(args.source, 'log', '-1', '--format=%cI')
    branch = git(args.source, 'rev-parse', '--abbrev-ref', 'HEAD')
    version = 'v1.11.1'
    template = (core / 'buildinfo.py.in').read_text()
    buildinfo = (template.replace('VERSION', version).replace('COMMIT', commit)
                 .replace('DAYTIME', date).replace('BRANCH', branch)
                 .replace('COPYRIGHT', COPYRIGHT))
    (package / 'version.py').write_text(buildinfo)
    (package / 'core/buildinfo.py').write_text(buildinfo)
    shutil.copytree(core / 'src', package / 'core', dirs_exist_ok=True)
    for junk in ('tests', '__pycache__'):
        target = package / 'core' / junk
        if target.exists():
            shutil.rmtree(target)
    (package / 'core/buildinfo.py').write_text(buildinfo)
    # Pure-Python runtime dependencies of chimerax.core (colors/commands).
    wheels = sorted((ROOT / 'build/downloads').glob('sortedcontainers-*.whl'))
    dependency = None
    if wheels:
        wheel = wheels[-1]
        with zipfile.ZipFile(wheel) as bundle:
            for name in bundle.namelist():
                if name.startswith('sortedcontainers/') and name.endswith('.py'):
                    destination = args.output / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(bundle.read(name))
        dependency = {'wheel': wheel.name,
                      'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest()}
    files = {str(p.relative_to(args.output)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(args.output.rglob('*')) if p.is_file()}
    record = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'source': str(args.source), 'commit': commit, 'version': version,
              'branch': branch, 'files': len(files), 'package': str(package),
              'dependencies': [dependency] if dependency else [],
              'modules': sorted({p.split('/')[1] for p in files if p.count('/') >= 1})[:40]}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: record[k] for k in ('version', 'commit', 'files')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
