"""Explicit live Telegram identity reconciliation for the local demo."""

import argparse
import asyncio
import json

from app.core.config import Settings
from app.infrastructure.database.bootstrap import SqlAlchemyOperatorBootstrap
from app.infrastructure.database.database import Database
from app.infrastructure.telegram.adapter import TelegramAdapter


async def run_bootstrap(
    settings: Settings, adapter: TelegramAdapter
) -> dict[str, object]:
    database = Database(settings)
    await database.start()
    try:
        result = await SqlAlchemyOperatorBootstrap(database.session_factory).reconcile(
            settings, await adapter.verify_identity()
        )
        return {
            "assistant_id": str(result.assistant_id),
            "platform_connection_id": str(result.platform_connection_id),
            "external_bot_id": result.external_bot_id,
            "username": result.username,
            "display_name": result.display_name,
            "can_join_groups": result.can_join_groups,
            "can_read_all_group_messages": result.can_read_all_group_messages,
            "env_assignment": (
                "JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID="
                f"{result.platform_connection_id}"
            ),
        }
    finally:
        await database.stop()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-live-telegram", action="store_true")
    parser.add_argument("--json", action="store_true")
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
    adapter = TelegramAdapter(settings)
    try:
        result = await run_bootstrap(settings, adapter)
    finally:
        await adapter.aclose()
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
