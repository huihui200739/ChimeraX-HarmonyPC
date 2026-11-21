import ctypes
import re
import numpy

def _open_gles_library():
    """Open libGLESv3; returns None where the platform has no such library (host tests)."""
    try:
        return ctypes.CDLL('libGLESv3.so', mode=ctypes.RTLD_GLOBAL)
    except OSError:
        return None


lib = _open_gles_library()

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
        # c_int is what keeps the current integration crash-free; switching to c_uint for
        # GLuint parameters is the next experiment but needs per-function argtype checking
        # first, because a few parameters that look like ids are really pointer offsets.
        return ctypes.c_int(int(arg))
    if isinstance(arg, (float, numpy.floating)):
        return ctypes.c_float(float(arg))
    if isinstance(arg, str):
        return ctypes.c_char_p(arg.encode())
    return arg


def _convert_for_type(arg, expected):
    """Convert a Python/numpy argument to what the declared ctypes type expects."""
    if expected is None:
        return _to_c(arg)
    if isinstance(arg, numpy.ndarray):
        try:
            return arg.ctypes.data_as(expected)
        except TypeError:
            return ctypes.cast(arg.ctypes.data, expected)
    if expected in (ctypes.c_uint, ctypes.c_int, ctypes.c_uint64, ctypes.c_int64):
        return int(arg)
    if expected in (ctypes.c_float, ctypes.c_double):
        return float(arg)
    if expected is ctypes.c_void_p:
        if arg is None:
            return None
        if isinstance(arg, (int, numpy.integer)):
            return ctypes.c_void_p(int(arg))
        if isinstance(arg, (str, bytes, bytearray)):
            return ctypes.c_char_p(bytes(arg) if not isinstance(arg, bytes) else arg)
        return _to_c(arg)
    if arg is None:
        return None
    return _to_c(arg)


