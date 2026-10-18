#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$project_root")"
export PYTHONPATH="$project_root/backend${PYTHONPATH:+:$PYTHONPATH}"

if [[ "${1:-}" != "--live" ]]; then
  "$uv_bin" run python - <<'PY'
from app.core.config import Settings

settings = Settings()
if not settings.telegram_enabled or settings.telegram_bot_token is None:
    raise SystemExit("Telegram delivery is disabled; set configuration before optional --live verification.")
if not settings.telegram_delivery_test_chat_id:
    raise SystemExit("JANUARY_TELEGRAM_DELIVERY_TEST_CHAT_ID is required for optional --live verification.")
if not settings.telegram_live_delivery_verification_enabled:
    raise SystemExit("JANUARY_TELEGRAM_LIVE_DELIVERY_VERIFICATION_ENABLED=true is required for optional --live verification.")
print("Telegram delivery configuration is present. Re-run with --live --confirm-live-send to send one synthetic message.")
PY
  exit 0
fi

if [[ "${2:-}" != "--confirm-live-send" ]]; then
  printf '%s\n' "--live requires --confirm-live-send; no Telegram request was made." >&2
  exit 2
fi

"$uv_bin" run python - <<'PY'
import asyncio

from app.application.ports.platform import SendTextRequest
from app.core.config import Settings
from app.infrastructure.telegram.adapter import TelegramAdapter


async def main() -> None:
    settings = Settings()
    if not settings.telegram_enabled or settings.telegram_bot_token is None:
        raise SystemExit("JANUARY_TELEGRAM_ENABLED=true and a bot token are required.")
    if not settings.telegram_delivery_test_chat_id:
        raise SystemExit("JANUARY_TELEGRAM_DELIVERY_TEST_CHAT_ID is required.")
    if not settings.telegram_live_delivery_verification_enabled:
        raise SystemExit("JANUARY_TELEGRAM_LIVE_DELIVERY_VERIFICATION_ENABLED=true is required.")
    adapter = TelegramAdapter(settings)
    try:
        await adapter.verify_identity()
        await adapter.send_text(SendTextRequest(
            conversation_id=settings.telegram_delivery_test_chat_id,
            text="[January SPEC-007 synthetic delivery verification]",
        ))
    finally:
        await adapter.aclose()
    print("Synthetic Telegram delivery verification completed.")


asyncio.run(main())
PY
