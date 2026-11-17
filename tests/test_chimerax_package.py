"""Guards for the staged ChimeraX Python package and the native extractor."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ChimeraXPackageTests(unittest.TestCase):
    def test_stage_tool_generates_real_version(self):
        source = (ROOT / 'tools/stage_chimerax_python.py').read_text()
        self.assertIn('buildinfo.py.in', source)
        self.assertIn('rev-parse', source)
        self.assertNotIn("version = 'dev'", source)

    def test_packaging_includes_the_package(self):
        source = (ROOT / 'tools/package_app_runtime.py').read_text()
        self.assertIn('chimerax', source)
        self.assertIn('lib/python3.11/', source)

    def test_native_extractor_is_exposed(self):
        native = (ROOT / 'app/entry/src/main/cpp/chimerax_native.cpp').read_text()
        self.assertIn('ExtractZip', native)
        self.assertIn('extractArchive', native)
        self.assertIn('inflateInit2', native)
        declarations = (ROOT / 'app/entry/src/main/cpp/types/libchimerax_native/index.d.ts').read_text()
        self.assertIn('extractArchive', declarations)

    def test_page_refreshes_the_archive_copy(self):
        page = (ROOT / 'app/entry/src/main/ets/pages/Index.ets').read_text()
        self.assertIn('cx-runtime-v4.zip', page)
        self.assertIn('extractArchive', page)
        self.assertIn('cx-chimerax', page)


if __name__ == '__main__':
    unittest.main()
