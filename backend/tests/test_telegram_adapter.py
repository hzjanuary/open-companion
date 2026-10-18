import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app.application.ports.platform import (
    EditTextRequest,
    PlatformAdapterError,
    PlatformCapability,
    PlatformErrorCategory,
    SendChatActionRequest,
    SendStickerRequest,
    SendTextRequest,
    SendVoiceRequest,
    SetReactionRequest,
)
from app.core.config import Settings
from app.domain.outbound import DeliveryCertainty
from app.domain.reactions import ReactionKind
from app.infrastructure.telegram.adapter import TelegramAdapter, create_telegram_adapter

TOKEN = "123456:UNMISTAKABLE_FAKE_TOKEN"


def settings(**values: object) -> Settings:
    return Settings(
        _env_file=None, telegram_enabled=True, telegram_bot_token=TOKEN, **values
    )


def client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="https://test.invalid")


def test_telegram_is_disabled_by_default_and_token_is_redacted() -> None:
    disabled = Settings(_env_file=None)

    assert disabled.telegram_enabled is False
    assert create_telegram_adapter(disabled) is None
    assert TOKEN not in repr(settings())


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JANUARY_TELEGRAM_TIMEOUT_SECONDS", "0"),
        ("JANUARY_TELEGRAM_CONNECTION_LIMIT", "0"),
        ("JANUARY_TELEGRAM_API_BASE_URL", "not-a-url"),
    ],
)
def test_invalid_telegram_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv("JANUARY_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("JANUARY_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_enabled_telegram_requires_token() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, telegram_enabled=True)


def test_get_me_maps_identity_without_network_at_construction() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "id": 99,
                    "is_bot": True,
                    "first_name": "January",
                    "username": "jan",
                    "can_join_groups": True,
                },
            },
        )

    async def scenario() -> None:
        supplied = client(httpx.MockTransport(handler))
        adapter = TelegramAdapter(settings(), supplied)
        assert calls == []
        identity = await adapter.verify_identity()
        assert identity.external_bot_id == "99"
        assert identity.username == "jan"
        assert calls[0].url.path.endswith("/getMe")
        await adapter.aclose()
        assert not supplied.is_closed
        await supplied.aclose()

    asyncio.run(scenario())


def test_send_operations_serialize_typed_payloads_and_reuse_client() -> None:
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 7,
                    "date": 1,
                    "chat": {"id": -100},
                    "from": {"id": 9},
                },
            },
        )

    async def scenario() -> None:
        supplied = client(httpx.MockTransport(handler))
        adapter = TelegramAdapter(settings(), supplied)
        message = await adapter.send_text(
            SendTextRequest(
                "-100", "hello", reply_to_message_id="4", disable_notification=True
            )
        )
        sticker = await adapter.send_sticker(
            SendStickerRequest("-100", "file-id", message_thread_id="8")
        )
        assert message.platform_message_id == "7"
        assert sticker.conversation_id == "-100"
        assert payloads == [
            {
                "chat_id": "-100",
                "text": "hello",
                "reply_parameters": {
                    "message_id": "4",
                    "allow_sending_without_reply": False,
                },
                "disable_notification": True,
            },
            {"chat_id": "-100", "sticker": "file-id", "message_thread_id": "8"},
        ]
        await supplied.aclose()

    asyncio.run(scenario())


def test_send_voice_uses_fixed_bounded_multipart_and_command_reply() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 17,
                    "date": 1,
                    "chat": {"id": -100},
                    "from": {"id": 9},
                },
            },
        )

    async def scenario() -> None:
        supplied = client(httpx.MockTransport(handler))
        adapter = TelegramAdapter(settings(), supplied)
        result = await adapter.send_voice(
            SendVoiceRequest(
                "-100",
                b"OggSopus",
                reply_to_message_id="14",
                message_thread_id="8",
                protect_content=True,
            )
        )
        assert result.platform_message_id == "17"
        request = requests[0]
        assert request.url.path.endswith("/sendVoice")
        content_type = request.headers["content-type"]
        assert content_type.startswith("multipart/form-data; boundary=")
        body = request.content
        assert b'name="chat_id"' in body
        assert b"\r\n\r\n-100\r\n" in body
        assert b'name="reply_parameters"' in body
        assert b'"message_id":"14"' in body
        assert b'name="message_thread_id"' in body
        assert b"\r\n\r\n8\r\n" in body
        assert b'name="protect_content"' in body
        assert b"\r\n\r\ntrue\r\n" in body
        assert b'name="voice"; filename="voice.ogg"' in body
        assert b"Content-Type: audio/ogg" in body
        assert b"OggSopus" in body
        assert b"speak this" not in body
        assert PlatformCapability.SEND_VOICE in adapter.capabilities
        await supplied.aclose()

    asyncio.run(scenario())


