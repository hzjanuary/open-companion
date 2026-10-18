"""Validated Telegram Update DTOs kept at the infrastructure boundary."""

from dataclasses import dataclass
from typing import Any

from app.application.ingress import IngressEnvelope
from app.domain.persistence import IngressSource, Platform

SUPPORTED_UPDATE_TYPES = frozenset(
    {"message", "edited_message", "my_chat_member", "chat_member"}
)


class TelegramUpdateValidationError(ValueError):
    """Safe parser failure suitable for a stable client response."""


@dataclass(frozen=True, slots=True)
class TelegramUpdate:
    update_id: str
    update_type: str
    supported: bool
    raw_payload: dict[str, Any]

    def to_ingress(
        self,
        *,
        platform_connection_id: object,
        ingress_source: IngressSource,
        received_at: object,
    ) -> IngressEnvelope:
        from datetime import datetime
        from uuid import UUID

        if not isinstance(platform_connection_id, UUID) or not isinstance(
            received_at, datetime
        ):
            raise TypeError("validated ingress metadata is required")
        return IngressEnvelope(
            platform=Platform.TELEGRAM,
            platform_connection_id=platform_connection_id,
            platform_update_id=self.update_id,
            update_type=self.update_type,
            supported=self.supported,
            ingress_source=ingress_source,
            received_at=received_at,
            raw_payload=self.raw_payload,
        )


def parse_telegram_update(payload: object) -> TelegramUpdate:
    """Validate the small, supported Update surface without normalizing messages."""

    if not isinstance(payload, dict):
        raise TelegramUpdateValidationError("update must be a JSON object")
    raw_update_id = payload.get("update_id")
    if isinstance(raw_update_id, bool) or not isinstance(raw_update_id, int):
        raise TelegramUpdateValidationError(
            "update_id is required and must be an integer"
        )

    active = [
        key
        for key, value in payload.items()
        if key != "update_id" and value is not None
    ]
    if len(active) > 1:
        raise TelegramUpdateValidationError("update has multiple active payloads")
    update_type = active[0] if active else "unknown"
    if update_type in SUPPORTED_UPDATE_TYPES and not isinstance(
        payload[update_type], dict
    ):
        raise TelegramUpdateValidationError(
            "supported update payload must be an object"
        )
    return TelegramUpdate(
        update_id=str(raw_update_id),
        update_type=update_type,
        supported=update_type in SUPPORTED_UPDATE_TYPES,
        raw_payload=payload,
    )
