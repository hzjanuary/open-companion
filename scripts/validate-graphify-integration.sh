#!/usr/bin/env bash
# Offline January-owned integration contract; no Graphify execution/build.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$root")"
export UV_OFFLINE=1
cd "$root"
bash -n scripts/dev/graphify.sh scripts/validate-graphify-integration.sh
"$uv_bin" run --locked python scripts/graphify/validate.py
"$uv_bin" run --locked pytest -q backend/tests/test_graphify_integration.py
