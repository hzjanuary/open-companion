"""Repository-safe schema/projection proof; transactional tests are separate."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.application.conversation import evaluate_eligibility
from app.application.governance_export import export_message
from app.domain.media import MediaKind, MediaStatus
from app.domain.persistence import MessageDirection, MessageType, ResponseMode
from app.infrastructure.database.media import redact_media_values
from app.infrastructure.database.models import MessageMediaModel, MessageModel

from .test_conversation_eligibility import value


def test_schema_has_no_raw_bytes_and_has_source_and_lease_fences() -> None:
    sql = str(
        CreateTable(MessageMediaModel.__table__).compile(dialect=postgresql.dialect())
    )
    assert "UNIQUE (message_id)" in sql
    assert "REFERENCES messages (id, conversation_id)" in sql
    assert "media_lease_shape" in sql and "media_content_shape" in sql
    columns = set(MessageMediaModel.__table__.columns.keys())
    assert not columns & {"data", "bytes", "raw_media", "file_path", "url", "token"}


@pytest.mark.parametrize("kind", ["photo", "voice", "audio", "unsupported_media"])
def test_media_is_addressed_only_not_ambient(kind: str) -> None:
    assert evaluate_eligibility(
        value(conversation_type="private", message_type=kind, message_text=None)
    ).eligible
    assert evaluate_eligibility(
        value(message_type=kind, message_text=None, replies_to_assistant=True)
    ).eligible
    assert not evaluate_eligibility(
        value(
            message_type=kind,
            message_text=None,
            response_mode=ResponseMode.AMBIENT_SELECTIVE,
        )
    ).eligible
    assert not evaluate_eligibility(
        value(
            conversation_type="private",
            message_type=kind,
            message_text=None,
            response_mode=ResponseMode.PAUSED,
        )
    ).eligible


def test_subject_projection_is_allowlisted_and_expiry_authoritative() -> None:
    now = datetime.now(UTC)
    message = MessageModel(
        id=uuid4(),
        conversation_id=uuid4(),
        participant_id=uuid4(),
        message_type=MessageType.VOICE,
        direction=MessageDirection.INCOMING,
        platform_sent_at=now,
        text="derived words",
        metadata_={"content_provenance": "voice_transcript", "unexpected": "secret"},
    )
    media = MessageMediaModel(
        kind=MediaKind.VOICE,
        status=MediaStatus.COMPLETE,
        caption="authored caption",
        file_id="own_reference",
        file_unique_id="own_unique",
        mime_type="audio/ogg",
        duration_seconds=10,
    )
    result = export_message(message, media, now, 30, False)
    assert result["text"] == "derived words"
    assert result["content_provenance"] == "voice_transcript"
    assert "unexpected" not in str(result) and "secret" not in str(result)
    for current, deleted in ((now + timedelta(days=30), False), (now, True)):
        redacted = export_message(message, media, current, 30, deleted)
        assert redacted["text"] is None and redacted["media"] is None
        assert redacted["content_provenance"] is None
    media.status = MediaStatus.REDACTED
    assert export_message(message, media, now, 30, False)["text"] is None


def test_redaction_clears_every_content_and_lease_field() -> None:
    fields = redact_media_values(datetime.now(UTC))
    assert fields["status"] == MediaStatus.REDACTED
    assert all(
        fields[name] is None
        for name in (
            "file_id",
            "file_unique_id",
            "mime_type",
            "caption",
            "file_size",
            "width",
            "height",
            "duration_seconds",
            "lease_token",
            "lease_expires_at",
        )
    )
