#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$root/scripts/lib/resolve-uv.sh"
source "$root/scripts/lib/db-ready.sh"
uv_bin="$(resolve_uv "$root")"
repository_only=false
if [ "${1:-}" = "--repository-only" ]; then
  repository_only=true
elif [ "$#" -ne 0 ]; then
  printf 'usage: %s [--repository-only]\n' "$0" >&2
  exit 2
fi
env -u JANUARY_ENVIRONMENT "$uv_bin" run pytest \
  backend/tests/test_scheduling.py \
  backend/tests/test_proactive_scheduler_worker.py \
  backend/tests/test_telegram_commands.py \
  backend/tests/test_config.py \
  backend/tests/test_observability.py -q

env -u JANUARY_ENVIRONMENT "$uv_bin" run python - "$root" <<'PY'
import ast
from pathlib import Path
import sys

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "backend"))
from app.infrastructure.telemetry import PROHIBITED_LABEL_NAMES

prohibited = set(PROHIBITED_LABEL_NAMES) | {
    "reminder_text", "timezone_name", "public_id"
}
targets = (
    root / "backend/app/infrastructure/database/scheduling.py",
    root / "backend/app/runtime/proactive_scheduler_worker.py",
    root / "backend/app/runtime/telegram_command_worker.py",
    root / "backend/app/runtime/outbound_delivery_worker.py",
)
for target in targets:
    tree = ast.parse(target.read_text(), filename=str(target))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"increment", "observe", "set_gauge"}:
            continue
        if any(keyword.arg is None for keyword in node.keywords):
            raise SystemExit(f"dynamic metric labels are not allowed: {target}")
        unsafe = prohibited.intersection(
            keyword.arg for keyword in node.keywords if keyword.arg is not None
        )
        if unsafe:
            raise SystemExit(
                f"prohibited scheduling metric labels in {target}: {sorted(unsafe)}"
            )
PY

if "$repository_only"; then
  printf '%s\n' \
    "Repository scheduling proof passed; PostgreSQL/Redis/migration/runtime proof PENDING (exit 2)." >&2
  exit 2
fi

export COMPOSE_PROJECT_NAME="${JANUARY_SPEC029_COMPOSE_PROJECT_NAME:-january-spec029-validation}"
export JANUARY_DB_HOST_PORT="${JANUARY_DB_HOST_PORT:-5442}"
export JANUARY_REDIS_HOST_PORT="${JANUARY_REDIS_HOST_PORT:-6389}"
export JANUARY_ENVIRONMENT=test JANUARY_DATABASE_HOST=127.0.0.1
export JANUARY_DATABASE_PORT="${JANUARY_DB_HOST_PORT:-5432}"
export JANUARY_REDIS_URL="redis://127.0.0.1:${JANUARY_REDIS_HOST_PORT:-6379}/0"

if ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' "Docker Compose is required for scheduling integration validation." >&2
  exit 1
fi

guard_log=""
cleanup() {
  result=$?
  trap - EXIT
  if [ -n "$guard_log" ] && [ -f "$guard_log" ]; then
    rm -f "$guard_log"
  fi
  if ! docker compose down -v --remove-orphans; then
    printf '%s\n' "SPEC-029 temporary project cleanup failed." >&2
    result=1
  fi
  exit "$result"
}
trap cleanup EXIT

docker compose up --detach database redis
pg_ready && redis_ready || { printf '%s\n' "PostgreSQL or Redis did not become ready." >&2; exit 1; }

"$uv_bin" run alembic upgrade 0019_telegram_media
"$uv_bin" run alembic upgrade 0020_proactive_scheduling
"$uv_bin" run alembic downgrade 0019_telegram_media
"$uv_bin" run alembic upgrade 0020_proactive_scheduling
# The historical SPEC-029 cycle above proves its own migration boundary. Run
# current integration fixtures against the repository head so newer model
# columns and cross-spec invariants are present.
"$uv_bin" run alembic upgrade head
"$uv_bin" run pytest -m scheduling_integration -q

# Scheduling fixtures use only the reserved legacy tenant. Normalize the newer
# SPEC-030 presentation/revision fields so the downgrade reaches and proves the
# SPEC-029 data-loss guard rather than stopping at the newer guard first.
docker compose exec -T database psql -v ON_ERROR_STOP=1 -U january -d january <<'SQL'
UPDATE control_tenants SET revision = 1;
UPDATE assistants
   SET revision = 1,
       slug = 'assistant-' || replace(id::text, '-', '')
 WHERE tenant_id = '00000000-0000-4000-8000-000000000030'::uuid
   AND status <> 'retired';
UPDATE platform_connections SET revision = 1 WHERE status <> 'retired';
SQL
guard_log="$(mktemp "${TMPDIR:-/tmp}/spec029-downgrade-guard.XXXXXX")"
if "$uv_bin" run alembic downgrade 0019_telegram_media >"$guard_log" 2>&1; then
  printf '%s\n' "schedule-bearing downgrade unexpectedly succeeded" >&2
  exit 1
fi
grep -q "SPEC-029 schedule state blocks downgrade" "$guard_log"
rm -f "$guard_log"
guard_log=""

PYTHONPATH=backend "$uv_bin" run python - <<'PY'
import asyncio
from sqlalchemy import text
from app.core.config import Settings
from app.infrastructure.database.database import Database

async def main() -> None:
    database = Database(Settings(_env_file=None, environment="test"))
    await database.start()
    try:
        async with database.engine.begin() as connection:
            await connection.execute(text("TRUNCATE assistants CASCADE"))
    finally:
        await database.stop()

asyncio.run(main())
PY
"$uv_bin" run alembic downgrade 0019_telegram_media
"$uv_bin" run alembic upgrade 0020_proactive_scheduling
"$uv_bin" run alembic current | grep -q '0020_proactive_scheduling'
"$uv_bin" run alembic downgrade base
"$uv_bin" run alembic upgrade head
"$uv_bin" run alembic current | grep -q '0026_conversation_feedback'

printf '%s\n' "SPEC-029 proactive scheduling validation: passed"
