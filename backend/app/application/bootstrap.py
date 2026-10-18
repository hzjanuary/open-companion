"""Typed results for explicit operator bootstrap."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    assistant_id: UUID
    platform_connection_id: UUID
    external_bot_id: str
    username: str | None
    display_name: str
    can_join_groups: bool | None
    can_read_all_group_messages: bool | None
