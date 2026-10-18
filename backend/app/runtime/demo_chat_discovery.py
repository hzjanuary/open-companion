"""Explicit, non-destructive Telegram chat discovery for a stopped local demo."""

import argparse
import asyncio
import json

from app.core.config import Settings
from app.infrastructure.telegram.adapter import TelegramAdapter
from app.runtime.telegram_connection_operations import load_approved_bot_id


def _safe_chat(update: object) -> dict[str, object] | None:
    raw = getattr(update, "raw_payload", None)
    if not isinstance(raw, dict):
        return None
    payload = next(
        (
            value
            for key, value in raw.items()
            if key != "update_id" and isinstance(value, dict)
        ),
        None,
    )
    chat = payload.get("chat") if isinstance(payload, dict) else None
    if not isinstance(chat, dict) or isinstance(chat.get("id"), bool):
        return None
    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return None
    label = chat.get("title") or chat.get("first_name") or chat.get("type")
    thread_id = payload.get("message_thread_id") if isinstance(payload, dict) else None
    return {
        "update_id": getattr(update, "update_id", None),
        "chat_id": str(chat_id),
        "chat_type": chat.get("type"),
        "display_label": label if isinstance(label, str) else None,
        "thread_id": str(thread_id) if isinstance(thread_id, int) else None,
    }


async def discover(
    settings: Settings, adapter: TelegramAdapter
) -> list[dict[str, object]]:
    info = await adapter.get_webhook_info()
    if info.url:
        raise RuntimeError("refusing discovery while a Telegram webhook is configured")
    # An omitted offset asks Telegram to retain the updates. This command never
    # touches January's durable cursor and never acknowledges/deletes updates.
    updates = await adapter.get_updates(
        offset=None,
        limit=settings.telegram_poll_batch_limit,
        timeout_seconds=1,
        allowed_updates=settings.telegram_allowed_updates,
    )
    return [item for update in updates if (item := _safe_chat(update)) is not None]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-live-telegram", action="store_true")
    args = parser.parse_args()
    if not args.confirm_live_telegram:
        parser.error(
            "--confirm-live-telegram is required; no Telegram request was made"
        )
    settings = Settings()
    if not settings.demo_live_enabled:
        parser.error("JANUARY_DEMO_LIVE_ENABLED=true is required")
    if not settings.demo_live_telegram_verification_enabled:
        parser.error("JANUARY_DEMO_LIVE_TELEGRAM_VERIFICATION_ENABLED=true is required")
    if await load_approved_bot_id(settings) is None:
        parser.error("an active approved Telegram connection is required")
    adapter = TelegramAdapter(settings)
    try:
        for item in await discover(settings, adapter):
            print(json.dumps(item, sort_keys=True))
    finally:
        await adapter.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
