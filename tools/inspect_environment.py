#!/usr/bin/env python3
"""Read-only host/device inventory. Does not install or launch any application."""
from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
DEVICE_COMMANDS = {
    "kernel": "uname -s",
    "architecture": "uname -m",
    "device_type": "param get const.product.devicetype",
    "model": "param get const.product.model",
    "api_version": "param get const.ohos.apiversion",
    "system_version": "param get const.ohos.fullname",
    "python_on_path": "command -v python3",
}
# Intentionally no device install, file transfer, system-setting changes or app commands.


def run_command(argv: list[str], timeout: float = 10) -> dict:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                check=False, encoding="utf-8", errors="replace")
        return {"returncode": result.returncode, "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(), "error": None}
    except FileNotFoundError:
        return {"returncode": None, "stdout": "", "stderr": "", "error": "not_found"}
    except subprocess.TimeoutExpired:
        return {"returncode": None, "stdout": "", "stderr": "", "error": "timeout"}
    except OSError as exc:
        return {"returncode": None, "stdout": "", "stderr": "", "error": str(exc)}


def parse_targets(text: str) -> list[str]:
    """Accept only target records, never daemon banners or '<Empty>' as a target."""
    targets = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("[", "*", "<", "-")):
            continue
        # The plain 'list targets' command returns one whitespace-free ID per line.
        if len(line.split()) == 1 and not any(c in line for c in "\x00\r\n"):
            targets.append(line)
    return list(dict.fromkeys(targets))


def select_target(targets: list[str], requested: str) -> str:
    if requested == "auto":
        if len(targets) != 1:
            raise ValueError("auto requires exactly one connected target")
        return targets[0]
    if requested not in targets:
        raise ValueError("requested target is not in the connected target list")
    return requested


def read_sdk(hdc: Path) -> dict:
    # The bundled SDK layout places native/ and toolchains/ beside one another.
    metadata = hdc.parent.parent / "native" / "oh-uni-package.json"
    try:
        contents = json.loads(metadata.read_text(encoding="utf-8"))
        return {"path": str(metadata), "api_version": contents.get("apiVersion"),
                "version": contents.get("version"), "status": "read"}
    except (OSError, ValueError) as exc:
        return {"path": str(metadata), "status": "unavailable", "error": str(exc)}


def usable_value(result: dict) -> str | None:
    if result.get("error") or result.get("returncode") != 0:
        return None
    value = result.get("stdout", "").strip()
    if not value or any(marker in value.lower() for marker in
                        ("not found", "permission denied", "[fail]", "get parameter failed")):
        return None
    return value


def assess_device(commands: dict) -> dict:
    values = {key: usable_value(value) for key, value in commands.items()}
    version = values.get("system_version") or ""
    harmony_family = "openharmony" in version.lower() or "harmonyos" in version.lower()
    python_path = values.get("python_on_path")
    # command -v is only a PATH lookup. It cannot prove a bundled runtime is absent.
    python_state = "found_on_path_not_validated" if python_path and python_path.startswith("/") else "not_observed_on_path"
    return {
        "observed": values,
        "harmony_family_identified": harmony_family,
        "native_binary_compatibility": "not_tested",
        "python_runtime": python_state,
        "qt_runtime": "not_tested",
        "physical_pc_confirmed": False,
        "upstream_app_launched": False,
        "port_validated": False,
        "notes": [
            "A Linux kernel or aarch64 CPU does not establish desktop Linux ABI compatibility.",
            "The 2in1 device type does not confirm a physical HarmonyOS PC.",
            "A PATH lookup cannot detect private application runtimes.",
        ],
    }


def collect_device(hdc: str, requested: str, timeout: float) -> dict:
    listing = run_command([hdc, "list", "targets"], timeout)
    report = {"listing": listing, "status": "unavailable"}
    if listing["error"] or listing["returncode"] != 0:
        return report
    targets = parse_targets(listing["stdout"])
    try:
        target = select_target(targets, requested)
    except ValueError as exc:
        return {**report, "status": "selection_required", "error": str(exc),
                "connected_target_count": len(targets)}
    commands = {key: run_command([hdc, "-t", target, "shell", command], timeout)
                for key, command in DEVICE_COMMANDS.items()}
    complete = all(usable_value(commands[key]) is not None for key in
                   ("kernel", "architecture", "device_type", "api_version", "system_version"))
    return {"status": "collected" if complete else "partial", "target": target,
            "listing": listing, "commands": commands, "assessment": assess_device(commands)}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hdc", help="Explicit hdc executable path; no device is contacted without --device")
    parser.add_argument("--device", help="Connected target ID, or auto for exactly one target")
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    report = {
        "schema_version": SCHEMA_VERSION,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "generic_install_launch_ui_compatibility_only",
        "host": {"system": platform.system(), "architecture": platform.machine(),
                 "python_version": platform.python_version(), "python_executable": sys.executable,
                 "qt_bindings_on_python_path": {name: importlib.util.find_spec(name) is not None
                                                 for name in ("PySide6", "PyQt6")}},
        "device": {"status": "not_requested"},
        "upstream_app_launched": False,
        "port_validated": False,
    }
    if args.device:
        hdc = args.hdc or shutil.which("hdc")
        if hdc:
            report["sdk"] = read_sdk(Path(hdc))
            report["device"] = collect_device(hdc, args.device, args.timeout)
        else:
            report["device"] = {"status": "unavailable", "error": "hdc_not_found"}
    write_json(args.output, report)
    print(f"Inventory saved: {args.output.resolve()}")
    print("This is an inventory, not proof of installation, launch, or UI compatibility.")
    # Success means inventory collection only, never a validated port.
    return 0 if report["device"]["status"] in ("not_requested", "collected") else 2


if __name__ == "__main__":
    raise SystemExit(main())
