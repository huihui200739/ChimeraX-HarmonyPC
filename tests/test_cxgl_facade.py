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
