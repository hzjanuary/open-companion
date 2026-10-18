#!/usr/bin/env bash
# Offline metadata identity only. Never authorizes deployment or external I/O.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$root")"
if [[ $# -ne 0 ]]; then
  echo "usage: $0 (configuration via approved environment injection only)" >&2
  exit 2
fi
PYTHONPATH="$root/backend" "$uv_bin" run python - <<'PY'
import hashlib
import json
import os
import sys

from pydantic import ValidationError

from app.core.config import Settings

try:
    settings = Settings(_env_file=None)
except ValidationError:
    print("Configuration fingerprint unavailable: invalid settings (values redacted)", file=sys.stderr)
    raise SystemExit(1) from None

# Reuse the existing runtime allowlist, not model_dump or URL/identity values.
# Presence is explicit injection presence, not a hash of secret material.
secret_names = (
    "JANUARY_DATABASE_PASSWORD", "JANUARY_DATABASE_URL", "JANUARY_REDIS_URL",
    "JANUARY_TELEGRAM_BOT_TOKEN", "JANUARY_TELEGRAM_WEBHOOK_SECRET_TOKEN",
    "JANUARY_LLM_OPENAI_API_KEY", "JANUARY_LLM_GEMINI_API_KEY",
    "JANUARY_LLM_GROQ_API_KEY", "JANUARY_LLM_OPENROUTER_API_KEY",
    "JANUARY_CONTROL_PLANE_JWT_SECRET",
)
metadata = {
    "schema_version": 1,
    "runtime_metadata": settings.safe_configuration_fingerprint(),
    "secret_injection_presence": {
        name: bool(os.environ.get(name, "").strip()) for name in secret_names
    },
}
canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
print(json.dumps({
    "schema_version": 1,
    "scope": "allowlisted runtime metadata and secret injection presence only",
    "sha256": hashlib.sha256(canonical.encode()).hexdigest(),
}, sort_keys=True))
PY
