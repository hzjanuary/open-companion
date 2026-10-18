#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$root")"
mode="${1:---offline}"

production_config() {
  PYTHONPATH="$root/backend" "$uv_bin" run python - <<'PY'
import os
import sys
from uuid import UUID

from pydantic import ValidationError

from app.core.config import Settings


def fail(message: str) -> None:
    print(f"Production configuration invalid: {message}", file=sys.stderr)
    raise SystemExit(1)


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        fail(f"{name} must be explicitly set")
    return value


def placeholder(name: str, value: str) -> None:
    normalized = value.strip().lower()
    markers = (
        "change-me",
        "changeme",
        "placeholder",
        "example.invalid",
        "synthetic",
        "test-only",
        "fake-",
        "dummy",
        "january-local",
    )
    if any(marker in normalized for marker in markers):
        fail(f"{name} contains an obvious placeholder")


if required_environment("JANUARY_ENVIRONMENT") != "production":
    fail("JANUARY_ENVIRONMENT must equal production")

database_url = os.environ.get("JANUARY_DATABASE_URL", "").strip()
if database_url:
    placeholder("JANUARY_DATABASE_URL", database_url)
else:
    for variable in (
        "JANUARY_DATABASE_HOST",
        "JANUARY_DATABASE_NAME",
        "JANUARY_DATABASE_USER",
        "JANUARY_DATABASE_PASSWORD",
    ):
        placeholder(variable, required_environment(variable))

for variable in (
    "JANUARY_REDIS_URL",
    "JANUARY_TELEGRAM_BOT_TOKEN",
    "JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID",
    "JANUARY_CONTROL_PLANE_JWT_SECRET",
    "JANUARY_CONTROL_PLANE_JWT_ISSUER",
    "JANUARY_CONTROL_PLANE_JWT_AUDIENCE",
):
    placeholder(variable, required_environment(variable))

try:
    settings = Settings(_env_file=None)
except ValidationError as error:
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"])
        print(f"Production configuration invalid: {location}: {item['msg']}", file=sys.stderr)
    raise SystemExit(1) from None

required_true = {
    "telegram_enabled": settings.telegram_enabled,
    "llm_enabled": settings.llm_enabled,
    "rate_limit_enabled": settings.rate_limit_enabled,
    "provider_concurrency_enabled": settings.provider_concurrency_enabled,
    "provider_governance_worker_enabled": settings.provider_governance_worker_enabled,
    "command_worker_enabled": settings.command_worker_enabled,
    "outbound_delivery_enabled": settings.outbound_delivery_enabled,
    "retention_worker_enabled": settings.retention_worker_enabled,
    "data_governance_enabled": settings.data_governance_enabled,
    "governance_worker_enabled": settings.governance_worker_enabled,
    "control_plane_enabled": settings.control_plane_enabled,
    "safety_moderation_enabled": settings.safety_moderation_enabled,
    "metrics_enabled": settings.metrics_enabled,
}
disabled = [name for name, enabled in required_true.items() if not enabled]
if disabled:
    fail("required Telegram-first controls are disabled: " + ", ".join(disabled))
if settings.telegram_delivery_mode not in {"webhook", "polling"}:
    fail("telegram_delivery_mode must be webhook or polling")
if settings.telegram_delivery_mode == "webhook":
    for variable in (
        "JANUARY_TELEGRAM_WEBHOOK_SECRET_TOKEN",
        "JANUARY_TELEGRAM_WEBHOOK_PUBLIC_BASE_URL",
    ):
        placeholder(variable, required_environment(variable))
if settings.provider_governance_mode != "enforce":
    fail("provider_governance_mode must equal enforce")
if not settings.control_plane_deployment_bootstrap_subjects:
    fail("control_plane_deployment_bootstrap_subjects must not be empty")
if settings.telegram_platform_connection_id == UUID(
    "00000000-0000-0000-0000-000000000020"
):
    fail("telegram_platform_connection_id uses the repository synthetic fixture")

for provider in filter(
    None, (settings.llm_primary_provider, settings.llm_fallback_provider)
):
    if provider == "ollama":
        continue
    key_name = f"JANUARY_LLM_{provider.upper()}_API_KEY"
    placeholder(key_name, required_environment(key_name))
if settings.telegram_voice_tts_enabled:
    placeholder(
        "JANUARY_LLM_OPENAI_API_KEY", required_environment("JANUARY_LLM_OPENAI_API_KEY")
    )

print("Production configuration: valid (values redacted; no external I/O)")
PY
}

