"""Trusted Telegram-only bounded media I/O and container validation."""

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from app.application.ports.media import MediaError
from app.domain.media import (
    EphemeralMedia,
    MediaAttachment,
    MediaFailureReason,
    MediaKind,
    MediaLimits,
)

_MEDIA_HTTP: ContextVar[bool] = ContextVar("telegram_media_http", default=False)
_PATH = re.compile(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)*\Z")
_REFERENCE = re.compile(r"[A-Za-z0-9_-]{1,255}\Z")


class _MediaHttpFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # HTTPX INFO exposes URL; httpcore DEBUG can expose request targets and
        # headers. Do not render any of those records during this task's I/O.
        return not _MEDIA_HTTP.get()


def install_media_http_filter() -> None:
    for name in (
        "httpx",
        "httpcore.connection",
        "httpcore.http11",
        "httpcore.http2",
        "httpcore.proxy",
        "httpcore.socks",
    ):
        logger = logging.getLogger(name)
        if not any(isinstance(value, _MediaHttpFilter) for value in logger.filters):
            logger.addFilter(_MediaHttpFilter())


@dataclass(frozen=True, slots=True)
class TelegramFile:
    path: str = field(repr=False)
    size: int | None


def validate_file_path(path: object) -> str:
    if (
        not isinstance(path, str)
        or not 1 <= len(path) <= 512
        or _PATH.fullmatch(path) is None
        or any(part in {".", ".."} or part.startswith(".") for part in path.split("/"))
    ):
        raise MediaError(MediaFailureReason.INVALID_FORMAT)
    return path


def validate_media_origin(base_url: str) -> str:
    try:
        parsed = urlsplit(base_url)
    except ValueError:
        raise MediaError(MediaFailureReason.UNAVAILABLE) from None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or not parsed.hostname
        or (
            parsed.scheme != "https"
            and not (
                parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            )
        )
    ):
        raise MediaError(MediaFailureReason.UNAVAILABLE)
    return base_url.rstrip("/")


async def _read_bounded(response: httpx.Response, limit: int) -> bytes:
    if response.status_code != 200:
        raise MediaError(MediaFailureReason.UNAVAILABLE)
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        raise MediaError(MediaFailureReason.INVALID_FORMAT)
    length: int | None = None
    raw_length = response.headers.get("content-length")
    if raw_length is not None:
        if not raw_length.isascii() or not raw_length.isdecimal():
            raise MediaError(MediaFailureReason.INVALID_FORMAT)
        if len(raw_length) > 20:
            raise MediaError(MediaFailureReason.TOO_LARGE)
        length = int(raw_length)
        if length > limit:
            raise MediaError(MediaFailureReason.TOO_LARGE)
    result = bytearray()
    try:
        async for chunk in response.aiter_bytes(chunk_size=min(limit + 1, 65536)):
            if len(result) + len(chunk) > limit:
                raise MediaError(MediaFailureReason.TOO_LARGE)
            result.extend(chunk)
        if not result or (length is not None and len(result) != length):
            raise MediaError(MediaFailureReason.INVALID_FORMAT)
        return bytes(result)
    finally:
        result.clear()


async def get_file(
    client: httpx.AsyncClient,
    base_url: str,
    bot_token: str,
    attachment: MediaAttachment,
    maximum_bytes: int,
) -> TelegramFile:
    """Internal authenticated resolution, never accepts an arbitrary URL."""

    if not _REFERENCE.fullmatch(attachment.file_id):
        raise MediaError(MediaFailureReason.INVALID_FORMAT)
    async with client.stream(
        "POST",
        f"{base_url}/bot{bot_token}/getFile",
        json={"file_id": attachment.file_id},
        headers={"Accept-Encoding": "identity"},
        follow_redirects=False,
    ) as response:
        raw = await _read_bounded(response, 16384)
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise MediaError(MediaFailureReason.INVALID_FORMAT) from None
    if not isinstance(envelope, dict):
        raise MediaError(MediaFailureReason.INVALID_FORMAT)
    if envelope.get("ok") is not True:
        raise MediaError(MediaFailureReason.UNAVAILABLE)
    value = envelope.get("result")
    if not isinstance(value, dict) or value.get("file_id") != attachment.file_id:
        raise MediaError(MediaFailureReason.INVALID_FORMAT)
    if value.get("file_unique_id") != attachment.file_unique_id:
        raise MediaError(MediaFailureReason.INVALID_FORMAT)
    size = value.get("file_size")
    if size is not None:
        if type(size) is not int or size <= 0:
            raise MediaError(MediaFailureReason.INVALID_FORMAT)
        if size > maximum_bytes:
            raise MediaError(MediaFailureReason.TOO_LARGE)
        if attachment.file_size is not None and attachment.file_size != size:
            raise MediaError(MediaFailureReason.INVALID_FORMAT)
    return TelegramFile(validate_file_path(value.get("file_path")), size)


