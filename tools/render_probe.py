#!/usr/bin/env python3
# vim: set expandtab shiftwidth=4 softtabstop=4:
"""Render integration probe for the ChimeraX HarmonyOS port.

Runs *on the device*, inside the app's private CPython interpreter, and walks the
render path the port needs: EGL context -> FBO -> ``chimerax.graphics``
``Drawing``/``View`` -> ``glReadPixels`` pixel checks.

It is deliberately independent of the GUI: it never constructs a
``GraphicsWindow`` and only uses the offscreen ``View.image_rgba()`` route, so a
failure here points at the rendering layer and not at the Qt shim.

Usage (device shell, from the app's runtime tree)::

    python3 tools/render_probe.py                 # full probe, JSON to stdout
    python3 tools/render_probe.py --atomic        # also draw a real residue
    python3 tools/render_probe.py --out /data/local/tmp/render-probe.json
    python3 tools/render_probe.py --size 256x256 --keep-going

Exit codes: 0 = all required stages passed, 1 = a required stage failed,
2 = the probe could not even import the graphics stack.
"""

import argparse
import json
import os
import sys
import traceback

REPORT = {
    'probe': 'render_probe',
    'date': '2026-11-18',
    'status': 'started',
    'stages': [],
}


def record(stage, ok, detail=None, **extra):
    entry = {'stage': stage, 'ok': bool(ok)}
    if detail:
        entry['detail'] = detail
    entry.update(extra)
    REPORT['stages'].append(entry)
    print('[%s] %s%s' % ('PASS' if ok else 'FAIL', stage,
                         (': ' + detail) if detail else ''), file=sys.stderr)
    return ok


# --------------------------------------------------------------------------
# stage 0: environment
# --------------------------------------------------------------------------
def stage_environment(args=None):
    info = {
        'python': sys.version.split()[0],
        'platform': sys.platform,
        'machine': getattr(os.uname(), 'machine', None) if hasattr(os, 'uname') else None,
        'PYOPENGL_PLATFORM': os.environ.get('PYOPENGL_PLATFORM'),
        'CHIMERAX_OHOS': os.environ.get('CHIMERAX_OHOS'),
        'CHIMERAX_PIXEL_SCALE': os.environ.get('CHIMERAX_PIXEL_SCALE'),
        'glsl_version_override': os.environ.get('CHIMERAX_OHOS_GLSL_VERSION'),
        'libEGL': [p for p in ('/system/lib64/libEGL.so', 'libEGL.so') if _exists(p)],
        'libGLES': [p for p in ('/system/lib64/libGLESv3.so', '/system/lib64/libGLESv2.so')
                    if _exists(p)],
    }
    try:
        from chimerax.graphics import opengl as cxgl
        info['running_on_ohos'] = cxgl.running_on_ohos()
        info['context_class'] = cxgl.OpenGLContext.__name__
        info['required_opengl_version'] = list(
            getattr(cxgl.OpenGLContext, 'required_opengl_version', (3, 3)))
        info['required_core_profile'] = getattr(
            cxgl.OpenGLContext, 'required_opengl_core_profile', True)
    except Exception as e:
        record('environment', False, 'cannot import chimerax.graphics.opengl: %r' % (e,))
        REPORT['status'] = 'import-failed'
        _finish()
        _emit(None)
        sys.exit(2)
    REPORT['environment'] = info
    ok = info.get('context_class') == 'EGLContext'
    return record('environment', ok,
                  'context class = %s (expect EGLContext on device)' % info.get('context_class'),
                  **info)


def _exists(p):
    try:
        return os.path.exists(p)
    except Exception:
        return False


# --------------------------------------------------------------------------
# stage 1: EGL context
# --------------------------------------------------------------------------
def stage_context(args):
    from chimerax.graphics import opengl as cxgl
    ctx = cxgl.OpenGLContext(None, None)
    REPORT['context'] = {'adopted_existing': not getattr(ctx, '_owns_context', True)}
    if not ctx.make_current():
        return record('context', False, 'make_current() returned False')
    GL = cxgl.GL
    strings = {}
    for name, enum in (('VERSION', 'GL_VERSION'), ('RENDERER', 'GL_RENDERER'),
                       ('VENDOR', 'GL_VENDOR'), ('SHADING_LANGUAGE_VERSION',
                                                 'GL_SHADING_LANGUAGE_VERSION')):
        try:
            v = GL.glGetString(getattr(GL, enum))
            strings[name] = v.decode('utf-8', 'replace') if v else None
        except Exception as e:
            strings[name] = 'unavailable: %r' % (e,)
    strings['adopted_existing_context'] = REPORT['context']['adopted_existing']
    try:
        strings['version_parsed'] = list(cxgl.Render(ctx).opengl_version_number())
    except Exception as e:
        strings['version_parsed'] = 'unparsed: %r' % (e,)
    REPORT['gl'] = strings
    has_version = bool(strings.get('VERSION'))
    return record('context', has_version,
                  'GL_VERSION=%s' % strings.get('VERSION'), **strings)


