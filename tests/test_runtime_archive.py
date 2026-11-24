"""Isolated archive fixtures only. No real interpreter, app, or device is run."""
from __future__ import annotations
import gzip
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
bspec = importlib.util.spec_from_file_location('archive_builder_fixture', ROOT / 'tools/build_cpython_harmony.py')
builder = importlib.util.module_from_spec(bspec)
bspec.loader.exec_module(builder)
pspec = importlib.util.spec_from_file_location('runtime_archive', ROOT / 'tools/package_generic_runtime.py')
packager = importlib.util.module_from_spec(pspec)
with patch.dict(sys.modules, {'build_cpython_harmony': builder}):
    pspec.loader.exec_module(packager)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cx-archive-unit-')
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / 'synthetic.tar.gz'
        self.payload = b'ISOLATED SYNTHETIC ARCHIVE FIXTURE. NOT A RUNTIME.\n'
        self.metadata = b'{"scope":"isolated_synthetic_archive_fixture"}\n'
        self.manifest = {'files': {'fixture.txt': hashlib.sha256(self.payload).hexdigest()},
                         'links': {'fixture-link': 'fixture.txt'}}

    def write_fixture(self, *, payload=None, omit_file=False, link='fixture.txt'):
        with self.archive.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode='w') as bundle:
                for name, data in [('runtime-manifest.json', self.metadata),
                                   *([] if omit_file else [('fixture.txt', self.payload if payload is None else payload)])]:
                    bundle.addfile(packager.tar_info(name, mode=0o644, size=len(data)), io.BytesIO(data))
                bundle.addfile(packager.tar_info('fixture-link', mode=0o777,
                                                 kind=tarfile.SYMTYPE, link=link))

    def verify(self):
        packager.verify_archive(self.archive, self.manifest, hashlib.sha256(self.metadata).hexdigest())

    def test_normalized_metadata_does_not_reveal_host_account(self):
        info = packager.tar_info('fixture.txt', mode=0o644, size=17)
        self.assertEqual((info.uid, info.gid, info.mtime), (0, 0, 0))
        self.assertEqual((info.uname, info.gname), ('', ''))
        self.assertEqual(info.name, 'cx-generic-runtime/fixture.txt')
        self.assertEqual(info.size, 17)

    def test_synthetic_payload_and_relative_link_are_verified(self):
        self.write_fixture()
        self.verify()

    def test_changed_payload_is_not_reported_as_verified(self):
        self.write_fixture(payload=b'ISOLATED SYNTHETIC DIFFERENT CONTENT')
        with self.assertRaisesRegex(RuntimeError, 'file differs'):
            self.verify()

    def test_missing_payload_is_not_reported_as_verified(self):
        self.write_fixture(omit_file=True)
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            self.verify()

    def test_different_link_is_not_reported_as_verified(self):
        self.write_fixture(link='synthetic-other-file')
        with self.assertRaisesRegex(RuntimeError, 'link differs'):
            self.verify()

    def test_normalized_fixture_produces_repeatable_bytes(self):
        self.write_fixture()
        first = self.archive.read_bytes()
        self.write_fixture()
        self.assertEqual(first, self.archive.read_bytes())


if __name__ == '__main__':
    unittest.main()
