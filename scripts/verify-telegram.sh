#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"

if [[ "${JANUARY_TELEGRAM_ENABLED:-false}" != "true" ]] || [[ -z "${JANUARY_TELEGRAM_BOT_TOKEN:-}" ]]; then
  printf '%s\n' "Set JANUARY_TELEGRAM_ENABLED=true and JANUARY_TELEGRAM_BOT_TOKEN before verification." >&2
  exit 1
fi

PYTHONPATH="$project_root/backend" "$(resolve_uv "$project_root")" run python -c '
import asyncio
from app.core.config import Settings
from app.infrastructure.telegram.adapter import TelegramAdapter
async def main():
    adapter = TelegramAdapter(Settings())
    try:
        identity = await adapter.verify_identity()
        print(f"Telegram bot verified: id={identity.external_bot_id} username={identity.username} name={identity.display_name}")
    finally:
        await adapter.aclose()
asyncio.run(main())
'
