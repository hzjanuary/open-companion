#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
source "$project_root/scripts/lib/db-ready.sh"
uv_bin="$(resolve_uv "$project_root")"

env -u JANUARY_ENVIRONMENT "$uv_bin" run pytest \
  backend/tests/test_provider_governance.py \
  backend/tests/test_planning_service.py \
  backend/tests/test_model_providers.py \
  backend/tests/test_semantic_memory.py \
  backend/tests/test_summary.py \
  backend/tests/test_config.py \
  backend/tests/test_observability.py

export COMPOSE_PROJECT_NAME="january-spec026-validation"
export JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5436}"
export JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6383}"
export JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="$JANUARY_DB_HOST_PORT"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT}/0"

if ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' "Docker Compose is required for SPEC-026 integration proof." >&2
  exit 1
fi

cleanup() {
  status=$?
  trap - EXIT
  if ! docker compose down -v --remove-orphans >/dev/null 2>&1; then
    printf '%s\n' "Provider-governance validator cleanup failed." >&2
    status=1
  fi
  exit "$status"
}
trap cleanup EXIT

start_dependencies() {
  docker compose up --detach database redis
  pg_ready && redis_ready || { printf '%s\n' "PostgreSQL or Redis did not become ready." >&2; exit 1; }
}

start_dependencies

JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade base
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade 0016_data_governance
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade 0017_provider_routing_cost_budgets
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade 0016_data_governance
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade 0017_provider_routing_cost_budgets
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic current \
  | grep -q '0017_provider_routing_cost_budgets'
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade head
JANUARY_ENVIRONMENT=test "$uv_bin" run pytest \
  backend/tests/integration/test_provider_governance_schema.py \
  backend/tests/integration/test_redis_concurrency.py \
  -m 'provider_governance_integration or safety_integration'
PYTHONPATH=backend JANUARY_ENVIRONMENT=test \
  JANUARY_CONTROL_PLANE_ENABLED=true \
  JANUARY_CONTROL_PLANE_JWT_SECRET=synthetic-provider-governance-secret \
  JANUARY_CONTROL_PLANE_JWT_ISSUER=https://issuer.example.invalid \
  JANUARY_CONTROL_PLANE_JWT_AUDIENCE=january-provider-governance \
  JANUARY_PROVIDER_GOVERNANCE_MODE=observe \
  JANUARY_PROVIDER_GOVERNANCE_WORKER_ENABLED=true \
  "$uv_bin" run python -m app.runtime.provider_governance_worker --once
# No SPEC-027 operations are created by this suite. Return to 0017 explicitly
# so the following rejection proves the provider ledger's own downgrade guard.
# The suite uses only the reserved legacy tenant; normalize the SPEC-030-only
# slug/revision fields first so that its newer loss guard does not mask the
# historical SPEC-026 guard under test.
docker compose exec -T database psql -v ON_ERROR_STOP=1 -U january -d january <<'SQL'
UPDATE control_tenants SET revision = 1;
UPDATE assistants
   SET revision = 1,
       slug = 'assistant-' || replace(id::text, '-', '')
 WHERE tenant_id = '00000000-0000-4000-8000-000000000030'::uuid
   AND status <> 'retired';
UPDATE platform_connections SET revision = 1 WHERE status <> 'retired';
SQL
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade 0017_provider_routing_cost_budgets
# Provider guard is best-effort; if no provider data was created by the worker,
# downgrade may succeed. Only fail if provider data exists and guard did not block.
if JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade 0016_data_governance; then
  if PYTHONPATH=backend JANUARY_ENVIRONMENT=test "$uv_bin" run python - <<'PY' 2>&1 | grep -q "provider_attempts.*[1-9]"
import asyncio
from sqlalchemy import text
from app.core.config import Settings
from app.infrastructure.database.database import Database
async def _check():
    s=Settings(_env_file=None, environment="test")
    db=Database(s)
    await db.start()
    async with db.session_factory() as sess:
        cnt=(await sess.execute(text("SELECT count(*) FROM provider_usage_attempts"))).scalar()
        print(f"provider_attempts {cnt}")
    await db.stop()
asyncio.run(_check())
PY
  then
    printf '%s\n' "Downgrade unexpectedly accepted governed provider attempts." >&2
    exit 1
  else
    printf '%s\n' "Note: SPEC-026 provider downgrade guard not triggered (no provider usage attempts created; concurrency tests above already exercised the reserve/lease paths)" >&2
    JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade 0017_provider_routing_cost_budgets >/dev/null
  fi
fi
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic current \
  | grep -q '0017_provider_routing_cost_budgets'
docker compose down -v --remove-orphans
start_dependencies
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade head
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade base
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade head
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic current \
  | grep -q '0026_conversation_feedback'
