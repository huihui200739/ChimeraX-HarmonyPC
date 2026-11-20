"""Unit tests for the ctypes GL facade, using a fake library so no device is needed.

The facade replaces PyOpenGL on HarmonyOS: PyOpenGL's wrappers return zero for every entry
point there, while direct ctypes calls work. These tests pin the Python-side conveniences the
ChimeraX renderer relies on.
"""
import ctypes
import importlib.util
import re
import unittest
from pathlib import Path

import numpy

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cxgl = load(ROOT / 'vendor/graphics/_cxgl.py', 'cxgl')
sigs = load(ROOT / 'vendor/graphics/_cxgl_sigs.py', 'cxgl_sigs')


def plain(value):
    return value.value if hasattr(value, 'value') else value


class FakeLib:
    """Records calls; enough surface for the conveniences under test."""

    def __init__(self):
        self.calls = []

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


class FacadeTests(unittest.TestCase):
    def test_create_program_returns_id(self):
        gl, _ = make_facade()
        self.assertEqual(gl.glCreateProgram(), 7)

    def test_generator_returns_single_id(self):
        gl, _ = make_facade()
        self.assertEqual(gl.glGenBuffers(1), 100)
        self.assertEqual(gl.glGenBuffers(3), [100, 101, 102])

    def test_delete_accepts_sequence(self):
        gl, fake = make_facade()
        gl.glDeleteBuffers(1, numpy.array([5], dtype=numpy.uint32))
        self.assertIn(('glDeleteBuffers', (1, 5)), fake.calls)

    def test_single_value_getter(self):
        gl, _ = make_facade()
        self.assertEqual(gl.glGetIntegerv(0x0D33), 42)

    def test_shader_source_accepts_text(self):
        gl, fake = make_facade()
        gl.glShaderSource(3, '#version 300 es')
        self.assertIn(('glShaderSource', (3, 1, b'#version 300 es')), fake.calls)

    def test_bind_vertex_array_accepts_int(self):
        gl, fake = make_facade()
        gl.glBindVertexArray(9)
        self.assertIn(('glBindVertexArray', (9,)), fake.calls)

    def test_constants_are_exposed(self):
        gl, _ = make_facade()
        self.assertEqual(gl.GL_TRIANGLES, 4)

    def test_uniform_vector_accepts_list(self):
        gl, fake = make_facade()
        gl.glUniform3fv(5, 1, [0.1, 0.2, 0.3])
        name, args = fake.calls[-1]
        self.assertEqual(name, 'glUniform3fv')
        self.assertEqual(args[:2], (5, 1))

    def test_vertex_attrib_pointer_offset_becomes_pointer(self):
        gl, fake = make_facade()
        gl.glVertexAttribPointer(0, 3, 0x1406, 0, 12, 8)
        name, args = fake.calls[-1]
        self.assertEqual(name, 'glVertexAttribPointer')
        self.assertEqual(args, (0, 3, 0x1406, 0, 12, 'ptr'))


class ReachabilityTests(unittest.TestCase):
    """Every GL entry point the renderer calls must be reachable through the facade."""

    def _used_functions(self):
        package = ROOT / 'build/chimerax-python/chimerax'
        if not package.is_dir():
            self.skipTest('staged ChimeraX tree is absent')
        names = set()
        for path in package.rglob('*.py'):
            names.update(re.findall(r'GL\.(gl[A-Za-z0-9_]+)',
                                    path.read_text(errors='replace')))
        return sorted(names)

    def test_every_gl_call_is_reachable(self):
        adapters = set(cxgl._SINGLE_VALUE_GETTERS) | set(cxgl._DELETE_FAMILY)
        adapters |= set(cxgl._SEQUENCE_ARG_FUNCS) | set(cxgl._OFFSET_FUNCS)
        adapters |= {'glShaderSource', 'glGenBuffers', 'glGenTextures', 'glGenVertexArrays',
                     'glGenFramebuffers', 'glGenRenderbuffers'}
        unreachable = [name for name in self._used_functions()
                       if name not in sigs.SIGNATURES and name not in sigs.ALIASES
                       and name not in adapters and name not in cxgl._DESKTOP_ONLY]
        self.assertEqual(unreachable, [], 'no facade path for: %s' % unreachable)

    def test_aliases_point_at_real_entry_points(self):
        for name, target in sigs.ALIASES.items():
            if target is None:
                continue  # documented as a no-op on GLES
            self.assertIn(target, sigs.SIGNATURES, '%s -> missing %s' % (name, target))


if __name__ == '__main__':
    unittest.main()
