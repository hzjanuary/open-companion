#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
source "$project_root/scripts/lib/db-ready.sh"
uv_bin="$(resolve_uv "$project_root")"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' "Docker Compose is required for PostgreSQL integration validation." >&2
  exit 1
fi

export JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="${JANUARY_DB_HOST_PORT:-5432}"
export JANUARY_DATABASE_NAME="${JANUARY_DATABASE_NAME:-january}"
export JANUARY_DATABASE_USER="${JANUARY_DATABASE_USER:-january}"
export JANUARY_DATABASE_PASSWORD="${JANUARY_DATABASE_PASSWORD:-january-local}"

cleanup() {
  [[ "${JANUARY_RELIABILITY_CHAIN:-}" == "1" ]] && return 0
  docker compose stop database >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose up --detach database
if ! pg_ready; then
  printf '%s\n' "PostgreSQL did not become ready." >&2
  exit 1
fi

# Start from a clean schema: the migration-chain proof must run unguarded, and
# SPEC-028's 0019 downgrade guard now refuses to reverse while media/transcription
# state exists (that guarded path is proven by validate-telegram-media.sh).
docker compose exec -T database psql -U "$JANUARY_DATABASE_USER" -d "$JANUARY_DATABASE_NAME" \
  -v ON_ERROR_STOP=1 -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' >/dev/null

"$uv_bin" run alembic upgrade head
"$uv_bin" run alembic downgrade base
"$uv_bin" run alembic upgrade head
"$uv_bin" run pytest -m "integration and not ingress_integration and not safety_integration"
# The suite leaves media/transcription state, which trips the SPEC-028 guard if a
# downstream validator's downward migration leg reverses through 0019. Reset to a
# clean 0019 so the rest of the chained matrix stays unguarded by SPEC-028 design.
docker compose exec -T database psql -U "$JANUARY_DATABASE_USER" -d "$JANUARY_DATABASE_NAME" \
  -v ON_ERROR_STOP=1 -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' >/dev/null
"$uv_bin" run alembic upgrade head
