"""Guards for the linked-extension runtime profile."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LinkedRuntimeTests(unittest.TestCase):
    def test_profile_is_registered(self):
        source = (ROOT / 'tools/build_cpython_harmony.py').read_text()
        self.assertIn("'with-libffi-linked'", source)
        self.assertIn('def profile_directory', source)

    def test_extension_relink_uses_origin_rpath(self):
        source = (ROOT / 'tools/build_cpython_harmony.py').read_text()
        self.assertIn('$$ORIGIN/../../lib', source,
                      'make would expand $ORIGIN; the rpath must survive as $$ORIGIN')
        self.assertIn('-l:libpython3.11.so.1.0', source)

    def test_device_check_can_skip_the_launcher_preload(self):
        source = (ROOT / 'tools/device_runtime_check.py').read_text()
        self.assertIn('--skip-launcher-preload', source)
        self.assertIn('CX_HARMONY_PRELOADED=1', source)

    def test_launcher_preload_is_guarded(self):
        source = (ROOT / 'harmony/bootstrap.c').read_text()
        self.assertIn('CX_HARMONY_PRELOADED', source)
        self.assertIn('LD_PRELOAD', source)


if __name__ == '__main__':
    unittest.main()
