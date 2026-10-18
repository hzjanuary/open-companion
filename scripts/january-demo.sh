#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
source "$root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$root")"
demo_env="$root/.env.demo"
runtime_dir="$root/.runtime/january-demo"
export PYTHONPATH="$root/backend${PYTHONPATH:+:$PYTHONPATH}"
# Keep demo-owned containers distinct from other project invocations.  The
# default Compose file and volumes remain unchanged.
export COMPOSE_PROJECT_NAME="january-demo"

load_demo() {
  [[ -f "$demo_env" ]] || { printf '%s\n' "Missing .env.demo. Run: ./scripts/january-demo.sh init" >&2; exit 1; }
  # This file is created locally from the committed template and is intentionally shell-compatible.
  set -a
  source "$demo_env"
  set +a
}

case "${1:-}" in
  init)
    [[ ! -e "$demo_env" ]] || { printf '%s\n' ".env.demo already exists; refusing to overwrite it." >&2; exit 1; }
    cp .env.demo.example "$demo_env"
    chmod 600 "$demo_env"
    printf '%s\n' "Created .env.demo with restrictive permissions. Replace placeholders before live use."
    ;;
  doctor)
    load_demo
    if ! git check-ignore -q .env.demo; then
      printf '%s\n' "FAIL .env.demo must remain ignored by Git." >&2
      exit 1
    fi
    permissions="$(stat -c '%a' "$demo_env")"
    if (( 8#$permissions & 077 )); then
      printf '%s\n' "WARN .env.demo permissions are $permissions; run: chmod 600 .env.demo" >&2
    else
      printf '%s\n' "PASS .env.demo permissions are restrictive ($permissions)."
    fi
    live_telegram=false
    live_provider=false
    for argument in "${@:2}"; do
      case "$argument" in
        --confirm-live-telegram) live_telegram=true ;;
        --confirm-live-provider) live_provider=true ;;
        *) printf '%s\n' "Unknown doctor option: $argument" >&2; exit 2 ;;
      esac
    done
    "$uv_bin" run python - <<'PY'
from app.core.config import Settings
from pydantic import ValidationError
try:
    s = Settings(_env_file='.env.demo')
except ValidationError as error:
    raise SystemExit(f'FAIL demo configuration is invalid: {error.errors()[0]["msg"]}')
if not s.demo_live_enabled:
    raise SystemExit('FAIL demo live mode is disabled; set JANUARY_DEMO_LIVE_ENABLED=true after review.')
if s.telegram_delivery_mode != 'polling':
    raise SystemExit('FAIL demo requires polling mode.')
if not s.demo_allowed_chat_ids or not s.llm_enabled or not s.outbound_delivery_enabled or not s.command_worker_enabled:
    raise SystemExit('FAIL demo allowlist, LLM, outbound delivery, and command worker must be configured.')
if s.telegram_delivery_mode == 'webhook':
    raise SystemExit('FAIL demo polling cannot run while webhook mode is configured.')
print('PASS configuration: polling, allowlist, LLM, outbound delivery, and command worker are enabled.')
PY
    if ! docker compose version >/dev/null 2>&1; then
      printf '%s\n' "FAIL Docker Compose is required for the local PostgreSQL and Redis demo services." >&2
      exit 1
    fi
    printf '%s\n' "PASS local prerequisites: Docker Compose is available."
    if [[ "$live_telegram" == true ]]; then
      [[ "${JANUARY_DEMO_LIVE_TELEGRAM_VERIFICATION_ENABLED:-false}" == "true" ]] || { printf '%s\n' "FAIL set JANUARY_DEMO_LIVE_TELEGRAM_VERIFICATION_ENABLED=true before live Telegram checks." >&2; exit 1; }
      "$uv_bin" run python - <<'PY'
import asyncio
from app.core.config import Settings
from app.infrastructure.telegram.adapter import TelegramAdapter

async def main() -> None:
    adapter = TelegramAdapter(Settings())
    try:
        identity = await adapter.verify_identity()
        info = await adapter.get_webhook_info()
        print(f"PASS Telegram identity: bot_id={identity.external_bot_id} username={identity.username or 'none'}")
        print(f"PASS Telegram capabilities: can_join_groups={identity.can_join_groups} can_read_all_group_messages={identity.can_read_all_group_messages}")
        if info.url:
            raise SystemExit("FAIL polling blocked: Telegram webhook is active; January will not remove it automatically.")
        print("PASS Telegram polling prerequisite: no active webhook. Privacy mode supports DM, mentions, and replies.")
    finally:
        await adapter.aclose()

