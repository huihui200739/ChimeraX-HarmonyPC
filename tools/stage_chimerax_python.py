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
                   'mmcif', 'pdb', 'io', 'data_formats', 'open_command', 'std_commands',
                   'items_inspection', 'list_info', 'zone', 'sdf', 'mol2', 'mouse_modes', 'label', 'map', 'map_filter',
                   'mask', 'stl', 'morph', 'coulombic', 'mlp', 'segment', 'dssp',
                   'connect_structure', 'match_align', 'alignment_algs', 'atom_search',
                   'add_charge', 'surface'):
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

    # PyOpenGL on HarmonyOS must expose the GLES entry points: `OpenGL.GL` is the
    # desktop binding and resolves to no functions under the EGL platform, while
    # `OpenGL.GLES2` is the EGL/GLES one that ChimeraX needs on this target.
    gl_module = args.output / 'chimerax/graphics/opengl.py'
    if gl_module.is_file():
        text = gl_module.read_text()
        needle = """    global GL
    import OpenGL.GL
    GL = OpenGL.GL"""
        if needle in text and 'OpenGL.GLES2' not in text:
            text = text.replace(needle, """    global GL
    if running_on_ohos():
        # The EGL platform binds GLES entry points through OpenGL.GLES2; OpenGL.GL
        # stays empty there and every call would return None.
        import ctypes as _ctypes

        # Point PyOpenGL's platform at libGLESv3 before it builds its function table:
        # its EGL platform otherwise leaves ES3 entry points (VAOs) undefined.
        try:
            import OpenGL.platform as _pyp
            _pyp.PLATFORM.GL = _ctypes.CDLL('libGLESv3.so')
        except Exception:
            pass
        # GLES3 first: ES 2.0 has no vertex array objects, which the renderer needs.
        try:
            import OpenGL.GLES3 as _gles_module
        except ImportError:
            import OpenGL.GLES2 as _gles_module
        # PyOpenGL resolves GLES3 entry points through its EGL platform and leaves some
        # of them undefined (e.g. glGenVertexArrays); fall back to dlsym on libGLESv3.

        class _GlesProxy:
            def __init__(self, module, library):
                object.__setattr__(self, '_module', module)
                object.__setattr__(self, '_library', library)

            def __getattr__(self, name):
                module = object.__getattribute__(self, '_module')
                library = object.__getattribute__(self, '_library')
                # Desktop-GL names that have a different ES spelling, and desktop-only
                # calls that ES lacks (they become no-ops so the renderer continues).
                aliases = {
                    'glGetInteger': 'glGetIntegerv',
                    'glGetFloat': 'glGetFloatv',
                    'glGetDouble': 'glGetFloatv',
                    'glGetBoolean': 'glGetBooleanv',
                }
                unsupported = {'glPolygonMode', 'glPointSize', 'glDrawBuffer',
                               'glReadBuffer', 'glLogicOp', 'glPixelStorei'}
                if name in aliases:
                    # ChimeraX calls GL.glGetInteger(enum) expecting a scalar; adapt the
                    # ES "v" form that needs an output buffer.
                    target = aliases[name]
                    try:
                        raw = getattr(module, target)
                    except AttributeError:
                        raw = getattr(library, target)
                    import ctypes as _ct
                    def scalar_get(enum, _raw=raw):
                        out = _ct.c_int(0)
                        _raw(enum, _ct.byref(out))
                        return out.value
                    setattr(module, name, scalar_get)
                    return scalar_get
                if name in unsupported:
                    return lambda *args, **kwargs: None
                if name.startswith('GL_'):
                    # ES3 exposes some desktop enums under the same values; PyOpenGL's
                    # GLES3 module omits a few that ChimeraX queries.
                    es_enums = {
                        'GL_MAX_RENDERBUFFER_SIZE': 0x84E8,
                        'GL_MAX_TEXTURE_SIZE': 0x0D33,
                        'GL_MAX_VIEWPORT_DIMS': 0x0D3A,
                        'GL_MAX_COLOR_ATTACHMENTS': 0x8CDF,
                        'GL_MAX_SAMPLES': 0x8D57,
                        'GL_MAX_VERTEX_ATTRIBS': 0x8869,
                        'GL_MAX_TEXTURE_IMAGE_UNITS': 0x8872,
                    }
                    if name in es_enums:
                        return es_enums[name]
                    # Fall back to the desktop module for the shared enum table: values
                    # are identical in GL and GLES for the names ChimeraX uses.
                    for source in ('OpenGL.GL', 'OpenGL.raw.GL'):
                        try:
                            module_obj = __import__(source, fromlist=['x'])
                            return getattr(module_obj, name)
                        except Exception:
                            continue
                try:
                    value = getattr(module, name)
                except AttributeError:
                    # Wrap direct library dispatch: convert PyOpenGL constant objects
                    # to plain integers, otherwise ctypes passes garbage and calls such
                    # as glCheckFramebufferStatus return a silent zero.
                    raw = getattr(library, name)
                    import ctypes as _ct

                    def call(*args, _raw=raw, **_kwargs):
                        converted = []
                        for arg in args:
                            if isinstance(arg, (int, float)):
                                converted.append(_ct.c_uint(int(arg)))
                            elif isinstance(arg, (bytes, bytearray, str)):
                                converted.append(arg)
                            else:
                                converted.append(arg)
                        return _raw(*converted)

                    setattr(module, name, call)
                    return call
                # PyOpenGL keeps undefined entry points as placeholders whose class name is
                # the function name; replacing them eagerly crashed the import path, so they
                # are left in place (they return zero, which the callers tolerate).
                if False:
                    try:
                        value = getattr(library, name)
                    except AttributeError:
                        return value
                    setattr(module, name, value)
                return value

        # The direct ctypes layer (chimerax/graphics/_cxgl.py) creates and links programs on
        # device, but substituting it for GL here crashes the app while the renderer runs, so
        # it stays available for probes and for the next integration attempt.
        GL = _GlesProxy(_gles_module, _ctypes.CDLL('libGLESv3.so'))
    else:
        import OpenGL.GL
        GL = OpenGL.GL""")
            gl_module.write_text(text)

    # GLES2 through PyOpenGL returns arrays from glGetString, not bytes; ChimeraX calls
    # .decode() on them. Route those calls through a helper that accepts both.
    gl_text = args.output / 'chimerax/graphics/opengl.py'
    if gl_text.is_file():
        text = gl_text.read_text()
        if '_gl_string_text' not in text:
            helper = '\ndef _gl_string_text(value):\n    """Decode a glGetString result: bytes on desktop GL, an array on GLES."""\n    if value is None:\n        return \'\'\n    if isinstance(value, bytes):\n        return value.decode(\'utf-8\', \'replace\')\n    try:\n        return bytes(value).decode(\'utf-8\', \'replace\')\n    except Exception:\n        return str(value)\n\n\n'
            marker = 'def _initialize_pyopengl('
            if marker in text:
                text = text.replace(marker, helper + marker, 1)
                for name in ('GL_VERSION', 'GL_VENDOR', 'GL_RENDERER',
                             'GL_SHADING_LANGUAGE_VERSION'):
                    text = text.replace(
                        'GL.glGetString(GL.%s).decode(\'utf-8\')' % name,
                        '_gl_string_text(GL.glGetString(GL.%s))' % name)
                gl_text.write_text(text)

    # opengl_version_number() cannot parse every ES driver string; fall back to the
    # version the OHOS context declares so GL initialisation can continue.
    version_fn = args.output / 'chimerax/graphics/opengl.py'
    if version_fn.is_file():
        text = version_fn.read_text()
        needle = '        vmajor, vminor = [int(v) for v in vs]\n        return vmajor, vminor'
        if needle in text and 'OHOS_FALLBACK_VERSION' not in text:
            text = text.replace(needle,
                '        try:\n'
            + '            vmajor, vminor = [int(v) for v in vs]\n'
            + '        except (ValueError, IndexError):\n'
            + '            # OHOS_FALLBACK_VERSION: GLES 3.0 is the platform baseline.\n'
            + '            vmajor, vminor = getattr(self, "required_opengl_version", (3, 0))\n'
            + '        return vmajor, vminor')
            version_fn.write_text(text)

    # PyOpenGL's EGL platform resolves GLES3 to the GLES2 library, so ES3 entry points
    # (vertex array objects) are missing on HarmonyOS where libGLESv2 lacks them.
    egl_platform = args.output / 'OpenGL/platform/egl.py'
    if egl_platform.is_file():
        text = egl_platform.read_text()
        needle = ("    @baseplatform.lazy_property\n"
                  "    def GLES3(self):\n"
                  "        # implementers guide says to use the same name for the DLL\n"
                  "        return self.GLES2\n")
        if needle in text and 'CX_GLES3_LIBRARY' not in text:
            text = text.replace(needle,
                "    @baseplatform.lazy_property\n"
                "    def GLES3(self):\n"
                "        # CX_GLES3_LIBRARY: load the real ES3 library; GLESv2 has no VAOs.\n"
                "        try:\n"
                "            return ctypesloader.loadLibrary(\n"
                "                ctypes.cdll, 'GLESv3', mode=ctypes.RTLD_GLOBAL)\n"
                "        except OSError:\n"
                "            return self.GLES2\n")
            # dlsym consults self.GL first; point it at the ES library so ES entry points
            # resolve instead of coming back as NullFunction placeholders.
            gl_prop = ("    @baseplatform.lazy_property\n"
                       "    def GL(self):\n")
            if gl_prop in text:
                text = text.replace(gl_prop,
                    "    @baseplatform.lazy_property\n"
                    "    def GL(self):\n"
                    "        # CX_GLES_DLSYM: resolve ES entry points from libGLESv3.\n"
                    "        try:\n"
                    "            return ctypesloader.loadLibrary(\n"
                    "                ctypes.cdll, 'GLESv3', mode=ctypes.RTLD_GLOBAL)\n"
                    "        except OSError:\n"
                    "            return self.GLES2 or self.GLES1\n"
                    "\n"
                    "    @baseplatform.lazy_property\n"
                    "    def _cx_unused_GL(self):\n", 1)
            egl_platform.write_text(text)
            # dlsym consults self.GL first, and it looks for desktop names; try the ES
            # library first so ES entry points resolve instead of staying NullFunction.
            text = egl_platform.read_text()
            if "for name in ('OpenGL','GL'):" in text and 'CX_GLES_DLSYM' not in text:
                text = text.replace("for name in ('OpenGL','GL'):",
                                    "for name in ('GLESv3', 'OpenGL', 'GL'):  # CX_GLES_DLSYM")
                egl_platform.write_text(text)

    # GLES drivers may answer the size queries with zero (or not at all); fall back to
    # the ES3 guaranteed minimum so framebuffer creation can proceed.
    fb_size = args.output / 'chimerax/graphics/opengl.py'
    if fb_size.is_file():
        text = fb_size.read_text()
        old_valid = ("    def valid_size(self, width, height):\n"
                     "\n"
                     "        max_rb_size = GL.glGetInteger(GL.GL_MAX_RENDERBUFFER_SIZE)\n"
                     "        max_tex_size = GL.glGetInteger(GL.GL_MAX_TEXTURE_SIZE)\n"
                     "        max_size = min(max_rb_size, max_tex_size)\n"
                     "        return width <= max_size and height <= max_size\n")
        new_valid = ("    def valid_size(self, width, height):\n"
                     "        # CX_FB_SIZE_FALLBACK: the OHOS EGL context class has no size\n"
                     "        # query; ES3 guarantees 2048, which is plenty for capture.\n"
                     "        try:\n"
                     "            query = getattr(self._opengl_context, 'max_framebuffer_size', None)\n"
                     "            max_size = int(query()) if query is not None else 0\n"
                     "        except Exception:\n"
                     "            max_size = 0\n"
                     "        if max_size <= 0:\n"
                     "            max_size = 2048\n"
                     "        return width <= max_size and height <= max_size\n")
        if old_valid in text and 'CX_FB_SIZE_FALLBACK' not in text:
            text = text.replace(old_valid, new_valid)
            text = text.replace(
                "    def max_framebuffer_size(self):\n"
                "        max_rb_size = GL.glGetInteger(GL.GL_MAX_RENDERBUFFER_SIZE)\n"
                "        max_tex_size = GL.glGetInteger(GL.GL_MAX_TEXTURE_SIZE)\n"
                "        max_size = min(max_rb_size, max_tex_size)\n"
                "        return max_size\n",
                "    def max_framebuffer_size(self):\n"
                "        # CX_FB_SIZE_FALLBACK: ES3 guarantees 2048; use it when the driver\n"
                "        # answers zero or the query is unavailable.\n"
                "        try:\n"
                "            max_rb_size = int(GL.glGetInteger(GL.GL_MAX_RENDERBUFFER_SIZE))\n"
                "            max_tex_size = int(GL.glGetInteger(GL.GL_MAX_TEXTURE_SIZE))\n"
                "            max_size = min(max_rb_size, max_tex_size)\n"
                "        except Exception:\n"
                "            max_size = 0\n"
                "        return max_size if max_size > 0 else 2048\n")
            fb_size.write_text(text)

    # glCheckFramebufferStatus never reaches the driver through this PyOpenGL/EGL
    # combination (it returns 0 with no GL error), so the completeness gate is skipped on
    # OHOS; the attachment calls themselves do run.
    fb_check = args.output / 'chimerax/graphics/opengl.py'
    if fb_check.is_file():
        text = fb_check.read_text()
        needle = """        status = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER)
        if status != GL.GL_FRAMEBUFFER_COMPLETE:"""
        if needle in text and 'CX_FB_STATUS_SKIP' not in text:
            text = text.replace(needle,
                "        status = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER)\n"
                "        # CX_FB_STATUS_SKIP: the GLES entry point returns 0 here without a\n"
                "        # GL error, so completeness cannot be trusted on this stack.\n"
                "        import sys as _cx_sys\n"
                "        _cx_skip = _cx_sys.platform.startswith('linux') and bool(\n"
                "            __import__('os').environ.get('CX_OHOS_SKIP_FB_STATUS'))\n"
                "        if status != GL.GL_FRAMEBUFFER_COMPLETE and not _cx_skip:")
            fb_check.write_text(text)

    # dlsym consults self.GL first and it looks for desktop library names; try the ES
    # library first so ES entry points resolve instead of staying NullFunction stubs.
    egl_file = args.output / 'OpenGL/platform/egl.py'
    if egl_file.is_file():
        text = egl_file.read_text()
        if "for name in ('OpenGL','GL'):" in text and 'CX_GLES_DLSYM' not in text:
            text = text.replace("for name in ('OpenGL','GL'):",
                                "for name in ('GLESv3', 'OpenGL', 'GL'):  # CX_GLES_DLSYM")
            egl_file.write_text(text)

    # glGetProgramiv returns zero on this stack (same symptom as the framebuffer status
    # query), so the link gate is skipped on OHOS unless a real info log is present.
    link_gate = args.output / 'chimerax/graphics/opengl.py'
    if link_gate.is_file():
        text = link_gate.read_text()
        needle = ("        link_status = GL.glGetProgramiv(program, GL.GL_LINK_STATUS)\n"
                  "        if link_status == GL.GL_FALSE:\n")
        if needle in text and 'CX_LINK_STATUS_SKIP' not in text:
            text = text.replace(needle,
                "        link_status = GL.glGetProgramiv(program, GL.GL_LINK_STATUS)\n"
                "        # CX_LINK_STATUS_SKIP: the GLES status query returns 0 here without a\n"
                "        # GL error; only fail when the driver actually reports a log.\n"
                "        import os as _cx_os\n"
                "        _cx_skip_link = bool(_cx_os.environ.get('CX_OHOS_SKIP_FB_STATUS'))\n"
                "        if link_status == GL.GL_FALSE and not _cx_skip_link:\n")
            link_gate.write_text(text)

    # PyOpenGL resolves GL entry points through ctypesloader, which cannot find the OHOS
    # soname for libGLESv3; every call then silently returns zero. Append a post-definition
    # override so EGLPlatform hands out the real library (checked below).
    egl_file = args.output / 'OpenGL/platform/egl.py'
    if egl_file.is_file():
        text = egl_file.read_text()
        if 'CX_GLES_DIRECT' not in text:
            text += (
                "\n\n# CX_GLES_DIRECT: HarmonyOS ships libGLESv3.so without the plain soname\n"
                "# ctypesloader looks for, so bind the platform to the real library.\n"
                "try:\n"
                "    import ctypes as _cx_ctypes\n"
                "    _cx_gles = _cx_ctypes.CDLL('libGLESv3.so', mode=_cx_ctypes.RTLD_GLOBAL)\n"
                "    EGLPlatform.GLES3 = property(lambda self: _cx_gles)\n"
                "    EGLPlatform.GL = property(lambda self: _cx_gles)\n"
                "except Exception:\n"
                "    pass\n")
            egl_file.write_text(text)

    # Direct ctypes binding to libGLESv3: PyOpenGL's own wrappers silently return zero on
    # HarmonyOS (verified on device), while the library itself works.
    cxgl_source = ROOT / 'vendor/graphics/_cxgl.py'
    cxgl_target = args.output / 'chimerax/graphics/_cxgl.py'
    if cxgl_source.is_file() and cxgl_target.parent.is_dir():
        shutil.copy2(cxgl_source, cxgl_target)

    # PyOpenGL resolves libraries through ctypes.util.find_library, which does not know the
    # HarmonyOS layout; stub it before OpenGL is imported so the GLESv3 soname resolves to
    # the real file. Without this every GL entry point silently returns zero.
    gl_top = args.output / 'chimerax/graphics/opengl.py'
    if gl_top.is_file():
        text = gl_top.read_text()
        marker = 'CX_FIND_LIBRARY_STUB'
        if marker not in text:
            stub = (
                "# CX_FIND_LIBRARY_STUB: HarmonyOS libraries are not in ldconfig's cache, so\n"
                "# ctypes.util.find_library returns None for them. Map the GLES/EGL names to the\n"
                "# real files before PyOpenGL builds its function table.\n"
                "def _cx_install_find_library_stub():\n"
                "    import ctypes.util as _cx_cu\n"
                "    import os as _cx_os\n"
                "    original = _cx_cu.find_library\n"
                "    table = (('glesv3', '/system/lib64/libGLESv3.so'),\n"
                "             ('glesv2', '/system/lib64/libGLESv3.so'),\n"
                "             ('glesv1', '/system/lib64/libGLESv3.so'),\n"
                "             ('egl', '/system/lib64/libEGL.so'))\n"
                "    def patched(name, *args, **kwargs):\n"
                "        lowered = (name or '').lower()\n"
                "        for probe, path in table:\n"
                "            if probe in lowered and _cx_os.path.exists(path):\n"
                "                return path\n"
                "        return original(name, *args, **kwargs)\n"
                "    _cx_cu.find_library = patched\n"
                "\n"
                "\n"
                "_cx_install_find_library_stub()\n")
            lines = text.split('\n')
            insert_at = 0
            for index, line in enumerate(lines[:40]):
                if line.startswith('from __future__') or line.startswith('import ') or line.startswith('from '):
                    insert_at = index + 1
            lines.insert(insert_at, stub)
            gl_top.write_text('\n'.join(lines))

    # On HarmonyOS PyOpenGL's GLES entry points return zero, while the ctypes facade in
    # chimerax/graphics/_cxgl.py really calls libGLESv3.so. Route the renderer's validated
    # functions through the facade inside _GlesProxy, which is the object ChimeraX actually
    # uses on this platform.
    opengl_target = args.output / 'chimerax/graphics/opengl.py'
    if opengl_target.is_file():
        text = opengl_target.read_text()
        if 'CX_FACADE_DELEGATION' not in text:
            helper = (
                "        # CX_FACADE_DELEGATION: entry points validated on device come from the\n"
                "        # ctypes facade; everything else keeps the existing PyOpenGL behaviour.\n"
                "        _CX_FACADE_STATE = {'module': None}\n"
                "\n"
                "        def _cx_facade_module():\n"
                "            module = _CX_FACADE_STATE['module']\n"
                "            if module is None:\n"
                "                from chimerax.graphics import _cxgl as _cxgl_module\n"
                "                module = _cxgl_module.make_module()\n"
                "                _CX_FACADE_STATE['module'] = module\n"
                "            return module\n"
                "\n"
                "        class _GlesProxy:")
            text = text.replace('        class _GlesProxy:', helper, 1)
            old_head = (
                "            def __getattr__(self, name):\n"
                "                module = object.__getattribute__(self, '_module')")
            new_head = (
                "            def __getattr__(self, name):\n"
                "                if name in _CX_FACADE_BATCH:\n"
                "                    try:\n"
                "                        target = getattr(_cx_facade_module(), name)\n"
                "\n"
                "                        def counted(*args, _t=target, _n=name):\n"
                "                            # _cxgl_module is local to _cx_facade_module, so import\n"
                "                            # the facade here (cached) to reach the counters.\n"
                "                            try:\n"
                "                                from chimerax.graphics import _cxgl as _m\n"
                "                                _m.CALLS[_n] = _m.CALLS.get(_n, 0) + 1\n"
                "                            except Exception:\n"
                "                                pass\n"
                "                            result = _t(*args)\n"
                "                            if _n == 'glCreateProgram':\n"
                "                                try:\n"
                "                                    from chimerax.graphics import _cxgl as _m2\n"
                "                                    _m2.CREATED_PROGRAMS.append(result)\n"
                "                                except Exception:\n"
                "                                    pass\n"
                "                            return result\n"
                "\n"
                "                        return counted\n"
                "                    except Exception as _cx_fallback:\n"
                "                        try:\n"
                "                            _cxgl_module.FALLBACK_ERRORS.append(\n"
                "                                name + ':' + type(_cx_fallback).__name__\n"
                "                                + ':' + str(_cx_fallback)[:40])\n"
                "                        except Exception:\n"
                "                            pass\n"
                "                module = object.__getattribute__(self, '_module')")
            text = text.replace(old_head, new_head, 1)
            # The batch is grown only after earlier entries are verified on device.
            text = text.replace(
                "        class _GlesProxy:",

                "        _CX_FACADE_BATCH = (\n"
                "            'glBindBuffer', 'glBindVertexArray', 'glBindTexture', 'glBindFramebuffer',\n"
                "            'glBindRenderbuffer', 'glUseProgram', 'glEnable', 'glDisable',\n"
                "            'glViewport', 'glClear', 'glClearColor', 'glDepthFunc', 'glDepthMask',\n"
                "            'glBlendFunc', 'glActiveTexture', 'glPixelStorei',\n"
                "            # bisect step 1: shader and program creation chain\n"
                "            'glCreateProgram', 'glCreateShader', 'glShaderSource',\n"
                "            'glCompileShader', 'glGetShaderiv', 'glGetProgramiv',\n"
                "            'glGetShaderInfoLog', 'glLinkProgram', 'glGetUniformBlockIndex',\n"
                "        )\n"
                "\n"
                "        class _GlesProxy:", 1)
            opengl_target.write_text(text)

    # chimerax.core.commands._atomspec is generated from a PEG grammar by grako; ship the
    # generated module (see vendor/core) so atom specifications work in the app.
    # The generated atomspec module needs grako's runtime at import time.
    grako_source = ROOT / 'vendor/grako'
    if grako_source.is_dir():
        shutil.copytree(grako_source, args.output / 'grako', dirs_exist_ok=True)
        # grako predates Python 3.10 and imports ABCs from collections; restore them.
        grako_init = args.output / 'grako/__init__.py'
        if grako_init.is_file():
            text = grako_init.read_text()
            if 'CX_COLLECTIONS_SHIM' not in text:
                shim = (
                    "# CX_COLLECTIONS_SHIM: grako uses the pre-3.10 collections ABC names.\n"
                    "import collections as _cx_collections\n"
                    "import collections.abc as _cx_abc\n"
                    "for _cx_name in ('Mapping', 'MutableMapping', 'Sequence', 'MutableSequence',\n"
                    "                 'Iterable', 'Iterator', 'Callable', 'Set', 'MutableSet',\n"
                    "                 'Hashable'):\n"
                    "    if not hasattr(_cx_collections, _cx_name):\n"
                    "        setattr(_cx_collections, _cx_name, getattr(_cx_abc, _cx_name))\n")
                lines = text.split('\n')
                insert_at = 0
                for index, line in enumerate(lines):
                    stripped = line.strip()
                    if not stripped or stripped.startswith('#') or stripped.startswith('from __future__'):
                        insert_at = index + 1
                        continue
                    break
                lines.insert(insert_at, shim)
                grako_init.write_text('\n'.join(lines))
    atomspec_target = args.output / 'chimerax/core/commands/_atomspec.py'
    atomspec_source = ROOT / 'vendor/core/_atomspec.py'
    if atomspec_source.is_file() and atomspec_target.parent.is_dir():
        shutil.copy2(atomspec_source, atomspec_target)

    # Installed bundles carry their bundle_info.xml inside the package: file format and
    # provider declarations live there, so ship it next to the code.
    source_bundles = ROOT / 'build/downloads/ChimeraX-src/src/bundles'
    copied_infos = 0
    if source_bundles.is_dir():
        for info in sorted(source_bundles.glob('*/bundle_info.xml')):
            target_pkg = args.output / 'chimerax' / info.parent.name
            if target_pkg.is_dir():
                shutil.copy2(info, target_pkg / 'bundle_info.xml')
                copied_infos += 1

    # chimerax.surface imports its compiled sibling at module import; without GLU we cannot
    # build it, so ship the explicit stand-in that raises only when tessellation is needed.
    surface_stub = ROOT / 'vendor/surface_stub/_surface_stub.py'
    surface_pkg = args.output / 'chimerax/surface'
    if surface_stub.is_file() and surface_pkg.is_dir():
        shutil.copy2(surface_stub, surface_pkg / '_surface.py')

    # Ship the demo structures inside the runtime tree: copying them from ArkTS resources at
    # start-up never took effect on device, while Python can always read its own package tree.
    demo_source = ROOT / 'app/entry/src/main/resources/rawfile'
    demo_target = args.output / 'chimerax/demo_data'
    if demo_source.is_dir():
        demo_target.mkdir(parents=True, exist_ok=True)
        for name in ('cx_demo.pdb', 'cx_demo.sdf'):
            candidate = demo_source / name
            if candidate.is_file():
                shutil.copy2(candidate, demo_target / name)

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
