"""Unit tests for the ctypes GL facade, using a fake library so no device is needed."""
import ctypes
import importlib.util
from pathlib import Path

import numpy

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('cxgl', ROOT / 'vendor/graphics/_cxgl.py')
cxgl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cxgl)


def plain(value):
    return value.value if hasattr(value, 'value') else value


class FakeLib:
    def __init__(self):
        self.calls = []
        self.buffers = {}

    def _record(self, name, *args):
        self.calls.append((name, tuple(plain(a) for a in args)))

    def glCreateProgram(self):
        self._record('glCreateProgram')
        return 7

    def glGetIntegerv(self, pname, out):
        self._record('glGetIntegerv', pname)
        out[0] = 42

    def glGenBuffers(self, count, out):
        self._record('glGenBuffers', count)
        for index in range(count):
            out[index] = 100 + index

    def glDeleteBuffers(self, count, out):
        self._record('glDeleteBuffers', count, out[0])

    def glShaderSource(self, shader, count, strings, lengths):
        self._record('glShaderSource', shader, count, strings[0])

    def glBindVertexArray(self, array):
        self._record('glBindVertexArray', array)

    def glUniform3fv(self, location, count, values):
        self._record('glUniform3fv', location, count, list(values)[:3])

    def glVertexAttribPointer(self, index, size, type_, normalized, stride, offset):
        self._record('glVertexAttribPointer', index, size, type_, normalized, stride,
                     offset if offset is None else 'ptr')


def make_facade():
    fake = FakeLib()
    return cxgl.GlesModule(constants={'GL_TRIANGLES': 4}, library=fake), fake


def test_create_program_returns_id():
    gl, _ = make_facade()
    assert gl.glCreateProgram() == 7


def test_generator_returns_single_id():
    gl, _ = make_facade()
    assert gl.glGenBuffers(1) == 100
    assert gl.glGenBuffers(3) == [100, 101, 102]


def test_delete_accepts_bare_int():
    gl, fake = make_facade()
    gl.glDeleteBuffers(1, numpy.array([5], dtype=numpy.uint32))
    assert ('glDeleteBuffers', (1, 5)) in fake.calls


def test_single_value_getter():
    gl, _ = make_facade()
    assert gl.glGetIntegerv(0x0D33) == 42


def test_shader_source_accepts_text():
    gl, fake = make_facade()
    gl.glShaderSource(3, '#version 300 es')
    assert ('glShaderSource', (3, 1, b'#version 300 es')) in fake.calls


def test_bind_vertex_array_accepts_int():
    gl, fake = make_facade()
    gl.glBindVertexArray(9)
    assert ('glBindVertexArray', (9,)) in fake.calls


def test_constants_are_exposed():
    gl, _ = make_facade()
    assert gl.GL_TRIANGLES == 4


USED_FUNCTIONS = Path(__file__).resolve().parents[1] / 'reports/cxgl-used-functions.txt'


def _facade_coverage():
    """Every GL entry point the renderer calls must be reachable through the facade."""
    import subprocess

    root = Path(__file__).resolve().parents[1]
    generated = root / 'vendor/graphics/_cxgl_sigs.py'
    spec = importlib.util.spec_from_file_location('cxgl_sigs', generated)
    sigs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sigs)
    package = root / 'build/chimerax-python/chimerax'
    import re
    names = sorted({name for path in package.rglob('*.py')
                    for name in re.findall(r'GL\.(gl[A-Za-z0-9_]+)',
                                           path.read_text(errors='replace'))})
    return names, sigs


def test_every_gl_call_is_reachable():
    names, sigs = _facade_coverage()
    adapters = set(cxgl._SINGLE_VALUE_GETTERS) | set(cxgl._DELETE_FAMILY)
    adapters |= {'glShaderSource', 'glGenBuffers', 'glGenTextures', 'glGenVertexArrays',
                 'glGenFramebuffers', 'glGenRenderbuffers'}
    unreachable = []
    for name in names:
        if name in sigs.SIGNATURES or name in sigs.ALIASES or name in adapters:
            continue
        if name in cxgl._DESKTOP_ONLY:
            continue
        unreachable.append(name)
    assert not unreachable, 'no facade path for: %s' % unreachable


def test_aliases_point_at_real_entry_points():
    _, sigs = _facade_coverage()
    for name, target in sigs.ALIASES.items():
        if target is None:
            continue  # documented as a no-op on GLES
        assert target in sigs.SIGNATURES, '%s -> missing %s' % (name, target)


def test_uniform_vector_accepts_list():
    gl, fake = make_facade()
    gl.glUniform3fv(5, 1, [0.1, 0.2, 0.3])
    assert fake.calls[-1][0] == 'glUniform3fv'
    assert fake.calls[-1][1][:2] == (5, 1)


def test_vertex_attrib_pointer_offset_becomes_pointer():
    gl, fake = make_facade()
    gl.glVertexAttribPointer(0, 3, 0x1406, 0, 12, 8)
    assert fake.calls[-1] == ('glVertexAttribPointer', (0, 3, 0x1406, 0, 12, 'ptr'))
