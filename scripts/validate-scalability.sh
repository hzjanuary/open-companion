#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$root/scripts/lib/resolve-uv.sh"
source "$root/scripts/lib/db-ready.sh"
uv_bin="$(resolve_uv "$root")"
export JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}"
export JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6380}"
export JANUARY_DATABASE_PORT="$JANUARY_DB_HOST_PORT"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT}/0"

cleanup() {
  docker compose stop database redis >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose up -d database redis >/dev/null
pg_ready && redis_ready || { printf '%s\n' "PostgreSQL or Redis did not become ready." >&2; exit 1; }
"$uv_bin" run alembic upgrade head >/dev/null
"$uv_bin" run pytest -s -m integration \
  backend/tests/integration/test_scalability.py
echo "Synthetic scalability harness: valid; local observations above are not production SLO claims."
