#!/usr/bin/env bash
# One-shot verification for the ChimeraX HarmonyOS port.
#
#   bash scripts/verify.sh            # local tests, then build and check on a running device
#   bash scripts/verify.sh --local    # local tests only
#
# The device step needs the emulator (127.0.0.1:5555) and DevEco's hdc on PATH or in its
# default location; the check itself is tools/device_app_check.py.
set -euo pipefail
cd "$(dirname "$0")/.."

echo '== local unit tests =='
python3 -m unittest discover -s tests

if [[ "${1:-}" == "--local" ]]; then
    echo 'local only: skipping the build and the device check'
    exit 0
fi

echo '== stage, package and build the HAP =='
python3 tools/stage_chimerax_python.py
python3 tools/build_all_bundle_cmodules.py
python3 tools/package_app_runtime.py
python3 tools/build_hap.py

echo '== device assertions =='
python3 tools/device_app_check.py