class GlesModule:
    """Drop-in replacement for PyOpenGL's GL module backed by libGLESv3 directly."""

    _CX_DIRECT = True  # marker so probes can tell this facade apart from the proxy

    def __init__(self, constants=None, signatures=None, library=None):
        # A private handle: setting argtypes on a shared CDLL attribute would mutate the
        # signatures every other caller sees.
        self._lib = library if library is not None else _open_gles_library()
        self._cache = {}
        self._constants = constants or {}
        # PyOpenGL's raw module carries the correct ctypes argtypes for every entry point;
        # copying them is what keeps bad pointers from turning into a segfault.
        self._signatures = signatures or {}
        self._signatures.update(_EXTRA_SIGNATURES)
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

    def _make_object_status_getter(self, c_name):
        """PyOpenGL returns the status directly: glGetShaderiv(shader, pname) -> int."""
        raw = getattr(self._lib, c_name)
        raw.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
        raw.restype = None

        def getter(obj, pname, out=None):
            holder = ctypes.c_int(0)
            raw(int(obj), int(pname), ctypes.byref(holder))
            value = holder.value
            if out is not None:
                try:
                    out.value = value
                except Exception:
                    try:
                        out[0] = value
                    except Exception:
                        pass
                return None
            return value

        return getter

    def _make_single_value_getter(self, c_name):
        c_type, count = _SINGLE_VALUE_GETTERS[c_name]
        raw = getattr(self._lib, c_name)
        try:
            raw.restype = None
        except AttributeError:
            pass

        def getter(pname, out=None):
            holder = (c_type * count)()
            raw(ctypes.c_uint(int(pname)), holder)
            if out is not None:
                for index in range(count):
                    out[index] = holder[index]
                return None
            return holder[0]

        return getter

    def _make_deleter(self, c_name):
        raw = getattr(self._lib, c_name)
        try:
            raw.restype = None
        except AttributeError:
            pass

        def delete(*args):
            if len(args) == 1 and isinstance(args[0], (int, numpy.integer)):
                holder = (ctypes.c_uint * 1)(int(args[0]))
                raw(ctypes.c_int(1), holder)
                return None
            if len(args) == 2:
                # A count plus a sequence: hand ctypes an array, not a data pointer.
                count, values = args
                holder = (ctypes.c_uint * len(values))(*[int(v) for v in values])
                return raw(ctypes.c_int(int(count)), holder)
            return raw(*[_to_c(a) for a in args])

        return delete

    def _make_sequence_wrapper(self, c_name):
        raw = getattr(self._lib, c_name)
        try:
            raw.restype = None
        except AttributeError:
            pass

        def call(*args):
            converted = []
            for value in args:
                if isinstance(value, (list, tuple)):
                    converted.append((ctypes.c_float * len(value))(*value))
                elif isinstance(value, (int, numpy.integer)):
                    converted.append(ctypes.c_int(int(value)))
                else:
                    converted.append(_to_c(value))
            return raw(*converted)

        return call

    def _make_offset_wrapper(self, c_name):
        raw = getattr(self._lib, c_name)
        try:
            raw.restype = None
        except AttributeError:
            pass

        def call(*args):
            converted = list(args)
            # The last parameter is a byte offset into the bound buffer; ctypes wants a pointer.
            if converted and isinstance(converted[-1], (int, numpy.integer)):
                converted[-1] = ctypes.c_void_p(int(converted[-1]))
            elif converted and converted[-1] is None:
                converted[-1] = None
            return raw(*[_to_c(v) for v in converted])

        return call

    def _make_generator(self, c_name):
        def generate(count=1, *rest):
            raw = getattr(self._lib, c_name)
            try:
                raw.restype = None
            except AttributeError:
                pass
            total = 1 if count is None else int(getattr(count, "value", count))
            holder = (ctypes.c_uint * max(1, total))()
            try:
                raw.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
            except AttributeError:
                pass
            raw(int(total), holder)
            values = [int(getattr(holder[i], 'value', holder[i]))
                      for i in range(max(1, total))]
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
        library = self._lib if getattr(self, "_lib", None) is not None else lib
        if isinstance(source, str):
            source = source.encode()
        if isinstance(source, (bytes, bytearray)):
            holder = (ctypes.c_char_p * 1)(bytes(source))
            library.glShaderSource(_to_c(shader), ctypes.c_int(1), holder, None)
            return None
        if isinstance(source, (list, tuple)):
            items = [s.encode() if isinstance(s, str) else bytes(s) for s in source]
            holder = (ctypes.c_char_p * len(items))(*items)
            library.glShaderSource(_to_c(shader), ctypes.c_int(len(items)), holder, None)
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
        if name in _OBJECT_STATUS_GETTERS:
            getter = self._make_object_status_getter(name)
            self._cache[name] = getter
            return getter
        if name in _SINGLE_VALUE_GETTERS:
            getter = self._make_single_value_getter(name)
            self._cache[name] = getter
            return getter
        if name in _SEQUENCE_ARG_FUNCS:
            wrapper = self._make_sequence_wrapper(name)
            self._cache[name] = wrapper
            return wrapper
        if name in _OFFSET_FUNCS:
            wrapper = self._make_offset_wrapper(name)
            self._cache[name] = wrapper
            return wrapper
        if name in _DELETE_FAMILY:
            deleter = self._make_deleter(name)
            self._cache[name] = deleter
            return deleter
        # A short, explicit list of desktop-GL calls GLES does not have. Anything else missing
        # must still raise, otherwise a real gap gets swallowed and the app misbehaves.
        if name in _DESKTOP_ONLY:
            def desktop_only(*args, **kwargs):
                return 0
            self._cache[name] = desktop_only
            return desktop_only
        signature = self._signatures.get(name)
        if signature is None and _POINTER_ARG_PATTERN.match(name):
            # Falling back to the original PyOpenGL entry point is far safer than handing an
            # integer to a parameter that expects an address.
            raise AttributeError(name)
        raw = getattr(self._lib, name)
        if signature is not None:
            argtypes, restype = signature
            try:
                raw.argtypes = argtypes
                raw.restype = restype
            except AttributeError:
                pass
        if name in _STRING_RETURNING:
            # ChimeraX compares these results as text, so hand back bytes not an address.
            try:
                raw.restype = ctypes.c_char_p
            except AttributeError:
                pass
            self._cache[name] = lambda *a, _raw=raw: _raw(*[_to_c(x) for x in a])
            return self._cache[name]
        try:
            raw.restype = ctypes.c_void_p if name in _POINTER_RETURNING else ctypes.c_uint
        except AttributeError:
            pass

        def call(*args, _raw=raw, _name=name):
            try:
                return _raw(*[_to_c(a) for a in args])
            except Exception as error:
                shapes = [type(a).__name__ for a in args]
                raise RuntimeError("%s(%s): %s" % (_name, ", ".join(shapes),
                                                   type(error).__name__)) from error

        self._cache[name] = call
        return call


