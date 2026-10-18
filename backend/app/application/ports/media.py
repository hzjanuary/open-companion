"""Narrow ephemeral media download port; callers supply canonical metadata only."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from app.domain.media import EphemeralMedia, MediaAttachment, MediaFailureReason


class MediaError(Exception):
    def __init__(self, reason: MediaFailureReason) -> None:
        self.reason = reason
        super().__init__(f"media processing: {reason.value}")


class MediaDownloader(Protocol):
    async def download_media(
        self,
        attachment: MediaAttachment,
        before_io: Callable[[], Awaitable[bool]] | None = None,
    ) -> EphemeralMedia: ...
