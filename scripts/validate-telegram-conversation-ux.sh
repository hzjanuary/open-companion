#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
source "$root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$root")"

clean_inner=false
if [[ "${1:-}" == "--clean-inner" && $# -eq 1 ]]; then
  clean_inner=true
elif [[ $# -ne 0 ]]; then
  printf 'usage: %s [--clean-inner]\n' "$0" >&2
  exit 2
fi

run_repository_proof() {
  env -u JANUARY_ENVIRONMENT \
    -u JANUARY_TELEGRAM_BOT_TOKEN \
    -u TELEGRAM_BOT_TOKEN \
    -u OPENAI_API_KEY \
    -u GROQ_API_KEY \
    "$uv_bin" run pytest \
      backend/tests/test_conversation_context.py \
      backend/tests/test_outbound.py \
      backend/tests/test_response_plan.py \
      backend/tests/test_telegram_adapter.py \
      backend/tests/test_ai_evaluations.py -q
  env -u JANUARY_ENVIRONMENT PYTHONPATH=backend "$uv_bin" run \
    python -m app.runtime.ai_evaluations >/dev/null
  "$uv_bin" run ruff check \
    backend alembic/versions/0023_telegram_reply_ordered_delivery.py
  "$uv_bin" run ruff format --check \
    backend alembic/versions/0023_telegram_reply_ordered_delivery.py
  "$uv_bin" run mypy backend/app
  [[ "$(env -u JANUARY_ENVIRONMENT "$uv_bin" run alembic heads)" \
    == "0026_conversation_feedback (head)" ]]
  if rg -n 'pytest\.skip|pytest\.xfail|asyncio\.sleep|time\.sleep' \
    backend/tests/test_conversation_context.py \
    backend/tests/test_outbound.py \
    backend/tests/test_response_plan.py \
    backend/tests/test_telegram_adapter.py \
    backend/tests/integration/test_telegram_conversation_ux.py; then
    printf '%s\n' \
      "SPEC-034 proof contains a skip, xfail, or timing-based race." >&2
    exit 1
  fi
}

run_repository_proof
if [[ "$clean_inner" == true ]]; then
  printf '%s\n' "SPEC-034 clean exported-tree proof passed."
  exit 0
fi

archive="$(mktemp "${TMPDIR:-/tmp}/spec034-workspace.XXXXXX.tar")"
archive_list="$(mktemp "${TMPDIR:-/tmp}/spec034-workspace-files.XXXXXX")"
clean_root="$(mktemp -d "${TMPDIR:-/tmp}/spec034-clean-runner.XXXXXX")"
guard_log="$(mktemp "${TMPDIR:-/tmp}/spec034-downgrade-guard.XXXXXX")"
export COMPOSE_PROJECT_NAME="${JANUARY_SPEC034_COMPOSE_PROJECT_NAME:-january-spec034-validation}"
export JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5448}"
export JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="$JANUARY_DB_HOST_PORT"
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

# Export tracked and untracked candidate files into a VCS-free tree. This proves
# the validator does not depend on ignored state or repository history.
source "$root/scripts/lib/source-files.sh"
source_file_list "$root" "$uv_bin" >"$archive_list"
tar --null --create --file "$archive" --files-from "$archive_list"
mkdir -p "$clean_root/repository" "$clean_root/bin"
tar --extract --file "$archive" --directory "$clean_root/repository"
ln -s "$uv_bin" "$clean_root/bin/uv"
env UV_PROJECT_ENVIRONMENT="$root/.venv" PATH="$clean_root/bin:$PATH" \
  "$clean_root/repository/scripts/validate-telegram-conversation-ux.sh" \
  --clean-inner

docker compose down -v --remove-orphans >/dev/null
docker compose up --detach --wait database
"$uv_bin" run alembic upgrade 0022_knowledge_base_rag
"$uv_bin" run alembic upgrade 0023_telegram_reply_ordered_delivery
"$uv_bin" run alembic current | grep -q '0023_telegram_reply_ordered_delivery'
"$uv_bin" run alembic downgrade 0022_knowledge_base_rag
"$uv_bin" run alembic upgrade 0023_telegram_reply_ordered_delivery
"$uv_bin" run alembic downgrade base
"$uv_bin" run alembic upgrade head

"$uv_bin" run pytest \
  backend/tests/integration/test_telegram_conversation_ux.py \
  -m telegram_conversation_ux_integration -q

if "$uv_bin" run alembic downgrade 0022_knowledge_base_rag \
  >"$guard_log" 2>&1; then
  printf '%s\n' "populated SPEC-034 downgrade unexpectedly succeeded" >&2
  exit 1
fi
grep -q 'SPEC-034 reply or ordered delivery state blocks downgrade' "$guard_log"
"$uv_bin" run alembic current | grep -q '0026_conversation_feedback'
[[ "$("$uv_bin" run alembic heads)" \
  == "0026_conversation_feedback (head)" ]]

printf '%s\n' \
  "SPEC-034 reply context, ordered delivery, clean-tree, PostgreSQL, fallback, and migration proofs passed."
