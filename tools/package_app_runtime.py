#!/usr/bin/env python3
"""Stage the private runtime into the HarmonyOS app module.

- copies libpython into entry/libs/arm64-v8a (packaged native library)
- writes the remaining runtime tree as a ZIP under resources/rawfile
  (@ohos.zlib decompresses ZIP archives, not tar.gz)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path,
                        default=ROOT / 'build/cpython-3.11.18/ohos-aarch64-with-libffi-linked/runtime')
    parser.add_argument('--app', type=Path, default=ROOT / 'app')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()
    day = datetime.now(timezone.utc).date().isoformat()
    report_path = args.report or ROOT / f'reports/app-runtime-{day}.json'
    import os
    chimerax_python = Path(os.environ.get('CX_CHIMERAX_PYTHON', ROOT / 'build/chimerax-python'))
    libs = args.app / 'entry/libs/arm64-v8a'
    raw = args.app / 'entry/src/main/resources/rawfile'
    libs.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    library = args.runtime / 'lib/libpython3.11.so.1.0'
    if not library.is_file():
        raise SystemExit(f'private libpython is missing: {library}')
    shutil.copy2(library, libs / library.name)
    link = libs / 'libpython3.11.so'
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(library.name)
    # Extension modules must live in the application native library directory:
    # the loader refuses to dlopen ELF objects extracted into the app data dir.
    # numpy ships its extension modules plus the Python package inside the native
    # library directory: the loader refuses to dlopen ELF objects extracted into
    # the application data directory, and numpy resolves submodules from its own
    # package path.
    # Only the ELF extension modules go to the native library directory; the
    # Python package itself travels in the runtime archive.
    numpy_package = chimerax_python / 'numpy'
    numpy_files = 0
    if numpy_package.is_dir():
        for module in numpy_package.rglob('*.so'):
            destination = libs / module.relative_to(numpy_package).parent / module.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(module, destination)
            numpy_files += 1
    dynload = args.runtime / 'lib/python3.11/lib-dynload'
    staged = 0
    for extension in sorted(dynload.glob('*.so')):
        shutil.copy2(extension, libs / extension.name)
        staged += 1
    archive = raw / 'cx-runtime.zip'
    count = 0
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        if chimerax_python.is_dir():
            for path in sorted(chimerax_python.rglob('*')):
                if path.is_file():
                    relative = path.relative_to(chimerax_python)
                    bundle.write(path, 'cx-generic-runtime/lib/python3.11/' + str(relative))
                    count += 1
        for path in sorted(args.runtime.rglob('*')):
            relative = path.relative_to(args.runtime)
            # libpython ships twice on purpose: as an app native library for the
            # N-API module, and inside the runtime tree so extension modules can
            # satisfy their NEEDED entry through their own $ORIGIN rpath.
            if path.is_symlink():
                continue
            bundle.write(path, 'cx-generic-runtime/' + str(relative))
            count += 1
    record = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'runtime': str(args.runtime), 'files': count,
              'archive': str(archive), 'archive_bytes': archive.stat().st_size,
              'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
              'extensions_in_libs': staged,
              'chimerax_python': str(chimerax_python),
              'numpy_files_in_libs': numpy_files,
              'libpython': str(libs / library.name),
              'libpython_sha256': hashlib.sha256((libs / library.name).read_bytes()).hexdigest()}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
