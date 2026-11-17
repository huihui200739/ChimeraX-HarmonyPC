"""Guards for the ChimeraX runtime dependencies and the numpy build attempt."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ChimeraXDependencyTests(unittest.TestCase):
    def test_staging_vendors_sortedcontainers(self):
        source = (ROOT / 'tools/stage_chimerax_python.py').read_text()
        self.assertIn('sortedcontainers', source)
        self.assertIn('zipfile', source)

    def test_numpy_build_pins_the_sdist(self):
        source = (ROOT / 'tools/build_numpy_harmony.py').read_text()
        self.assertIn("VERSION = '1.26.4'", source)
        self.assertIn('2a02aba9ed12e4ac4eb3ea9421c420301a0c6460d9830d74a9df87efa4912010', source)
        self.assertIn('SETUPTOOLS_USE_DISTUTILS', source)

    def test_trigger_probe_is_verified_on_device(self):
        page = (ROOT / 'app/entry/src/main/ets/pages/Index.ets').read_text()
        self.assertIn('chimerax.core.triggerset', page)
        self.assertIn('cx-trigger', page)
        checker = (ROOT / 'tools/device_app_check.py').read_text()
        self.assertIn('cx_app_probe', checker)


if __name__ == '__main__':
    unittest.main()
