#!/usr/bin/env bash
# Repository distribution proof only; never run test validators on personal data.
set +x
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$root")"
export UV_OFFLINE=1
cd "$root"
command -v docker >/dev/null 2>&1 || { printf '%s\n' 'Docker CLI/Compose is required for offline topology rendering.' >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { printf '%s\n' 'Install a compatible Docker Compose plugin.' >&2; exit 1; }
for script in scripts/self-host-doctor.sh scripts/self-host-compose.sh \
  scripts/lib/self-host-env.sh scripts/validate-self-hosted.sh; do
  bash -n "$script"
done
"$uv_bin" run --locked python scripts/self_host/validate_distribution.py
"$uv_bin" run --locked pytest -q \
  backend/tests/test_self_host_distribution.py backend/tests/test_self_host_doctor.py \
  backend/tests/test_self_host_runtime.py backend/tests/test_self_host_setup.py \
  backend/tests/test_self_host_http.py
printf '%s\n' 'Offline self-host packaging/doctor proof passed; startup/delivery and Git tree modes are separate gates.'
