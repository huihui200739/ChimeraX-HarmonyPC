"""Offline builder checks; synthetic text fixtures are NOT target runtime tests."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cpython_builder', ROOT / 'tools/build_cpython_harmony.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class EnvironmentTests(unittest.TestCase):
    def test_host_include_and_library_flags_are_removed(self):
        source = {key: 'synthetic-host-value' for key in (
            'CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'LIBRARY_PATH',
            'SDKROOT', 'MACOSX_DEPLOYMENT_TARGET', 'ARCHFLAGS',
            'CFLAGS', 'CPPFLAGS', 'LDFLAGS', 'LD_PRELOAD',
            'DYLD_LIBRARY_PATH', 'LD_LIBRARY_PATH')}
        result = builder.clean_environment(source)
        self.assertTrue(set(source).isdisjoint(result))

    def test_host_python_overrides_are_removed(self):
        result = builder.clean_environment({
            'PYTHONHOME': '/synthetic/home', 'PYTHONPATH': '/synthetic/site',
            '_PYTHON_HOST_PLATFORM': 'synthetic',
            '_PYTHON_SYSCONFIGDATA_NAME': 'synthetic',
            '_PYTHON_PROJECT_BASE': '/synthetic', 'VIRTUAL_ENV': '/synthetic',
            'CONDA_PREFIX': '/synthetic'})
        self.assertNotIn('PYTHONHOME', result)
        self.assertNotIn('PYTHONPATH', result)
        self.assertFalse(any(key.startswith('_PYTHON') for key in result))
        self.assertNotIn('VIRTUAL_ENV', result)
        self.assertNotIn('CONDA_PREFIX', result)
        self.assertEqual(result['PYTHONNOUSERSITE'], '1')
        self.assertEqual(result['PYTHONDONTWRITEBYTECODE'], '1')

    def test_build_parallelism_cannot_leak_in(self):
        result = builder.clean_environment({'MAKEFLAGS': '-j99', 'MFLAGS': '-j99'})
        self.assertNotIn('MAKEFLAGS', result)
        self.assertNotIn('MFLAGS', result)

    def test_pkg_config_and_config_site_are_isolated(self):
        result = builder.clean_environment({'PKG_CONFIG_PATH': '/synthetic/host',
            'PKG_CONFIG_LIBDIR': '/synthetic/lib', 'CONFIG_SITE': '/synthetic/site'})
        self.assertNotIn('PKG_CONFIG_PATH', result)
        self.assertNotIn('PKG_CONFIG_LIBDIR', result)
        self.assertEqual(result['PKG_CONFIG'], '/usr/bin/false')
        self.assertEqual(result['CONFIG_SITE'], '/dev/null')

    def test_unrelated_environment_is_preserved_without_modifying_input(self):
        original = {'PATH': '/synthetic/bin', 'HOME': '/synthetic/home', 'CC': 'host-cc'}
        result = builder.clean_environment(original)
        self.assertEqual(result['PATH'], original['PATH'])
        self.assertEqual(result['HOME'], original['HOME'])
        self.assertEqual(original['CC'], 'host-cc')


class OwnedFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cx-runtime-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_matching_file_is_accepted(self):
        path = self.root / 'fixture.txt'
        path.write_text('ISOLATED SYNTHETIC FILE FIXTURE\n')
        builder.verify_files(self.root, {'fixture.txt': builder.sha256(path)})

    def test_changed_file_is_preserved(self):
        path = self.root / 'fixture.txt'
        path.write_text('ISOLATED SYNTHETIC ORIGINAL\n')
        expected = builder.sha256(path)
        path.write_text('ISOLATED SYNTHETIC EDIT\n')
        with self.assertRaisesRegex(RuntimeError, 'Preserving changed'):
            builder.verify_files(self.root, {'fixture.txt': expected})
        self.assertEqual(path.read_text(), 'ISOLATED SYNTHETIC EDIT\n')

    def test_missing_file_is_reported(self):
        with self.assertRaises(RuntimeError):
            builder.verify_files(self.root, {'absent': '0' * 64})
        self.assertFalse((self.root / 'absent').exists())

    def test_parent_directory_outside_owned_root_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.checked_path(self.root, '../synthetic-outside')

    def test_absolute_path_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.checked_path(self.root, '/synthetic-absolute')

    def test_file_symlink_is_not_silently_followed(self):
        target = self.root / 'synthetic-target'
        target.write_text('ISOLATED SYNTHETIC LINK FIXTURE')
        (self.root / 'synthetic-link').symlink_to(target.name)
        with self.assertRaisesRegex(RuntimeError, 'Symlinks'):
            builder.checked_path(self.root, 'synthetic-link')

    def test_json_report_is_valid_utf8(self):
        report = self.root / '中文目录/report.json'
        builder.write_json(report, {'synthetic': True, 'label': '本地测试'})
        self.assertEqual(json.loads(report.read_text())['label'], '本地测试')
        self.assertEqual(list(report.parent.glob('report.json.*')), [])


class MetadataTests(unittest.TestCase):
    def test_synthetic_elf_text_extracts_only_needed_libraries(self):
        text = '''ISOLATED SYNTHETIC ELF TEXT, NOT A REAL TARGET RESULT
 0x01 (NEEDED) Shared library: [libsynthetic-one.so]
 0x02 (SONAME) Library soname: [not-a-needed-library.so]
 0x03 (NEEDED) Shared library: [libsynthetic-two.so]
'''
        self.assertEqual(builder.needed_libraries(text),
                         ['libsynthetic-one.so', 'libsynthetic-two.so'])

    def test_empty_elf_text_does_not_invent_dependencies(self):
        self.assertEqual(builder.needed_libraries(''), [])

    def test_platform_patch_matches_lock(self):
        lock = json.loads((ROOT / 'runtime-patch.lock.json').read_text())
        patch = ROOT / lock['patch']
        self.assertEqual(builder.sha256(patch), lock['patch_sha256'])
        self.assertEqual(lock['source_commit'], builder.COMMIT)
        self.assertEqual(set(lock['original_files']), set(lock['patched_files']))

    def test_runtime_and_source_pins_agree(self):
        lock = json.loads((ROOT / 'runtime-sources.lock.json').read_text())
        self.assertEqual(lock['git_commit'], builder.COMMIT)
        self.assertEqual(lock['python_version'], builder.VERSION)
        self.assertEqual(lock['target_architecture'], builder.TRIPLE)


class SummaryAndRuntimeTests(unittest.TestCase):
    def test_synthetic_successful_make_still_lists_failed_optional_extensions(self):
        text = """ISOLATED SYNTHETIC BUILD LOG, NOT A REAL COMPILATION
