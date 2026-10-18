#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
source "$root/scripts/lib/resolve-uv.sh"
source "$root/scripts/lib/db-ready.sh"
uv_bin="$(resolve_uv "$root")"

clean_inner=false
if [[ "${1:-}" == "--clean-inner" && $# -eq 1 ]]; then
  clean_inner=true
elif [[ $# -ne 0 ]]; then
  printf 'usage: %s [--clean-inner]\n' "$0" >&2
  exit 2
fi

run_repository_proof() {
  env -u OPENAI_API_KEY -u GROQ_API_KEY -u JANUARY_TELEGRAM_BOT_TOKEN \
    "$uv_bin" run pytest \
      backend/tests/test_knowledge.py \
      backend/tests/test_ai_evaluations.py -q
  "$uv_bin" run ruff check backend alembic/versions/0022_knowledge_base_rag.py
  "$uv_bin" run ruff format --check backend alembic/versions/0022_knowledge_base_rag.py
  "$uv_bin" run mypy backend/app
  [[ "$("$uv_bin" run alembic heads)" == "0026_conversation_feedback (head)" ]]
  if rg -n 'pytest\.skip|pytest\.xfail|asyncio\.sleep|time\.sleep' \
    backend/tests/test_knowledge.py \
    backend/tests/integration/test_knowledge_rag.py; then
    printf '%s\n' "SPEC-033 proof contains a skip, xfail, or timing-based race." >&2
    exit 1
  fi
}

run_repository_proof
if [[ "$clean_inner" == true ]]; then
  printf '%s\n' "SPEC-033 clean exported-tree proof passed."
  exit 0
fi

archive="$(mktemp "${TMPDIR:-/tmp}/spec033-workspace.XXXXXX.tar")"
archive_list="$(mktemp "${TMPDIR:-/tmp}/spec033-workspace-files.XXXXXX")"
clean_root="$(mktemp -d "${TMPDIR:-/tmp}/spec033-clean-runner.XXXXXX")"
guard_log="$(mktemp "${TMPDIR:-/tmp}/spec033-downgrade-guard.XXXXXX")"
export COMPOSE_PROJECT_NAME="${JANUARY_SPEC033_COMPOSE_PROJECT_NAME:-january-spec033-validation}"
export JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5447}"
export JANUARY_QDRANT_HOST_PORT="${JANUARY_QDRANT_HOST_PORT:-6337}"
export JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="$JANUARY_DB_HOST_PORT"
export JANUARY_QDRANT_URL="http://127.0.0.1:${JANUARY_QDRANT_HOST_PORT}"
export JANUARY_ENVIRONMENT=test

cleanup() {
  result=$?
  trap - EXIT
  docker compose down -v --remove-orphans >/dev/null 2>&1 || result=1
  rm -f -- "$archive" "$archive_list" "$guard_log"
  rm -rf -- "$clean_root"
  exit "$result"
}
trap cleanup EXIT

# Run from a VCS-free exported tree so no local-only or full-history behavior is
# required; this is stricter than a shallow checkout for repository reads.
source "$root/scripts/lib/source-files.sh"
source_file_list "$root" "$uv_bin" >"$archive_list"
tar --null --create --file "$archive" --files-from "$archive_list"
mkdir -p "$clean_root/repository" "$clean_root/bin"
tar --extract --file "$archive" --directory "$clean_root/repository"
ln -s "$uv_bin" "$clean_root/bin/uv"
env UV_PROJECT_ENVIRONMENT="$root/.venv" PATH="$clean_root/bin:$PATH" \
  "$clean_root/repository/scripts/validate-knowledge-rag.sh" --clean-inner

docker compose down -v --remove-orphans >/dev/null
docker compose up --detach --wait database qdrant
"$uv_bin" run alembic upgrade 0021_multi_assistant_tenancy
"$uv_bin" run alembic upgrade 0022_knowledge_base_rag
"$uv_bin" run alembic current | grep -q '0022_knowledge_base_rag'
# Keep the SPEC-033 boundary assertion above, then install newer schema columns
# before current ORM-backed integration fixtures run.
"$uv_bin" run alembic upgrade head
"$uv_bin" run pytest backend/tests/integration/test_knowledge_rag.py \
  -m knowledge_rag_integration -q

# Normalize newer SPEC-034 state so the chained downgrade reaches the
# SPEC-033 populated-state guard that this validator owns.
docker compose exec -T database psql -v ON_ERROR_STOP=1 -U january -d january <<'SQL'
UPDATE messages SET reply_to_platform_message_id = NULL;
UPDATE outbound_delivery_attempts
   SET reply_fallback_used = false,
       reply_fallback_error_code = NULL;
TRUNCATE outbound_actions CASCADE;
SQL
if "$uv_bin" run alembic downgrade 0021_multi_assistant_tenancy \
  >"$guard_log" 2>&1; then
  printf '%s\n' "populated SPEC-033 downgrade unexpectedly succeeded" >&2
  exit 1
fi
if ! grep -q 'SPEC-033 knowledge state blocks downgrade' "$guard_log"; then
  cat "$guard_log" >&2
  exit 1
fi
# PostgreSQL rolls the chained 0025->0021 downgrade back atomically when the
# SPEC-033 guard rejects its 0022->0021 leg.
"$uv_bin" run alembic current | grep -q '0026_conversation_feedback'

docker compose down -v --remove-orphans >/dev/null
docker compose up --detach --wait database qdrant
"$uv_bin" run alembic upgrade head
"$uv_bin" run alembic downgrade 0021_multi_assistant_tenancy
"$uv_bin" run alembic upgrade 0022_knowledge_base_rag
"$uv_bin" run alembic downgrade base
"$uv_bin" run alembic upgrade head
[[ "$("$uv_bin" run alembic heads)" == "0026_conversation_feedback (head)" ]]

printf '%s\n' \
  "SPEC-033 knowledge RAG unit, clean-tree, PostgreSQL, Qdrant, guard, and migration proofs passed."
