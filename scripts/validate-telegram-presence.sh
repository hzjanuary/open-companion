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
    "$uv_bin" run pytest \
      backend/tests/test_telegram_presence.py \
      backend/tests/test_telegram_adapter.py \
      backend/tests/test_provider_governance.py \
      backend/tests/test_ai_evaluations.py -q
  env -u JANUARY_ENVIRONMENT \
    -u JANUARY_TELEGRAM_BOT_TOKEN \
    -u TELEGRAM_BOT_TOKEN \
    -u OPENAI_API_KEY \
    -u GEMINI_API_KEY \
    -u GROQ_API_KEY \
    -u OPENROUTER_API_KEY \
    PYTHONPATH=backend "$uv_bin" run python -m app.runtime.ai_evaluations \
    >/dev/null
  "$uv_bin" run ruff check backend
  "$uv_bin" run ruff format --check backend
  "$uv_bin" run mypy backend/app
  [[ "$(env -u JANUARY_ENVIRONMENT "$uv_bin" run alembic heads)" \
    == "0026_conversation_feedback (head)" ]]
  if rg -n 'pytest\.skip|pytest\.mark\.skip|pytest\.xfail|time\.sleep|ensure_future' \
    backend/tests/test_telegram_presence.py \
    backend/tests/test_telegram_adapter.py \
    backend/tests/integration/test_telegram_presence_worker.py \
    backend/tests/integration/test_ingress.py; then
    printf '%s\n' "SPEC-035 proof contains a skip, xfail, or blocking wait." >&2
    exit 1
  fi
}

run_repository_proof
if [[ "$clean_inner" == true ]]; then
  printf '%s\n' "SPEC-035 clean exported-tree proof passed."
  exit 0
fi

archive="$(mktemp "${TMPDIR:-/tmp}/spec035-workspace.XXXXXX.tar")"
archive_list="$(mktemp "${TMPDIR:-/tmp}/spec035-workspace-files.XXXXXX")"
clean_root="$(mktemp -d "${TMPDIR:-/tmp}/spec035-clean-runner.XXXXXX")"
export COMPOSE_PROJECT_NAME="${JANUARY_SPEC035_COMPOSE_PROJECT_NAME:-january-spec035-validation}"
export JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5450}"
export JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6397}"
export JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="$JANUARY_DB_HOST_PORT"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT}/0"
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

# Export tracked and untracked non-ignored candidate files into a VCS-free tree.
# The inner run has no .env, Git history, ignored virtualenv, or credentials.
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
  "$clean_root/repository/scripts/validate-telegram-presence.sh" --clean-inner

docker compose down -v --remove-orphans >/dev/null
docker compose up --detach --wait database redis
"$uv_bin" run alembic upgrade head
"$uv_bin" run pytest \
  backend/tests/integration/test_telegram_presence_worker.py \
  backend/tests/integration/test_ingress.py::test_eligible_ingress_creates_one_durable_response_plan \
  backend/tests/integration/test_ingress.py::test_disabled_ambient_job_completes_without_provider_io \
  -m 'telegram_presence_integration or planning_integration' -q
[[ "$("$uv_bin" run alembic heads)" \
  == "0026_conversation_feedback (head)" ]]

printf '%s\n' \
  "SPEC-035 presence unit, clean-tree, PostgreSQL, admission, lease, and session-boundary proofs passed."