def test_edit_text_uses_exact_target_and_typed_payload() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 7,
                    "date": 1,
                    "chat": {"id": -100},
                    "from": {"id": 9},
                },
            },
        )

    async def scenario() -> None:
        supplied = client(httpx.MockTransport(handler))
        adapter = TelegramAdapter(settings(), supplied)
        result = await adapter.edit_text(EditTextRequest("-100", "7", "replacement"))
        assert result.platform_message_id == "7"
        assert requests[0].url.path.endswith("/editMessageText")
        assert json.loads(requests[0].content) == {
            "chat_id": "-100",
            "message_id": "7",
            "text": "replacement",
        }
        assert PlatformCapability.EDIT_TEXT in adapter.capabilities
        await supplied.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status", "description", "rejected", "not_modified", "certainty"),
    [
        (
            400,
            "Bad Request: message to edit not found",
            True,
            False,
            DeliveryCertainty.REJECTED,
        ),
        (
            400,
            "Bad Request: message can't be edited",
            True,
            False,
            DeliveryCertainty.REJECTED,
        ),
        (
            400,
            "Bad Request: there is no text in the message to edit",
            True,
            False,
            DeliveryCertainty.REJECTED,
        ),
        (
            400,
            "Bad Request: message is not modified: same content",
            False,
            True,
            DeliveryCertainty.REJECTED,
        ),
        (
            400,
            "Bad Request: chat not found",
            False,
            False,
            DeliveryCertainty.REJECTED,
        ),
        (
            500,
            "Internal Server Error",
            False,
            False,
            DeliveryCertainty.UNKNOWN,
        ),
    ],
)
def test_edit_classification_is_exact_and_5xx_is_ambiguous(
    status: int,
    description: str,
    rejected: bool,
    not_modified: bool,
    certainty: DeliveryCertainty,
) -> None:
    async def scenario() -> None:
        supplied = client(
            httpx.MockTransport(
                lambda _: httpx.Response(
                    status,
                    json={
                        "ok": False,
                        "error_code": status,
                        "description": description,
                    },
                )
            )
        )
        with pytest.raises(PlatformAdapterError) as captured:
            await TelegramAdapter(settings(), supplied).edit_text(
                EditTextRequest("-100", "7", "replacement")
            )
        assert captured.value.edit_target_rejected is rejected
        assert captured.value.edit_not_modified is not_modified
        assert captured.value.delivery_certainty == certainty
        await supplied.aclose()

    asyncio.run(scenario())


