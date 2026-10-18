#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$project_root")"

"$uv_bin" run pytest
"$uv_bin" run ruff check backend
"$uv_bin" run ruff format --check backend
"$uv_bin" run mypy
if [ -x scripts/bin/harness ]; then
  scripts/bin/harness status
  scripts/bin/harness doctor
else
  echo "harness binary not found (gitignored), skipping harness checks"
fi

if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git diff --check
fi
