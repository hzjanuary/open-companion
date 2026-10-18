#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$project_root")"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' "Docker Compose is required for planning integration validation." >&2
  exit 1
fi
export JANUARY_ENVIRONMENT=test JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="${JANUARY_DB_HOST_PORT:-5432}"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT:-6379}/0"
cleanup() {
  [[ "${JANUARY_RELIABILITY_CHAIN:-}" == "1" ]] && return 0
  docker compose stop database redis >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker compose up --detach database redis
for _ in $(seq 1 30); do
  docker compose exec -T database pg_isready -U january -d january >/dev/null 2>&1 && docker compose exec -T redis redis-cli ping >/dev/null 2>&1 && break
  sleep 1
done
"$uv_bin" run alembic upgrade head
"$uv_bin" run pytest -m planning_integration
