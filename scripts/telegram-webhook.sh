#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"

action="${1:-inspect}"
if [[ "$action" != "register" && "$action" != "inspect" && "$action" != "remove" ]]; then
  printf '%s\n' "Usage: $0 {register|inspect|remove} [--drop-pending-updates]" >&2
  exit 2
fi
if [[ "$action" == "remove" && "${2:-}" != "" && "${2:-}" != "--drop-pending-updates" ]]; then
  printf '%s\n' "Use --drop-pending-updates only to explicitly discard Telegram pending updates." >&2
  exit 2
fi

PYTHONPATH="$project_root/backend" "$(resolve_uv "$project_root")" run python - "$action" "${2:-}" <<'PY'
import asyncio
import sys

from app.core.config import Settings
from app.infrastructure.telegram.adapter import create_telegram_adapter

async def main() -> None:
    action, drop_flag = sys.argv[1:]
    settings = Settings()
    if not settings.telegram_enabled or settings.telegram_bot_token is None:
        raise RuntimeError("Set JANUARY_TELEGRAM_ENABLED=true and JANUARY_TELEGRAM_BOT_TOKEN first.")
    if settings.telegram_platform_connection_id is None:
        raise RuntimeError("Set JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID first.")
    adapter = create_telegram_adapter(settings)
    assert adapter is not None
    try:
        if action == "inspect":
            info = await adapter.get_webhook_info()
            print(f"Webhook configured={bool(info.url)} pending_updates={info.pending_update_count}")
        elif action == "register":
            if settings.telegram_webhook_public_base_url is None or settings.telegram_webhook_secret_token is None:
                raise RuntimeError("Webhook registration requires HTTPS public URL and secret token configuration.")
            url = f"{settings.telegram_webhook_public_base_url}/api/v1/platforms/telegram/webhook/{settings.telegram_platform_connection_id}"
            await adapter.set_webhook(url=url, secret_token=settings.telegram_webhook_secret_token.get_secret_value(), allowed_updates=settings.telegram_allowed_updates, max_connections=settings.telegram_webhook_max_connections)
            print("Webhook registration requested.")
        else:
            await adapter.delete_webhook(drop_pending_updates=drop_flag == "--drop-pending-updates")
            print("Webhook removal requested.")
    finally:
        await adapter.aclose()

try:
    asyncio.run(main())
except RuntimeError as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(1) from None
PY
