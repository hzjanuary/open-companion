"""Actual HTTP boundary safety and bounded cleanup for SPEC-028."""

import asyncio
import logging
import traceback
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from app.application.ports.media import MediaError
from app.core.config import Settings
from app.domain.media import MediaAttachment, MediaFailureReason, MediaKind, MediaLimits
from app.infrastructure.telegram.adapter import TelegramAdapter
from app.infrastructure.telegram.media_download import (
    download_media,
    validate_file_path,
    validate_media_bytes,
    validate_media_origin,
)

TOKEN = "123:SPEC028_SECRET_MUST_NOT_APPEAR"
JPEG = (
    b"\xff\xd8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x01\xff\xd9"
)
PHOTO = MediaAttachment(
    MediaKind.PHOTO, "source_file", "source_unique", "image/jpeg", width=1, height=1
)


class Stream(httpx.AsyncByteStream):
    def __init__(self, *chunks: bytes, delay: float = 0, fail: bool = False) -> None:
        self.chunks = chunks
        self.delay = delay
        self.fail = fail
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk
        if self.fail:
            raise httpx.ReadError(
                f"secret URL https://api.telegram.org/file/bot{TOKEN}/photo.jpg"
            )

    async def aclose(self) -> None:
        self.closed = True


def resolver(path: str = "photos/file.jpg", **overrides: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "ok": True,
            "result": {
                "file_id": PHOTO.file_id,
                "file_unique_id": PHOTO.file_unique_id,
                "file_path": path,
                **overrides,
            },
        },
    )


async def fetch(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    maximum: int = 5000,
    timeout: float = 1,
) -> bytes:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await download_media(
            client,
            "https://api.telegram.org",
            TOKEN,
            PHOTO,
            MediaLimits(photo_max_bytes=maximum),
            timeout,
        )
        return result.data