The necessary bits to build these optional modules were not found:
_ssl              _bz2
readline
To find the necessary bits, look in setup.py in detect_modules() for the module's name.

The following modules found by detect_modules() in setup.py have not
been built, they are *disabled* by configure:
_testcapi         _sqlite3

Failed to build these modules:
_ctypes           _socket

running build_scripts
"""
        summary = builder.parse_build_summary(text)
        self.assertEqual(summary['not_found'], ['_bz2', '_ssl', 'readline'])
        self.assertEqual(summary['failed'], ['_ctypes', '_socket'])
        self.assertEqual(summary['disabled'], ['_sqlite3', '_testcapi'])

    def test_empty_log_does_not_invent_failures_or_success(self):
        self.assertEqual(builder.parse_build_summary(''),
                         {'not_found': [], 'failed': [], 'disabled': []})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cx-owned-runtime-unit-')
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        lib = self.runtime / 'lib'
        lib.mkdir()
        fixture = lib / 'libsynthetic.so.1'
        fixture.write_text('ISOLATED SYNTHETIC FILE, NOT AN ELF LIBRARY')
        (lib / 'libsynthetic.so').symlink_to(fixture.name)
        self.manifest = {'owner': builder.OWNER,
            'files': {'lib/libsynthetic.so.1': builder.sha256(fixture)},
            'links': {'lib/libsynthetic.so': fixture.name}}
        builder.write_json(self.runtime / 'runtime-manifest.json', self.manifest)

    def test_owned_file_and_relative_link_are_verified(self):
        builder.validate_runtime_directory(self.runtime, self.manifest)

    def test_changed_runtime_is_preserved(self):
        fixture = self.runtime / 'lib/libsynthetic.so.1'
        fixture.write_text('ISOLATED SYNTHETIC EDIT')
        with self.assertRaises(RuntimeError):
            builder.validate_runtime_directory(self.runtime, self.manifest)
        self.assertEqual(fixture.read_text(), 'ISOLATED SYNTHETIC EDIT')

    def test_additional_runtime_file_is_not_removed(self):
        extra = self.runtime / 'synthetic-user-file'
        extra.write_text('ISOLATED SYNTHETIC USER FILE')
        with self.assertRaisesRegex(RuntimeError, 'unrecorded'):
            builder.validate_runtime_directory(self.runtime, self.manifest)
        self.assertTrue(extra.is_file())

    def test_changed_link_is_preserved(self):
        link = self.runtime / 'lib/libsynthetic.so'
        link.unlink()
        link.symlink_to('synthetic-missing-library')
        with self.assertRaisesRegex(RuntimeError, 'unexpected runtime link'):
            builder.validate_runtime_directory(self.runtime, self.manifest)
        self.assertEqual(link.readlink(), Path('synthetic-missing-library'))

    def test_ownership_marker_is_required(self):
        wrong_owner = dict(self.manifest, owner='synthetic-unrelated-owner')
        with self.assertRaisesRegex(RuntimeError, 'ownership'):
            builder.validate_runtime_directory(self.runtime, wrong_owner)


if __name__ == '__main__':
    unittest.main()
