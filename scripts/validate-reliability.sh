#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/resolve-uv.sh
source "$ROOT/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$ROOT")"
cd "$ROOT"
# Chained validators share one compose project: keep database/redis running
# across adjacent children (container stop/start churn in CI restarted redis
# between ingress and conversation and it never became ready). Children skip
# their exit stop when chained; this orchestrator stops the shared project only
# at the two port-handoff boundaries (delivery and memory run their own compose
# project on the same host ports) and once at the very end.
export JANUARY_RELIABILITY_CHAIN=1
cleanup() {
  status=$?
  trap - EXIT
  docker compose stop database redis >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT
"$uv_bin" run pytest \
  backend/tests/test_concurrency.py \
  backend/tests/test_outbound.py \
  backend/tests/test_planning_service.py \
  backend/tests/test_config.py \
  backend/tests/test_observability.py
JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}" "$ROOT/scripts/validate-db.sh"
JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}" \
  JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6380}" \
  "$ROOT/scripts/validate-ingress.sh"
JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}" \
  JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6380}" \
  "$ROOT/scripts/validate-conversation.sh"
JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}" \
  JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6380}" \
  "$ROOT/scripts/validate-planning.sh"
docker compose stop database redis >/dev/null
JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}" \
  JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6380}" \
  "$ROOT/scripts/validate-delivery.sh"
JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}" \
  JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6380}" \
  "$ROOT/scripts/validate-commands.sh"
docker compose stop database redis >/dev/null
JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}" \
  JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6380}" \
  "$ROOT/scripts/validate-memory.sh"
JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}" \
  JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6380}" \
  "$ROOT/scripts/validate-safety.sh"
JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6380}" docker compose up -d redis >/dev/null
JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT:-6380}/0" \
  "$uv_bin" run pytest -m safety_integration backend/tests/integration/test_redis_concurrency.py
JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6380}" docker compose stop redis >/dev/null
JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}" "$ROOT/scripts/validate-backup-restore.sh"
"$uv_bin" run ruff check backend/app
echo "Reliability checks: valid"