def test_official_get_file_and_download_via_adapter(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[httpx.Request] = []
    stream = Stream(JPEG)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.host == "api.telegram.org"
        if request.method == "POST":
            assert request.url.path == f"/bot{TOKEN}/getFile"
            assert request.content == b'{"file_id":"source_file"}'
            return resolver(file_size=len(JPEG))
        assert request.url.path == f"/file/bot{TOKEN}/photos/file.jpg"
        return httpx.Response(
            200, stream=stream, headers={"Content-Type": "image/jpeg"}
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = TelegramAdapter(
                Settings(
                    _env_file=None, telegram_enabled=True, telegram_bot_token=TOKEN
                ),
                client,
            )
            result = await adapter.download_media(PHOTO)
            assert result.data == JPEG
            await adapter.aclose()
            assert not client.is_closed

    caplog.set_level(logging.DEBUG)
    asyncio.run(scenario())
    assert len(calls) == 2 and stream.closed
    for secret in (TOKEN, PHOTO.file_id, "photos/file.jpg"):
        assert secret not in caplog.text


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.invalid/x",
        "//evil.invalid/x",
        "/etc/passwd",
        "../x",
        "photos/../secret",
        "photos/./secret",
        "photos//x",
        "photos/%2e%2e/x",
        "photos/a%2fb",
        "photos\\x",
        "photos/x?token=x",
        "photos/x#fragment",
        "photos/x\n",
        "photos/.hidden",
        "",
        "x" * 513,
    ],
)
def test_injected_paths_never_reach_file_fetch(path: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "POST"
        return resolver(path)

    with pytest.raises(MediaError):
        asyncio.run(fetch(handler))
    assert calls == 1
    with pytest.raises(MediaError):
        validate_file_path(path)


@pytest.mark.parametrize(
    "url",
    [
        "http://evil.invalid",
        "https://user:secret@api.telegram.org",
        "https://api.telegram.org/a",
        "https://api.telegram.org/?x=y",
        "https://api.telegram.org/#x",
        "file:///tmp/x",
    ],
)
def test_configured_boundary_does_not_allow_credentials_or_paths(url: str) -> None:
    with pytest.raises(MediaError):
        validate_media_origin(url)
    assert validate_media_origin("http://127.0.0.1:8888") == "http://127.0.0.1:8888"


@pytest.mark.parametrize("phase", ["resolve", "download"])
def test_redirects_are_not_followed(phase: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if phase == "resolve" or request.method == "GET":
            return httpx.Response(302, headers={"Location": "https://evil.invalid"})
        return resolver()

    with pytest.raises(MediaError):
        asyncio.run(fetch(handler))
    assert calls == (1 if phase == "resolve" else 2)


@pytest.mark.parametrize(
    "headers,chunks,reason",
    [
        ({"Content-Length": "5001"}, (b"a",), "too_large"),
        ({}, (b"a" * 2500, b"b" * 2501), "too_large"),
        ({"Content-Length": "1"}, (JPEG,), "invalid_format"),
        ({"Content-Length": "-1"}, (JPEG,), "invalid_format"),
        ({"Content-Length": "100"}, (b"short",), "invalid_format"),
        ({"Content-Encoding": "gzip"}, (JPEG,), "invalid_format"),
        ({"Content-Type": "text/html"}, (JPEG,), "invalid_format"),
        ({}, (), "invalid_format"),
    ],
)
def test_stream_limits_and_failure_cleanup(
    headers: dict[str, str], chunks: tuple[bytes, ...], reason: str
) -> None:
    stream = Stream(*chunks)

    def handler(request: httpx.Request) -> httpx.Response:
        return (
            resolver()
            if request.method == "POST"
            else httpx.Response(200, headers=headers, stream=stream)
        )

    with pytest.raises(MediaError) as error:
        asyncio.run(fetch(handler))
    assert error.value.reason == reason
    assert stream.closed


def test_timeout_is_total_deadline_and_closes_stream() -> None:
    stream = Stream(JPEG, delay=0.03)

    def handler(request: httpx.Request) -> httpx.Response:
        return (
            resolver()
            if request.method == "POST"
            else httpx.Response(200, stream=stream)
        )

    with pytest.raises(MediaError) as error:
        asyncio.run(fetch(handler, timeout=0.005))
    assert error.value.reason == MediaFailureReason.TIMEOUT
    assert stream.closed


def test_failed_download_exception_chain_and_logs_are_content_safe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stream = Stream(JPEG, fail=True)

    def handler(request: httpx.Request) -> httpx.Response:
        logging.getLogger("httpcore.http11").debug("request %s", request.url)
        return (
            resolver()
            if request.method == "POST"
            else httpx.Response(200, stream=stream)
        )

    caplog.set_level(logging.DEBUG)
    try:
        asyncio.run(fetch(handler))
    except MediaError as error:
        rendered = "".join(traceback.format_exception(error))
    else:
        pytest.fail("failed stream accepted")
    assert TOKEN not in rendered and TOKEN not in caplog.text
    assert stream.closed


def test_cancellation_closes_download() -> None:
    stream = Stream(JPEG, delay=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return (
            resolver()
            if request.method == "POST"
            else httpx.Response(200, stream=stream)
        )

    async def scenario() -> None:
        task = asyncio.create_task(fetch(handler))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert stream.closed


def test_deeply_nested_getfile_json_is_a_safe_rejection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, content=b"[" * 1500 + b"0" + b"]" * 1500)

    with pytest.raises(MediaError) as error:
        asyncio.run(fetch(handler))
    assert error.value.reason == MediaFailureReason.INVALID_FORMAT


def test_privacy_rechecked_after_get_file_before_download() -> None:
    calls = 0
    checks = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "POST"
        return resolver()

    async def allowed() -> bool:
        nonlocal checks
        checks += 1
        return checks == 1

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await download_media(
                client,
                "https://api.telegram.org",
                TOKEN,
                PHOTO,
                MediaLimits(),
                1,
                allowed,
            )

    with pytest.raises(MediaError) as error:
        asyncio.run(scenario())
    assert error.value.reason == MediaFailureReason.PRIVACY_CHANGED
    assert calls == 1 and checks == 2


def test_jpeg_header_without_scan_is_rejected() -> None:
    with pytest.raises(MediaError):
        validate_media_bytes(
            JPEG[:15] + b"\xff\xd9", "image/jpeg", PHOTO, MediaLimits()
        )


@pytest.mark.parametrize(
    "values",
    [
        {"file_id": "foreign"},
        {"file_unique_id": "foreign"},
        {"file_size": True},
        {"file_size": 6000},
        {"file_size": 0},
    ],
)
def test_get_file_metadata_is_bound_and_validated(values: dict[str, object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return resolver(**values)

    with pytest.raises(MediaError):
        asyncio.run(fetch(handler))


def test_container_signatures_and_dimensions() -> None:
    limits = MediaLimits()
    assert validate_media_bytes(JPEG, "image/jpeg", PHOTO, limits).width == 1
    for bad in (
        b"not jpeg",
        JPEG[:-1],
        JPEG.replace(b"\x00\x01\x00\x01", b"\x10\x01\x10\x01"),
    ):
        with pytest.raises(MediaError):
            validate_media_bytes(bad, "image/jpeg", PHOTO, limits)
    voice = MediaAttachment(MediaKind.VOICE, "v", "u", "audio/ogg")
    ogg = b"OggS\x00\x02" + b"\x00" * 20 + b"\x01\x13" + b"OpusHead" + b"\x00" * 11
    assert validate_media_bytes(ogg, "audio/ogg", voice, limits).data == ogg
    with pytest.raises(MediaError):
        validate_media_bytes(b"OpusHead" + b"a" * 100, "audio/ogg", voice, limits)
    audio = MediaAttachment(MediaKind.AUDIO, "a", "u", "audio/mpeg")
    assert validate_media_bytes(b"\xff\xfb\x90\x00more", "audio/mpeg", audio, limits)
    with pytest.raises(MediaError):
        validate_media_bytes(b"ID3", "audio/mpeg", audio, limits)
