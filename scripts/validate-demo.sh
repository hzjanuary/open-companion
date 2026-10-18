#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$project_root")"

export JANUARY_ENVIRONMENT=test JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="${JANUARY_DB_HOST_PORT:-5432}"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT:-6379}/0"
"$project_root/scripts/validate-delivery.sh"
JANUARY_ENVIRONMENT=local "$uv_bin" run pytest backend/tests/test_config.py

cleanup() { docker compose stop database redis >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker compose up --detach database redis
for _ in $(seq 1 30); do
  if docker compose exec -T database pg_isready -U january -d january >/dev/null 2>&1 \
    && docker compose exec -T redis redis-cli ping >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
"$uv_bin" run alembic upgrade head
"$uv_bin" run pytest -m demo_integration
printf '%s\n' "PASS demo synthetic proof: bootstrap, allowlisted pipeline, replay, and denied outbound suppression used fake adapters only."
