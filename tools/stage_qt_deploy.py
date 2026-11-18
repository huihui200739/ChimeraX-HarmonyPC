#!/usr/bin/env python3
"""Stage the Qt 6.12 HarmonyOS runtime into the app so libqohos can start a window.

Copies the prebuilt Qt libraries (plus libc++_shared.so, which the SDK does not put in
the sysroot) into the app native library directory and the PySide6 Python side into the
staged package tree. Run before building the HAP.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREBUILT = ROOT / 'build/qt/prebuilt/harmonyos-arm64'
SDK = Path('/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native')
QT_BIND = ROOT / 'build/qtbind'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-libs', type=Path,
                        default=ROOT / 'app/entry/libs/arm64-v8a')
    parser.add_argument('--packages', type=Path, default=ROOT / 'build/chimerax-python')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()
    day = datetime.now(timezone.utc).date().isoformat()
    report_path = args.report or ROOT / f'reports/qt-deploy-{day}.json'
    report: dict = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                    'copied': [], 'missing': []}
    args.app_libs.mkdir(parents=True, exist_ok=True)

    def copy(src: Path, dst: Path, label: str) -> None:
        if not src.is_file():
            report['missing'].append(label)
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        report['copied'].append({'label': label, 'bytes': dst.stat().st_size,
                                 'path': str(dst.relative_to(ROOT))})

    # Qt platform plugin and libraries: libqohos must sit flat in the app library dir.
    copy(PREBUILT / 'plugins/platforms/libqohos.so', args.app_libs / 'libqohos.so', 'libqohos.so')
    for library in sorted((PREBUILT / 'lib').glob('libQt6*.so*')):
        copy(library, args.app_libs / library.name, library.name)
    copy(SDK / 'llvm/lib/aarch64-linux-ohos/libc++_shared.so',
         args.app_libs / 'libc++_shared.so', 'libc++_shared.so')

    # PySide6 build output: shiboken + module bindings.
    for candidate in sorted((QT_BIND / 'out').rglob('*.so')) if (QT_BIND / 'out').is_dir() else []:
        copy(candidate, args.app_libs / candidate.name, candidate.name)

    # The plugin evaluates LocalStorage.makeNewLocalStorage(), which the ArkTS runtime
    # rejects; the equal-length constructor form is patched in place.
    qohos = args.app_libs / 'libqohos.so'
    if qohos.is_file():
        original = b'LocalStorage.makeNewLocalStorage'
        replacement = (b'(()=>new LocalStorage())'
                       + b' ' * (len(original) - len(b'(()=>new LocalStorage())')))
        data = qohos.read_bytes()
        if original in data:
            qohos.write_bytes(data.replace(original, replacement))
            report['localstorage_patched'] = True

    report['app_libs_count'] = len(list(args.app_libs.glob('*.so*')))
    report['status'] = 'qt_runtime_staged'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'copied': len(report['copied']), 'missing': report['missing'],
                      'app_libs': report['app_libs_count']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
