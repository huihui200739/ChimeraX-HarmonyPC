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

    _CX_DIRECT = True  # marker so probes can tell this facade apart from the proxy

    def __init__(self, constants=None, signatures=None):
        self._cache = {}
        self._constants = constants or {}
        # PyOpenGL's raw module carries the correct ctypes argtypes for every entry point;
        # copying them is what keeps bad pointers from turning into a segfault.
        self._signatures = signatures or {}
        # Adapters for calls whose Python signature differs from the C one.
        self._adapters = {
            'glShaderSource': self._shader_source,
        }
        # PyOpenGL lets callers pass a count and get the generated id back; the C API needs
        # an output array, so these adapters recreate that convenience.
        for generator, creator in (('glGenBuffers', 'glGenBuffers'),
                                   ('glGenTextures', 'glGenTextures'),
                                   ('glGenVertexArrays', 'glGenVertexArrays'),
                                   ('glGenFramebuffers', 'glGenFramebuffers'),
                                   ('glGenRenderbuffers', 'glGenRenderbuffers')):
            self._adapters[generator] = self._make_generator(creator)

    def _make_generator(self, c_name):
        def generate(count=1, *rest):
            raw = getattr(lib, c_name)
            raw.restype = None
            total = 1 if count is None else int(count)
            holder = (ctypes.c_uint * max(1, total))()
            raw(ctypes.c_int(total), holder)
            values = [int(holder[i]) for i in range(max(1, total))]
            if rest:
                # Explicit output array was supplied by the caller.
                target = rest[0]
                for index, value in enumerate(values):
                    target[index] = value
                return None
            return values[0] if total == 1 else values

        return generate

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
        signature = self._signatures.get(name)
        if signature is not None:
            argtypes, restype = signature
            raw.argtypes = argtypes
            raw.restype = restype
        if name in _STRING_RETURNING:
            # ChimeraX compares these results as text, so hand back bytes not an address.
            raw.restype = ctypes.c_char_p
            self._cache[name] = lambda *a, _raw=raw: _raw(*[_to_c(x) for x in a])
            return self._cache[name]
        raw.restype = ctypes.c_void_p if name in _POINTER_RETURNING else ctypes.c_uint

        def call(*args, _raw=raw, _name=name):
            try:
                return _raw(*[_to_c(a) for a in args])
            except Exception as error:
                shapes = [type(a).__name__ for a in args]
                raise RuntimeError("%s(%s): %s" % (_name, ", ".join(shapes),
                                                   type(error).__name__)) from error

        self._cache[name] = call
        return call


def make_module(constants_module=None, signatures_module=None):
    """Build the GL facade. Pass the already-imported PyOpenGL module for enum constants;
    importing it here would happen too early in ChimeraX's own import sequence."""
    gles = constants_module
    if gles is None:
        import OpenGL.GLES3 as gles
    constants = {k: v for k, v in vars(gles).items() if k.startswith('GL_')}
    signatures = {}
    if signatures_module is not None:
        for key, value in vars(signatures_module).items():
            if key.startswith('gl') and hasattr(value, 'argtypes'):
                signatures[key] = (value.argtypes, value.restype)
    return GlesModule(constants, signatures)
