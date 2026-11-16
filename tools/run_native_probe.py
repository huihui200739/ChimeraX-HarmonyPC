#!/usr/bin/env python3
"""Build a generic NDK executable, run it temporarily via hdc, then remove it."""
from __future__ import annotations

import argparse
import json
import shlex
import sys
import uuid
from pathlib import Path

from inspect_environment import collect_device, run_command, usable_value, write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", required=True, type=Path, help="Native SDK directory")
    parser.add_argument("--hdc", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    report = {"schema_version": 1, "purpose": "generic_native_runtime_only",
              "status": "initializing", "upstream_app_launched": False,
              "port_validated": False, "cleanup": "not_needed"}
    write_json(args.output, report)
    inventory = collect_device(args.hdc, args.device, 10)
    report["inventory_status"] = inventory["status"]
    if inventory["status"] != "collected":
        report.update(status="blocked_device_inventory", inventory=inventory)
        write_json(args.output, report)
        return 2
    assessment = inventory["assessment"]
    arch = assessment["observed"]["architecture"]
    triples = {"aarch64": "aarch64-linux-ohos", "x86_64": "x86_64-linux-ohos"}
    if not assessment["harmony_family_identified"] or arch not in triples:
        report.update(status="blocked_unrecognized_target")
        write_json(args.output, report)
        return 2
    target = inventory["target"]
    root = Path(__file__).resolve().parents[1]
    build = root / "build" / f"native-{arch}"
    build.mkdir(parents=True, exist_ok=True)
    executable = build / "generic-loader-probe"
    command = [str(args.sdk / "llvm/bin/clang"), f"--target={triples[arch]}",
               f"--sysroot={args.sdk / 'sysroot'}", "-std=c11", "-Wall", "-Wextra", "-Werror",
               str(root / "tools/native_loader_probe.c"), "-o", str(executable), "-ldl"]
    report["compile"] = run_command(command, 60)
    if report["compile"]["error"] or report["compile"]["returncode"] != 0:
        report["status"] = "blocked_compile"
        write_json(args.output, report)
        return 2
    remote = "/data/local/tmp/cx-generic-compat-" + uuid.uuid4().hex
    report["target"] = target
    report["target_architecture"] = arch
    report["remote_temporary_file"] = remote
    base = [args.hdc, "-t", target]
    try:
        report["upload"] = run_command(base + ["file", "send", str(executable), remote], 30)
        if report["upload"]["error"] or report["upload"]["returncode"] != 0:
            report["status"] = "blocked_upload"
        else:
            quoted = shlex.quote(remote)
            report["execution"] = run_command(base + ["shell", f"chmod 700 {quoted} && {quoted}"], 20)
            output = usable_value(report["execution"])
            try:
                report["probe"] = json.loads(output) if output else None
                valid = isinstance(report["probe"], dict) and report["probe"].get("purpose") == "generic_native_loader_probe"
                report["status"] = "native_probe_executed" if valid else "blocked_execution"
            except ValueError:
                report["status"] = "blocked_invalid_probe_output"
    finally:
        quoted = shlex.quote(remote)
        cleanup = f"rm -f {quoted} && if [ ! -e {quoted} ]; then printf CX_CLEANUP_OK; else printf CX_CLEANUP_FAILED; fi"
        report["cleanup_command"] = run_command(base + ["shell", cleanup], 10)
        result = report["cleanup_command"]
        report["cleanup"] = ("removed" if result["returncode"] == 0 and not result["error"]
                             and result["stdout"].strip() == "CX_CLEANUP_OK" else "failed")
        write_json(args.output, report)
    print(f"Native probe report: {args.output.resolve()}")
    print(f"Probe: {report['status']}; temporary file: {report['cleanup']}; application port: not validated")
    return 0 if report["status"] == "native_probe_executed" and report["cleanup"] == "removed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