def test_send_chat_action_uses_exact_typing_payload_and_thread() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": True})

    async def scenario() -> None:
        supplied = client(httpx.MockTransport(handler))
        adapter = TelegramAdapter(settings(), supplied)
        await adapter.send_chat_action(SendChatActionRequest("-100", "42"))
        assert requests[0].url.path.endswith("/sendChatAction")
        assert json.loads(requests[0].content) == {
            "chat_id": "-100",
            "action": "typing",
            "message_thread_id": "42",
        }
        assert PlatformCapability.SEND_CHAT_ACTION in adapter.capabilities
        await supplied.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("kind", "emoji"),
    [(ReactionKind.THUMBS_UP, "👍"), (ReactionKind.HEART, "❤️")],
)
def test_set_reaction_uses_exact_typed_payload(kind: ReactionKind, emoji: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": True})

    async def scenario() -> None:
        supplied = client(httpx.MockTransport(handler))
        adapter = TelegramAdapter(settings(), supplied)
        await adapter.set_reaction(SetReactionRequest("-100", "42", kind))
        assert requests[0].url.path.endswith("/setMessageReaction")
        assert json.loads(requests[0].content) == {
            "chat_id": "-100",
            "message_id": 42,
            "reaction": [{"type": "emoji", "emoji": emoji}],
            "is_big": False,
        }
        assert PlatformCapability.SET_MESSAGE_REACTION in adapter.capabilities
        await supplied.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "reaction_request",
    [
        SetReactionRequest("", "42", ReactionKind.HEART),
        SetReactionRequest("chat-name", "42", ReactionKind.HEART),
        SetReactionRequest("0", "42", ReactionKind.HEART),
        SetReactionRequest("-100", "0", ReactionKind.HEART),
        SetReactionRequest("-100", "message", ReactionKind.HEART),
        SetReactionRequest("-100", "42", "🔥"),  # type: ignore[arg-type]
    ],
)
def test_set_reaction_rejects_invalid_or_non_allowlisted_targets(
    reaction_request: SetReactionRequest,
) -> None:
    async def scenario() -> None:
        calls = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"ok": True, "result": True})

        supplied = client(httpx.MockTransport(handler))
        with pytest.raises(PlatformAdapterError) as captured:
            await TelegramAdapter(settings(), supplied).set_reaction(reaction_request)
        assert captured.value.category == PlatformErrorCategory.INVALID_REQUEST
        assert calls == 0
        await supplied.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("400", PlatformErrorCategory.INVALID_REQUEST),
        ("403", PlatformErrorCategory.PERMISSION),
        ("429", PlatformErrorCategory.RATE_LIMITED),
        ("500", PlatformErrorCategory.SERVER),
        ("503", PlatformErrorCategory.SERVER),
        ("timeout", PlatformErrorCategory.TIMEOUT),
        ("reset", PlatformErrorCategory.NETWORK),
        ("malformed", PlatformErrorCategory.MALFORMED_RESPONSE),
        ("false", PlatformErrorCategory.UNSUPPORTED_RESPONSE),
    ],
)
def test_set_reaction_classifies_failure_and_never_retries(
    kind: str, expected: PlatformErrorCategory
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if kind == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        if kind == "reset":
            raise httpx.ReadError("synthetic reset")
        if kind == "malformed":
            return httpx.Response(200, text="{")
        if kind == "false":
            return httpx.Response(200, json={"ok": True, "result": False})
        code = int(kind)
        return httpx.Response(code, json={"ok": False, "error_code": code})

    async def scenario() -> None:
        supplied = client(httpx.MockTransport(handler))
        with pytest.raises(PlatformAdapterError) as captured:
            await TelegramAdapter(settings(), supplied).set_reaction(
                SetReactionRequest("-100", "42", ReactionKind.HEART)
            )
        assert captured.value.category == expected
        assert calls == 1
        await supplied.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "action_request",
    [
        SendChatActionRequest(""),
        SendChatActionRequest("-100", action="upload_photo"),
        SendChatActionRequest("-100", "0"),
        SendChatActionRequest("-100", "thread"),
    ],
)
def test_send_chat_action_rejects_non_typing_or_invalid_targets(
    action_request: SendChatActionRequest,
) -> None:
    async def scenario() -> None:
        supplied = client(
            httpx.MockTransport(
                lambda _: httpx.Response(200, json={"ok": True, "result": True})
            )
        )
        with pytest.raises(PlatformAdapterError) as captured:
            await TelegramAdapter(settings(), supplied).send_chat_action(action_request)
        assert captured.value.category == PlatformErrorCategory.INVALID_REQUEST
        await supplied.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("400", PlatformErrorCategory.INVALID_REQUEST),
        ("401", PlatformErrorCategory.AUTHENTICATION),
        ("403", PlatformErrorCategory.PERMISSION),
        ("429", PlatformErrorCategory.RATE_LIMITED),
        ("500", PlatformErrorCategory.SERVER),
        ("timeout", PlatformErrorCategory.TIMEOUT),
        ("reset", PlatformErrorCategory.NETWORK),
        ("malformed", PlatformErrorCategory.MALFORMED_RESPONSE),
    ],
)
def test_send_chat_action_classifies_failures_without_internal_retry(
    kind: str, expected: PlatformErrorCategory
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if kind == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        if kind == "reset":
            raise httpx.ReadError("synthetic reset")
        if kind == "malformed":
            return httpx.Response(200, text="{")
        code = int(kind)
        return httpx.Response(code, json={"ok": False, "error_code": code})

    async def scenario() -> None:
        supplied = client(httpx.MockTransport(handler))
        with pytest.raises(PlatformAdapterError) as captured:
            await TelegramAdapter(settings(), supplied).send_chat_action(
                SendChatActionRequest("-100")
            )
        assert captured.value.category == expected
        assert captured.value.delivery_certainty == (
            DeliveryCertainty.NOT_SENT
            if kind in {"timeout", "reset", "malformed"}
            else DeliveryCertainty.REJECTED
        )
        assert calls == 1
        await supplied.aclose()

    asyncio.run(scenario())


def test_send_text_enforces_telegram_utf16_limit() -> None:
    async def scenario() -> None:
        supplied = client(
            httpx.MockTransport(
                lambda _: httpx.Response(500, json={"ok": False, "error_code": 500})
            )
        )
        adapter = TelegramAdapter(settings(), supplied)
        with pytest.raises(PlatformAdapterError) as rejected:
            await adapter.send_text(SendTextRequest("1", "😀" * 2049))
        assert rejected.value.category == PlatformErrorCategory.INVALID_REQUEST
        await supplied.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Bad Request: message to be replied not found", True),
        ("Bad Request: reply message not found", True),
        ("Bad Request: chat not found", False),
        ("message to be replied not found", False),
    ],
)
def test_only_exact_missing_reply_rejection_is_classified_for_fallback(
    description: str, expected: bool
) -> None:
    async def scenario() -> None:
        supplied = client(
            httpx.MockTransport(
                lambda _: httpx.Response(
                    400,
                    json={
                        "ok": False,
                        "error_code": 400,
                        "description": description,
                    },
                )
            )
        )
        adapter = TelegramAdapter(settings(), supplied)
        with pytest.raises(PlatformAdapterError) as rejected:
            await adapter.send_text(
                SendTextRequest("1", "hello", reply_to_message_id="9")
            )
        assert rejected.value.delivery_certainty == DeliveryCertainty.REJECTED
        assert rejected.value.reply_target_rejected is expected
        await supplied.aclose()

    asyncio.run(scenario())


