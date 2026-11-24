#!/usr/bin/env python3
"""Stage the Qt / PySide6 / QPA stack for the ChimeraX HarmonyOS port.

The cross-build already produced the artifacts; this script places them where
the on-device interpreter and the OHOS dynamic loader will look for them.  It
consumes ``build/qtbind/out/deploy-manifest.json`` (the machine readable twin of
``deploy-manifest.txt``) and splits the payload in two halves:

``--python-root`` (default ``build/chimerax-python``)
    Python package side: ``PySide6/`` (pure python + abi3 extension modules),
    ``shiboken6/`` (binding runtime module + its ``libshiboken6`` copy) and the
    patched ``Qt/`` shim package taken from the upstream tree.

``--libs-root`` (default ``build/qt-deploy/libs``)
    Native side: the Qt 6.12 HarmonyOS prebuilt libraries, ``libqohos.so``
    (plus the ``platforms/`` directory Qt expects for QPA plugins),
    ``libc++_shared.so`` from the OHOS SDK, ``libpyside6``/``libshiboken6``.

Two things are added on top of the manifest, because the manifest was written
before the first real import attempt and misses them (see ``gaps`` in the
output):

1. the ``shiboken6`` *package* -- ``PySide6/__init__.py`` does
   ``from shiboken6 import Shiboken`` on every import, so without it no Qt
   module can load at all;
2. ``$ORIGIN/../lib`` -- every cross-built extension is linked with that
   RUNPATH, so ``<python-root>/lib`` has to point at ``<libs-root>``; the Qt
   prebuilt in turn keeps ``/usr/local/Qt-6.12.0/lib`` and therefore relies on
   ``LD_LIBRARY_PATH`` (reported, not rewritten -- the prebuilt stays pristine).

Dry run is the default: nothing is created, the plan and the ELF NEEDED closure
are printed.  ``--apply`` performs the copies, so a parallel work line is never
surprised by half-written directories.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / 'build/qtbind/out/deploy-manifest.json'
DEFAULT_PYTHON_ROOT = ROOT / 'build/chimerax-python'
DEFAULT_LIBS_ROOT = ROOT / 'build/qt-deploy/libs'
DEFAULT_SHIBOKEN_PKG = (ROOT / 'build/qtbind/build/shiboken6-target-install'
                        / 'lib/python3.11/site-packages/shiboken6')
DEFAULT_QTSHIM = ROOT / 'build/downloads/ChimeraX-src/prereqs/qtshim/Qt'
DEFAULT_QTSHIM_PATCH = ROOT / 'patches/0004-qt-ohos-pyside6-shim.patch'
DEFAULT_APP_LIBS = ROOT / 'app/entry/libs/arm64-v8a'
SDK_CANDIDATES = [
    '/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony',
    os.environ.get('OHOS_SDK_ROOT') or '',
]


def find_sdk_root():
    for candidate in SDK_CANDIDATES:
        if candidate and (Path(candidate) / 'native/sysroot').is_dir():
            return Path(candidate)
    return None


def find_llvm_readelf(sdk):
    if sdk is not None:
        tool = sdk / 'native/llvm/bin/llvm-readelf'
        if tool.is_file():
            return tool
    found = shutil.which('llvm-readelf')
    return Path(found) if found else None


class Plan:
    def __init__(self):
        self.entries = []      # dicts: kind/dest/source/note
        self.gaps = []         # manifest items the runtime needs but does not list
        self.warnings = []
        self.links = []        # (path, target, note)
        self.shim = None       # patched Qt shim package plan
        self.missing_in_app_libs = []

    def add(self, kind, dest, source, note=''):
        self.entries.append({'kind': kind, 'dest': str(dest), 'source': str(source),
                             'note': note})

    def dests(self):
        return [e['dest'] for e in self.entries]


def classify_native(entry, python_root, libs_root, plan, app_libs):
    """Split one manifest 'native' entry into its staged destination(s)."""
    src = Path(entry['source'])
    dest_rel = entry['dest']                      # e.g. libs/arm64-v8a/libQt6Gui.so
    name = Path(dest_rel).name
    note = entry.get('note', '')
    if not src.is_file():
        plan.warnings.append('missing source for %s: %s' % (dest_rel, src))
        return
    if '/' in dest_rel.replace('libs/arm64-v8a/', '', 1) and 'PySide6' in dest_rel:
        # libs/arm64-v8a/PySide6/QtWidgets.abi3.so -> <python-root>/PySide6/...
        target = python_root / Path(dest_rel).relative_to('libs/arm64-v8a')
        plan.add('python-ext', target, src, note)
        return
    target = libs_root / name
    plan.add('native', target, src, note)
    if name.startswith('libqohos'):
        # Qt looks for QPA plugins in <plugin root>/platforms/<name>.
        plan.add('native', libs_root / 'platforms' / name, src,
                 'QPA plugin location (QT_PLUGIN_PATH=<libs-root>)')
    # The app loader also searches app/entry/libs/arm64-v8a on device; the
    # release packaging step copies the same file there, report the expectation
    # once (not per library) to keep the plan readable.
    if app_libs is not None:
        plan.missing_in_app_libs.append(name)


def build_plan(args):
    python_root = args.python_root
    libs_root = args.libs_root
    plan = Plan()
    manifest = json.loads(Path(args.manifest).read_text())
    for entry in manifest.get('native', []):
        classify_native(entry, python_root, libs_root, plan, args.app_libs)
    for entry in manifest.get('python_package', []):
        src = Path(entry['source'])
        if entry.get('kind') == 'dir':
            if not src.is_dir():
                plan.warnings.append('missing dir %s' % src)
                continue
            for path in sorted(src.rglob('*')):
                if path.is_file():
                    rel = Path(entry['path']) / path.relative_to(src)
                    plan.add('python', python_root / rel, path, '')
            continue
        target = python_root / entry['path']
        if src.is_file():
            plan.add('python', target, src, '')
        else:
            plan.warnings.append('missing source for %s: %s' % (entry['path'], src))

    # --- gap 1: shiboken6 package (not in the manifest) -------------------
    shiboken_pkg = args.shiboken_pkg
    if shiboken_pkg.is_dir():
        for path in sorted(shiboken_pkg.rglob('*')):
            if not path.is_file():
                continue
            rel = path.relative_to(shiboken_pkg)
            plan.add('python', python_root / 'shiboken6' / rel, path,
                     'gap: PySide6/__init__.py imports shiboken6.Shiboken')
            plan.gaps.append('shiboken6/%s' % rel)
        runtime = libs_root / 'libshiboken6.abi3.so.6.12'
        if runtime.is_file() or any(Path(e['source']).name == 'libshiboken6.abi3.so.6.12'
                                    for e in plan.entries):
            plan.add('native', python_root / 'shiboken6' / 'libshiboken6.abi3.so.6.12',
                     runtime if runtime.is_file() else Path(shiboken_pkg).parent / '..' /
                     '..' / 'lib' / 'libshiboken6.abi3.so.6.12',
                     'gap: shiboken6/{Shiboken.abi3.so} has RUNPATH $ORIGIN/, '
                     'so the runtime lib must sit next to it')
            plan.gaps.append('shiboken6/libshiboken6.abi3.so.6.12')
    else:
        plan.warnings.append('shiboken6 package not built at %s' % shiboken_pkg)

    # --- gap 2: <python-root>/lib -> <libs-root> (RUNPATH $ORIGIN/../lib) ---
    lib_link = python_root / 'lib'
    try:
        link_target = os.path.relpath(libs_root, python_root)
    except ValueError:
        link_target = str(libs_root)
    plan.links.append((lib_link, link_target,
                       'RUNPATH $ORIGIN/../lib of every PySide6 extension'))

    # --- qtshim package (patched by 0004-qt-ohos-pyside6-shim.patch) --------
    if args.with_qtshim:
        qtshim = args.qtshim_dir
        patch = args.qtshim_patch
        if not qtshim.is_dir():
            plan.warnings.append('qtshim package not found at %s' % qtshim)
        else:
            already = (qtshim / 'ohos.py').is_file()
            if not already and not patch.is_file():
                plan.warnings.append(
                    'qtshim is unpatched and %s is missing: the staged Qt shim will '
                    'not enable the OHOS platform defaults' % patch)
            plan.shim = {'source': str(qtshim), 'patch': str(patch),
                         'needs_patch': not already, 'target': str(python_root / 'Qt')}
            if already:
                for path in sorted(qtshim.rglob('*')):
                    if path.is_file() and path.suffix == '.py':
                        plan.add('shim', python_root / 'Qt' / path.relative_to(qtshim),
                                 path, 'already patched')
            else:
                # The patch adds Qt/ohos.py, so the produced package has one more
                # module than the pristine tree.
                for path in sorted(qtshim.rglob('*')):
                    if path.is_file() and path.suffix == '.py':
                        plan.add('shim', python_root / 'Qt' / path.relative_to(qtshim),
                                 path, 'from patch %s' % patch.name)
                plan.add('shim', python_root / 'Qt' / 'ohos.py',
                         Path('<generated by %s>' % patch.name),
                         'new module added by the patch')
                plan.gaps.append('Qt/ohos.py (added by %s)' % patch.name)
    return plan


def parse_needed(readelf, path):
    """Return (needed, runpath) for one ELF, or None if it is not readable."""
    try:
        out = subprocess.run([str(readelf), '-d', str(path)], capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    needed, runpath = [], None
    for line in out.stdout.splitlines():
        if '(NEEDED)' in line:
            if '[' in line and ']' in line:
                needed.append(line[line.index('[') + 1:line.index(']')])
        elif '(RUNPATH)' in line or '(RPATH)' in line:
            if '[' in line and ']' in line:
                runpath = line[line.index('[') + 1:line.index(']')]
    return needed, runpath


def parse_soname(readelf, path):
    try:
        out = subprocess.run([str(readelf), '-d', str(path)], capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.stdout.splitlines():
        if '(SONAME)' in line and '[' in line and ']' in line:
            return line[line.index('[') + 1:line.index(']')]
    return None


def elf_closure(plan, args, sdk):
    """Check that every NEEDED of the staged set resolves inside the deployment."""
    readelf = find_llvm_readelf(sdk)
    if readelf is None:
        return {'available': False,
                'reason': 'llvm-readelf not found (pass --sdk-root)'}
    search = [
        ('deployed-libs', args.libs_root),
        ('python-root/PySide6', args.python_root / 'PySide6'),
        ('python-root/shiboken6', args.python_root / 'shiboken6'),
        ('python-root/lib', args.python_root / 'lib'),
        ('app-libs', args.app_libs),
    ]
    if sdk is not None:
        search.append(('sdk-sysroot', sdk / 'native/sysroot/usr/lib/aarch64-linux-ohos'))
        search.append(('sdk-clang-runtime', sdk / 'native/llvm/lib/aarch64-linux-ohos'))
    libs = []
    for entry in plan.entries:
        src = Path(entry['source'])
        if entry['kind'] in ('native', 'python-ext') and src.is_file() and \
                src.read_bytes()[:4] == b'\x7fELF':
            libs.append(entry)
    # A dry run must be able to verify the closure too, so resolve against the
    # *planned* set (by SONAME) before falling back to what exists on disk.
    provided = {}
    for entry in libs:
        name = Path(entry['dest']).name
        provided[name] = entry['dest']
        parsed = parse_needed(readelf, entry['source'])
        if parsed is not None:
            soname = parse_soname(readelf, entry['source'])
            if soname:
                provided.setdefault(soname, entry['dest'])
    results, unresolved_all = [], []
    for entry in libs:
        name = Path(entry['dest']).name
        parsed = parse_needed(readelf, entry['source'])
        if parsed is None:
            results.append({'lib': name, 'error': 'readelf failed'})
            continue
        needed, runpath = parsed
        resolved, unresolved = {}, []
        for dep in needed:
            if dep in provided:
                resolved[dep] = 'staged-set'
                continue
            hit = None
            for label, directory in search:
                if directory is not None and (Path(directory) / dep).exists():
                    hit = label
                    break
            if hit is None:
                unresolved.append(dep)
                unresolved_all.append({'lib': name, 'needed': dep})
            else:
                resolved[dep] = hit
        results.append({'lib': name, 'dest': entry['dest'], 'runpath': runpath,
                        'needed': needed, 'resolved': resolved,
                        'unresolved': unresolved})
    return {
        'available': True,
        'readelf': str(readelf),
        'search_path': [(label, str(directory)) for label, directory in search
                        if directory is not None],
        'libs_checked': len(results),
        'provided_sonames': sorted(provided),
        'unresolved': unresolved_all,
        'complete': not unresolved_all,
        'details': results,
    }


def print_plan(plan, args, apply):
    print('Qt/PySide6 staging plan  (%s)' % ('APPLY' if apply else 'dry-run'))
    print('  python root : %s' % args.python_root)
    print('  libs root   : %s' % args.libs_root)
    print('  manifest    : %s' % args.manifest)
    print()
    groups = {}
    for entry in plan.entries:
        groups.setdefault(entry['kind'], []).append(entry)
    total = 0
    for kind in ('native', 'python-ext', 'python', 'shim', 'shim-state'):
        entries = groups.get(kind, [])
        if not entries:
            continue
        print('[%s] %d file(s)' % (kind, len(entries)))
        for entry in entries:
            print('  %-56s <- %s' % (str(Path(entry['dest'])), entry['source']))
            if entry['note']:
                print('  %-56s    (%s)' % ('', entry['note']))
            total += 1
        print()
    if plan.links:
        print('[symlinks] %d' % len(plan.links))
        for path, target, note in plan.links:
            print('  %s -> %s   (%s)' % (path, target, note))
        print()
    if plan.shim:
        shim = plan.shim
        print('[Qt shim] %s' % shim['target'])
        print('  source : %s' % shim['source'])
        if shim['needs_patch']:
            print('  patch  : %s  (applied to a scratch copy, upstream tree untouched)'
                  % shim['patch'])
        else:
            print('  patch  : already present in the source tree')
        print()
    if plan.gaps:
        print('[manifest gaps filled] %d' % len(plan.gaps))
        for gap in plan.gaps:
            print('  + %s' % gap)
        print()
    if plan.missing_in_app_libs:
        print('[hand-off] %d lib(s) still to be copied into app/entry/libs/arm64-v8a '
              'by the packaging line' % len(plan.missing_in_app_libs))
        print('  %s' % ', '.join(plan.missing_in_app_libs))
        print()
    if plan.warnings:
        print('[warnings] %d' % len(plan.warnings))
        for warning in plan.warnings:
            print('  ! %s' % warning)
        print()
    print('total entries: %d' % total)


def stage_qtshim_shim(plan, python_root):
    """Produce <python-root>/Qt from the pristine shim + patch 0004."""
    shim = plan.shim
    if shim is None:
        return
    target = Path(shim['target'])
    if not shim['needs_patch']:
        src = Path(shim['source'])
        target.mkdir(parents=True, exist_ok=True)
        for path in sorted(src.rglob('*')):
            if path.is_file() and path.suffix == '.py':
                dest = target / path.relative_to(src)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
        print('Qt shim copied from %s (%d module(s))'
              % (src, len(list(target.glob('*.py')))))
        return
    scratch = python_root / '.qtshim-scratch'
    if scratch.exists():
        shutil.rmtree(scratch)
    (scratch / 'prereqs/qtshim').mkdir(parents=True)
    shutil.copytree(shim['source'], scratch / 'prereqs/qtshim/Qt')
    command = ['git', 'apply', '--verbose', shim['patch']]
    result = subprocess.run(command, cwd=scratch, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit('git apply failed for %s:\n%s%s'
                         % (shim['patch'], result.stdout, result.stderr))
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(scratch / 'prereqs/qtshim/Qt'), str(target))
    shutil.rmtree(scratch)
    print('Qt shim patched with %s -> %s' % (Path(shim['patch']).name, target))


def apply_plan(plan, args):
    created_dirs = set()
    copied = 0
    for entry in plan.entries:
        if entry['kind'] in ('shim-state', 'shim'):
            continue
        dest = Path(entry['dest'])
        src = Path(entry['source'])
        if not src.is_file():
            print('SKIP (missing source): %s' % src, file=sys.stderr)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        created_dirs.add(str(dest.parent))
        shutil.copy2(src, dest)
        copied += 1
    for path, target, _note in plan.links:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.exists():
            if path.is_symlink() and os.readlink(path) == target:
                continue
            if path.is_dir() and not path.is_symlink():
                print('SKIP (real directory already present): %s' % path, file=sys.stderr)
                continue
            path.unlink()
        os.symlink(target, path)
        print('symlink %s -> %s' % (path, target))
    stage_qtshim_shim(plan, args.python_root)
    print('copied %d file(s), %d symlink(s), %d directory(ies) touched'
          % (copied, len(plan.links), len(created_dirs)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--python-root', type=Path, default=DEFAULT_PYTHON_ROOT,
                        help='Python package side destination')
    parser.add_argument('--libs-root', type=Path, default=DEFAULT_LIBS_ROOT,
                        help='native library destination')
    parser.add_argument('--shiboken-pkg', type=Path, default=DEFAULT_SHIBOKEN_PKG)
    parser.add_argument('--qtshim-dir', type=Path, default=DEFAULT_QTSHIM)
    parser.add_argument('--qtshim-patch', type=Path, default=DEFAULT_QTSHIM_PATCH,
                        help='patch applied to a scratch copy of the shim')
    parser.add_argument('--app-libs', type=Path, default=DEFAULT_APP_LIBS)
    parser.add_argument('--no-qtshim', dest='with_qtshim', action='store_false',
                        help='only stage Qt/PySide6, not the Qt shim package')
    parser.add_argument('--sdk-root', type=Path, default=None,
                        help='OpenHarmony SDK root (for sysroot / llvm-readelf)')
    parser.add_argument('--no-elf-check', dest='elf_check', action='store_false')
    parser.add_argument('--apply', action='store_true',
                        help='really write (default is a dry-run report)')
    parser.add_argument('--json-out', type=Path, default=None,
                        help='write the plan and ELF closure as JSON')
    args = parser.parse_args()

    sdk = args.sdk_root or find_sdk_root()
    plan = build_plan(args)
    print_plan(plan, args, args.apply)
    closure = None
    if args.elf_check:
        closure = elf_closure(plan, args, sdk)
        print()
        if not closure['available']:
            print('ELF closure: not checked (%s)' % closure['reason'])
        else:
            print('ELF closure via %s: %d lib(s) checked, %d unresolved'
                  % (closure['readelf'], closure['libs_checked'],
                     len(closure['unresolved'])))
            if closure['complete']:
                print('  NEEDED closure: COMPLETE (every dependency resolvable '
                      'inside the staged set / sysroot)')
            else:
                for item in closure['unresolved']:
                    print('  UNRESOLVED %s needs %s' % (item['lib'], item['needed']))
    if args.apply:
        print()
        apply_plan(plan, args)
    if args.json_out:
        payload = {
            'generated': datetime.now(timezone.utc).isoformat(),
            'mode': 'apply' if args.apply else 'dry-run',
            'python_root': str(args.python_root),
            'libs_root': str(args.libs_root),
            'manifest': str(args.manifest),
            'sdk_root': str(sdk) if sdk else None,
            'entries': plan.entries,
            'symlinks': [{'path': str(p), 'target': t, 'note': n}
                         for p, t, n in plan.links],
            'qtshim': plan.shim,
            'gaps': plan.gaps,
            'hand_off_to_app_libs': plan.missing_in_app_libs,
            'warnings': plan.warnings,
            'elf_closure': closure,
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=1) + '\n')
        print('json: %s' % args.json_out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
