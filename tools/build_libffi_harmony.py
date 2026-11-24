#!/usr/bin/env python3
"""Locally cross-compile a pinned private libffi dependency, with no device access.

Builds a PIC static archive and a link-only shared-object check; neither the
check nor the target archive is executed. No application code is used.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from build_cpython_harmony import (Builder, DEFAULT_SDK, ROOT, TRIPLE, checked_path,
    clean_environment, sha256, verify_files, write_json, needed_libraries)

VERSION = '3.8.0'
OWNER = 'cx-generic-libffi-builder-v1'
PREFIX_FILES = {'include/ffi.h', 'include/ffitarget.h', 'lib/libffi.a', 'LICENSE-libffi.txt'}


def validate_prefix(prefix: Path, *, sdk: Path | None = None) -> dict:
    if prefix.is_symlink():
        raise RuntimeError('Preserving dependency prefix symlink')
    manifest_path = prefix / 'dependency-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get('owner') != OWNER or manifest.get('version') != VERSION
            or manifest.get('target_triplet') != TRIPLE
            or manifest.get('library_kind') != 'static_PIC'
            or set(manifest.get('files', {})) != PREFIX_FILES):
        raise RuntimeError('Dependency manifest is not the expected private libffi build')
    verify_files(prefix, manifest['files'])
    actual = {str(p.relative_to(prefix)) for p in prefix.rglob('*') if p.is_file() or p.is_symlink()}
    if actual != PREFIX_FILES | {'dependency-manifest.json'}:
        raise RuntimeError('Preserving unrecorded or missing dependency files')
    if sdk is not None and manifest.get('compiler_sha256') != sha256(sdk / 'llvm/bin/clang'):
        raise RuntimeError('Dependency compiler does not match the selected SDK')
    return manifest


class DependencyBuilder:
    run = Builder.run

    def __init__(self, sdk: Path, jobs: int, report: dict):
        self.sdk = sdk.resolve()
        self.jobs = jobs
        self.report = report
        self.env = clean_environment(dict(os.environ))
        self.work = checked_path(ROOT, f'build/libffi-{VERSION}/ohos-aarch64')
        self.source = checked_path(self.work, 'source')
        self.objects = checked_path(self.work, 'objects')
        self.prefix = checked_path(self.work, 'prefix')
        self.compiler = self.sdk / 'llvm/bin/clang'
        self.readelf = self.sdk / 'llvm/bin/llvm-readelf'

    def prepare_source(self) -> dict:
        lock = json.loads((ROOT / 'libffi-sources.lock.json').read_text())
        if lock['version'] != VERSION or lock['target_architecture'] != TRIPLE:
            raise RuntimeError('Unexpected dependency version/target in source lock')
        patch_lock = json.loads((ROOT / 'libffi-patch.lock.json').read_text())
        patch = checked_path(ROOT, patch_lock['patch'])
        if sha256(patch) != patch_lock['patch_sha256']:
            raise RuntimeError('Dependency platform patch differs from its source lock')
        archive = checked_path(ROOT, lock['archive'])
        if sha256(archive) != lock['download_sha256']:
            raise RuntimeError('Dependency archive differs from its verified source lock')
        manifest_path = self.work / 'source-manifest.json'
        if self.source.exists():
            manifest = json.loads(manifest_path.read_text())
            if (manifest.get('owner') != OWNER or manifest.get('archive_sha256') != lock['download_sha256']
                    or manifest.get('patch_sha256') != patch_lock['patch_sha256']):
                raise RuntimeError('Preserving dependency source with different provenance')
            verify_files(self.source, manifest['files'])
            actual = {str(p.relative_to(self.source)) for p in self.source.rglob('*')
                      if p.is_file() or p.is_symlink()}
            if actual != set(manifest['files']):
                raise RuntimeError('Preserving changed dependency source tree')
        else:
            with tempfile.TemporaryDirectory(prefix='extract-', dir=self.work) as temporary:
                extraction = Path(temporary)
                with tarfile.open(archive) as bundle:
                    names = set()
                    for member in bundle:
                        parts = Path(member.name).parts
                        if (not parts or parts[0] != f'libffi-{VERSION}' or '..' in parts
                                or member.name in names or not (member.isfile() or member.isdir())):
                            raise RuntimeError('Unexpected dependency source archive entry')
                        names.add(member.name)
                    bundle.extractall(extraction, filter='data')
                source = extraction / f'libffi-{VERSION}'
                if f"PACKAGE_VERSION='{VERSION}'" not in (source / 'configure').read_text():
                    raise RuntimeError('Dependency configure version differs from release metadata')
                verify_files(source, patch_lock['original_files'])
                self.run('apply-platform-patch', ['/usr/bin/patch', '--batch', '-p1', '-i', str(patch)], cwd=source)
                verify_files(source, patch_lock['patched_files'])
                source.rename(self.source)
            write_json(manifest_path, {'owner': OWNER, 'archive_sha256': lock['download_sha256'],
                'patch_sha256': patch_lock['patch_sha256'],
                'files': {str(p.relative_to(self.source)): sha256(p)
                          for p in sorted(self.source.rglob('*')) if p.is_file()}})
        self.report['source_archive_sha256'] = lock['download_sha256']
        self.report['patch_sha256'] = patch_lock['patch_sha256']
        return lock

    def build(self, lock: dict) -> None:
        for path in (self.compiler, self.readelf, self.sdk / 'llvm/bin/llvm-ar', self.sdk / 'llvm/bin/llvm-ranlib'):
            if not path.is_file():
                raise RuntimeError(f'Missing local build tool: {path}')
        for path in (self.work, self.sdk):
            if any(c.isspace() for c in str(path)):
                raise RuntimeError('Autotools cross-build paths must not contain whitespace')
        build_triple = self.run('host-triple', ['/bin/sh', str(self.source / 'config.guess')]).strip()
        common = f'--target={TRIPLE} --sysroot={shlex.quote(str(self.sdk / "sysroot"))}'
        self.env.update(CC=f'{shlex.quote(str(self.compiler))} {common}',
            CXX=f'{shlex.quote(str(self.sdk / "llvm/bin/clang++"))} {common}',
            AR=str(self.sdk / 'llvm/bin/llvm-ar'), RANLIB=str(self.sdk / 'llvm/bin/llvm-ranlib'),
            CFLAGS='-O2 -fPIC -fstack-protector-strong', LDFLAGS='-Wl,-z,relro,-z,now')
        options = ['/bin/sh', str(self.source / 'configure'), f'--build={build_triple}',
            '--host=aarch64-unknown-linux-ohos', f'--prefix={self.prefix}', '--with-pic',
            '--disable-shared', '--enable-static', '--disable-docs']
        fingerprint = {'owner': OWNER, 'source_archive_sha256': lock['download_sha256'],
            'patch_sha256': self.report['patch_sha256'], 'configure': options, 'compiler_sha256': sha256(self.compiler),
            'environment': {k: self.env[k] for k in ('CC', 'CXX', 'AR', 'RANLIB', 'CFLAGS', 'LDFLAGS')}}
        self.objects.mkdir(exist_ok=True)
        configuration = self.work / 'configuration.json'
        if configuration.exists() and json.loads(configuration.read_text()) != fingerprint:
            raise RuntimeError('Preserving dependency objects with a different build configuration')
        write_json(configuration, fingerprint)
        configured = self.run('configure', options, cwd=self.objects, timeout=300)
        if 'checking whether we are cross compiling... yes' not in configured:
            raise RuntimeError('Dependency cross-build configuration was not verified')
        self.run('make', ['/usr/bin/make', f'-j{self.jobs}', 'all'], cwd=self.objects, timeout=600)
        archive = self.objects / '.libs/libffi.a'
        elf = self.run('archive-elf', [str(self.readelf), '--file-header', str(archive)])
        machines = re.findall(r'Machine:\s+(\S+)', elf)
        if not machines or any(machine != 'AArch64' for machine in machines):
            raise RuntimeError('Not all dependency archive members are AArch64 ELF objects')
        self.report['archive_object_count'] = len(machines)
        self.report['archive_sha256'] = sha256(archive)
        # Link only: resolve required standard FFI symbols without running code.
        probe = self.work / 'ffi-link-only.c'
        probe.write_text('#include <ffi.h>\n'
            'int cx_generic_ffi_link_only(void) {\n'
            '  ffi_cif cif; ffi_type *args[] = {&ffi_type_sint32};\n'
            '  void *code = 0; ffi_closure *cl = ffi_closure_alloc(sizeof(ffi_closure), &code);\n'
            '  if (cl) ffi_closure_free(cl);\n'
            '  return ffi_prep_cif(&cif, FFI_DEFAULT_ABI, 1, &ffi_type_sint32, args);\n}\n')
        shared = self.work / 'ffi-link-only.so'
        self.run('link-only', [str(self.compiler), f'--target={TRIPLE}', f'--sysroot={self.sdk / "sysroot"}',
            '-shared', '-fPIC', '-fstack-protector-strong', '-Wl,--no-undefined', '-Wl,-z,relro,-z,now',
            f'-I{self.objects / "include"}', f'-I{self.source / "include"}', str(probe), str(archive),
            '-ldl', '-o', str(shared)])
        dynamic = self.run('link-only-elf', [str(self.readelf), '--file-header', '--dynamic', str(shared)])
        self.report['link_only_check'] = {'passed': True, 'executed': False,
            'sha256': sha256(shared), 'needed_libraries': needed_libraries(dynamic)}
        if self.prefix.exists():
            manifest = validate_prefix(self.prefix, sdk=self.sdk)
            if (manifest.get('source_archive_sha256') != lock['download_sha256']
                    or manifest.get('configuration_sha256') != sha256(configuration)):
                raise RuntimeError('Preserving private dependency prefix with a different provenance')
            self.report['existing_prefix_reused'] = True
        else:
            with tempfile.TemporaryDirectory(prefix='stage-', dir=self.work) as temporary:
                staging = Path(temporary) / 'prefix'
                (staging / 'include').mkdir(parents=True)
                (staging / 'lib').mkdir()
                shutil.copy2(self.objects / 'include/ffi.h', staging / 'include/ffi.h')
                shutil.copy2(self.objects / 'include/ffitarget.h', staging / 'include/ffitarget.h')
                shutil.copy2(archive, staging / 'lib/libffi.a')
                shutil.copy2(self.source / 'LICENSE', staging / 'LICENSE-libffi.txt')
                manifest = {'owner': OWNER, 'version': VERSION, 'target_triplet': TRIPLE,
                    'library_kind': 'static_PIC', 'source_archive_sha256': lock['download_sha256'],
                    'compiler_sha256': sha256(self.compiler), 'configuration_sha256': sha256(configuration),
                    'files': {name: sha256(staging / name) for name in sorted(PREFIX_FILES)},
                    'target_executed': False, 'callbacks_validated_on_target': False}
                write_json(staging / 'dependency-manifest.json', manifest)
                validate_prefix(staging, sdk=self.sdk)
                staging.rename(self.prefix)
            self.report['existing_prefix_reused'] = False
        self.report.update(status='local_libffi_static_cross_compile_passed_not_target_tested',
            prefix=str(self.prefix), staged_archive_sha256=sha256(self.prefix / 'lib/libffi.a'),
            dependency_manifest_sha256=sha256(self.prefix / 'dependency-manifest.json'))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, default=DEFAULT_SDK)
    parser.add_argument('--jobs', type=int, choices=(1, 2), default=2)
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    parser.add_argument('--report', type=Path, default=ROOT / f'reports/libffi-local-{day}.json')
    args = parser.parse_args(argv)
    report = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'generic_libffi_dependency_cross_compile_only', 'version': VERSION,
        'builder_source_sha256': sha256(Path(__file__)), 'device_contacted': False,
        'target_executed': False, 'application_included': False, 'commands': []}
    builder = DependencyBuilder(args.sdk, args.jobs, report)
    builder.work.mkdir(parents=True, exist_ok=True)
    try:
        with (builder.work / 'build.lock').open('w') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('Dependency build is already active') from exc
            builder.build(builder.prepare_source())
    except (OSError, RuntimeError, ValueError, KeyError, tarfile.TarError) as exc:
        report.update(status='local_dependency_build_incomplete', error=str(exc))
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    write_json(args.report, report)
    print(f"{report['status']}: {args.report}", flush=True)
    if 'error' in report:
        print(report['error'], flush=True)
    return 0 if report['status'].endswith('_not_target_tested') else 2


if __name__ == '__main__':
    raise SystemExit(main())
