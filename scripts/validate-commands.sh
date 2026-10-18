#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
source "$project_root/scripts/lib/db-ready.sh"
uv_bin="$(resolve_uv "$project_root")"

export JANUARY_ENVIRONMENT=test JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="${JANUARY_DB_HOST_PORT:-5432}"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT:-6379}/0"

if ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' "Docker Compose is required for command integration validation." >&2
  exit 1
fi

cleanup() {
  [[ "${JANUARY_RELIABILITY_CHAIN:-}" == "1" ]] && return 0
  docker compose stop database redis >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker compose up --detach database redis
pg_ready && redis_ready || { printf '%s\n' "PostgreSQL or Redis did not become ready." >&2; exit 1; }
"$uv_bin" run alembic upgrade head
"$uv_bin" run pytest backend/tests/test_telegram_commands.py
"$uv_bin" run pytest -m command_integration
