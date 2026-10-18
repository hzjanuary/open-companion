#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
source "$project_root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$project_root")"
mode=full
if [[ $# -eq 1 && "$1" == --repository-only ]]; then
  mode=repository-only
elif [[ $# -ne 0 ]]; then
  printf '%s\n' "Usage: $0 [--repository-only]" >&2
  exit 2
fi

env -u JANUARY_ENVIRONMENT "$uv_bin" run pytest \
  backend/tests/test_telegram_media.py \
  backend/tests/test_telegram_media_download.py \
  backend/tests/test_media_persistence.py \
  backend/tests/test_media_model_providers.py \
  backend/tests/test_media_provider_governance.py \
  backend/tests/test_telegram_media_runtime.py \
  backend/tests/test_telegram_adapter.py \
  backend/tests/test_provider_governance.py \
  backend/tests/test_planning_service.py \
  backend/tests/test_conversation_context.py \
  backend/tests/test_config.py

if [[ "$mode" == repository-only ]]; then
  printf '%s\n' "Repository media proof passed; PostgreSQL/Redis/migration/runtime proof PENDING (exit 2)." >&2
  exit 2
fi

# Dedicated project and alternate ports; never stop an unrelated stack.
export COMPOSE_PROJECT_NAME=january-spec028-validation
export JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5440}"
export JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6387}"
export JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="$JANUARY_DB_HOST_PORT"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT}/0"

cleanup() {
  result=$?
  trap - EXIT
  if ! docker compose down -v --remove-orphans; then
    printf '%s\n' "SPEC-028 temporary project cleanup failed." >&2
    result=1
  fi
  exit "$result"
}
docker compose version >/dev/null
trap cleanup EXIT
docker compose up --detach --wait database redis
docker compose exec -T database pg_isready -U january -d january
docker compose exec -T redis redis-cli ping

JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade 0018_user_controlled_memory
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade 0019_telegram_media
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade 0018_user_controlled_memory
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade 0019_telegram_media
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade base
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic upgrade head
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic current | grep -q '0026_conversation_feedback'

JANUARY_ENVIRONMENT=test "$uv_bin" run pytest \
  backend/tests/integration/test_provider_governance_schema.py \
  backend/tests/integration/test_redis_concurrency.py \
  -m 'provider_governance_integration or safety_integration'
# Governance fixtures reset their own scope: media proof runs last so the
# downgrade guard below necessarily sees media state, not only provider state.
JANUARY_ENVIRONMENT=test "$uv_bin" run pytest \
  backend/tests/integration/test_telegram_media_schema.py \
  backend/tests/integration/test_telegram_media_worker.py -m telegram_media_integration

# A content-bearing media candidate must refuse destructive downgrade.
docker compose exec -T database psql -v ON_ERROR_STOP=1 -U january -d january <<'SQL'
UPDATE control_tenants SET revision = 1;
UPDATE assistants
   SET revision = 1,
       slug = 'assistant-' || replace(id::text, '-', '')
 WHERE tenant_id = '00000000-0000-4000-8000-000000000030'::uuid
   AND status <> 'retired';
UPDATE platform_connections SET revision = 1 WHERE status <> 'retired';
SQL
if downgrade_output=$(JANUARY_ENVIRONMENT=test "$uv_bin" run alembic downgrade 0018_user_controlled_memory 2>&1); then
  printf '%s\n' "Media downgrade guard failed: active media state was accepted." >&2
  exit 1
fi
printf '%s\n' "$downgrade_output" | grep -q 'SPEC-028 media or transcription state blocks downgrade'
JANUARY_ENVIRONMENT=test "$uv_bin" run alembic current | grep -q '0026_conversation_feedback'
printf '%s\n' "SPEC-028 repository and isolated PostgreSQL/Redis proofs passed."
