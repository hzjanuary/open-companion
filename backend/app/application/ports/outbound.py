"""Platform-independent outbound asset-resolution contracts."""

from typing import Protocol

from app.domain.planning import StickerIntent


class StickerAssetResolver(Protocol):
    """Resolve semantic sticker intent without exposing provider asset values."""

    def resolve(self, intent: StickerIntent) -> str | None: ...
