"""Telegram plain-text limits shared by planning and durable compilation."""

TELEGRAM_TEXT_CHUNK_UTF16_LIMIT = 3400
TELEGRAM_LOGICAL_RESPONSE_UTF16_LIMIT = 13600
TELEGRAM_MAX_TEXT_CHUNKS = 4


def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2