# --------------------------------------------------------------------------
# stage 2: explicit FBO + clear + readback
# --------------------------------------------------------------------------
def stage_fbo(args):
    from chimerax.graphics import opengl as cxgl
    GL = cxgl.GL
    ctx = cxgl.OpenGLContext(None, None)
    ctx.make_current()
    w, h = args.size
    from chimerax.graphics.opengl import Framebuffer
    fb = Framebuffer('probe', ctx, w, h)
    if not fb.activate():
        fb.delete()
        return record('fbo', False, 'framebuffer %dx%d rejected (max %s)' % (
            w, h, _max_fb_size(GL)))
    try:
        GL.glViewport(0, 0, w, h)
        GL.glDisable(GL.GL_SCISSOR_TEST)
        GL.glClearColor(0.25, 0.5, 0.75, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        GL.glFinish()
        px = GL.glReadPixels(0, 0, 1, 1, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        got = [int(p) for p in bytes(px)]
        want = [64, 128, 191, 255]
        tol = 4
        ok = all(abs(a - b) <= tol for a, b in zip(got[:4], want))
        fb_status = getattr(fb, '_fbo', None)
        fb.delete()
        return record('fbo', ok, 'center pixel %s vs expected %s (tolerance %d)' % (
            got[:4], want, tol), size=[w, h], fbo=fb_status)
    except Exception:
        try:
            fb.delete()
        except Exception:
            pass
        return record('fbo', False, traceback.format_exc(limit=3))


def _max_fb_size(GL):
    try:
        m = GL.glGetIntegerv(GL.GL_MAX_RENDERBUFFER_SIZE)
        return int(m)
    except Exception:
        return None


# --------------------------------------------------------------------------
# stage 3: chimerax.graphics Drawing -> View.image_rgba()
# --------------------------------------------------------------------------
def _probe_triangle():
    """A triangle spanning most of the view, in the z=0 plane, facing +z."""
    from numpy import array, float32, int32, uint8
    vertices = array([[-1.0, -1.0, 0.0],
                      [ 1.0, -1.0, 0.0],
                      [ 0.0,  1.0, 0.0]], float32)
    normals = array([[0.0, 0.0, 1.0]] * 3, float32)
    triangles = array([[0, 1, 2]], int32)
    return vertices, normals, triangles


def _make_drawing():
    from chimerax.graphics import Drawing
    from numpy import array, uint8
    d = Drawing('render-probe')
    v, n, t = _probe_triangle()
    d.set_geometry(v, n, t)
    d.set_colors(array([250, 40, 40, 255], uint8))
    d.display = True
    return d


def stage_drawing(args):
    from chimerax.graphics import opengl as cxgl
    from chimerax.graphics.view import View
    ctx = cxgl.OpenGLContext(None, None)
    ctx.make_current()
    w, h = args.size
    d = _make_drawing()
    view = View(d, window_size=(w, h))
    view.background_color = (0.0, 0.0, 0.0, 1.0)
    view.initialize_rendering(ctx)
    try:
        view.initial_camera_view()
    except Exception as e:
        print('initial_camera_view unavailable: %r' % (e,), file=sys.stderr)
        view.camera.view_all(d.bounds(), window_size=(w, h))
    rgba = view.image_rgba(w, h)
    if rgba is None:
        return record('drawing', False, 'View.image_rgba() returned None')
    REPORT['drawing'] = {'size': list(rgba.shape[:2])}
    cx, cy = w // 2, h // 2
    center = [int(v) for v in rgba[cy, cx][:4]]
    corner = [int(v) for v in rgba[2, 2][:4]]
    lit = sum(1 for row in rgba for p in row if int(p[0]) > 40)
    frac = lit / float(w * h)
    # Triangle covers ~1/2 of the framed area; red channel must dominate.
    ok = center[0] > 60 and center[0] > center[1] and corner[0] < 20 and 0.15 < frac < 0.75
    REPORT['drawing'].update({'center': center, 'corner': corner,
                              'lit_fraction': round(frac, 3)})
    return record('drawing', ok,
                  'center=%s corner=%s lit=%.2f' % (center, corner, frac), **REPORT['drawing'])


# --------------------------------------------------------------------------
# stage 4: real atoms through chimerax.atomic (optional)
# --------------------------------------------------------------------------
def stage_atomic(args):
    try:
        from chimerax.core.session import Session
        from chimerax.atomic import AtomicStructure
        sess = Session('render-probe', minimal=False)
        m = AtomicStructure(sess)
        for i in range(6):
            m.new_atom('C%d' % i, 'C')
        import numpy as np
        coords = np.array([[0, 0, 0], [1.4, 0, 0], [0, 1.4, 0],
                           [1.4, 1.4, 0], [0, 0, 1.4], [1.4, 0, 1.4]], np.float32)
        for a, c in zip(m.atoms, coords):
            a.coord = c
        sess.models.add([m])
        ctx = sess.main_view.render.opengl_context if sess.main_view.render else None
        if ctx is None:
            from chimerax.graphics import opengl as cxgl
            ctx = cxgl.OpenGLContext(None, None)
            sess.main_view.initialize_rendering(ctx)
        ctx.make_current()
        sess.main_view.background_color = (0.0, 0.0, 0.0, 1.0)
        rgba = sess.main_view.image_rgba(*args.size)
        if rgba is None:
            return record('atomic', False, 'image_rgba() returned None for atom scene')
        lit = sum(1 for row in rgba for p in row if int(p[1]) > 40 or int(p[0]) > 40)
        return record('atomic', lit > 0, 'non-black pixels: %d' % lit,
                      atoms=len(m.atoms))
    except Exception:
        return record('atomic', False, traceback.format_exc(limit=4))


# --------------------------------------------------------------------------
# stage 5: shader translation sanity (no GL needed)
# --------------------------------------------------------------------------
def stage_shader_translation(args=None):
    try:
        from chimerax.graphics import opengl as cxgl
        from os.path import dirname, join
        src_dir = dirname(cxgl.__file__)
        results = {}
        for name in ('vertexShader.txt', 'fragmentShader.txt'):
            text = open(join(src_dir, name)).read()
            out = cxgl.translate_shader_to_gles(text) if hasattr(
                cxgl, 'translate_shader_to_gles') else text
            results[name] = {'has_330': '#version 330' in out,
                             'version_line': out.split('\n')[0],
                             'has_precision': 'precision' in out}
        ok = cxgl.running_on_ohos() is False or all(
            (not r['has_330']) and r['has_precision'] for r in results.values())
        return record('shader-translation', ok, json.dumps(results), **results)
    except Exception:
        return record('shader-translation', False, traceback.format_exc(limit=3))


# --------------------------------------------------------------------------
def _finish():
    ok = all(s['ok'] for s in REPORT['stages'] if s['stage'] != 'atomic')
    REPORT['status'] = 'ok' if ok else 'failed'
    REPORT['failed_stages'] = [s['stage'] for s in REPORT['stages'] if not s['ok']]


def _emit(args=None):
    text = json.dumps(REPORT, indent=2, sort_keys=True, default=str)
    print(text)
    out = getattr(args, 'out', None) if args is not None else None
    if out:
        with open(out, 'w') as f:
            f.write(text + '\n')
        print('report written to %s' % out, file=sys.stderr)
    return text


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--size', default='256x256', help='render size, WxH (default 256x256)')
    p.add_argument('--atomic', action='store_true', help='also render real atoms')
    p.add_argument('--out', default=None, help='write the JSON report to this path')
    p.add_argument('--keep-going', action='store_true',
                   help='continue after a failed stage (default: stop at first failure)')
    args = p.parse_args(argv)
    try:
        w, h = [int(x) for x in args.size.lower().split('x')]
    except Exception:
        p.error('--size must look like 256x256')
    args.size = (w, h)

    stages = [stage_environment, stage_context, stage_fbo, stage_drawing,
              stage_shader_translation]
    for fn in stages:
        ok = fn(args)
        if not ok and not args.keep_going:
            break
    if args.atomic:
        stage_atomic(args)

    _finish()
    _emit(args)
    return 0 if REPORT['status'] == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
