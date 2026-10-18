#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$root")"
export COMPOSE_PROJECT_NAME="january-spec020"
export JANUARY_BACKEND_IMAGE="january-backend:spec-020-validation"
export JANUARY_DATABASE_NAME="january_staging"
export JANUARY_DATABASE_USER="january_staging"
export JANUARY_DATABASE_PASSWORD="synthetic-staging-password"
export JANUARY_TELEGRAM_BOT_TOKEN="synthetic-bot-token"
export JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID="00000000-0000-0000-0000-000000000020"
export JANUARY_TELEGRAM_WEBHOOK_SECRET_TOKEN="synthetic-webhook-secret"
export JANUARY_TELEGRAM_WEBHOOK_PUBLIC_BASE_URL="https://staging.example.invalid"
export JANUARY_LLM_OPENAI_MODEL="synthetic-model"
export JANUARY_LLM_OPENAI_API_KEY="synthetic-provider-key"
export JANUARY_CONTROL_PLANE_JWT_SECRET="synthetic-control-plane-secret-value"
export JANUARY_CONTROL_PLANE_JWT_ISSUER="https://issuer.example.invalid"
export JANUARY_CONTROL_PLANE_JWT_AUDIENCE="january-staging"
export JANUARY_CONTROL_PLANE_DEPLOYMENT_BOOTSTRAP_SUBJECTS='["deployment-root"]'
export JANUARY_PROVIDER_GOVERNANCE_MODE="observe"

# This validator renders configuration only and starts no containers. It must
# never tear down an existing operator staging project on exit.

docker compose -f "$root/compose.staging.yaml" config >/dev/null
env -u JANUARY_LLM_ENABLED -u JANUARY_TELEGRAM_ENABLED \
  -u JANUARY_OUTBOUND_DELIVERY_ENABLED -u JANUARY_COMMAND_WORKER_ENABLED \
  -u JANUARY_LLM_PRIMARY_PROVIDER -u JANUARY_LLM_OPENAI_MODEL \
  -u JANUARY_LLM_OPENAI_API_KEY \
  -u JANUARY_CONTROL_PLANE_JWT_SECRET -u JANUARY_CONTROL_PLANE_JWT_ISSUER \
  -u JANUARY_CONTROL_PLANE_JWT_AUDIENCE \
  -u JANUARY_CONTROL_PLANE_DEPLOYMENT_BOOTSTRAP_SUBJECTS \
  -u JANUARY_PROVIDER_GOVERNANCE_MODE \
  -u JANUARY_PROVIDER_GOVERNANCE_WORKER_ENABLED \
  "$uv_bin" run pytest backend/tests/test_lifecycle.py backend/tests/test_config.py -q
"$uv_bin" run python - "$root" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
text = (root / "compose.staging.yaml").read_text()
for forbidden in ("january-local", "password: january", ".env.production"):
    if forbidden in text:
        raise SystemExit(f"forbidden staging default: {forbidden}")
required = (
    "migration", "backend", "dispatcher", "conversation", "planning",
    "commands", "outbound", "scheduler", "governance", "retention", "provider-governance",
    "summary", "semantic-memory", "knowledge-index",
    "stop_grace_period",
    "app.runtime.governance_worker", "app.runtime.retention_worker",
    "JANUARY_DATA_GOVERNANCE_ENABLED", "JANUARY_GOVERNANCE_WORKER_ENABLED",
    "JANUARY_RETENTION_WORKER_ENABLED", "restart: unless-stopped",
    "app.runtime.provider_governance_worker",
    "app.runtime.conversation_summary_worker",
    "app.runtime.semantic_memory_index_worker",
    "app.runtime.knowledge_index_worker",
    "JANUARY_PROVIDER_GOVERNANCE_MODE",
    "JANUARY_PROVIDER_GOVERNANCE_WORKER_ENABLED",
    "JANUARY_CONTROL_PLANE_ENABLED", "JANUARY_CONTROL_PLANE_JWT_SECRET",
    "JANUARY_CONTROL_PLANE_DEPLOYMENT_BOOTSTRAP_SUBJECTS",
    "JANUARY_CONVERSATION_SUMMARIES_ENABLED", "JANUARY_SUMMARY_WORKER_ENABLED",
    "JANUARY_SEMANTIC_MEMORY_ENABLED", "JANUARY_SEMANTIC_MEMORY_WORKER_ENABLED",
    "service_completed_successfully",
    "JANUARY_TELEGRAM_MEDIA_ENABLED", "JANUARY_TELEGRAM_MEDIA_PHOTO_MAX_BYTES",
    "JANUARY_TELEGRAM_MEDIA_AUDIO_MAX_BYTES", "JANUARY_PROVIDER_CONCURRENCY_ENABLED",
    "JANUARY_TELEGRAM_MEDIA_TRANSCRIPTION_TIMEOUT_SECONDS",
    "app.runtime.proactive_scheduler_worker",
    "JANUARY_PROACTIVE_SCHEDULING_ENABLED", "JANUARY_SCHEDULER_WORKER_ENABLED",
    "JANUARY_SCHEDULER_OWNER_NAME",
)
missing = [item for item in required if item not in text]
if missing:
    raise SystemExit(f"missing deployment artifact entries: {', '.join(missing)}")
dockerfile = (root / "Dockerfile").read_text()
if "USER january" not in dockerfile:
    raise SystemExit("runtime image must run as the non-root january user")
if "COPY --from=builder --chown=january:january" not in dockerfile:
    raise SystemExit("runtime image files must be owned by the non-root runtime user")
print("Deployment artifact checks: valid")
PY
echo "Deployment validation: valid (configuration and lifecycle proof; no external I/O)"
