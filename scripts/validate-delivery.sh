#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$project_root")"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-january-delivery-validation}"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' "Docker Compose is required for delivery validation." >&2
  exit 1
fi
export JANUARY_ENVIRONMENT=test JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="${JANUARY_DB_HOST_PORT:-5432}"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT:-6379}/0"
cleanup() {
  status=$?
  trap - EXIT
  if ! docker compose stop database redis >/dev/null 2>&1; then
    printf '%s\n' "Delivery validator cleanup failed." >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT
docker compose up --detach database redis
for _ in $(seq 1 30); do
  if docker compose exec -T database pg_isready -U january -d january >/dev/null 2>&1 \
    && docker compose exec -T redis redis-cli ping >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
# The historical delivery migration cycle is an empty-schema proof. Prior
# chained validators leave canonical tenancy state that must remain guarded, so
# start this leg from a fresh validator-owned volume.
docker compose down -v --remove-orphans
docker compose up --detach --wait database redis
"$uv_bin" run alembic upgrade head
"$uv_bin" run alembic downgrade 0004_response_planning
"$uv_bin" run alembic upgrade head
"$uv_bin" run pytest backend/tests/test_outbound.py
"$uv_bin" run pytest backend/tests/test_telegram_adapter.py
"$uv_bin" run pytest -m 'ingress_integration or conversation_integration or planning_integration or delivery_integration'
