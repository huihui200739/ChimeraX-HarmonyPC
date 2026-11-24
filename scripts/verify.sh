#!/usr/bin/env bash
# Verify the checkout without overwriting the published evidence.
set -euo pipefail
cd "$(dirname "$0")/.."

mode="${1-}"
if (( $# > 1 )) || [[ "$mode" != "" && "$mode" != --local && "$mode" != --build-only ]]; then
    echo "Usage: bash scripts/verify.sh [--local | --build-only]" >&2
    exit 2
fi

if [[ "$mode" != --build-only ]]; then
    echo "== local unit tests =="
    python3 -m unittest discover -s tests
fi
if [[ "$mode" == --local ]]; then
    exit 0
fi

echo "== build HAP with checked-in runtime =="
python3 tools/build_hap.py
if [[ "$mode" != --build-only ]]; then
    echo "== device assertions =="
    python3 tools/device_app_check.py
fi
