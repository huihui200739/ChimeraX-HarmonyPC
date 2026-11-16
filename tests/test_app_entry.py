"""Guards for the HarmonyOS application entry tooling."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AppEntryTests(unittest.TestCase):
    def test_app_module_files_exist(self):
        for relative in ('app/build-profile.json5', 'app/entry/build-profile.json5',
                         'app/entry/src/main/module.json5',
                         'app/entry/src/main/ets/pages/Index.ets',
                         'app/entry/src/main/cpp/chimerax_native.cpp',
                         'app/entry/src/main/cpp/CMakeLists.txt'):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_native_module_embeds_the_private_runtime(self):
        source = (ROOT / 'app/entry/src/main/cpp/chimerax_native.cpp').read_text()
        self.assertIn('Py_SetPythonHome', source)
        self.assertIn('Py_InitializeEx', source)
        self.assertIn('PyRun_String', source)
        self.assertIn("lib-dynload", source, 'the extracted extension path must be replaced')

    def test_packaging_puts_extensions_into_native_libs(self):
        source = (ROOT / 'tools/package_app_runtime.py').read_text()
        self.assertIn("lib/python3.11/lib-dynload", source)
        self.assertIn('cx-runtime.zip', source)

    def test_hap_build_uses_ascii_stage(self):
        source = (ROOT / 'tools/build_hap.py').read_text()
        self.assertIn('/tmp', source)
        self.assertIn('assembleHap', source)

    def test_device_check_reads_the_ui(self):
        source = (ROOT / 'tools/device_app_check.py').read_text()
        for node in ('cx-status', 'cx-version', 'cx-math', 'cx-ctypes', 'cx-stdlib'):
            self.assertIn(node, source)


if __name__ == '__main__':
    unittest.main()
