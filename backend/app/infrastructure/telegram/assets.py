"""Telegram sticker assets configured outside response plans and prompts."""

from app.application.ports.outbound import StickerAssetResolver
from app.core.config import Settings
from app.domain.planning import StickerIntent


class TelegramStickerAssetResolver(StickerAssetResolver):
    def __init__(self, settings: Settings) -> None:
        self._mapping = settings.telegram_sticker_mapping

    def resolve(self, intent: StickerIntent) -> str | None:
        return self._mapping.get(intent.value)
