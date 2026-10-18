from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.ingress import IngressQueueEvent
from app.domain.persistence import Platform
from app.infrastructure.queue.redis_streams import (
    QueuePayloadError,
    parse_event_payload,
)


def test_queue_event_payload_round_trip_is_reference_only() -> None:
    event = IngressQueueEvent(
        schema_version=1,
        incoming_update_id=uuid4(),
        platform=Platform.TELEGRAM,
        platform_connection_id=uuid4(),
        platform_update_id="4000000000",
        update_type="message",
        received_at=datetime.now(UTC),
    )
    from app.infrastructure.queue.redis_streams import _event_payload

    parsed = parse_event_payload(_event_payload(event))
    assert parsed == event
    assert "raw_payload" not in _event_payload(event)


def test_malformed_queue_payload_is_rejected() -> None:
    with pytest.raises(QueuePayloadError):
        parse_event_payload("{not-json")