async def download_media(
    client: httpx.AsyncClient,
    base_url: str,
    bot_token: str,
    attachment: MediaAttachment,
    limits: MediaLimits,
    timeout_seconds: float,
    before_io: Callable[[], Awaitable[bool]] | None = None,
) -> EphemeralMedia:
    """One deadline includes getFile, stream reads and pure byte validation."""

    base = validate_media_origin(base_url)
    maximum = (
        limits.photo_max_bytes
        if attachment.kind == MediaKind.PHOTO
        else limits.audio_max_bytes
    )
    if attachment.file_size is not None and attachment.file_size > maximum:
        raise MediaError(MediaFailureReason.TOO_LARGE)
    install_media_http_filter()
    context_token = _MEDIA_HTTP.set(True)
    try:
        async with asyncio.timeout(timeout_seconds):
            if before_io is not None and not await before_io():
                raise MediaError(MediaFailureReason.PRIVACY_CHANGED)
            file = await get_file(client, base, bot_token, attachment, maximum)
            if before_io is not None and not await before_io():
                raise MediaError(MediaFailureReason.PRIVACY_CHANGED)
            async with client.stream(
                "GET",
                f"{base}/file/bot{bot_token}/{file.path}",
                headers={"Accept-Encoding": "identity"},
                follow_redirects=False,
            ) as response:
                raw = await _read_bounded(response, maximum)
                content_type = response.headers.get("content-type", "").split(";")[0]
            if file.size is not None and len(raw) != file.size:
                raise MediaError(MediaFailureReason.INVALID_FORMAT)
            if attachment.file_size is not None and len(raw) != attachment.file_size:
                raise MediaError(MediaFailureReason.INVALID_FORMAT)
            return validate_media_bytes(raw, content_type, attachment, limits)
    except (TimeoutError, httpx.TimeoutException):
        raise MediaError(MediaFailureReason.TIMEOUT) from None
    except (httpx.HTTPError, httpx.InvalidURL):
        raise MediaError(MediaFailureReason.UNAVAILABLE) from None
    finally:
        _MEDIA_HTTP.reset(context_token)


def validate_media_bytes(
    raw: bytes, content_type: str, attachment: MediaAttachment, limits: MediaLimits
) -> EphemeralMedia:
    if content_type.lower() not in {
        "",
        "application/octet-stream",
        attachment.mime_type,
    }:
        raise MediaError(MediaFailureReason.INVALID_FORMAT)
    width, height = None, None
    if attachment.kind == MediaKind.PHOTO:
        width, height = _jpeg_dimensions(raw)
        if max(width, height) > limits.photo_max_side:
            raise MediaError(MediaFailureReason.TOO_LARGE)
        if width != attachment.width or height != attachment.height:
            raise MediaError(MediaFailureReason.INVALID_FORMAT)
    elif attachment.kind == MediaKind.VOICE:
        # Identification packet must be in the first bounded Ogg page, not an
        # arbitrary marker hidden in another format or a later unbounded scan.
        if (
            len(raw) < 47
            or raw[:5] != b"OggS\x00"
            or not raw[5] & 2
            or raw[26] < 1
            or len(raw) < 27 + raw[26] + 19
            or raw[27 + raw[26] : 35 + raw[26]] != b"OpusHead"
        ):
            raise MediaError(MediaFailureReason.INVALID_FORMAT)
    else:
        _validate_mp3(raw)
    return EphemeralMedia(attachment.kind, attachment.mime_type, raw, width, height)


def _jpeg_dimensions(raw: bytes) -> tuple[int, int]:
    if len(raw) < 12 or raw[:2] != b"\xff\xd8" or raw[-2:] != b"\xff\xd9":
        raise MediaError(MediaFailureReason.INVALID_FORMAT)
    cursor = 2
    dimensions: tuple[int, int] | None = None
    while cursor + 4 <= len(raw):
        if raw[cursor] != 255:
            break
        while cursor < len(raw) and raw[cursor] == 255:
            cursor += 1
        if cursor + 3 > len(raw):
            break
        marker = raw[cursor]
        cursor += 1
        if marker == 0xD9:
            break
        size = int.from_bytes(raw[cursor : cursor + 2], "big")
        if size < 2 or cursor + size > len(raw):
            break
        if marker == 0xDA:
            if (
                dimensions is not None
                and size >= 6
                and size == 6 + 2 * raw[cursor + 2]
                and cursor + size < len(raw) - 2
            ):
                return dimensions
            break
        if marker in {0xC0, 0xC1, 0xC2} and size >= 8:
            height = int.from_bytes(raw[cursor + 3 : cursor + 5], "big")
            width = int.from_bytes(raw[cursor + 5 : cursor + 7], "big")
            components = raw[cursor + 7]
            if (
                dimensions is not None
                or width == 0
                or height == 0
                or raw[cursor + 2] != 8
                or components not in {1, 3}
                or size != 8 + 3 * components
            ):
                break
            dimensions = width, height
        cursor += size
    raise MediaError(MediaFailureReason.INVALID_FORMAT)


def _validate_mp3(raw: bytes) -> None:
    cursor = 0
    if raw.startswith(b"ID3"):
        if len(raw) < 10 or any(value & 128 for value in raw[6:10]):
            raise MediaError(MediaFailureReason.INVALID_FORMAT)
        size = 0
        for value in raw[6:10]:
            size = (size << 7) | value
        cursor = 10 + size
    if (
        cursor + 4 > len(raw)
        or raw[cursor] != 255
        or raw[cursor + 1] & 0xE0 != 0xE0
        or raw[cursor + 1] & 0x06 != 0x02  # MPEG layer III only.
        or raw[cursor + 2] & 0xF0 in {0, 0xF0}
        or raw[cursor + 2] & 0x0C == 0x0C
    ):
        raise MediaError(MediaFailureReason.INVALID_FORMAT)
