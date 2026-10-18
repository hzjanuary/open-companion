#!/usr/bin/env bash
# Offline source contract only. No GitHub, network, daemon or publication.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$root")"
export UV_OFFLINE=1
cd "$root"
bash -n scripts/validate-public-release.sh
"$uv_bin" run --locked python scripts/public_release/validate.py
"$uv_bin" run --locked pytest -q backend/tests/test_public_release.py
