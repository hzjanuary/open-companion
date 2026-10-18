#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$root")"

"$uv_bin" run pytest \
  backend/tests/test_ambient.py \
  backend/tests/test_conversation_eligibility.py \
  backend/tests/test_telegram_commands.py \
  backend/tests/test_planning_service.py \
  backend/tests/test_observability.py
JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}" "$root/scripts/validate-db.sh"
JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5433}" \
JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6380}" \
  "$root/scripts/validate-ingress.sh"
"$uv_bin" run ruff check backend/app
echo "Ambient participation checks: valid"
