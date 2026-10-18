#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
source "$project_root/scripts/lib/db-ready.sh"
uv_bin="$(resolve_uv "$project_root")"

export COMPOSE_PROJECT_NAME="january-spec025-validation"
export JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5434}"
export JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6381}"
export JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="$JANUARY_DB_HOST_PORT"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT}/0"

if ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' "Docker Compose is required for governance integration validation." >&2
  exit 1
fi

cleanup() {
  status=$?
  trap - EXIT
  if ! docker compose down -v --remove-orphans >/dev/null 2>&1; then
    printf '%s\n' "Governance validator cleanup failed." >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT
docker compose up --detach database redis
pg_ready && redis_ready || { printf '%s\n' "PostgreSQL or Redis did not become ready." >&2; exit 1; }
env -u JANUARY_ENVIRONMENT "$uv_bin" run pytest \
  backend/tests/test_telegram_commands.py \
  backend/tests/test_observability.py backend/tests/test_config.py

JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade base
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade 0015_safety_moderation
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade 0016_data_governance
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade 0015_safety_moderation
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade 0016_data_governance
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic current | grep -q '0016_data_governance'
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade head
JANUARY_ENVIRONMENT=test "$uv_bin" run pytest \
  backend/tests/integration/test_governance_schema.py -m governance_integration
# Governance tests deliberately create non-legacy tenants. Use a fresh
# validator-owned volume for the generic empty base/head reversibility proof so
# SPEC-030's data-loss guard is not bypassed or mistaken for a schema failure.
docker compose down -v --remove-orphans
docker compose up --detach --wait database redis
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade base
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade head
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic current \
  | grep -q '0026_conversation_feedback'