def test_chat_member_and_classified_failures_are_safe() -> None:
    responses = [
        {
            "ok": True,
            "result": {"status": "administrator", "can_delete_messages": True},
        },
        {
            "ok": False,
            "error_code": 429,
            "description": TOKEN,
            "parameters": {"retry_after": 4, "migrate_to_chat_id": -200},
        },
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    async def scenario() -> None:
        supplied = client(httpx.MockTransport(handler))
        adapter = TelegramAdapter(settings(), supplied)
        member = await adapter.get_chat_member("-100", "42")
        assert member.is_administrator and not member.is_owner
        with pytest.raises(PlatformAdapterError) as captured:
            await adapter.send_text(SendTextRequest("-100", "hello"))
        error = captured.value
        assert error.category == PlatformErrorCategory.RATE_LIMITED
        assert error.retry_after_seconds == 4
        assert error.replacement_conversation_id == "-200"
        assert error.delivery_certainty == DeliveryCertainty.REJECTED
        assert TOKEN not in str(error)
        await supplied.aclose()

    asyncio.run(scenario())


def test_malformed_and_timeout_responses_are_not_retried() -> None:
    async def scenario() -> None:
        timeout = TelegramAdapter(
            settings(),
            client(
                httpx.MockTransport(
                    lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("timeout"))
                )
            ),
        )
        with pytest.raises(PlatformAdapterError) as captured:
            await timeout.send_sticker(SendStickerRequest("-100", "file"))
        assert captured.value.category == PlatformErrorCategory.TIMEOUT
        assert captured.value.delivery_certainty == DeliveryCertainty.UNKNOWN
        with pytest.raises(PlatformAdapterError) as invalid:
            await timeout.send_text(SendTextRequest("", ""))
        assert invalid.value.category == PlatformErrorCategory.INVALID_REQUEST
        assert invalid.value.delivery_certainty == DeliveryCertainty.NOT_SENT

        malformed = TelegramAdapter(
            settings(),
            client(httpx.MockTransport(lambda _: httpx.Response(200, text="{"))),
        )
        with pytest.raises(PlatformAdapterError) as malformed_error:
            await malformed.send_text(SendTextRequest("-100", "hello"))
        assert (
            malformed_error.value.category == PlatformErrorCategory.MALFORMED_RESPONSE
        )
        assert malformed_error.value.delivery_certainty == DeliveryCertainty.UNKNOWN

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("code", "category"),
    [
        (401, PlatformErrorCategory.AUTHENTICATION),
        (403, PlatformErrorCategory.PERMISSION),
        (404, PlatformErrorCategory.NOT_FOUND),
        (409, PlatformErrorCategory.CONFLICT),
        (500, PlatformErrorCategory.SERVER),
    ],
)
def test_telegram_http_failures_are_classified(
    code: int, category: PlatformErrorCategory
) -> None:
    async def scenario() -> None:
        supplied = client(
            httpx.MockTransport(
                lambda _: httpx.Response(code, json={"ok": False, "error_code": code})
            )
        )
        with pytest.raises(PlatformAdapterError) as captured:
            await TelegramAdapter(settings(), supplied).verify_identity()
        assert captured.value.category == category
        await supplied.aclose()

    asyncio.run(scenario())


