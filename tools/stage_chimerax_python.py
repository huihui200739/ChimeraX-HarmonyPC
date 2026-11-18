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
import re
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
    # Additional core bundles whose Python packages the runtime needs: array
    # marshalling and the graphics layer (their C++ modules are built separately
    # by tools/build_graphics_ext_harmony.py).
    for bundle in ('arrays', 'graphics', 'geometry', 'atomic_lib', 'atomic', 'pdb_lib',
                   'mmcif', 'pdb', 'io', 'data_formats', 'open_command'):
        source_bundle = args.source / 'src/bundles' / bundle / 'src'
        if source_bundle.is_dir():
            shutil.copytree(source_bundle, package / bundle, dirs_exist_ok=True)
    for junk in ('tests', '__pycache__'):
        target = package / 'core' / junk
        if target.exists():
            shutil.rmtree(target)
    (package / 'core/buildinfo.py').write_text(buildinfo)
    # Pure-Python runtime dependencies of chimerax.core (colors/commands).
    dependencies = []
    for pattern, package in (('sortedcontainers-*.whl', 'sortedcontainers'),
                             ('packaging-*.whl', 'packaging'),
                             ('appdirs-*.whl', 'appdirs')):
        wheels = sorted((ROOT / 'build/downloads').glob(pattern))
        if not wheels:
            continue
        wheel = wheels[-1]
        with zipfile.ZipFile(wheel) as bundle:
            for name in bundle.namelist():
                if (name.startswith(package + '/') and name.endswith('.py')) or name == 'appdirs.py':
                    destination = args.output / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(bundle.read(name))
        dependencies.append({'wheel': wheel.name,
                             'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest()})
    dependency = dependencies[0] if dependencies else None
    # --- upstream patches ---------------------------------------------------
    # The render patch adds the OHOS EGL context to chimerax.graphics.opengl; it is
    # kept as a patch (patches/) so the upstream tree stays untouched.
    patches_dir = ROOT / 'patches'
    applied = []
    for patch_file in sorted(patches_dir.glob('*-render-ohos-*.patch')):
        # Patches are written against the upstream layout (src/bundles/<b>/src/...)
        # while the staged tree flattens a bundle to chimerax/<b>/..., so the paths
        # are rewritten into a temporary patch and applied with -p1.
        text = patch_file.read_text()
        rewritten = re.sub(r'(?m)^(---|\+\+\+) ([ab])/src/bundles/([a-z_]+)/src/',
                           lambda m: f'{m.group(1)} {m.group(2)}/chimerax/{m.group(3)}/', text)
        temp_patch = args.output.parent / (patch_file.stem + '.staged.patch')
        temp_patch.write_text(rewritten)
        result = subprocess.run(['patch', '-p1', '--forward', '--batch', '-i', str(temp_patch)],
                                cwd=args.output, capture_output=True, text=True)
        applied.append({'patch': patch_file.name, 'returncode': result.returncode,
                        'stdout': result.stdout.strip()[:200]})
    report_extra = applied

    # --- platform shims -----------------------------------------------------
    # Upstream *_lib bundles dlopen per-library shared objects through a Cython
    # _load_libs module; this port links those translation units into one shared
    # library, so the module only has to exist for the upstream import to work.
    for bundle, dotted in (('atomic_lib', 'chimerax.atomic_lib'), ('pdb_lib', 'chimerax.pdb_lib')):
        target = args.output / 'chimerax' / bundle / '_load_libs.py'
        if target.parent.is_dir():
            target.write_text(
                f'"""Platform shim for the HarmonyOS build ({bundle}).\n\n'
                'The C++ libraries are linked into chimerax/lib/libcxatomstruct.so instead of\n'
                'being loaded individually, so this module only satisfies the upstream import.\n"""\n'
                '\nloaded: dict[str, str] = {}\n\n\n'
                'def load_lib(name: str) -> str:\n'
                '    return f"static:{name}"\n\n\n'
                'def lib_path(name: str) -> str:\n'
                '    return load_lib(name)\n\n\n'
                f'def python_module_name(name: str) -> str:\n    return "{dotted}.lib" + name\n')

    # molc.py loads libmolc with ctypes from the package directory; ELF objects in
    # the app data directory cannot be dlopen'ed, so prefer the native library dir.
    molc = args.output / 'chimerax/atomic/molc.py'
    if molc.is_file():
        text = molc.read_text()
        if 'CX_NATIVE_LIB_DIR' not in text:
            needle = """    for ext in exts:
        if os.path.isabs(lib_name):
            lib_path = lib_name
        else:
            lib_path = os.path.join(os.path.dirname(__file__), lib_name)"""
            replacement = """    # HarmonyOS port: shared objects extracted under the app data directory cannot be
    # dlopen'ed there, so the same libraries are packaged in the application native
    # library directory and looked up first (CX_NATIVE_LIB_DIR is set by the shell).
    native_dir = os.environ.get('CX_NATIVE_LIB_DIR')
    for ext in exts:
        if os.path.isabs(lib_name):
            lib_path = lib_name
        else:
            lib_path = os.path.join(os.path.dirname(__file__), lib_name)
        if native_dir and not os.path.isabs(lib_name):
            candidate = os.path.join(native_dir, 'chimerax', 'atomic',
                                     os.path.basename(lib_path) + ext)
            if os.path.exists(candidate):
                lib_path = candidate"""
            if needle in text:
                text = text.replace(needle, replacement)
                text = text.replace("""        lib_path += ext
        if not os.path.exists(lib_path):""",
"""        if not lib_path.endswith(ext):
            lib_path += ext
        if not os.path.exists(lib_path):""")
                molc.write_text(text)

    files = {str(p.relative_to(args.output)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(args.output.rglob('*')) if p.is_file()}
    record = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'source': str(args.source), 'commit': commit, 'version': version,
              'branch': branch, 'files': len(files), 'package': str(package),
              'dependencies': dependencies, 'patches': report_extra,
              'modules': sorted({p.split('/')[1] for p in files if p.count('/') >= 1})[:40]}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: record[k] for k in ('version', 'commit', 'files')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
