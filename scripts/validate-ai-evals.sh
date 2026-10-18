#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
source "$project_root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$project_root")"

clean_inner=false
if [[ "${1:-}" == "--clean-inner" && $# -eq 1 ]]; then
  clean_inner=true
elif [[ $# -ne 0 ]]; then
  printf 'usage: %s [--clean-inner]\n' "$0" >&2
  exit 2
fi

report_one="$(mktemp "${TMPDIR:-/tmp}/spec032-eval-report-one.XXXXXX")"
report_two="$(mktemp "${TMPDIR:-/tmp}/spec032-eval-report-two.XXXXXX")"
snapshot=""
snapshot_list=""
clean_root=""
cleanup() {
  result=$?
  trap - EXIT
  rm -f -- "$report_one" "$report_two"
  if [[ -n "$snapshot" ]]; then
    rm -f -- "$snapshot"
  fi
  if [[ -n "$snapshot_list" ]]; then
    rm -f -- "$snapshot_list"
  fi
  if [[ -n "$clean_root" ]]; then
    rm -rf -- "$clean_root"
  fi
  exit "$result"
}
trap cleanup EXIT

env -u JANUARY_ENVIRONMENT \
  -u JANUARY_TELEGRAM_BOT_TOKEN \
  -u TELEGRAM_BOT_TOKEN \
  -u OPENAI_API_KEY \
  -u GROQ_API_KEY \
  "$uv_bin" run pytest backend/tests/test_ai_evaluations.py -q

env -u JANUARY_ENVIRONMENT PYTHONPATH=backend "$uv_bin" run \
  python -m app.runtime.ai_evaluations --json "$report_one" >/dev/null
env -u JANUARY_ENVIRONMENT PYTHONPATH=backend "$uv_bin" run \
  python -m app.runtime.ai_evaluations --json "$report_two" >/dev/null
cmp --silent "$report_one" "$report_two"
env -u JANUARY_ENVIRONMENT PYTHONPATH=backend "$uv_bin" run \
  python -m app.runtime.ai_evaluations --category media >/dev/null
env -u JANUARY_ENVIRONMENT PYTHONPATH=backend "$uv_bin" run \
  python -m app.runtime.ai_evaluations \
  --scenario multi-tenant.foreign-tenant-history >/dev/null

"$uv_bin" run ruff check \
  backend/app/evaluation \
  backend/app/runtime/ai_evaluations.py \
  backend/tests/test_ai_evaluations.py
"$uv_bin" run ruff format --check \
  backend/app/evaluation \
  backend/app/runtime/ai_evaluations.py \
  backend/tests/test_ai_evaluations.py
"$uv_bin" run mypy backend/app/evaluation backend/app/runtime/ai_evaluations.py

heads_output="$(env -u JANUARY_ENVIRONMENT "$uv_bin" run alembic heads)"
if [[ "$heads_output" != "0026_conversation_feedback (head)" ]]; then
  printf 'unexpected Alembic heads:\n%s\n' "$heads_output" >&2
  exit 1
fi

if [[ "$clean_inner" == false ]]; then
  snapshot="$(mktemp "${TMPDIR:-/tmp}/spec032-workspace.XXXXXX.tar")"
  snapshot_list="$(mktemp "${TMPDIR:-/tmp}/spec032-workspace-files.XXXXXX")"
  clean_root="$(mktemp -d "${TMPDIR:-/tmp}/spec032-clean-runner.XXXXXX")"
  source "$project_root/scripts/lib/source-files.sh"
  source_file_list "$project_root" "$uv_bin" >"$snapshot_list"
  tar --null --create --file "$snapshot" --files-from "$snapshot_list"
  mkdir -p "$clean_root/repository" "$clean_root/bin"
  tar --extract --file "$snapshot" --directory "$clean_root/repository"
  ln -s "$uv_bin" "$clean_root/bin/uv"
  if [[ -d "$project_root/.venv" ]]; then
    env UV_PROJECT_ENVIRONMENT="$project_root/.venv" \
      PATH="$clean_root/bin:$PATH" \
      "$clean_root/repository/scripts/validate-ai-evals.sh" --clean-inner
  else
    env PATH="$clean_root/bin:$PATH" \
      "$clean_root/repository/scripts/validate-ai-evals.sh" --clean-inner
  fi
fi

printf '%s\n' \
  "SPEC-032 offline AI evaluation, negative, determinism, and clean-runner proofs passed."