database_preflight() {
  production_config
  PYTHONPATH="$root/backend" "$uv_bin" run python - "$root" <<'PY'
import asyncio
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings

EXPECTED_HEAD = "0026_conversation_feedback"


def ancestors(script: ScriptDirectory, revision: str) -> set[str]:
    found: set[str] = set()
    pending = [revision]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        node = script.get_revision(current)
        if node is None:
            raise SystemExit("Migration preflight invalid: unknown source revision")
        down = node.down_revision
        if isinstance(down, tuple):
            pending.extend(down)
        elif down is not None:
            pending.append(down)
    return found


async def run() -> None:
    root = Path(sys.argv[1])
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if heads != [EXPECTED_HEAD]:
        raise SystemExit("Migration preflight invalid: unexpected source heads")
    allowed = ancestors(script, EXPECTED_HEAD)
    settings = Settings(_env_file=None)
    engine = create_async_engine(
        settings.resolved_database_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=settings.database_connect_timeout_seconds,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={
            "timeout": settings.database_connect_timeout_seconds,
            "command_timeout": settings.database_connect_timeout_seconds,
        },
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            revision_rows = await connection.scalars(
                text("SELECT version_num FROM alembic_version")
            )
            revisions = list(revision_rows)
    except Exception:
        raise SystemExit(
            "Migration preflight invalid: database unavailable or revision query failed "
            "(details redacted)"
        ) from None
    finally:
        await engine.dispose()
    if len(revisions) != 1 or revisions[0] not in allowed:
        raise SystemExit(
            "Migration preflight invalid: database revision is absent or not on "
            "the approved upgrade path"
        )
    print(f"Migration preflight: current={revisions[0]} target={EXPECTED_HEAD}")


asyncio.run(run())
PY
}

offline() {
  "$uv_bin" run python - "$root" <<'PY'
import ast
import os
import re
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
config_path = root / "backend/app/core/config.py"
tree = ast.parse(config_path.read_text())
settings_names: list[str] = []
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "Settings":
        settings_names = [
            f"JANUARY_{item.target.id.upper()}"
            for item in node.body
            if isinstance(item, ast.AnnAssign)
            and isinstance(item.target, ast.Name)
        ]
        break
if not settings_names:
    raise SystemExit("Settings inventory not found")

example = (root / ".env.example").read_text()
example_names = re.findall(r"^(JANUARY_[A-Z0-9_]+)=", example, re.MULTILINE)
if len(example_names) != len(set(example_names)):
    raise SystemExit(".env.example contains duplicate variables")
missing = sorted(set(settings_names) - set(example_names))
extra = sorted(set(example_names) - set(settings_names))
if missing or extra:
    raise SystemExit(
        ".env.example inventory mismatch; missing="
        + ",".join(missing)
        + " extra="
        + ",".join(extra)
    )
inventory = (
    root / "docs/runbooks/telegram-first-release-readiness.md"
).read_text()
documented_names = set(re.findall(r"JANUARY_[A-Z0-9_]+", inventory))
undocumented = sorted(set(settings_names) - documented_names)
if undocumented:
    raise SystemExit(
        "release configuration inventory is incomplete: "
        + ",".join(undocumented)
    )

dockerignore = (root / ".dockerignore").read_text().splitlines()
for required in (".git", ".venv", ".env", "docs"):
    if required not in dockerignore:
        raise SystemExit(f".dockerignore must exclude {required}")
dockerfile = (root / "Dockerfile").read_text()
for required in (
    "python:3.12-slim",
    "uv sync --locked --no-dev",
    "USER january",
    'CMD ["uvicorn", "app.main:app"',
):
    if required not in dockerfile:
        raise SystemExit(f"Dockerfile contract missing: {required}")

workflow = (root / ".github/workflows/ci.yml").read_text()
if "continue-on-error" in workflow:
    raise SystemExit("Quality workflow must not use continue-on-error")
direct_scripts = sorted(set(re.findall(r"\./(scripts/[a-z0-9-]+\.sh)", workflow)))
if not direct_scripts:
    raise SystemExit("Quality workflow direct scripts not found")
for relative in direct_scripts + ["scripts/validate-production-readiness.sh"]:
    mode = stat.S_IMODE(os.stat(root / relative).st_mode)
    if mode != 0o755:
        raise SystemExit(f"direct validator is not mode 100755: {relative}")

staging = (root / "compose.staging.yaml").read_text()
for forbidden in ("january-local", "password: january", ".env.production"):
    if forbidden in staging:
        raise SystemExit(f"staging contains unsafe default: {forbidden}")
for required in (
    'JANUARY_SAFETY_MODERATION_ENABLED: "true"',
    'JANUARY_RATE_LIMIT_ENABLED: "true"',
    'JANUARY_CONTROL_PLANE_ENABLED: "true"',
    'JANUARY_RETENTION_WORKER_ENABLED: "true"',
    "service_completed_successfully",
    "127.0.0.1:${JANUARY_STAGING_HTTP_PORT",
):
    if required not in staging:
        raise SystemExit(f"staging release contract missing: {required}")

print(
    f"Release static contracts: valid ({len(settings_names)} settings; "
    f"{len(direct_scripts)} direct Quality scripts)"
)
PY
  "$root/scripts/validate-deployment.sh"
  "$uv_bin" run pytest \
    "$root/backend/tests/test_config.py" \
    "$root/backend/tests/test_lifecycle.py" \
    "$root/backend/tests/test_http.py" -q
  heads="$($uv_bin run alembic heads)"
  if [[ "$heads" != "0026_conversation_feedback (head)" ]]; then
    echo "Unexpected Alembic head: $heads" >&2
    exit 1
  fi
  echo "Production readiness validation: valid (offline; no external I/O)"
}

case "$mode" in
  --offline)
    offline
    ;;
  --production-config)
    production_config
    ;;
  --database-preflight)
    database_preflight
    ;;
  --help)
    echo "usage: $0 [--offline|--production-config|--database-preflight]"
    ;;
  *)
    echo "unknown mode: $mode" >&2
    exit 2
    ;;
esac
