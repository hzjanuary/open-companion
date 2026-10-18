#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$project_root")"

app_files=(
  "backend/app/runtime/telegram_connection_operations.py"
  "backend/app/runtime/acceptance_evidence.py"
)
test_files=(
  "backend/tests/test_telegram_connection_operations.py"
  "backend/tests/test_acceptance_evidence.py"
)

"$uv_bin" run ruff check "${app_files[@]}" "${test_files[@]}"
"$uv_bin" run ruff format --check "${app_files[@]}" "${test_files[@]}"
"$uv_bin" run mypy "${app_files[@]}"
"$uv_bin" run pytest "${test_files[@]}"
printf '%s\n' "PASS SPEC-022 connection operations and content-safe evidence bundles use fake adapters only."
