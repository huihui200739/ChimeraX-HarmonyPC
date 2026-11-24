"""Isolated synthetic unit-test inputs. These are NOT collected device records."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("inventory", ROOT / "tools/inspect_environment.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def synthetic_result(value="", returncode=0):
    return {"stdout": value, "stderr": "", "returncode": returncode, "error": None}


class InventoryTests(unittest.TestCase):
    def test_parse_empty(self):
        self.assertEqual(inventory.parse_targets("[Empty]\n"), [])
        self.assertEqual(inventory.parse_targets("<Empty>\n"), [])

    def test_parse_banners_and_duplicates(self):
        text = "[Info] daemon started\nsynthetic-target\nsynthetic-target\n"
        self.assertEqual(inventory.parse_targets(text), ["synthetic-target"])

    def test_auto_refuses_ambiguity(self):
        for targets in ([], ["synthetic-one", "synthetic-two"]):
            with self.assertRaises(ValueError):
                inventory.select_target(targets, "auto")

    def test_explicit_target(self):
        self.assertEqual(inventory.select_target(["synthetic-one", "synthetic-two"], "synthetic-two"),
                         "synthetic-two")
        with self.assertRaises(ValueError):
            inventory.select_target(["synthetic-one"], "unknown")

    def test_auto_selects_only_target(self):
        self.assertEqual(inventory.select_target(["synthetic-one"], "auto"), "synthetic-one")

    def test_error_not_valid_value(self):
        self.assertIsNone(inventory.usable_value(synthetic_result("permission denied")))
        self.assertIsNone(inventory.usable_value(synthetic_result("", 0)))
        self.assertIsNone(inventory.usable_value(synthetic_result("/bin/python3", 1)))

    def test_linux_not_assumed_harmony(self):
        result = inventory.assess_device({"kernel": synthetic_result("Linux")})
        self.assertFalse(result["harmony_family_identified"])
        self.assertFalse(result["port_validated"])

    def test_harmony_not_assumed_linux_binary_compatible(self):
        result = inventory.assess_device({"kernel": synthetic_result("Linux"),
                    "system_version": synthetic_result("OpenHarmony-SYNTHETIC"),
                    "device_type": synthetic_result("2in1")})
        self.assertTrue(result["harmony_family_identified"])
        self.assertFalse(result["physical_pc_confirmed"])
        self.assertEqual(result["native_binary_compatibility"], "not_tested")
        self.assertEqual(result["python_runtime"], "not_observed_on_path")

    def test_python_path_not_validated_runtime(self):
        result = inventory.assess_device({"python_on_path": synthetic_result("/synthetic/python3")})
        self.assertEqual(result["python_runtime"], "found_on_path_not_validated")
        self.assertFalse(result["upstream_app_launched"])

    def test_subprocess_timeout(self):
        with patch.object(inventory.subprocess, "run", side_effect=subprocess.TimeoutExpired(["fake"], 1)):
            self.assertEqual(inventory.run_command(["fake"], 1)["error"], "timeout")

    def test_missing_executable(self):
        with patch.object(inventory.subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(inventory.run_command(["fake"])["error"], "not_found")

    def test_unavailable_device_does_not_issue_shell_commands(self):
        with patch.object(inventory, "run_command", return_value=synthetic_result("[Empty]")) as runner:
            result = inventory.collect_device("synthetic-hdc", "auto", 1)
            self.assertEqual(result["status"], "selection_required")
            self.assertEqual(runner.call_count, 1)

    def test_collection_is_only_fixed_read_queries(self):
        def runner(argv, timeout):
            if argv[1:] == ["list", "targets"]:
                return synthetic_result("synthetic-one")
            return synthetic_result({
                "uname -s": "Linux", "uname -m": "aarch64",
                "param get const.product.devicetype": "2in1",
                "param get const.ohos.apiversion": "SYNTHETIC",
                "param get const.ohos.fullname": "OpenHarmony-SYNTHETIC",
            }.get(argv[-1], ""))
        with patch.object(inventory, "run_command", side_effect=runner) as mocked:
            report = inventory.collect_device("synthetic-hdc", "auto", 1)
            self.assertEqual(report["status"], "collected")
            self.assertFalse(report["assessment"]["port_validated"])
            for call in mocked.call_args_list[1:]:
                self.assertEqual(call.args[0][1:4], ["-t", "synthetic-one", "shell"])
                self.assertIn(call.args[0][-1], inventory.DEVICE_COMMANDS.values())

    def test_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "report.json"
            inventory.write_json(path, {"synthetic": True, "label": "中文"})
            self.assertEqual(json.loads(path.read_text())["label"], "中文")
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_host_only_does_not_contact_device(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(inventory, "collect_device") as collect:
            path = Path(temporary) / "host.json"
            self.assertEqual(inventory.main(["--output", str(path)]), 0)
            collect.assert_not_called()
            self.assertFalse(json.loads(path.read_text())["port_validated"])

    def test_qt_missing_runtime_writes_blocked_report(self):
        spec = importlib.util.spec_from_file_location("qt_probe", ROOT / "tools/qt_window_probe.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "qt.json"
            with patch.object(module.importlib, "import_module", side_effect=ImportError("synthetic missing binding")):
                self.assertEqual(module.main(["--report", str(path)]), 2)
            report = json.loads(path.read_text())
            self.assertEqual(report["status"], "blocked_missing_runtime")
            self.assertFalse(report["port_validated"])


class NativeRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("native_runner", ROOT / "tools/run_native_probe.py")
        cls.native = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"inspect_environment": inventory}):
            spec.loader.exec_module(cls.native)

    def run_synthetic(self, results, device=None):
        if device is None:
            device = {"status": "collected", "target": "synthetic-one", "assessment": {
                "harmony_family_identified": True, "observed": {"architecture": "aarch64"}}}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            with patch.object(self.native, "collect_device", return_value=device), \
                 patch.object(self.native, "run_command", side_effect=results) as command:
                status = self.native.main(["--sdk", temporary, "--hdc", "synthetic-hdc",
                                           "--device", "auto", "--output", str(path)])
                return status, json.loads(path.read_text()), command.call_args_list

    def test_success_requires_parseable_probe_and_verified_cleanup(self):
        payload = json.dumps({"purpose": "generic_native_loader_probe"})
        status, report, calls = self.run_synthetic([
            synthetic_result(), synthetic_result(), synthetic_result(payload), synthetic_result("CX_CLEANUP_OK")])
        self.assertEqual(status, 0)
        self.assertEqual(report["cleanup"], "removed")
        self.assertFalse(report["port_validated"])
        self.assertIn("rm -f", calls[-1].args[0][-1])

    def test_invalid_json_still_cleans(self):
        status, report, _ = self.run_synthetic([
            synthetic_result(), synthetic_result(), synthetic_result("synthetic not JSON"), synthetic_result("CX_CLEANUP_OK")])
        self.assertEqual(status, 2)
        self.assertEqual(report["status"], "blocked_invalid_probe_output")
        self.assertEqual(report["cleanup"], "removed")

    def test_exit_zero_without_cleanup_confirmation_is_not_success(self):
        payload = json.dumps({"purpose": "generic_native_loader_probe"})
        status, report, _ = self.run_synthetic([
            synthetic_result(), synthetic_result(), synthetic_result(payload), synthetic_result("")])
        self.assertEqual(status, 2)
        self.assertEqual(report["cleanup"], "failed")

    def test_compile_failure_does_not_upload(self):
        status, report, calls = self.run_synthetic([synthetic_result("synthetic error", 1)])
        self.assertEqual(status, 2)
        self.assertEqual(report["status"], "blocked_compile")
        self.assertEqual(len(calls), 1)

    def test_unknown_target_does_not_compile_or_upload(self):
        device = {"status": "collected", "target": "synthetic-one", "assessment": {
            "harmony_family_identified": False, "observed": {"architecture": "aarch64"}}}
        status, report, calls = self.run_synthetic([], device)
        self.assertEqual(status, 2)
        self.assertEqual(report["status"], "blocked_unrecognized_target")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
