"""Replay the renderer's recorded GL call shapes through the ctypes facade.

The shapes come from a real render attempt on device (reports/cx-gl-calls digest): each entry
is "name:count:type/type/...". Feeding synthesised arguments of those types back through the
facade catches conversion gaps without needing the device.
"""
import ctypes
import importlib.util
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

# Trimmed from the device digest: the functions the renderer actually calls, with the argument
# type shapes it passes.
RECORDED = [
    ('glBindBuffer', 23, 'IntConstant/uint32'),
    ('glGenBuffers', 6, 'int'),
    ('glBufferData', 6, 'IntConstant/int/c_void_p/IntConstant'),
    ('glVertexAttribPointer', 4, 'int/int/IntConstant/IntConstant/int/NoneType'),
    ('glEnableVertexAttribArray', 4, 'int'),
    ('glVertexAttribDivisor', 4, 'int/int'),
    ('glGetString', 3, 'IntConstant'),
    ('glBindVertexArray', 3, 'int'),
    ('glUseProgram', 3, 'int'),
    ('glGetIntegerv', 3, 'IntConstant/uint32'),
    ('glUniformBlockBinding', 2, 'int/int/int'),
]


class IntConstant(int):
    """Stand-in for PyOpenGL's constant type, which subclasses int."""


class FakeLib:
    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        def call(*args):
            self.calls += 1
            return 0
        return call


def synthetic(arg_type):
    if arg_type == 'IntConstant':
        return IntConstant(0x8D40)
    if arg_type == 'int':
        return 7
    if arg_type == 'uint32':
        return numpy.zeros(4, dtype=numpy.uint32)
    if arg_type == 'c_void_p':
        return ctypes.c_void_p(None)
    if arg_type == 'NoneType':
        return None
    raise AssertionError('unhandled type %s' % arg_type)


class ReplayTests(unittest.TestCase):
    def test_recorded_call_shapes_survive_the_facade(self):
        facade = cxgl.GlesModule(constants={'GL_FRAMEBUFFER': 0x8D40},
                                 library=FakeLib())
        for name, count, shapes in RECORDED:
            arg_types = shapes.split('/')
            for _ in range(count):
                args = [synthetic(t) for t in arg_types]
                with self.subTest(function=name):
                    facade.__getattr__(name)(*args)

    def test_intconstant_is_treated_as_int(self):
        facade = cxgl.GlesModule(constants={}, library=FakeLib())
        self.assertEqual(int(IntConstant(5)), 5)
        facade.glBindVertexArray(IntConstant(3))
