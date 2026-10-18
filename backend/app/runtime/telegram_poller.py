"""Controlled Telegram long-polling runtime; never started by the API process."""

import asyncio
import logging
from datetime import UTC, datetime

from app.application.ports.platform import PlatformAdapterError
from app.core.config import Settings
from app.domain.persistence import IngressSource
from app.infrastructure.database.database import Database
from app.infrastructure.database.ingress import SqlAlchemyDurableIngressRepository
from app.infrastructure.telegram.adapter import TelegramAdapter, create_telegram_adapter
from app.runtime.lifecycle import RuntimeLifecycle


async def poll_once(
    settings: Settings,
    database: Database,
    adapter: TelegramAdapter,
) -> int:
    if settings.telegram_delivery_mode != "polling" or (
        settings.telegram_platform_connection_id is None
    ):
        raise RuntimeError(
            "telegram_delivery_mode=polling and a platform connection are required"
        )
    repository = SqlAlchemyDurableIngressRepository(
        database.session_factory, settings.ingress_event_schema_version
    )
    offset = await repository.polling_offset(settings.telegram_platform_connection_id)
    info = await adapter.get_webhook_info()
    if info.url:
        raise RuntimeError("refusing to poll while a Telegram webhook is configured")
    updates = await adapter.get_updates(
        offset=offset,
        limit=settings.telegram_poll_batch_limit,
        timeout_seconds=settings.telegram_poll_timeout_seconds,
        allowed_updates=settings.telegram_allowed_updates,
    )
    if not updates:
        return 0
    next_offset = str(max(int(update.update_id) for update in updates) + 1)
    envelopes = tuple(
        update.to_ingress(
            platform_connection_id=settings.telegram_platform_connection_id,
            ingress_source=IngressSource.POLLING,
            received_at=datetime.now(UTC),
        )
        for update in updates
    )
    await repository.accept_batch_and_advance_cursor(envelopes, next_offset)
    return len(updates)


async def run() -> None:
    settings = Settings()
    database = Database(settings)
    adapter = create_telegram_adapter(settings)
    if adapter is None:
        raise RuntimeError("Telegram must be enabled to run the polling runtime")
    await database.start()
    delay = settings.telegram_poll_retry_backoff_seconds
    lifecycle = RuntimeLifecycle("telegram_poller")
    lifecycle.install()
    try:
        while not lifecycle.stopping:
            try:
                await poll_once(settings, database, adapter)
                delay = settings.telegram_poll_retry_backoff_seconds
            except asyncio.CancelledError:
                raise
            except PlatformAdapterError as error:
                if not error.retryable:
                    raise RuntimeError("Telegram polling failed permanently") from error
                logging.getLogger("january.ingress").warning(
                    "telegram_poll_retryable_failure"
                )
                await lifecycle.wait(delay)
                delay = min(delay * 2, settings.telegram_poll_max_backoff_seconds)
            except Exception as error:
                logging.getLogger("january.ingress").warning(
                    "telegram_poll_failed", exc_info=error
                )
                await lifecycle.wait(delay)
                delay = min(delay * 2, settings.telegram_poll_max_backoff_seconds)
    finally:
        lifecycle.close()
        await adapter.aclose()
        await database.stop()


if __name__ == "__main__":
    asyncio.run(run())
