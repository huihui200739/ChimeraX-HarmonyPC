#!/usr/bin/env python3
"""Create a verified, deterministic private-runtime archive; no device access.

This is NOT a HAP, a complete application, or a runtime execution result.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from build_cpython_harmony import (ROOT, VERSION, COMMIT, sha256, write_json,
                                    validate_runtime_directory)

ARCHIVE_ROOT = 'cx-generic-runtime'


def tar_info(name: str, *, mode: int, size: int = 0, kind: bytes = tarfile.REGTYPE,
             link: str = '') -> tarfile.TarInfo:
    info = tarfile.TarInfo(f'{ARCHIVE_ROOT}/{name}')
    info.uid = info.gid = info.mtime = 0
    info.uname = info.gname = ''
    info.mode = mode
    info.size = size
    info.type = kind
    info.linkname = link
    return info


def verify_archive(path: Path, manifest: dict, manifest_hash: str) -> None:
    """Check payload bytes without executing or extracting anything."""
    files = dict(manifest['files'], **{'runtime-manifest.json': manifest_hash})
    expected = {f'{ARCHIVE_ROOT}/{name}' for name in files.keys() | manifest['links'].keys()}
    seen = set()
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            if member.isdir():
                continue
            if member.name not in expected or member.name in seen:
                raise RuntimeError('Archive contains an unexpected or repeated entry')
            seen.add(member.name)
            relative = member.name[len(ARCHIVE_ROOT) + 1:]
            if relative in manifest['links']:
                if not member.issym() or member.linkname != manifest['links'][relative]:
                    raise RuntimeError('Runtime archive link differs from its manifest')
            else:
                if not member.isfile():
                    raise RuntimeError('Runtime archive contains an unexpected entry type')
                with archive.extractfile(member) as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != files[relative]:
                        raise RuntimeError('Runtime archive file differs from its manifest')
    if seen != expected:
        raise RuntimeError('Runtime archive is incomplete')


def package_runtime(runtime: Path, output: Path) -> dict:
    runtime = runtime.absolute()
    manifest_path = runtime / 'runtime-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    validate_runtime_directory(runtime, manifest)
    if (manifest.get('source_commit') != COMMIT or manifest.get('python_version') != VERSION
            or manifest.get('application_included') is not False
            or manifest.get('qt_included') is not False):
        raise RuntimeError('Only this pinned generic runtime without application/Qt contents can be archived')
    for name in ('bin/ChimeraX', 'lib/libpython3.11.so.1.0',
                 'lib/python3.11/encodings/__init__.py', 'LICENSE-CPython.txt'):
        if name not in manifest['files']:
            raise RuntimeError(f'Required generic runtime file is not recorded: {name}')
    names = set(manifest['files']) | set(manifest['links']) | {'runtime-manifest.json'}
    directories = {'lib/python3.11/site-packages'}
    for name in names:
        parent = Path(name).parent
        while str(parent) != '.':
            directories.add(parent.as_posix())
            parent = parent.parent
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise RuntimeError('Preserving existing output symlink')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', prefix=output.name + '.', dir=output.parent,
                                         delete=False) as raw:
            temporary = Path(raw.name)
            with gzip.GzipFile(fileobj=raw, filename='', mode='wb', compresslevel=3, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                    for directory in sorted(directories):
                        archive.addfile(tar_info(directory, mode=0o755, kind=tarfile.DIRTYPE))
                    for name in sorted(names):
                        source = runtime / name
                        if name in manifest['links']:
                            archive.addfile(tar_info(name, mode=0o777, kind=tarfile.SYMTYPE,
                                                     link=manifest['links'][name]))
                        else:
                            mode = 0o755 if name.startswith('bin/') else 0o644
                            info = tar_info(name, mode=mode, size=source.stat().st_size)
                            with source.open('rb') as stream:
                                archive.addfile(info, stream)
        verify_archive(temporary, manifest, sha256(manifest_path))
        if output.exists():
            if sha256(output) != sha256(temporary):
                raise RuntimeError('Preserving different existing archive; choose a new output path')
            temporary.unlink()
        else:
            temporary.replace(output)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return {'archive': str(output), 'archive_sha256': sha256(output),
            'archive_bytes': output.stat().st_size, 'file_count': len(manifest['files']) + 1,
            'symlink_count': len(manifest['links']), 'runtime_manifest_sha256': sha256(manifest_path),
            'python_version': VERSION, 'source_commit': COMMIT, 'contents_verified': True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=ROOT / f'build/cpython-{VERSION}/ohos-aarch64/runtime')
    parser.add_argument('--output', type=Path, default=ROOT / f'build/runtime-payload/cx-generic-runtime-{VERSION}-aarch64-ohos.tar.gz')
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    parser.add_argument('--report', type=Path, default=ROOT / f'reports/runtime-archive-{day}.json')
    args = parser.parse_args(argv)
    report = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'generic_runtime_archive_not_HAP_or_application',
              'packager_source_sha256': sha256(Path(__file__)),
              'device_contacted': False, 'target_executed': False,
              'target_python_validated': False, 'target_ui_validated': False,
              'application_included': False, 'port_validated': False}
    try:
        report.update(package_runtime(args.runtime, args.output), status='generic_archive_verified_locally')
    except (OSError, RuntimeError, ValueError, KeyError, tarfile.TarError) as exc:
        report.update(status='generic_archive_incomplete', error=str(exc))
    write_json(args.report, report)
    print(f"{report['status']}: {args.report}")
    if 'error' in report:
        print(report['error'])
    return 0 if report['status'] == 'generic_archive_verified_locally' else 2


if __name__ == '__main__':
    raise SystemExit(main())
