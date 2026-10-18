#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$root")"

"$uv_bin" run pytest \
  backend/tests/test_summary.py \
  backend/tests/test_conversation_context.py \
  backend/tests/test_observability.py
JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}" "$root/scripts/validate-db.sh"
"$uv_bin" run ruff check backend/app
"$uv_bin" run mypy backend/app
echo "Conversation summary checks: valid (synthetic, no provider or Telegram I/O)"
