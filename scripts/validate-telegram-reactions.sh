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
    -u GEMINI_API_KEY \
    -u GROQ_API_KEY \
    -u OPENROUTER_API_KEY \
    "$uv_bin" run pytest -q \
      backend/tests/test_telegram_reactions.py \
      backend/tests/test_telegram_adapter.py \
      backend/tests/test_telegram_updates.py \
      backend/tests/test_ai_evaluations.py \
      backend/tests/test_observability.py::test_reaction_metrics_are_closed_and_identity_free
  env -u JANUARY_ENVIRONMENT \
    -u JANUARY_TELEGRAM_BOT_TOKEN \
    -u TELEGRAM_BOT_TOKEN \
    -u OPENAI_API_KEY \
    -u GEMINI_API_KEY \
    -u GROQ_API_KEY \
    -u OPENROUTER_API_KEY \
    PYTHONPATH=backend "$uv_bin" run python -m app.runtime.ai_evaluations \
    --category reaction >/dev/null
  "$uv_bin" run ruff check backend
  "$uv_bin" run ruff format --check backend
  "$uv_bin" run mypy backend/app
  [[ "$(env -u JANUARY_ENVIRONMENT "$uv_bin" run alembic heads)" \
    == "0026_conversation_feedback (head)" ]]
  [[ -x scripts/validate-telegram-reactions.sh ]]
  [[ "$(stat -c '%a' scripts/validate-telegram-reactions.sh)" == "755" ]]
  if rg -n \
    'pytest\.skip|pytest\.mark\.skip|pytest\.xfail|xfail|asyncio\.sleep|time\.sleep|continue-on-error|\|\| true|except Exception|sentiment|classifier|random|time\.time|datetime\.now|create_task' \
    backend/app/application/reactions.py \
    backend/app/domain/reactions.py \
    backend/app/infrastructure/database/reactions.py \
    backend/tests/test_telegram_reactions.py \
    backend/tests/integration/test_telegram_reactions_worker.py; then
    printf '%s\n' \
      "SPEC-037 proof contains a skip, broad catch, classifier, random/time policy, task leak, or masked failure." >&2
    exit 1
  fi
}

run_repository_proof
if [[ "$clean_inner" == true ]]; then
  if find . -maxdepth 1 -type f -name '.env*' ! -name '*.example' | grep -q .; then
    printf '%s\n' "SPEC-037 clean export unexpectedly contains an environment file." >&2
    exit 1
  fi
  printf '%s\n' "SPEC-037 clean exported-tree proof passed."
  exit 0
fi

archive="$(mktemp "${TMPDIR:-/tmp}/spec037-workspace.XXXXXX.tar")"
archive_list="$(mktemp "${TMPDIR:-/tmp}/spec037-workspace-files.XXXXXX")"
clean_root="$(mktemp -d "${TMPDIR:-/tmp}/spec037-clean-runner.XXXXXX")"
export COMPOSE_PROJECT_NAME="${JANUARY_SPEC037_COMPOSE_PROJECT_NAME:-january-spec037-validation}"
export JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5454}"
export JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="$JANUARY_DB_HOST_PORT"
export JANUARY_ENVIRONMENT=test

cleanup() {
  result=$?
  trap - EXIT
  docker compose down -v --remove-orphans >/dev/null 2>&1 || result=1
  rm -f -- "$archive" "$archive_list"
  rm -rf -- "$clean_root"
  exit "$result"
}
trap cleanup EXIT

# Export tracked plus untracked, non-ignored candidate files into a VCS-free tree.
source "$root/scripts/lib/source-files.sh"
source_file_list "$root" "$uv_bin" >"$archive_list"
tar --null --create --file "$archive" --files-from "$archive_list"
mkdir -p "$clean_root/repository" "$clean_root/bin"
tar --extract --file "$archive" --directory "$clean_root/repository"
ln -s "$uv_bin" "$clean_root/bin/uv"
env -u JANUARY_ENVIRONMENT \
  -u JANUARY_TELEGRAM_BOT_TOKEN \
  -u TELEGRAM_BOT_TOKEN \
  -u OPENAI_API_KEY \
  -u GEMINI_API_KEY \
  -u GROQ_API_KEY \
  -u OPENROUTER_API_KEY \
  UV_PROJECT_ENVIRONMENT="$root/.venv" \
  PATH="$clean_root/bin:$PATH" \
  "$clean_root/repository/scripts/validate-telegram-reactions.sh" --clean-inner

docker compose down -v --remove-orphans >/dev/null
docker compose up --detach --wait database
"$uv_bin" run alembic upgrade head
"$uv_bin" run pytest -q \
  backend/tests/integration/test_telegram_reactions_worker.py \
  -m telegram_reactions_integration
[[ "$("$uv_bin" run alembic current)" == *"0026_conversation_feedback"* ]]

printf '%s\n' \
  "SPEC-037 reaction unit, eval, clean-tree, PostgreSQL authority, session, loop, idempotency, and failure proofs passed."