# PyOpenGL conveniences that ChimeraX relies on: the renderer calls e.g.
# GL.glGetIntegerv(pname) and expects a value back, while GLES needs an output buffer.
_OBJECT_STATUS_GETTERS = {'glGetShaderiv', 'glGetProgramiv'}
_SINGLE_VALUE_GETTERS = {
    'glGetIntegerv': (ctypes.c_int, 1),
    'glGetFloatv': (ctypes.c_float, 1),
    'glGetBooleanv': (ctypes.c_ubyte, 1),
}
# Functions whose GLuint parameters must receive an unsigned value; passing c_int makes
# ctypes reject the call, which is what stopped the renderer at glBindVertexArray.
_UNSIGNED_FIRST_ARG = {
    'glBindVertexArray', 'glBindBuffer', 'glBindTexture', 'glBindFramebuffer',
    'glBindRenderbuffer', 'glUseProgram', 'glDeleteProgram', 'glDeleteShader',
    'glEnableVertexAttribArray', 'glDisableVertexAttribArray', 'glValidateProgram',
    'glLinkProgram', 'glCompileShader', 'glAttachShader', 'glDetachShader',
}
# Functions that take a Python sequence and a count in PyOpenGL but a raw pointer in GLES.
_SEQUENCE_ARG_FUNCS = {'glUniform1fv', 'glUniform2fv', 'glUniform3fv', 'glUniform4fv',
                       'glUniform1iv', 'glUniform2iv', 'glUniform3iv', 'glUniform4iv',
                       'glVertexAttrib1fv', 'glVertexAttrib2fv', 'glVertexAttrib3fv',
                       'glVertexAttrib4fv'}
# "offset" style parameters: an integer is a byte offset, not an address.
_OFFSET_FUNCS = {'glVertexAttribPointer': -1, 'glDrawElements': -1,
                 'glDrawElementsInstanced': -1}
# Signatures for calls the generated table misses. Without argtypes ctypes passes a Python int
# as a 32-bit value, so an output parameter becomes address 0x1 and the process segfaults.
_EXTRA_SIGNATURES = {
    'glGetShaderiv': ([ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)], None),
    'glGetShaderSource': ([ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_int),
                           ctypes.c_char_p], None),
}
# Calls that take output pointers; when no signature is known they must not be called blindly.
_POINTER_ARG_PATTERN = re.compile(r'^glGet[A-Z][A-Za-z0-9]*(iv|fv|bv|InfoLog|Source|Binary)$')

_DELETE_FAMILY = ('glDeleteBuffers', 'glDeleteTextures', 'glDeleteFramebuffers',
                  'glDeleteRenderbuffers', 'glDeleteVertexArrays', 'glDeleteProgram',
                  'glDeleteShader')


# Entry points actually exercised, counted at the facade boundary.
CALLS = {}

# Problems the renderer hit while delegating to the facade; probes read this to see why a
# call fell back to PyOpenGL.
FALLBACK_ERRORS = []

# Programs created through the facade; probes read this to inspect link status.
CREATED_PROGRAMS = []


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
