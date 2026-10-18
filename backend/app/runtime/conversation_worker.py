"""Consume durable ingress references into normalized conversation state."""

import asyncio
import logging
import socket
from time import perf_counter

from sqlalchemy import select

from app.application.ingress import IngressQueueEvent
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.core.config import Settings
from app.core.telemetry_context import reset_correlation_id, set_correlation_id
from app.domain.media import MediaLimits
from app.infrastructure.database.conversation import (
    ConversationProcessingError,
    SqlAlchemyConversationProcessor,
)
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import (
    AssistantModel,
    IncomingPlatformUpdateModel,
    PlatformConnectionModel,
)
from app.infrastructure.queue.redis_streams import QueuePayloadError, RedisIngressQueue
from app.infrastructure.telegram.normalizer import (
    TelegramNormalizationError,
    normalize_telegram_update,
)
from app.infrastructure.telegram.updates import parse_telegram_update
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.runtime.lifecycle import RuntimeLifecycle

logger = logging.getLogger(__name__)


def consumer_name(settings: Settings) -> str:
    return settings.conversation_consumer_name or f"conversation-{socket.gethostname()}"


async def process_event(
    event: IngressQueueEvent,
    settings: Settings,
    database: Database,
    processor: SqlAlchemyConversationProcessor,
    telemetry: MetricsRecorder | None = None,
) -> None:
    """Process one event; ledger permanent malformed data and raise transient errors."""

    recorder = telemetry or NoOpMetricsRecorder()
    started = perf_counter()
    token = set_correlation_id(str(event.incoming_update_id))
    try:
        if event.schema_version != 1:
            await processor.reject_malformed(event)
            recorder.increment(
                "january_telegram_updates_total", outcome="invalid", transport="stream"
            )
            return
        async with database.session_factory() as session:
            row = await session.execute(
                select(
                    IncomingPlatformUpdateModel,
                    PlatformConnectionModel,
                    AssistantModel,
                )
                .join(
                    PlatformConnectionModel,
                    IncomingPlatformUpdateModel.platform_connection_id
                    == PlatformConnectionModel.id,
                )
                .join(
                    AssistantModel,
                    PlatformConnectionModel.assistant_id == AssistantModel.id,
                )
                .where(IncomingPlatformUpdateModel.id == event.incoming_update_id)
            )
            durable = row.first()
        if durable is None:
            raise ConversationProcessingError("durable ingress record is missing")
        incoming, connection, assistant = durable
        try:
            normalized = normalize_telegram_update(
                parse_telegram_update(incoming.raw_payload),
                platform_connection_id=connection.id,
                assistant_platform_user_id=connection.external_bot_id,
                assistant_display_name=assistant.name,
                assistant_username=(
                    connection.configuration.get("username")
                    if isinstance(connection.configuration.get("username"), str)
                    else None
                ),
                command_argument_limit=settings.command_max_argument_length,
                media_limits=MediaLimits(
                    photo_max_bytes=settings.telegram_media_photo_max_bytes,
                    audio_max_bytes=settings.telegram_media_audio_max_bytes,
                    photo_max_side=settings.telegram_media_photo_max_side,
                    audio_max_duration_seconds=settings.telegram_media_audio_max_duration_seconds,
                    transcript_max_characters=settings.telegram_media_transcript_max_characters,
                ),
            )
        except (TelegramNormalizationError, ValueError):
            await processor.reject_malformed(event)
            recorder.increment(
                "january_telegram_updates_total", outcome="invalid", transport="stream"
            )
            return
        if (
            settings.demo_live_enabled
            and normalized.conversation.platform_conversation_id
            not in settings.demo_allowed_chat_ids
        ):
            await processor.ignore_not_allowed(event)
            recorder.increment(
                "january_telegram_updates_total",
                outcome="suppressed",
                transport="stream",
            )
            return
        result = await processor.process(event, normalized)
        recorder.increment(
            "january_telegram_updates_total",
            outcome="duplicate" if result.duplicate else "accepted",
            transport="stream",
        )
        if result.eligibility is not None:
            recorder.increment(
                "january_conversation_eligibility_total",
                eligible="yes" if result.eligibility.eligible else "no",
                reason=result.eligibility.reason.value,
            )
        recorder.increment(
            "january_worker_operations_total",
            runtime="conversation",
            operation="process",
            outcome=result.outcome,
        )
        recorder.observe(
            "january_worker_operation_duration_seconds",
            perf_counter() - started,
            runtime="conversation",
            operation="process",
            outcome=result.outcome,
        )
        logger.info(
            "conversation event processed",
            extra={
                "incoming_update_id": str(result.incoming_update_id),
                "outcome": result.outcome,
                "duplicate": result.duplicate,
                "eligible": result.eligibility.eligible if result.eligibility else None,
            },
        )
    finally:
        reset_correlation_id(token)


async def consume_once(
    settings: Settings,
    database: Database,
    queue: RedisIngressQueue,
    processor: SqlAlchemyConversationProcessor,
    consumer: str | None = None,
    *,
    reclaim: bool = True,
    telemetry: MetricsRecorder | None = None,
) -> int:
    """Acknowledge queue entries only after durable transaction completion."""

    name = consumer or consumer_name(settings)
    await queue.ensure_group()
    entries = await queue.reclaim(name) if reclaim else []
    entries.extend(await queue.read_new(name))
    for entry_id, event in entries:
        await process_event(event, settings, database, processor, telemetry)
        await queue.acknowledge(entry_id)
    return len(entries)


async def run() -> None:
    settings = Settings()
    database = Database(settings)
    queue = RedisIngressQueue(settings)
    telemetry = (
        InMemoryMetricsRecorder() if settings.metrics_enabled else NoOpMetricsRecorder()
    )
    await database.start()
    processor = SqlAlchemyConversationProcessor(
        database.session_factory,
        stickers_enabled=bool(settings.telegram_sticker_mapping),
    )
    lifecycle = RuntimeLifecycle("conversation_worker")
    lifecycle.install()
    try:
        while not lifecycle.stopping:
            try:
                processed = await consume_once(
                    settings, database, queue, processor, telemetry=telemetry
                )
                if processed == 0:
                    await lifecycle.wait(
                        settings.conversation_worker_poll_interval_seconds
                    )
            except QueuePayloadError:
                logger.exception("conversation queue payload rejected")
                await lifecycle.wait(settings.conversation_worker_poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("conversation worker transient failure")
                await lifecycle.wait(settings.conversation_worker_poll_interval_seconds)
    finally:
        lifecycle.close()
        await queue.aclose()
        await database.stop()


if __name__ == "__main__":
    asyncio.run(run())