def test_malformed_response_and_unknown_member_status_are_rejected() -> None:
    responses = [
        {"ok": True, "result": []},
        {"ok": True, "result": {"status": "future"}},
    ]

    async def scenario() -> None:
        supplied = client(
            httpx.MockTransport(lambda _: httpx.Response(200, json=responses.pop(0)))
        )
        adapter = TelegramAdapter(settings(), supplied)
        with pytest.raises(PlatformAdapterError) as malformed:
            await adapter.verify_identity()
        assert malformed.value.category == PlatformErrorCategory.MALFORMED_RESPONSE
        with pytest.raises(PlatformAdapterError) as unsupported:
            await adapter.get_chat_member("-100", "1")
        assert unsupported.value.category == PlatformErrorCategory.UNSUPPORTED_RESPONSE
        await supplied.aclose()

    asyncio.run(scenario())


def test_update_delivery_and_webhook_lifecycle_are_typed() -> None:
    payloads: list[dict[str, object]] = []
    responses = [
        {"ok": True, "result": [{"update_id": 4_000_000_000, "message": {}}]},
        {"ok": True, "result": True},
        {"ok": True, "result": True},
        {
            "ok": True,
            "result": {
                "url": "https://example.invalid/hook",
                "has_custom_certificate": False,
                "pending_update_count": 2,
                "allowed_updates": ["message"],
                "max_connections": 10,
            },
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json=responses.pop(0))

    async def scenario() -> None:
        supplied = client(httpx.MockTransport(handler))
        adapter = TelegramAdapter(settings(), supplied)
        updates = await adapter.get_updates(
            offset="4000000000",
            limit=10,
            timeout_seconds=20,
            allowed_updates=("message",),
        )
        assert updates[0].update_id == "4000000000"
        await adapter.set_webhook(
            url="https://example.invalid/hook",
            secret_token="safe-secret",
            allowed_updates=("message",),
            max_connections=10,
        )
        await adapter.delete_webhook()
        info = await adapter.get_webhook_info()
        assert info.pending_update_count == 2
        assert payloads[0]["offset"] == 4_000_000_000
        assert payloads[1]["drop_pending_updates"] is False
        assert payloads[2]["drop_pending_updates"] is False
        await supplied.aclose()

    asyncio.run(scenario())
