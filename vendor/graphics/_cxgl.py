import ctypes
import numpy

lib = ctypes.CDLL('libGLESv3.so', mode=ctypes.RTLD_GLOBAL)

_POINTER_RETURNING = {'glMapBufferRange', 'glMapBuffer'}
_DESKTOP_ONLY = {'glDrawBuffer', 'glReadBuffer', 'glPolygonMode', 'glPointSize', 'glLogicOp',
                 'glGetDoublev', 'glGetBooleanv', 'glPushAttrib', 'glPopAttrib',
                 'glClearDepth', 'glDepthRange', 'glPolygonStipple', 'glDrawPixels',
                 'glRasterPos2f', 'glRasterPos3f', 'glAccum', 'glEvalMesh2', 'glFeedbackBuffer'}
_STRING_RETURNING = {'glGetString', 'glGetStringi', 'glGetShaderInfoLog',
                     'glGetProgramInfoLog'}


def _to_c(arg):
    if isinstance(arg, numpy.ndarray):
        return ctypes.c_void_p(arg.ctypes.data)
    if isinstance(arg, (bytes, bytearray)):
        return ctypes.c_char_p(bytes(arg))
    if isinstance(arg, ctypes._SimpleCData):
        return arg
    if isinstance(arg, bool):
        return ctypes.c_int(int(arg))
    if isinstance(arg, (int, numpy.integer)):
        return ctypes.c_int(int(arg))
    if isinstance(arg, (float, numpy.floating)):
        return ctypes.c_float(float(arg))
    if isinstance(arg, str):
        return ctypes.c_char_p(arg.encode())
    return arg


class GlesModule:
    """Drop-in replacement for PyOpenGL's GL module backed by libGLESv3 directly."""

    def __init__(self, constants=None):
        self._cache = {}
        self._constants = constants or {}
        # Adapters for calls whose Python signature differs from the C one.
        self._adapters = {
            'glShaderSource': self._shader_source,
        }

    # -- special cases -----------------------------------------------------
    def _shader_source(self, shader, source, *rest):
        if isinstance(source, str):
            source = source.encode()
        if isinstance(source, (bytes, bytearray)):
            holder = (ctypes.c_char_p * 1)(bytes(source))
            lib.glShaderSource(_to_c(shader), ctypes.c_int(1), holder, None)
            return None
        if isinstance(source, (list, tuple)):
            items = [s.encode() if isinstance(s, str) else bytes(s) for s in source]
            holder = (ctypes.c_char_p * len(items))(*items)
            lib.glShaderSource(_to_c(shader), ctypes.c_int(len(items)), holder, None)
            return None
        lib.glShaderSource(_to_c(shader), _to_c(source), None, None)
        return None

    # -- generic dispatch --------------------------------------------------
    def __getattr__(self, name):
        if name in self._cache:
            return self._cache[name]
        if name.startswith('GL_'):
            if name in self._constants:
                return self._constants[name]
            raise AttributeError(name)
        if not name.startswith('gl'):
            raise AttributeError(name)
        if name in self._adapters:
            return self._adapters[name]
        # A short, explicit list of desktop-GL calls GLES does not have. Anything else missing
        # must still raise, otherwise a real gap gets swallowed and the app misbehaves.
        if name in _DESKTOP_ONLY:
            def desktop_only(*args, **kwargs):
                return 0
            self._cache[name] = desktop_only
            return desktop_only
        raw = getattr(lib, name)
        if name in _STRING_RETURNING:
            # ChimeraX compares these results as text, so hand back bytes not an address.
            raw.restype = ctypes.c_char_p
            self._cache[name] = lambda *a, _raw=raw: _raw(*[_to_c(x) for x in a])
            return self._cache[name]
        raw.restype = ctypes.c_void_p if name in _POINTER_RETURNING else ctypes.c_uint

        def call(*args, _raw=raw):
            return _raw(*[_to_c(a) for a in args])

        self._cache[name] = call
        return call


def make_module():
    import OpenGL.GLES3 as gles
    constants = {k: v for k, v in vars(gles).items() if k.startswith('GL_')}
    return GlesModule(constants)
