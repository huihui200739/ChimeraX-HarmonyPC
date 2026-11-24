#!/usr/bin/env python3
"""Patch the Qt OHOS platform plugin for the ArkTS 1.2 LocalStorage API.

``libqohos.so`` builds the LocalStorage for ``windowStage.loadContent`` by evaluating
``LocalStorage.makeNewLocalStorage()`` inside the ArkTS VM (qohosjsmain.cpp:1322 and
render/qohoswindowproxydatafactory.cpp:88). That static helper no longer exists; the
ArkTS runtime rejects the expression with "global expression doesn't start with known
module path". The replacement uses the constructor form and keeps the byte length so
no offsets inside the ELF need to change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Qt evaluates "<this string>()", so the replacement must itself be a callable
# expression that returns a LocalStorage instance.
ORIGINAL = b'LocalStorage.makeNewLocalStorage'
REPLACEMENT = b'(()=>new LocalStorage())' + b' ' * (len(ORIGINAL) - len(b'(()=>new LocalStorage())'))
assert len(REPLACEMENT) == len(ORIGINAL), 'replacement must keep the byte length'


def sha256(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path,
                        default=ROOT / 'app/entry/libs/arm64-v8a/libqohos.so')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()
    day = datetime.now(timezone.utc).date().isoformat()
    report_path = args.report or ROOT / f'reports/qohos-patch-{day}.json'
    report: dict = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'library': str(args.library)}
    data = bytearray(args.library.read_bytes())
    occurrences = data.count(ORIGINAL)
    report['occurrences'] = occurrences
    if occurrences:
        data = data.replace(ORIGINAL, REPLACEMENT)
        args.library.write_bytes(bytes(data))
        report['patched'] = True
    else:
        report['patched'] = False
    report['sha256'] = sha256(args.library)
    report['bytes'] = args.library.stat().st_size
    report['status'] = 'qohos_localstorage_patched' if occurrences else 'qohos_already_patched'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'occurrences': occurrences, 'patched': report['patched'],
                      'sha256': report['sha256'][:16]}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