asyncio.run(main())
PY
    fi
    if [[ "$live_provider" == true ]]; then
      JANUARY_LLM_LIVE_VERIFICATION_ENABLED=true "$root/scripts/verify-model-provider.sh" --live
    fi
    ;;
  bootstrap)
    load_demo
    [[ "${2:-}" == "--confirm-live-telegram" ]] || { printf '%s\n' "bootstrap requires --confirm-live-telegram" >&2; exit 2; }
    "$uv_bin" run python -m app.runtime.operator_bootstrap --confirm-live-telegram
    ;;
  discover-chats)
    load_demo
    [[ ! -e "$runtime_dir/pids" ]] || { printf '%s\n' "Stop the demo stack before discovering chats." >&2; exit 1; }
    [[ "${2:-}" == "--confirm-live-telegram" ]] || { printf '%s\n' "discover-chats requires --confirm-live-telegram" >&2; exit 2; }
    "$uv_bin" run python -m app.runtime.demo_chat_discovery --confirm-live-telegram
    printf '%s\n' "Copy an intended chat_id into .env.demo manually; discovery never changes the allowlist or polling cursor."
    ;;
  up)
    load_demo
    [[ "${2:-}" == "--confirm-live-demo" ]] || { printf '%s\n' "up requires --confirm-live-demo" >&2; exit 2; }
    [[ "${JANUARY_DEMO_LIVE_ENABLED:-false}" == "true" ]] || { printf '%s\n' "JANUARY_DEMO_LIVE_ENABLED=true is required." >&2; exit 1; }
    [[ ! -e "$runtime_dir/pids" ]] || { printf '%s\n' "Demo stack already has PID metadata; run down first." >&2; exit 1; }
    "$0" doctor
    "$0" bootstrap --confirm-live-telegram
    mkdir -p "$runtime_dir/logs"
    docker compose up --detach --wait database redis
    "$uv_bin" run alembic upgrade head
    : > "$runtime_dir/pids"
    launch() { name="$1"; shift; nohup "$@" >"$runtime_dir/logs/$name.log" 2>&1 & echo "$! $name" >> "$runtime_dir/pids"; }
    launch api "$uv_bin" run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "${JANUARY_HOST_PORT:-8000}"
    launch poller "$uv_bin" run python -m app.runtime.telegram_poller
    launch dispatcher "$uv_bin" run python -m app.runtime.ingress_outbox_dispatcher
    launch conversation "$uv_bin" run python -m app.runtime.conversation_worker
    launch planning "$uv_bin" run python -m app.runtime.response_planning_worker
    launch commands "$uv_bin" run python -m app.runtime.telegram_command_worker
    launch outbound "$uv_bin" run python -m app.runtime.outbound_delivery_worker
    if [[ "${JANUARY_GOVERNANCE_WORKER_ENABLED:-false}" == "true" && "${JANUARY_DATA_GOVERNANCE_ENABLED:-false}" == "true" ]]; then
      launch governance "$uv_bin" run python -m app.runtime.governance_worker
    fi
    if [[ "${JANUARY_RETENTION_WORKER_ENABLED:-false}" == "true" ]]; then
      launch retention "$uv_bin" run python -m app.runtime.retention_worker
    fi
    sleep 1
    while read -r pid name; do kill -0 "$pid" 2>/dev/null || { "$0" down; printf '%s\n' "$name exited during startup" >&2; exit 1; }; done < "$runtime_dir/pids"
    printf '%s\n' "Demo stack started. Run status or logs; no synthetic Telegram message was sent."
    ;;
  status)
    [[ -f "$runtime_dir/pids" ]] || { printf '%s\n' "Demo stack is not running."; exit 0; }
    load_demo
    if curl --silent --fail --max-time 2 "http://127.0.0.1:${JANUARY_HOST_PORT:-8000}/health" >/dev/null; then
      printf '%s\n' "api=healthy"
    else
      printf '%s\n' "api=unreachable"
    fi
    docker compose ps --format 'table {{.Name}}\t{{.Status}}'
    while read -r pid name; do if kill -0 "$pid" 2>/dev/null; then echo "$name=running"; else echo "$name=stopped"; fi; done < "$runtime_dir/pids"
    "$uv_bin" run alembic current
    "$uv_bin" run python - <<'PY'
from app.core.config import Settings
s = Settings()
model = getattr(s, f"llm_{s.llm_primary_provider}_model")
print(f"provider={s.llm_primary_provider} model={model}")
print(f"allowed_chat_ids={','.join(s.demo_allowed_chat_ids)}")
PY
    "$uv_bin" run python -m app.runtime.demo_inspector --json
    ;;
  logs)
    [[ -d "$runtime_dir/logs" ]] || { printf '%s\n' "No demo logs." >&2; exit 1; }
    tail -n 100 "$runtime_dir/logs"/*.log
    ;;
  inspect)
    load_demo
    "$uv_bin" run python -m app.runtime.demo_inspector
    ;;
  down)
    if [[ -f "$runtime_dir/pids" ]]; then
      while read -r pid name; do kill "$pid" 2>/dev/null || true; done < "$runtime_dir/pids"
      rm -f "$runtime_dir/pids"
    fi
    docker compose stop database redis >/dev/null 2>&1 || true
    printf '%s\n' "Stopped only demo-owned processes and project database/Redis containers; volumes were preserved."
    ;;
  *)
    printf '%s\n' "Usage: $0 {init|doctor|discover-chats|bootstrap|up|status|inspect|logs|down}" >&2
    exit 2
    ;;
esac
