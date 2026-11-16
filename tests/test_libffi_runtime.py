"""Offline checks with isolated, explicitly synthetic dependency fixtures.

These are NOT target-runtime, callback, application or device tests.
"""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'tools') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tools'))
import build_cpython_harmony as cpython
import build_libffi_harmony as libffi


class DependencyManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cx-synthetic-ffi-unit-')
        self.addCleanup(self.temporary.cleanup)
        self.prefix = Path(self.temporary.name)
        for name in libffi.PREFIX_FILES:
            path = self.prefix / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('ISOLATED SYNTHETIC FILE, NOT COMPILED TARGET CONTENT\n' + name)
        self.manifest = {'owner': libffi.OWNER, 'version': libffi.VERSION,
            'target_triplet': cpython.TRIPLE, 'library_kind': 'static_PIC',
            'synthetic_fixture': True,
            'files': {name: cpython.sha256(self.prefix / name) for name in libffi.PREFIX_FILES}}
        self.save_manifest()

    def save_manifest(self):
        cpython.write_json(self.prefix / 'dependency-manifest.json', self.manifest)

    def test_owned_synthetic_files_match_manifest(self):
        self.assertTrue(libffi.validate_prefix(self.prefix)['synthetic_fixture'])

    def test_changed_file_is_preserved(self):
        path = self.prefix / 'include/ffi.h'
        path.write_text('ISOLATED SYNTHETIC USER EDIT')
        with self.assertRaisesRegex(RuntimeError, 'Preserving changed'):
            libffi.validate_prefix(self.prefix)
        self.assertEqual(path.read_text(), 'ISOLATED SYNTHETIC USER EDIT')

    def test_extra_file_is_preserved(self):
        path = self.prefix / 'user-note.txt'
        path.write_text('ISOLATED SYNTHETIC USER NOTE')
        with self.assertRaisesRegex(RuntimeError, 'unrecorded'):
            libffi.validate_prefix(self.prefix)
        self.assertTrue(path.is_file())

    def test_missing_license_is_not_accepted(self):
        (self.prefix / 'LICENSE-libffi.txt').unlink()
        with self.assertRaises(RuntimeError):
            libffi.validate_prefix(self.prefix)

    def test_unrecorded_license_is_not_accepted(self):
        self.manifest['files'].pop('LICENSE-libffi.txt')
        self.save_manifest()
        with self.assertRaisesRegex(RuntimeError, 'manifest'):
            libffi.validate_prefix(self.prefix)

    def test_unknown_owner_is_not_modified(self):
        self.manifest['owner'] = 'isolated-synthetic-other-owner'
        self.save_manifest()
        with self.assertRaisesRegex(RuntimeError, 'manifest'):
            libffi.validate_prefix(self.prefix)
        self.assertEqual(json.loads((self.prefix / 'dependency-manifest.json').read_text())['owner'],
                         'isolated-synthetic-other-owner')

    def test_shared_archive_is_not_claimed_as_static(self):
        self.manifest['library_kind'] = 'isolated-synthetic-shared-kind'
        self.save_manifest()
        with self.assertRaisesRegex(RuntimeError, 'manifest'):
            libffi.validate_prefix(self.prefix)

    def test_wrong_architecture_is_not_accepted(self):
        self.manifest['target_triplet'] = 'isolated-synthetic-other-target'
        self.save_manifest()
        with self.assertRaisesRegex(RuntimeError, 'manifest'):
            libffi.validate_prefix(self.prefix)

    def test_other_compiler_is_not_accepted(self):
        self.manifest['compiler_sha256'] = '0' * 64
        self.save_manifest()
        with tempfile.TemporaryDirectory(prefix='cx-synthetic-sdk-unit-') as directory:
            sdk = Path(directory)
            compiler = sdk / 'llvm/bin/clang'
            compiler.parent.mkdir(parents=True)
            compiler.write_text('ISOLATED SYNTHETIC COMPILER IDENTITY, NOT EXECUTABLE')
            with self.assertRaisesRegex(RuntimeError, 'compiler'):
                libffi.validate_prefix(self.prefix, sdk=sdk)



