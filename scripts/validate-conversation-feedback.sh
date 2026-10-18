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

without_credentials() {
  env -u JANUARY_ENVIRONMENT \
    -u JANUARY_TELEGRAM_BOT_TOKEN \
    -u TELEGRAM_BOT_TOKEN \
    -u JANUARY_LLM_OPENAI_API_KEY \
    -u OPENAI_API_KEY \
    -u GEMINI_API_KEY \
    -u GROQ_API_KEY \
    -u OPENROUTER_API_KEY \
    "$@"
}

audit_direct_validator_modes() {
  mapfile -t direct_validators < <(
    sed -n 's/^[[:space:]]*- run: \(\.\/scripts\/[^[:space:]]*\.sh\)$/\1/p' \
      .github/workflows/ci.yml | sort -u
  )
  [[ "${#direct_validators[@]}" -gt 0 ]]
  for validator in "${direct_validators[@]}"; do
    [[ -x "$validator" ]]
    [[ "$(stat -c '%a' "$validator")" == "755" ]]
  done
}

run_repository_proof() {
  without_credentials "$uv_bin" run pytest -q \
    backend/tests/test_telegram_commands.py \
    backend/tests/test_ai_evaluations.py \
    backend/tests/test_observability.py
  without_credentials PYTHONPATH=backend "$uv_bin" run python \
    -m app.runtime.ai_evaluations --category feedback >/dev/null
  "$uv_bin" run ruff check \
    backend/app/domain/feedback.py \
    backend/app/infrastructure/database/feedback.py \
    backend/app/runtime/telegram_command_worker.py \
    backend/tests/integration/test_conversation_feedback.py \
    alembic/versions/0026_conversation_feedback.py
  "$uv_bin" run ruff format --check \
    backend/app/domain/feedback.py \
    backend/app/infrastructure/database/feedback.py \
    backend/app/runtime/telegram_command_worker.py \
    backend/tests/integration/test_conversation_feedback.py \
    alembic/versions/0026_conversation_feedback.py
  "$uv_bin" run mypy backend/app
  [[ "$(without_credentials "$uv_bin" run alembic heads)" \
    == "0026_conversation_feedback (head)" ]]
  [[ -x scripts/validate-conversation-feedback.sh ]]
  [[ "$(stat -c '%a' scripts/validate-conversation-feedback.sh)" == "755" ]]
  audit_direct_validator_modes
  if rg -n \
    'pytest\.skip|pytest\.mark\.skip|pytest\.xfail|xfail|asyncio\.sleep|time\.sleep|continue-on-error|\|\| true|except Exception|random|time\.time|ALTER TABLE' \
    backend/app/domain/feedback.py \
    backend/app/infrastructure/database/feedback.py \
    backend/tests/integration/test_conversation_feedback.py \
    alembic/versions/0026_conversation_feedback.py; then
    printf '%s\n' \
      "SPEC-039 proof contains a skip, broad catch, timing race, randomness, manual ALTER, or masked failure." >&2
    exit 1
  fi
  if rg -n -i 'feedback' backend/app/interface; then
    printf '%s\n' \
      "SPEC-039 unexpectedly exposes feedback through an API/control-plane route." >&2
    exit 1
  fi
}

run_repository_proof
if [[ "$clean_inner" == true ]]; then
  if find . -maxdepth 1 -type f -name '.env*' ! -name '*.example' | grep -q .; then
    printf '%s\n' "SPEC-039 clean export unexpectedly contains an environment file." >&2
    exit 1
  fi
  [[ ! -e .git ]]
  printf '%s\n' "SPEC-039 clean exported-tree proof passed."
  exit 0
fi

archive="$(mktemp "${TMPDIR:-/tmp}/spec039-workspace.XXXXXX.tar")"
archive_list="$(mktemp "${TMPDIR:-/tmp}/spec039-workspace-files.XXXXXX")"
clean_root="$(mktemp -d "${TMPDIR:-/tmp}/spec039-clean-runner.XXXXXX")"
guard_log="$(mktemp "${TMPDIR:-/tmp}/spec039-downgrade-guard.XXXXXX")"
export COMPOSE_PROJECT_NAME="${JANUARY_SPEC039_COMPOSE_PROJECT_NAME:-january-spec039-validation}"
export JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5458}"
export JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="$JANUARY_DB_HOST_PORT"
export JANUARY_ENVIRONMENT=test

cleanup() {
  result=$?
  trap - EXIT
  if ! docker compose down -v --remove-orphans >/dev/null 2>&1; then
    result=1
  fi
  rm -f -- "$archive" "$archive_list" "$guard_log"
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
without_credentials \
  UV_PROJECT_ENVIRONMENT="$root/.venv" \
  PATH="$clean_root/bin:$PATH" \
  "$clean_root/repository/scripts/validate-conversation-feedback.sh" --clean-inner

docker compose down -v --remove-orphans >/dev/null
docker compose up --detach --wait database
"$uv_bin" run alembic upgrade 0025_telegram_voice_tts
"$uv_bin" run alembic upgrade 0026_conversation_feedback
"$uv_bin" run alembic downgrade 0025_telegram_voice_tts
"$uv_bin" run alembic upgrade 0026_conversation_feedback
"$uv_bin" run alembic downgrade base
"$uv_bin" run alembic upgrade head
"$uv_bin" run alembic current | grep -q '0026_conversation_feedback'

JANUARY_SPEC039_PRESERVE_TEST_STATE=1 "$uv_bin" run pytest -q \
  backend/tests/integration/test_conversation_feedback.py \
  -m conversation_feedback_integration

if "$uv_bin" run alembic downgrade 0025_telegram_voice_tts \
  >"$guard_log" 2>&1; then
  printf '%s\n' "populated SPEC-039 downgrade unexpectedly succeeded" >&2
  exit 1
fi
grep -q 'SPEC-039 conversation feedback state blocks downgrade' "$guard_log"
"$uv_bin" run alembic current | grep -q '0026_conversation_feedback'

printf '%s\n' \
  "SPEC-039 feedback unit, eval, clean-tree, PostgreSQL, privacy, concurrency, and migration proofs passed."
