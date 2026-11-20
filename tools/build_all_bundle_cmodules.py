#!/usr/bin/env python3
"""Build the C modules of every bundle in the staging list.

Run after tools/stage_chimerax_python.py: staging recreates the package tree, so the compiled
modules have to be produced afterwards and before tools/package_app_runtime.py.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = ['map', 'mask', 'stl', 'morph', 'coulombic', 'mlp', 'segment',
           'dssp', 'connect_structure', 'match_align']


def main() -> int:
    report = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'bundles': {}}
    for bundle in BUNDLES:
        proc = subprocess.run([sys.executable, str(ROOT / 'tools/build_bundle_cmodule_harmony.py'),
                               '--bundle', bundle],
                              capture_output=True, text=True)
        summary = proc.stdout.strip().splitlines()[-6:] if proc.stdout else []
        report['bundles'][bundle] = {'returncode': proc.returncode,
                                     'tail': summary,
                                     'stderr': (proc.stderr or '')[-500:]}
    out = ROOT / 'reports/bundle-cmodules-all.json'
    out.write_text(json.dumps(report, indent=2) + '\n')
    built = [name for name, info in report['bundles'].items() if info['returncode'] == 0]
    print(json.dumps({'built': built, 'report': str(out)}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
