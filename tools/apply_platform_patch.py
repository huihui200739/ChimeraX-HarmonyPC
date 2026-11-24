#!/usr/bin/env python3
"""Check or explicitly apply a version-locked generic build patch; no network/device use."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='Without this flag, source files are never modified')
    parser.add_argument('--report', type=Path, default=ROOT/'reports/platform-patch-2026-11-08.json')
    args=parser.parse_args(argv)
    source=args.source_root.resolve()
    lock=json.loads((ROOT/'platform-patch.lock.json').read_text())
    patch=ROOT/lock['patch']
    report={'schema_version':1, 'scope':lock['scope'], 'device_contacted':False,
            'source_root':str(source),'source_commit':lock['source_commit'],
            'apply_requested':args.apply, 'upstream_app_built':False, 'port_validated':False}
    try:
        if hashlib.sha256(patch.read_bytes()).hexdigest()!=lock['patch_sha256']:
            raise RuntimeError('Patch checksum differs from the recorded adapter patch')
        for rel, checksum in lock['original_files'].items():
            path=source/rel
            if not path.resolve().is_relative_to(source) or path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=checksum:
                raise RuntimeError(f'Original file changed or does not match the pinned version: {rel}; nothing applied')
        for rel in lock['new_files']:
            if not (source/rel).resolve().is_relative_to(source) or (source/rel).exists() or (source/rel).is_symlink():
                raise RuntimeError(f'Preserving existing file {rel}; nothing applied')
        checked=subprocess.run(['git','apply','--check',str(patch)],cwd=source,
                                capture_output=True,text=True,check=False)
        if checked.returncode:
            raise RuntimeError('Patch does not apply cleanly: '+checked.stderr.strip())
        report['status']='patch_checked_not_applied'
        if args.apply:
            applied=subprocess.run(['git','apply',str(patch)],cwd=source,capture_output=True,text=True,check=False)
            if applied.returncode:
                raise RuntimeError('Patch application failed: '+applied.stderr.strip())
            report['status']='patch_applied'
    except (OSError, RuntimeError) as exc:
        report.update(status='blocked_patch',error=str(exc))
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"{report['status']}: {args.report}")
    return 0 if report['status']!='blocked_patch' else 2


if __name__=='__main__':
    raise SystemExit(main())
