"""Regression coverage for misleading hdc installation output."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('device_app_check', ROOT / 'tools/device_app_check.py')
device = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(device)


class DeviceAppCheckTests(unittest.TestCase):
    def test_zero_exit_with_install_error_never_tests_existing_app(self):
        with tempfile.TemporaryDirectory() as directory:
            hap = Path(directory) / 'synthetic.hap'
            hap.write_bytes(b'synthetic HAP')
            report = Path(directory) / 'device.json'
            result = subprocess.CompletedProcess([], 0,
                'msg:error: failed to install bundle. code:9568288', '')
            argv = ['device_app_check.py', '--hap', str(hap), '--report', str(report)]
            with patch('sys.argv', argv), patch.object(device, 'run', return_value=result) as run:
                self.assertEqual(device.main(), 1)
            run.assert_called_once()
            self.assertIn('install', run.call_args.args[0])
            payload = json.loads(report.read_text())
            self.assertEqual(payload['status'], 'app_runtime_incomplete')
            self.assertEqual(payload['result'], {'passed': 0, 'failed': 1})
            self.assertFalse(payload['checks'][0]['passed'])
