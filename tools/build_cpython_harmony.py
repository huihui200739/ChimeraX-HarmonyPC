#!/usr/bin/env python3
"""Build a private generic CPython runtime locally; never contact a device.

Only the pinned CPython archive and this project's startup adapter are built.
Target binaries are inspected, never executed on the development host. This is
not an application package and does not import or build application modules.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SDK = Path('/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native')
VERSION = '3.11.18'
COMMIT = '26badd80b6dc7786cd8fb63c3608a31f04754219'
TRIPLE = 'aarch64-linux-ohos'
OWNER = 'cx-generic-cpython-runtime-builder-v1'


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temporary file avoids clobbering an unrelated .tmp file.
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                     prefix=path.name + '.', delete=False) as output:
        temporary = Path(output.name)
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write('\n')
    temporary.replace(path)


def clean_environment(environ: dict[str, str]) -> dict[str, str]:
    """Do not accidentally use host headers, libraries or Python packages."""
    excluded = {'CC', 'CXX', 'CPP', 'AR', 'RANLIB', 'READELF', 'LD', 'LDSHARED',
                'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'CPATH',
                'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'LIBRARY_PATH',
                'SDKROOT', 'MACOSX_DEPLOYMENT_TARGET', 'ARCHFLAGS',
                'VIRTUAL_ENV', 'MAKEFLAGS', 'MFLAGS', 'CONFIG_SITE',
                'CONFIG_SHELL', 'LD_PRELOAD', '_PYTHON_HOST_PLATFORM',
                '_PYTHON_SYSCONFIGDATA_NAME', '_PYTHON_PROJECT_BASE'}
    env = {key: value for key, value in environ.items()
           if key not in excluded and not key.startswith(
               ('PYTHON', 'CONDA', 'PKG_CONFIG', 'DYLD_', 'LD_LIBRARY_PATH'))}
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', LC_ALL='C', CONFIG_SITE='/dev/null',
               PKG_CONFIG='/usr/bin/false')
    return env


def checked_path(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise RuntimeError(f'Path is outside the owned directory: {relative}')
    if path.is_symlink():
        raise RuntimeError(f'Symlinks are not accepted here: {path}')
    return path


def verify_files(root: Path, expected: dict[str, str]) -> None:
    for relative, checksum in expected.items():
        path = checked_path(root, relative)
        if not path.is_file() or sha256(path) != checksum:
            raise RuntimeError(f'Preserving changed/missing source file: {path}')


def needed_libraries(text: str) -> list[str]:
    return re.findall(r'\(NEEDED\).*?\[([^\]]+)\]', text)


def parse_build_summary(text: str) -> dict[str, list[str]]:
    """CPython setup.py can exit zero despite optional extension failures."""
    sections = {
        'not_found': 'The necessary bits to build these optional modules were not found:',
        'failed': 'Failed to build these modules:',
        'disabled': 'been built, they are *disabled* by configure:',
    }
    result = {}
    for name, heading in sections.items():
        match = re.search(re.escape(heading) + r'\n(.*?)(?:\n\s*\n|\Z)', text, re.S)
        modules = set()
        if match:
            for line in match.group(1).splitlines():
                tokens = line.split()
                if not tokens or not all(re.fullmatch(r'[a-z_][a-z0-9_]*', token) for token in tokens):
                    break
                modules.update(tokens)
        result[name] = sorted(modules)
    return result


def validate_runtime_directory(runtime: Path, manifest: dict) -> None:
    if runtime.is_symlink() or manifest.get('owner') != OWNER:
        raise RuntimeError('Preserving runtime without the expected ownership marker')
    verify_files(runtime, manifest['files'])
    for relative, target in manifest['links'].items():
        path = runtime / relative
        if (Path(relative).is_absolute() or not path.parent.resolve().is_relative_to(runtime.resolve())
                or not path.is_symlink() or os.readlink(path) != target
                or not path.resolve().is_relative_to(runtime.resolve()) or not path.is_file()):
            raise RuntimeError(f'Preserving unexpected runtime link: {path}')
    expected = set(manifest['files']) | set(manifest['links']) | {'runtime-manifest.json'}
    actual = {str(p.relative_to(runtime)) for p in runtime.rglob('*') if p.is_file() or p.is_symlink()}
    if actual != expected:
        raise RuntimeError('Preserving unrecorded or missing files in the staged runtime')


PROFILES = ('baseline', 'with-libffi', 'with-libffi-linked')


def profile_directory(profile: str) -> str:
    if profile not in PROFILES:
        raise ValueError('Unknown private runtime profile')
    suffix = {'baseline': '', 'with-libffi': '-with-libffi',
              'with-libffi-linked': '-with-libffi-linked'}[profile]
    return f'build/cpython-{VERSION}/ohos-aarch64{suffix}'


def defined_dynamic_symbols(text: str) -> set[str]:
    """Read exported definitions, not merely references to unresolved symbols."""
    result = set()
    for line in text.splitlines():
        fields = line.split()
        if (len(fields) >= 8 and fields[0].endswith(':') and fields[6] != 'UND'
                and fields[4] in ('GLOBAL', 'WEAK') and fields[5] in ('DEFAULT', 'PROTECTED')):
            result.add(fields[7].split('@')[0])
    return result


class Builder:
    def __init__(self, sdk: Path, host_python: Path, jobs: int, report: dict,
                 *, profile: str = 'baseline', libffi_prefix: Path | None = None):
        self.sdk = sdk.resolve()
        self.host_python = host_python.resolve()
        self.jobs = jobs
        self.report = report
        self.profile = profile
        self.work = checked_path(ROOT, profile_directory(profile))
        if profile == 'baseline' and libffi_prefix is not None:
            raise ValueError('A private dependency prefix requires the with-libffi profile')
        self.libffi_prefix = (libffi_prefix or ROOT / 'build/libffi-3.8.0/ohos-aarch64/prefix').absolute()
        self.libffi_manifest = None
        self.report['runtime_profile'] = profile
        self.source = checked_path(self.work, 'source')
        self.objects = checked_path(self.work, 'objects')
        self.runtime = checked_path(self.work, 'runtime')
        self.env = clean_environment(dict(os.environ))
        self.compiler = self.sdk / 'llvm/bin/clang'
        self.readelf = self.sdk / 'llvm/bin/llvm-readelf'

    def run(self, name: str, argv: list[str], *, cwd: Path | None = None,
            timeout: int = 120, allow_failure: bool = False) -> str:
        log = self.work / 'logs' / (name + '.txt')
        log.parent.mkdir(parents=True, exist_ok=True)
        command = {'name': name, 'argv': argv, 'cwd': str(cwd or self.work), 'log': str(log),
                   'failure_allowed_for_feature_detection': allow_failure}
        self.report['commands'].append(command)
        print(f'{name}: {log}', flush=True)
        try:
            with log.open('w', encoding='utf-8') as stream:
                result = subprocess.run(argv, cwd=cwd or self.work, env=self.env,
                                        stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=timeout, check=False)
            command['returncode'] = result.returncode
        except subprocess.TimeoutExpired as exc:
            command['timed_out'] = True
            raise RuntimeError(f'{name} timed out; see {log}') from exc
        if result.returncode and not allow_failure:
            tail = log.read_text(encoding='utf-8', errors='replace').splitlines()[-35:]
            raise RuntimeError(f'{name} failed ({result.returncode}):\n' + '\n'.join(tail))
        return log.read_text(encoding='utf-8', errors='replace')

    def prepare_source(self) -> tuple[dict, dict]:
        lock = json.loads((ROOT / 'runtime-sources.lock.json').read_text())
        patch_lock = json.loads((ROOT / 'runtime-patch.lock.json').read_text())
        if (lock['python_version'] != VERSION or lock['git_commit'] != COMMIT
                or patch_lock['source_commit'] != COMMIT):
            raise RuntimeError('Source and platform patch must match the pinned CPython commit')
        archive = ROOT / f'build/downloads/cpython-{COMMIT}.tar.gz'
        if not archive.is_file() or sha256(archive) != lock['download_sha256']:
            raise RuntimeError('The locally cached source archive is missing or changed; no network fallback')
        patch = checked_path(ROOT, patch_lock['patch'])
        if sha256(patch) != patch_lock['patch_sha256']:
            raise RuntimeError('The CPython platform patch differs from its recorded checksum')
        manifest_path = self.work / 'source-manifest.json'
        if self.source.exists():
            if not manifest_path.is_file():
                raise RuntimeError('Preserving source directory without an ownership manifest')
            manifest = json.loads(manifest_path.read_text())
            if manifest.get('owner') != OWNER or manifest.get('patch_sha256') != patch_lock['patch_sha256']:
                raise RuntimeError('Preserving existing source with a different provenance')
            verify_files(self.source, manifest['files'])
            actual = {str(p.relative_to(self.source)) for p in self.source.rglob('*') if p.is_file()}
            if actual != set(manifest['files']):
                raise RuntimeError('Preserving additional or removed files in prepared source')
        else:
            # Build and patch a fresh owned copy. Never alter the previously acquired source.
            with tempfile.TemporaryDirectory(prefix='extract-', dir=self.work) as temporary:
                extraction = Path(temporary)
                with tarfile.open(archive) as bundle:
                    for member in bundle.getmembers():
                        if (member.name.split('/')[0] != f'cpython-{COMMIT}'
                                or member.issym() or member.islnk()):
                            raise RuntimeError('Unexpected source archive root or link')
                    bundle.extractall(extraction, filter='data')
                source = extraction / f'cpython-{COMMIT}'
                verify_files(source, patch_lock['original_files'])
                self.run('apply-platform-patch', ['/usr/bin/patch', '--batch', '-p1', '-i', str(patch)], cwd=source)
                verify_files(source, patch_lock['patched_files'])
                source.rename(self.source)
            write_json(manifest_path, {'owner': OWNER, 'source_commit': COMMIT,
                       'archive_sha256': lock['download_sha256'],
                       'patch_sha256': patch_lock['patch_sha256'],
                       'files': {str(p.relative_to(self.source)): sha256(p)
                                 for p in sorted(self.source.rglob('*')) if p.is_file()}})
        self.report.update(source_commit=COMMIT, source_archive_sha256=lock['download_sha256'],
                           patch_sha256=patch_lock['patch_sha256'])
        return lock, patch_lock

    def configure_and_build(self, lock: dict, patch_lock: dict) -> None:
        for path in (self.compiler, self.readelf, self.sdk / 'llvm/bin/llvm-ar',
                     self.sdk / 'llvm/bin/llvm-ranlib', self.host_python):
            if not path.is_file():
                raise RuntimeError(f'Required local build tool is missing: {path}')
        # CPython's configure invokes --with-build-python without quoting it.
        for path in (self.work, self.host_python, self.sdk):
            if any(character.isspace() for character in str(path)):
                raise RuntimeError('CPython 3.11 cross-build paths must not contain whitespace')
        host_info = json.loads(self.run('host-python', [str(self.host_python), '-I', '-c',
            "import json,sys; print(json.dumps(dict(version=list(sys.version_info[:3]),platform=sys.platform)))"]))
        if host_info['version'][:2] != [3, 11] or host_info['platform'] != 'darwin':
            raise RuntimeError('This local builder requires a real macOS CPython 3.11 build interpreter')
        self.report['build_python'] = host_info
        build_triple = self.run('host-triple', ['/bin/sh', str(self.source / 'config.guess')]).strip()
        common = f'--target={TRIPLE} --sysroot={shlex.quote(str(self.sdk / "sysroot"))}'
        self.env.update(CC=f'{shlex.quote(str(self.compiler))} {common}',
                        CXX=f'{shlex.quote(str(self.sdk / "llvm/bin/clang++"))} {common}',
                        AR=str(self.sdk / 'llvm/bin/llvm-ar'),
                        RANLIB=str(self.sdk / 'llvm/bin/llvm-ranlib'),
                        READELF=str(self.readelf),
                        CFLAGS='-O2 -fPIC -fstack-protector-strong',
                        LDFLAGS='-Wl,-z,relro,-z,now',
                        ac_cv_file__dev_ptmx='no', ac_cv_file__dev_ptc='no',
                        CX_CPYTHON_BUILD_JOBS=str(self.jobs))
        if self.profile in ('with-libffi', 'with-libffi-linked'):
            from build_libffi_harmony import validate_prefix
            if any(c.isspace() for c in str(self.libffi_prefix)):
                raise RuntimeError('Dependency cross-build paths must not contain whitespace')
            self.libffi_manifest = validate_prefix(self.libffi_prefix, sdk=self.sdk)
            self.env['CPPFLAGS'] = f'-I{self.libffi_prefix / "include"}'
            self.env['LDFLAGS'] += f' -L{self.libffi_prefix / "lib"}'
            self.report['private_libffi'] = {
                'version': self.libffi_manifest['version'], 'prefix': str(self.libffi_prefix),
                'manifest_sha256': sha256(self.libffi_prefix / 'dependency-manifest.json'),
                'library_kind': 'static_PIC', 'target_executed': False}
        # Some SDKs ship an empty libintl.h. Header existence alone must not
        # enable APIs which are neither declared nor usable. Compile only;
        # never execute a feature probe or suppress undeclared-function errors.
        probe = self.work / 'libintl-compile-probe.c'
        probe.write_text('#include <libintl.h>\n'
                         'const char *cx_check_gettext(void) {\n'
                         '  (void)gettext("x"); (void)dgettext("x", "x");\n'
                         '  (void)dcgettext("x", "x", 0);\n'
                         '  (void)textdomain("x"); return bindtextdomain("x", "x");\n'
                         '}\n')
        self.run('libintl-header-check', [str(self.compiler), f'--target={TRIPLE}',
                 f'--sysroot={self.sdk / "sysroot"}', '-std=c11',
                 '-Werror=implicit-function-declaration', '-Werror=int-conversion',
                 '-c', str(probe), '-o', str(self.work / 'libintl-compile-probe.o')],
                 allow_failure=True)
        if self.report['commands'][-1]['returncode'] != 0:
            self.env['ac_cv_header_libintl_h'] = 'no'
            self.report['native_gettext'] = 'disabled_after_SDK_declaration_compile_check_failed'
        else:
            self.report['native_gettext'] = 'SDK_declarations_compile_checked_not_target_tested'
        if self.profile == 'with-libffi-linked':
            # HarmonyOS resolves extension symbols only through their own dependency
            # chain, so the extensions are re-linked against the private libpython
            # after the shared library exists (see relink_extensions()).
            self.report['extension_linkage'] = {
                'strategy': 'second pass re-links extension modules against the private libpython',
                'reason': 'target loader does not resolve CPython symbols for extensions loaded '
                          'after a dlopen(RTLD_GLOBAL) of the shared library',
                'target_executed': False}
        options = [str(self.source / 'configure'), f'--build={build_triple}',
                   '--host=aarch64-unknown-linux-ohos', f'--with-build-python={self.host_python}',
                   '--prefix=/data/storage/el2/base/files/cx-generic-runtime',
                   '--enable-shared', '--without-static-libpython', '--without-ensurepip',
                   '--disable-test-modules', '--with-pkg-config=no', '--enable-ipv6']
        fingerprint = {'owner': OWNER, 'source': lock['download_sha256'],
                       'patch': patch_lock['patch_sha256'], 'configure': options,
                       'compiler_sha256': sha256(self.compiler),
                       'environment': {k: self.env[k] for k in ('CC', 'CXX', 'AR', 'RANLIB',
                           'READELF', 'CFLAGS', 'LDFLAGS', 'ac_cv_file__dev_ptmx', 'ac_cv_file__dev_ptc', 'CX_CPYTHON_BUILD_JOBS')},
                       'ldshared': self.env.get('LDSHARED', ''),
                       'libintl_header_override': self.env.get('ac_cv_header_libintl_h')}
        if self.libffi_manifest is not None:
            fingerprint['private_libffi'] = self.report['private_libffi']
            fingerprint['environment']['CPPFLAGS'] = self.env['CPPFLAGS']
        self.objects.mkdir(exist_ok=True)
        saved = self.work / 'configuration.json'
        if saved.exists() and json.loads(saved.read_text()) != fingerprint:
            raise RuntimeError('Preserving previous objects from a different build configuration')
        write_json(saved, fingerprint)
        configured = self.run('configure', ['/bin/sh', *options], cwd=self.objects, timeout=300)
        makefile = (self.objects / 'Makefile').read_text()
        if ('checking whether we are cross compiling... yes' not in configured
                or not re.search(r'^_PYTHON_HOST_PLATFORM\s*=\s*linux-aarch64$', makefile, re.M)
                or f'PYTHON_FOR_FREEZE={self.host_python}' not in makefile
                or '_PYTHON_HOST_PLATFORM=$(_PYTHON_HOST_PLATFORM)' not in makefile):
            raise RuntimeError('Cross-build and host-only build-interpreter selection were not verified')
        if 'aarch64-linux-ohos' not in makefile:
            raise RuntimeError('Target-specific OHOS ABI identification is missing')
        self.report['cross_configuration'] = {
            'cross_compiling': True, 'target_triplet': TRIPLE,
            'pseudoterminals': 'conservatively_disabled_not_device_verified',
            'ipv6': 'enabled_using_upstream_cross_configuration_not_device_verified',
            'make_jobs': self.jobs, 'target_executed': False}
        built = self.run('make', ['/usr/bin/make', f'-j{self.jobs}', 'all'], cwd=self.objects, timeout=1800)
        self.report['extension_build_summary'] = parse_build_summary(built)
        if self.profile == 'with-libffi-linked':
            if self.report['commands'][-1]['returncode'] != 0:
                raise RuntimeError('make failed before the extension re-link pass')
            self.relink_extensions()

    def inspect_elf(self, path: Path, label: str) -> dict:
        text = self.run('elf-' + label, [str(self.readelf), '--file-header', '--dynamic',
                                       '--dyn-syms', str(path)])
        if not re.search(r'Machine:\s+AArch64', text):
            raise RuntimeError(f'Not a verified AArch64 ELF: {path}')
        if 'libpython' in path.name:
            for symbol in ('Py_Main', 'Py_GetVersion', 'Py_SetPythonHome', 'Py_SetProgramName'):
                if not re.search(r'\b' + symbol + r'\b', text):
                    raise RuntimeError(f'Runtime export is missing: {symbol}')
        return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha256(path),
                'needed_libraries': needed_libraries(text)}

    def relink_extensions(self) -> None:
        """Re-link extension modules against the private libpython.

        The shared library uses the same linker variable as extension modules, so
        the extra flag cannot be set during the first pass. Once libpython exists,
        the extension outputs are removed and re-linked with a relocatable rpath.
        """
        if self.profile != 'with-libffi-linked':
            return
        makefile = self.objects / 'Makefile'
        text = makefile.read_text()
        marker = '\nBLDSHARED='
        start = text.index(marker) + 1
        end = text.index('\n', start)
        line = text[start:end]
        if 'libpython3.11.so.1.0' not in line and '-lpython3.11' not in line:
            # $$ORIGIN survives make's own expansion so the linker records $ORIGIN.
            patched = line + f' -L{self.objects} -l:libpython3.11.so.1.0 -Wl,-rpath,$$ORIGIN/../../lib'
            makefile.write_text(text[:start] + patched + text[end:])
        extension_dir = self.objects / 'build'
        removed = []
        for candidate in sorted(extension_dir.glob('lib.*/**.so')):
            candidate.unlink()
            removed.append(candidate.name)
        self.report['extension_relink_removed'] = sorted(removed)
        self.run('make-relink-extensions', ['/usr/bin/make', f'-j{self.jobs}', 'all'], cwd=self.objects, timeout=1800)
        if self.report['commands'][-1]['returncode'] != 0:
            raise RuntimeError('Re-linking extension modules failed')

    def stage_runtime(self) -> None:
        library = self.objects / 'libpython3.11.so.1.0'
        self.report['object_python_library'] = self.inspect_elf(library, 'libpython')
        build_relative = (self.objects / 'pybuilddir.txt').read_text().strip()
        extensions = checked_path(self.objects, build_relative)
        if not extensions.is_dir():
            raise RuntimeError('Compiled extension output directory is missing')
        sysconfig = list(extensions.glob('_sysconfigdata_*.py'))
        if len(sysconfig) != 1 or TRIPLE not in sysconfig[0].name:
            raise RuntimeError('Exactly one OHOS sysconfig data file is required')
        # Do not package CPython's example/test extension modules as application dependencies.
        compiled = [p for p in sorted(extensions.glob('*.so'))
                    if not p.name.startswith(('xxlimited.', 'xxlimited_35.', '_test', '_xxtest'))]
        extension_names = [p.name.split('.')[0] for p in compiled]
        required = {'_socket', '_struct', '_json', 'unicodedata', 'select', 'math', 'zlib'}
        if self.profile in ('with-libffi', 'with-libffi-linked'):
            required.add('_ctypes')
        if missing := required - set(extension_names):
            raise RuntimeError(f'Required generic runtime extensions did not build: {sorted(missing)}')
        extension_records = [self.inspect_elf(p, 'module-' + p.name) for p in compiled]
        summary = self.report['extension_build_summary']
        self.report['known_missing_optional_extensions'] = sorted(
            (set(summary['not_found']) | set(summary['failed']) |
             {'_ssl', '_hashlib', '_ctypes', '_sqlite3', '_bz2', '_lzma', '_tkinter'}) - set(extension_names))
        provenance = {'source_commit': COMMIT, 'patch_sha256': self.report['patch_sha256'],
                      'adapter_source_sha256': sha256(ROOT / 'harmony/bootstrap.c'),
                      'adapter_header_sha256': sha256(ROOT / 'harmony/bootstrap.h'),
                      'configuration_sha256': sha256(self.work / 'configuration.json')}
        if self.libffi_manifest is not None:
            provenance.update(runtime_profile=self.profile,
                libffi_dependency_manifest_sha256=self.report['private_libffi']['manifest_sha256'])
        reused = False
        if self.runtime.exists():
            manifest_path = self.runtime / 'runtime-manifest.json'
            if not manifest_path.is_file():
                raise RuntimeError('Preserving runtime directory without an ownership manifest')
            manifest = json.loads(manifest_path.read_text())
            validate_runtime_directory(self.runtime, manifest)
            if (any(manifest.get(key) != value for key, value in provenance.items())
                    or manifest['extension_modules'] != extension_names):
                raise RuntimeError('Preserving a runtime built with different inputs; use a separate staging directory')
            # CPython embeds a build timestamp, so re-linking identical inputs
            # need not yield identical library bytes. Keep the verified owned
            # runtime; report its actual hashes instead of silently replacing it.
            reused = True
        else:
            with tempfile.TemporaryDirectory(prefix='stage-', dir=self.work) as temporary:
                staging = Path(temporary) / 'runtime'
                lib = staging / 'lib'
                stdlib = lib / 'python3.11'
                stdlib.parent.mkdir(parents=True)
                shutil.copytree(self.source / 'Lib', stdlib,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'test', 'tests', 'site-packages'))
                (stdlib / 'site-packages').mkdir(exist_ok=True)
                dynload = stdlib / 'lib-dynload'
                dynload.mkdir()
                for extension in compiled:
                    shutil.copy2(extension, dynload / extension.name)
                shutil.copy2(sysconfig[0], stdlib / sysconfig[0].name)
                shutil.copy2(library, lib / library.name)
                (lib / 'libpython3.11.so').symlink_to(library.name)
                shutil.copy2(self.source / 'LICENSE', stdlib / 'LICENSE.txt')
                shutil.copy2(self.source / 'LICENSE', staging / 'LICENSE-CPython.txt')
                if self.libffi_manifest is not None:
                    shutil.copy2(self.libffi_prefix / 'LICENSE-libffi.txt', staging / 'LICENSE-libffi.txt')
                (staging / 'bin').mkdir()
                common = [str(self.compiler), f'--target={TRIPLE}', f'--sysroot={self.sdk / "sysroot"}',
                          '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-fPIC',
                          '-fvisibility=hidden', '-fstack-protector-strong',
                          '-Wl,-z,relro,-z,now', '-Wl,--no-undefined', str(ROOT / 'harmony/bootstrap.c'), '-ldl']
                adapter = staging / 'bin/ChimeraX'
                self.run('compile-startup-adapter', common + ['-Wl,-rpath,$ORIGIN/../lib', '-o', str(adapter)])
                self.inspect_elf(adapter, 'startup-adapter')
                shared = lib / 'libcx_harmony_bootstrap.so'
                self.run('compile-startup-library', common + ['-shared', '-DCX_BOOTSTRAP_LIBRARY',
                    '-Wl,-soname,libcx_harmony_bootstrap.so', '-Wl,-rpath,$ORIGIN', '-o', str(shared)])
                self.inspect_elf(shared, 'startup-library')
                if not (stdlib / 'encodings/__init__.py').is_file():
                    raise RuntimeError('A genuine standard library was not staged')
                files = {str(p.relative_to(staging)): sha256(p)
                         for p in sorted(staging.rglob('*')) if p.is_file() and not p.is_symlink()}
                manifest = {'owner': OWNER, 'scope': 'generic_private_runtime_not_application_or_installable_package',
                    'python_version': VERSION, **provenance,
                    'extension_modules': extension_names, 'files': files,
                    'links': {'lib/libpython3.11.so': library.name},
                    'missing_optional_extensions': self.report['known_missing_optional_extensions'],
                    'native_gettext': self.report['native_gettext'],
                    'target_executed': False, 'application_included': False,
                    'qt_included': False, 'runtime_validated_on_target': False}
                write_json(staging / 'runtime-manifest.json', manifest)
                validate_runtime_directory(staging, manifest)
                staging.rename(self.runtime)
        if self.profile in ('with-libffi', 'with-libffi-linked'):
            ctypes_files = list((self.runtime / 'lib/python3.11/lib-dynload').glob('_ctypes.*.so'))
            if len(ctypes_files) != 1:
                raise RuntimeError('Exactly one staged _ctypes extension is required')
            text = self.run('staged-ctypes-linkage', [str(self.readelf), '--dynamic', '--dyn-syms', str(ctypes_files[0])])
            required_ffi = {'ffi_call', 'ffi_prep_cif', 'ffi_closure_alloc', 'ffi_closure_free', 'ffi_prep_closure_loc'}
            if required_ffi - defined_dynamic_symbols(text):
                raise RuntimeError('Expected static FFI definitions are missing from _ctypes')
            if any('libffi' in name for name in needed_libraries(text)):
                raise RuntimeError('Private static FFI integration unexpectedly needs a shared libffi')
            if 'LICENSE-libffi.txt' not in manifest['files']:
                raise RuntimeError('Private FFI license was not staged')
            self.report['ctypes_linkage'] = {'static_ffi_symbols_defined': sorted(required_ffi),
                'needed_libraries': needed_libraries(text), 'target_executed': False,
                'callbacks_validated_on_target': False}
        files = manifest['files']
        self.report['python_library'] = self.inspect_elf(self.runtime / 'lib' / library.name, 'staged-libpython')
        self.report['object_extension_elfs'] = extension_records
        extension_records = [self.inspect_elf(self.runtime / 'lib/python3.11/lib-dynload' / p.name,
                             'staged-module-' + p.name) for p in compiled]
        self.report.update(runtime_directory=str(self.runtime), extension_modules=extension_names,
                           extension_elfs=extension_records, staged_file_count=len(files),
                           staged_bytes=sum((self.runtime / name).stat().st_size for name in files),
                           existing_runtime_reused=reused, standard_library_complete=False,
                           status='local_generic_runtime_cross_compile_passed_not_target_tested')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, default=DEFAULT_SDK)
    parser.add_argument('--build-python', type=Path, default=ROOT / 'build/host-python/cpython-3.11.17-macos-aarch64-none/bin/python3.11')
    parser.add_argument('--jobs', type=int, choices=(1, 2), default=2)
    parser.add_argument('--profile', choices=PROFILES, default='baseline')
    parser.add_argument('--libffi-prefix', type=Path)
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    suffix = {'baseline': '', 'with-libffi': '-with-libffi',
              'with-libffi-linked': '-with-libffi-linked'}[args.profile]
    if args.report is None:
        args.report = ROOT / f'reports/cpython-local{suffix}-{day}.json'
    report = {'schema_version': 1, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'generic_CPython_private_runtime_cross_compile_only',
              'builder_source_sha256': sha256(Path(__file__)),
              'device_contacted': False, 'target_executed': False,
              'target_python_validated': False, 'target_ui_validated': False,
              'upstream_app_launched': False, 'port_validated': False, 'commands': []}
    if args.profile == 'baseline' and args.libffi_prefix is not None:
        parser.error('--libffi-prefix requires --profile with-libffi')
    builder = Builder(args.sdk, args.build_python, args.jobs, report,
                      profile=args.profile, libffi_prefix=args.libffi_prefix)
    builder.work.mkdir(parents=True, exist_ok=True)
    try:
        with (builder.work / 'build.lock').open('w') as build_lock:
            try:
                fcntl.flock(build_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('This runtime build is already active; no second build started') from exc
            lock, patch_lock = builder.prepare_source()
            builder.configure_and_build(lock, patch_lock)
            builder.stage_runtime()
    except (OSError, RuntimeError, ValueError, KeyError, tarfile.TarError) as exc:
        report.update(status='local_runtime_build_incomplete', error=str(exc))
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    write_json(args.report, report)
    print(f"{report['status']}: {args.report}", flush=True)
    if 'error' in report:
        print(report['error'], flush=True)
    return 0 if report['status'].endswith('_not_target_tested') else 2


if __name__ == '__main__':
    raise SystemExit(main())
