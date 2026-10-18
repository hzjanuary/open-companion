"""Redis 7 Streams queue primitives for durable ingress references."""

import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.application.ingress import IngressQueueEvent
from app.core.config import Settings
from app.domain.persistence import Platform


class QueuePayloadError(ValueError):
    """A Stream entry did not match the versioned ingress event contract."""


def _event_payload(event: IngressQueueEvent) -> str:
    return json.dumps(
        {
            "schema_version": event.schema_version,
            "incoming_update_id": str(event.incoming_update_id),
            "platform": event.platform.value,
            "platform_connection_id": str(event.platform_connection_id),
            "platform_update_id": event.platform_update_id,
            "update_type": event.update_type,
            "received_at": event.received_at.isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def parse_event_payload(payload: bytes | str) -> IngressQueueEvent:
    try:
        decoded = payload.decode() if isinstance(payload, bytes) else payload
        value = json.loads(decoded)
        if not isinstance(value, dict):
            raise TypeError
        return IngressQueueEvent(
            schema_version=int(value["schema_version"]),
            incoming_update_id=UUID(str(value["incoming_update_id"])),
            platform=Platform(str(value["platform"])),
            platform_connection_id=UUID(str(value["platform_connection_id"])),
            platform_update_id=str(value["platform_update_id"]),
            update_type=str(value["update_type"]),
            received_at=datetime.fromisoformat(str(value["received_at"])),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise QueuePayloadError("malformed ingress queue payload") from error


class RedisIngressQueue:
    def __init__(self, settings: Settings, client: Redis | None = None) -> None:
        self._settings = settings
        self._owned_client = client is None
        self._client = client or Redis.from_url(
            settings.redis_url.get_secret_value(), decode_responses=False
        )

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def is_ready(self) -> bool:
        try:
            return bool(await self._client.ping())
        except RedisError:
            return False

    async def publish(self, event: IngressQueueEvent) -> str:
        entry_id = await self._client.xadd(
            self._settings.redis_stream_name, {"event": _event_payload(event)}
        )
        return entry_id.decode() if isinstance(entry_id, bytes) else entry_id

    async def ensure_group(self) -> None:
        try:
            await self._client.xgroup_create(
                self._settings.redis_stream_name,
                self._settings.redis_consumer_group,
                id="0",
                mkstream=True,
            )
        except RedisError as error:
            if "BUSYGROUP" not in str(error):
                raise

    async def read_new(self, consumer: str) -> list[tuple[str, IngressQueueEvent]]:
        entries = await self._client.xreadgroup(
            self._settings.redis_consumer_group,
            consumer,
            {self._settings.redis_stream_name: ">"},
            count=self._settings.redis_batch_size,
            block=self._settings.redis_block_timeout_ms,
        )
        return self._decode_entries(entries)

    async def acknowledge(self, entry_id: str) -> None:
        await self._client.xack(
            self._settings.redis_stream_name,
            self._settings.redis_consumer_group,
            entry_id,
        )

    async def reclaim(self, consumer: str) -> list[tuple[str, IngressQueueEvent]]:
        result = await self._client.xautoclaim(
            self._settings.redis_stream_name,
            self._settings.redis_consumer_group,
            consumer,
            min_idle_time=self._settings.redis_reclaim_idle_ms,
            start_id="0-0",
            count=self._settings.redis_batch_size,
        )
        entries = result[1]
        return self._decode_entries([(self._settings.redis_stream_name, entries)])

    def _decode_entries(self, raw: Any) -> list[tuple[str, IngressQueueEvent]]:
        result: list[tuple[str, IngressQueueEvent]] = []
        for _stream, entries in raw:
            for entry_id, fields in entries:
                raw_event = fields.get(b"event") if isinstance(fields, dict) else None
                if raw_event is None and isinstance(fields, dict):
                    raw_event = fields.get("event")
                if not isinstance(raw_event, bytes | str):
                    raise QueuePayloadError("queue entry is missing event")
                identifier = (
                    entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                )
                result.append((identifier, parse_event_payload(raw_event)))
        return result


async def consume_once(
    queue: RedisIngressQueue,
    consumer: str,
    handler: Callable[[IngressQueueEvent], Awaitable[None]],
) -> int:
    """Acknowledge only after the supplied handler completes successfully."""

    await queue.ensure_group()
    entries = await queue.read_new(consumer)
    for entry_id, event in entries:
        await handler(event)
        await queue.acknowledge(entry_id)
    return len(entries)
