#!/usr/bin/env python3
"""Recompute a private runtime manifest after an intentional adapter change.

The runtime manifest owns the staged file hashes and the adapter provenance.
When the startup adapter source changes, the staged runtime is copied to a new
directory and re-stamped here: every file hash is recomputed, the adapter source
hash is refreshed, and the directory is validated before it can be packaged.
Nothing is copied from a host Python installation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    manifest_path = runtime / 'runtime-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    files = {str(p.relative_to(runtime)): sha256(p)
             for p in sorted(runtime.rglob('*')) if p.is_file() and not p.is_symlink()
             and p.name != 'runtime-manifest.json'}
    links = {str(p.relative_to(runtime)): p.readlink().name
             for p in sorted(runtime.rglob('*')) if p.is_symlink()}
    manifest['files'] = files
    manifest['links'] = links
    manifest['adapter_source_sha256'] = sha256(ROOT / 'harmony/bootstrap.c')
    manifest['adapter_header_sha256'] = sha256(ROOT / 'harmony/bootstrap.h')
    manifest['target_executed'] = False
    manifest['runtime_validated_on_target'] = False
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'runtime': str(runtime), 'files': len(files), 'links': len(links),
                      'manifest_sha256': sha256(manifest_path)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