class RuntimeProfileTests(unittest.TestCase):
    def test_baseline_path_is_unchanged(self):
        self.assertEqual(cpython.profile_directory('baseline'),
                         'build/cpython-3.11.18/ohos-aarch64')

    def test_new_profile_has_a_separate_directory(self):
        self.assertEqual(cpython.profile_directory('with-libffi'),
                         'build/cpython-3.11.18/ohos-aarch64-with-libffi')
        self.assertNotEqual(cpython.profile_directory('baseline'),
                            cpython.profile_directory('with-libffi'))

    def test_unknown_profile_does_not_select_a_directory(self):
        with self.assertRaises(ValueError):
            cpython.profile_directory('isolated-synthetic-unknown-profile')

    def test_baseline_rejects_dependency_prefix(self):
        with self.assertRaises(ValueError):
            cpython.Builder(Path('/synthetic-sdk'), Path('/synthetic-host-python'), 1, {},
                            libffi_prefix=Path('/synthetic-prefix'))

    def test_builder_records_explicit_profile_without_starting_a_build(self):
        report = {}
        builder = cpython.Builder(Path('/synthetic-sdk'), Path('/synthetic-host-python'),
                                 1, report, profile='with-libffi')
        self.assertEqual(report['runtime_profile'], 'with-libffi')
        self.assertEqual(builder.work, ROOT / cpython.profile_directory('with-libffi'))
        self.assertIsNone(builder.libffi_manifest)

    def test_synthetic_undefined_reference_is_not_a_definition(self):
        text = '''ISOLATED SYNTHETIC READELF TEXT, NOT TARGET CONTENT
  1: 0000000000000000 0 FUNC GLOBAL DEFAULT UND ffi_call
  2: 0000000000001234 8 FUNC GLOBAL DEFAULT 12 ffi_prep_cif
  3: 0000000000002345 8 FUNC GLOBAL DEFAULT 12 ffi_closure_alloc@@SYNTHETIC
'''
        self.assertEqual(cpython.defined_dynamic_symbols(text),
                         {'ffi_prep_cif', 'ffi_closure_alloc'})

    def test_synthetic_local_or_hidden_symbols_are_not_exports(self):
        text = """ISOLATED SYNTHETIC READELF TEXT, NOT TARGET CONTENT
  1: 0000000000001234 8 FUNC LOCAL DEFAULT 12 ffi_call
  2: 0000000000002345 8 FUNC GLOBAL HIDDEN 12 ffi_prep_cif
"""
        self.assertEqual(cpython.defined_dynamic_symbols(text), set())

    def test_synthetic_weak_protected_definition_is_an_export(self):
        text = """ISOLATED SYNTHETIC READELF TEXT, NOT TARGET CONTENT
  1: 0000000000001234 8 FUNC WEAK PROTECTED 12 ffi_call
"""
        self.assertEqual(cpython.defined_dynamic_symbols(text), {'ffi_call'})

    def test_empty_text_does_not_invent_definitions(self):
        self.assertEqual(cpython.defined_dynamic_symbols(''), set())


class PinnedDependencyTests(unittest.TestCase):
    def test_patch_matches_recorded_hash(self):
        lock = json.loads((ROOT / 'libffi-patch.lock.json').read_text())
        self.assertEqual(cpython.sha256(ROOT / lock['patch']), lock['patch_sha256'])
        self.assertEqual(set(lock['original_files']), set(lock['patched_files']))

    def test_source_version_and_target_match_builder(self):
        lock = json.loads((ROOT / 'libffi-sources.lock.json').read_text())
        self.assertEqual(lock['version'], libffi.VERSION)
        self.assertEqual(lock['target_architecture'], cpython.TRIPLE)
        self.assertEqual(lock['git_tag'], 'v' + libffi.VERSION)


if __name__ == '__main__':
    unittest.main()
