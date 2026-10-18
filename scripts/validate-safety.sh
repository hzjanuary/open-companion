#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
source "$project_root/scripts/lib/db-ready.sh"
uv_bin="$(resolve_uv "$project_root")"

export JANUARY_ENVIRONMENT=test JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="${JANUARY_DB_HOST_PORT:-5432}"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT:-6379}/0"

cleanup() {
  status=$?
  trap - EXIT
  if [[ "${JANUARY_RELIABILITY_CHAIN:-}" == "1" ]]; then
    exit "$status"
  fi
  if ! docker compose stop database redis >/dev/null 2>&1; then
    printf '%s\n' "Safety validator cleanup failed." >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT
docker compose up --detach database redis
pg_ready && redis_ready || { printf '%s\n' "PostgreSQL or Redis did not become ready." >&2; exit 1; }
"$uv_bin" run alembic upgrade head
"$uv_bin" run pytest backend/tests/test_safety.py
"$uv_bin" run pytest -m safety_integration
# Safety tests leave lifecycle and resource rows that SPEC-030 correctly guards.
# Rehearse the generic schema reversal only on a fresh validator-owned volume.
docker compose down -v --remove-orphans
docker compose up --detach --wait database redis
"$uv_bin" run alembic upgrade head
"$uv_bin" run alembic downgrade 0008_memory_privacy_retention
"$uv_bin" run alembic upgrade head
