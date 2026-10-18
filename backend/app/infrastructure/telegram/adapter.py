"""Narrow Telegram Bot API adapter with token-safe failures."""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from app.application.ports.platform import (
    BotIdentity,
    ChatMember,
    EditTextRequest,
    PlatformAdapterError,
    PlatformCapability,
    PlatformErrorCategory,
    SendChatActionRequest,
    SendStickerRequest,
    SendTextRequest,
    SendVoiceRequest,
    SentMessage,
    SetReactionRequest,
    WebhookInfo,
)
from app.application.telegram_text import utf16_length
from app.core.config import Settings
from app.domain.media import EphemeralMedia, MediaAttachment, MediaLimits
from app.domain.outbound import DeliveryCertainty
from app.domain.persistence import Platform
from app.domain.reactions import ReactionKind, reaction_emoji
from app.domain.voice import VOICE_ARTIFACT_MAX_BYTES
from app.infrastructure.telegram.media_download import download_media
from app.infrastructure.telegram.updates import TelegramUpdate, parse_telegram_update


class TelegramAdapter:
    """Typed Telegram Bot API adapter; provider DTOs never cross its boundary."""

    def __init__(
        self, settings: Settings, client: httpx.AsyncClient | None = None
    ) -> None:
        if not settings.telegram_enabled or settings.telegram_bot_token is None:
            raise PlatformAdapterError(
                PlatformErrorCategory.CONFIGURATION, "telegram_configuration"
            )
        self._token = settings.telegram_bot_token.get_secret_value()
        self._base_url = settings.telegram_api_base_url
        self._media_limits = MediaLimits(
            photo_max_bytes=settings.telegram_media_photo_max_bytes,
            audio_max_bytes=settings.telegram_media_audio_max_bytes,
            photo_max_side=settings.telegram_media_photo_max_side,
            audio_max_duration_seconds=settings.telegram_media_audio_max_duration_seconds,
            transcript_max_characters=settings.telegram_media_transcript_max_characters,
        )
        self._media_timeout = settings.telegram_media_download_timeout_seconds
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.telegram_timeout_seconds,
                connect=settings.telegram_connect_timeout_seconds,
            ),
            limits=httpx.Limits(max_connections=settings.telegram_connection_limit),
            headers={"User-Agent": settings.telegram_user_agent},
        )

    @property
    def capabilities(self) -> frozenset[PlatformCapability]:
        return frozenset(PlatformCapability)

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def download_media(
        self,
        attachment: MediaAttachment,
        before_io: Callable[[], Awaitable[bool]] | None = None,
    ) -> EphemeralMedia:
        return await download_media(
            self._client,
            self._base_url,
            self._token,
            attachment,
            self._media_limits,
            self._media_timeout,
            before_io,
        )

    async def verify_identity(self) -> BotIdentity:
        result = await self._request("getMe", {})
        if result.get("is_bot") is not True:
            raise PlatformAdapterError(
                PlatformErrorCategory.UNSUPPORTED_RESPONSE, "getMe"
            )
        return BotIdentity(
            platform=Platform.TELEGRAM,
            external_bot_id=self._string(result, "id", "getMe"),
            username=self._optional_string(result, "username", "getMe"),
            display_name=self._string(result, "first_name", "getMe"),
            is_bot=True,
            can_join_groups=self._optional_bool(result, "can_join_groups", "getMe"),
            can_read_all_group_messages=self._optional_bool(
                result, "can_read_all_group_messages", "getMe"
            ),
        )

    async def send_text(self, request: SendTextRequest) -> SentMessage:
        if (
            not request.conversation_id
            or not request.text
            or utf16_length(request.text) > 4096
        ):
            raise PlatformAdapterError(
                PlatformErrorCategory.INVALID_REQUEST, "sendMessage"
            )
        payload: dict[str, Any] = {
            "chat_id": request.conversation_id,
            "text": request.text,
        }
        self._add_send_options(payload, request)
        if request.entities:
            payload["entities"] = [
                {
                    "type": entity.entity_type,
                    "offset": entity.offset,
                    "length": entity.length,
                }
                for entity in request.entities
            ]
        return self._message(await self._request("sendMessage", payload), "sendMessage")

    async def edit_text(self, request: EditTextRequest) -> SentMessage:
        if (
            not request.conversation_id
            or not request.platform_message_id.isdecimal()
            or int(request.platform_message_id) <= 0
            or not request.text
            or utf16_length(request.text) > 4096
        ):
            raise PlatformAdapterError(
                PlatformErrorCategory.INVALID_REQUEST, "editMessageText"
            )
        payload: dict[str, Any] = {
            "chat_id": request.conversation_id,
            "message_id": request.platform_message_id,
            "text": request.text,
        }
        if request.entities:
            payload["entities"] = [
                {
                    "type": entity.entity_type,
                    "offset": entity.offset,
                    "length": entity.length,
                }
                for entity in request.entities
            ]
        message = self._message(
            await self._request("editMessageText", payload), "editMessageText"
        )
        if (
            message.platform_message_id != request.platform_message_id
            or message.conversation_id != request.conversation_id
        ):
            raise PlatformAdapterError(
                PlatformErrorCategory.MALFORMED_RESPONSE,
                "editMessageText",
                delivery_certainty=DeliveryCertainty.UNKNOWN,
            )
        return message

    async def send_sticker(self, request: SendStickerRequest) -> SentMessage:
        if not request.conversation_id or not request.asset_reference.strip():
            raise PlatformAdapterError(
                PlatformErrorCategory.INVALID_REQUEST, "sendSticker"
            )
        payload: dict[str, Any] = {
            "chat_id": request.conversation_id,
            "sticker": request.asset_reference,
        }
        self._add_send_options(payload, request)
        return self._message(await self._request("sendSticker", payload), "sendSticker")

    async def send_voice(self, request: SendVoiceRequest) -> SentMessage:
        if (
            not request.conversation_id
            or not 1 <= len(request.audio_bytes) <= VOICE_ARTIFACT_MAX_BYTES
            or not request.audio_bytes.startswith(b"OggS")
        ):
            raise PlatformAdapterError(
                PlatformErrorCategory.INVALID_REQUEST, "sendVoice"
            )
        payload: dict[str, Any] = {"chat_id": request.conversation_id}
        self._add_send_options(payload, request)
        data: dict[str, str] = {}
        for key, value in payload.items():
            if isinstance(value, dict | list):
                data[key] = json.dumps(value, separators=(",", ":"))
            elif isinstance(value, bool):
                data[key] = str(value).lower()
            else:
                data[key] = str(value)
        try:
            response = await self._client.post(
                f"{self._base_url}/bot{self._token}/sendVoice",
                data=data,
                files={"voice": ("voice.ogg", request.audio_bytes, "audio/ogg")},
            )
        except httpx.TimeoutException as error:
            raise PlatformAdapterError(
                PlatformErrorCategory.TIMEOUT,
                "sendVoice",
                delivery_certainty=DeliveryCertainty.UNKNOWN,
            ) from error
        except httpx.HTTPError as error:
            raise PlatformAdapterError(
                PlatformErrorCategory.NETWORK,
                "sendVoice",
                retryable=True,
                delivery_certainty=DeliveryCertainty.UNKNOWN,
            ) from error
        return self._message(
            self._response_result(response, "sendVoice", dict), "sendVoice"
        )

    async def send_chat_action(self, request: SendChatActionRequest) -> None:
        if not request.conversation_id or request.action != "typing":
            raise PlatformAdapterError(
                PlatformErrorCategory.INVALID_REQUEST, "sendChatAction"
            )
        payload: dict[str, Any] = {
            "chat_id": request.conversation_id,
            "action": request.action,
        }
        if request.message_thread_id is not None:
            if (
                not request.message_thread_id.isdecimal()
                or int(request.message_thread_id) <= 0
            ):
                raise PlatformAdapterError(
                    PlatformErrorCategory.INVALID_REQUEST, "sendChatAction"
                )
            payload["message_thread_id"] = request.message_thread_id
        result = await self._request("sendChatAction", payload, result_type=bool)
        if result is not True:
            raise PlatformAdapterError(
                PlatformErrorCategory.UNSUPPORTED_RESPONSE, "sendChatAction"
            )

    async def set_reaction(self, request: SetReactionRequest) -> None:
        chat_id = request.conversation_id
        message_id = request.platform_message_id
        if (
            not chat_id
            or not chat_id.lstrip("-").isdecimal()
            or int(chat_id) == 0
            or not message_id.isdecimal()
            or int(message_id) <= 0
            or not isinstance(request.kind, ReactionKind)
        ):
            raise PlatformAdapterError(
                PlatformErrorCategory.INVALID_REQUEST, "setMessageReaction"
            )
        result = await self._request(
            "setMessageReaction",
            {
                "chat_id": chat_id,
                "message_id": int(message_id),
                "reaction": [{"type": "emoji", "emoji": reaction_emoji(request.kind)}],
                "is_big": False,
            },
            result_type=bool,
        )
        if result is not True:
            raise PlatformAdapterError(
                PlatformErrorCategory.UNSUPPORTED_RESPONSE, "setMessageReaction"
            )

    async def get_chat_member(self, conversation_id: str, user_id: str) -> ChatMember:
        if not conversation_id or not user_id:
            raise PlatformAdapterError(
                PlatformErrorCategory.INVALID_REQUEST, "getChatMember"
            )
        result = await self._request(
            "getChatMember", {"chat_id": conversation_id, "user_id": user_id}
        )
        status = self._string(result, "status", "getChatMember")
        normalized = {
            "creator": "owner",
            "owner": "owner",
            "administrator": "administrator",
            "member": "member",
            "restricted": "restricted",
            "left": "left",
            "kicked": "kicked",
        }
        if status not in normalized:
            raise PlatformAdapterError(
                PlatformErrorCategory.UNSUPPORTED_RESPONSE, "getChatMember"
            )
        permissions = frozenset(
            key
            for key, value in result.items()
            if key.startswith("can_") and value is True
        )
        return ChatMember(
            conversation_id=conversation_id,
            user_id=user_id,
            status=normalized[status],
            is_administrator=status in {"creator", "owner", "administrator"},
            is_owner=status in {"creator", "owner"},
            permissions=permissions,
        )

    async def get_updates(
        self,
        *,
        offset: str | None,
        limit: int,
        timeout_seconds: int,
        allowed_updates: tuple[str, ...],
    ) -> tuple[TelegramUpdate, ...]:
        if not 1 <= limit <= 100 or timeout_seconds <= 0:
            raise PlatformAdapterError(
                PlatformErrorCategory.INVALID_REQUEST, "getUpdates"
            )
        payload: dict[str, Any] = {
            "limit": limit,
            "timeout": timeout_seconds,
            "allowed_updates": list(allowed_updates),
        }
        if offset is not None:
            try:
                payload["offset"] = int(offset)
            except ValueError as error:
                raise PlatformAdapterError(
                    PlatformErrorCategory.INVALID_REQUEST, "getUpdates"
                ) from error
        result = await self._request("getUpdates", payload, result_type=list)
        return tuple(parse_telegram_update(item) for item in result)

    async def set_webhook(
        self,
        *,
        url: str,
        secret_token: str,
        allowed_updates: tuple[str, ...],
        max_connections: int,
        drop_pending_updates: bool = False,
    ) -> None:
        if not url.startswith("https://") or not 1 <= max_connections <= 100:
            raise PlatformAdapterError(
                PlatformErrorCategory.INVALID_REQUEST, "setWebhook"
            )
        result = await self._request(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": list(allowed_updates),
                "max_connections": max_connections,
                "drop_pending_updates": drop_pending_updates,
            },
            result_type=bool,
        )
        if result is not True:
            raise PlatformAdapterError(
                PlatformErrorCategory.UNSUPPORTED_RESPONSE, "setWebhook"
            )

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        result = await self._request(
            "deleteWebhook",
            {"drop_pending_updates": drop_pending_updates},
            result_type=bool,
        )
        if result is not True:
            raise PlatformAdapterError(
                PlatformErrorCategory.UNSUPPORTED_RESPONSE, "deleteWebhook"
            )

    async def get_webhook_info(self) -> WebhookInfo:
        result = await self._request("getWebhookInfo", {})
        raw_allowed = result.get("allowed_updates", [])
        if not isinstance(raw_allowed, list) or not all(
            isinstance(item, str) for item in raw_allowed
        ):
            raise PlatformAdapterError(
                PlatformErrorCategory.MALFORMED_RESPONSE, "getWebhookInfo"
            )
        raw_date = result.get("last_error_date")
        return WebhookInfo(
            url=self._string(result, "url", "getWebhookInfo"),
            pending_update_count=self._integer(
                result, "pending_update_count", "getWebhookInfo"
            ),
            allowed_updates=tuple(raw_allowed),
            max_connections=self._optional_integer(
                result, "max_connections", "getWebhookInfo"
            ),
            last_error_at=datetime.fromtimestamp(raw_date, UTC)
            if isinstance(raw_date, int)
            else None,
            last_error_message=self._optional_string(
                result, "last_error_message", "getWebhookInfo"
            ),
            ip_address=self._optional_string(result, "ip_address", "getWebhookInfo"),
            has_custom_certificate=self._optional_bool(
                result, "has_custom_certificate", "getWebhookInfo"
            )
            is True,
        )

    def _add_send_options(
        self,
        payload: dict[str, Any],
        request: SendTextRequest | SendStickerRequest | SendVoiceRequest,
    ) -> None:
        if request.message_thread_id is not None and (
            not request.message_thread_id.isdecimal()
            or int(request.message_thread_id) <= 0
        ):
            raise PlatformAdapterError(
                PlatformErrorCategory.INVALID_REQUEST, "send_thread"
            )
        if request.reply_to_message_id is not None:
            payload["reply_parameters"] = {
                "message_id": request.reply_to_message_id,
                "allow_sending_without_reply": False,
            }
        if request.message_thread_id is not None:
            payload["message_thread_id"] = request.message_thread_id
        if request.disable_notification is not None:
            payload["disable_notification"] = request.disable_notification
        if request.protect_content is not None:
            payload["protect_content"] = request.protect_content

    async def _request(
        self, operation: str, payload: dict[str, Any], result_type: type[object] = dict
    ) -> Any:
        try:
            response = await self._client.post(
                f"{self._base_url}/bot{self._token}/{operation}", json=payload
            )
        except httpx.TimeoutException as error:
            raise PlatformAdapterError(
                PlatformErrorCategory.TIMEOUT,
                operation,
                delivery_certainty=self._certainty_for_transport(operation),
            ) from error
        except httpx.HTTPError as error:
            raise PlatformAdapterError(
                PlatformErrorCategory.NETWORK,
                operation,
                retryable=True,
                delivery_certainty=self._certainty_for_transport(operation),
            ) from error
        return self._response_result(response, operation, result_type)

    def _response_result(
        self, response: httpx.Response, operation: str, result_type: type[object]
    ) -> Any:
        try:
            envelope = response.json()
        except ValueError as error:
            raise PlatformAdapterError(
                PlatformErrorCategory.MALFORMED_RESPONSE,
                operation,
                delivery_certainty=self._certainty_for_transport(operation),
            ) from error
        if not isinstance(envelope, dict) or not isinstance(envelope.get("ok"), bool):
            raise PlatformAdapterError(
                PlatformErrorCategory.MALFORMED_RESPONSE,
                operation,
                delivery_certainty=self._certainty_for_transport(operation),
            )
        if envelope["ok"] is True:
            result = envelope.get("result")
            if not isinstance(result, result_type):
                raise PlatformAdapterError(
                    PlatformErrorCategory.MALFORMED_RESPONSE,
                    operation,
                    delivery_certainty=self._certainty_for_transport(operation),
                )
            return result
        self._raise_failure(operation, envelope, response.status_code)
        raise AssertionError("unreachable")

    def _raise_failure(
        self, operation: str, envelope: dict[str, Any], status_code: int
    ) -> None:
        raw_code = envelope.get("error_code")
        code = raw_code if isinstance(raw_code, int) else status_code
        category = {
            401: PlatformErrorCategory.AUTHENTICATION,
            403: PlatformErrorCategory.PERMISSION,
            400: PlatformErrorCategory.INVALID_REQUEST,
            404: PlatformErrorCategory.NOT_FOUND,
            409: PlatformErrorCategory.CONFLICT,
            429: PlatformErrorCategory.RATE_LIMITED,
        }.get(code)
        if category is None:
            category = (
                PlatformErrorCategory.SERVER
                if code >= 500
                else PlatformErrorCategory.INVALID_REQUEST
            )
        raw_parameters = envelope.get("parameters")
        parameters: dict[str, Any] = (
            raw_parameters if isinstance(raw_parameters, dict) else {}
        )
        retry_after = (
            parameters.get("retry_after")
            if isinstance(parameters.get("retry_after"), int)
            else None
        )
        migrate = parameters.get("migrate_to_chat_id")
        description = envelope.get("description")
        normalized_description = (
            description.strip().casefold() if isinstance(description, str) else ""
        )
        reply_target_rejected = (
            operation in {"sendMessage", "sendSticker", "sendVoice"}
            and code == 400
            and normalized_description
            in {
                "bad request: message to be replied not found",
                "bad request: reply message not found",
                "bad request: replied message not found",
            }
        )
        edit_not_modified = (
            operation == "editMessageText"
            and code == 400
            and normalized_description.startswith(
                "bad request: message is not modified"
            )
        )
        edit_target_rejected = (
            operation == "editMessageText"
            and code == 400
            and normalized_description
            in {
                "bad request: message to edit not found",
                "bad request: message can't be edited",
                "bad request: there is no text in the message to edit",
            }
        )
        raise PlatformAdapterError(
            category,
            operation,
            retryable=category
            in {PlatformErrorCategory.RATE_LIMITED, PlatformErrorCategory.SERVER},
            retry_after_seconds=retry_after,
            replacement_conversation_id=str(migrate)
            if isinstance(migrate, str | int)
            else None,
            telegram_error_code=code,
            reply_target_rejected=reply_target_rejected,
            edit_target_rejected=edit_target_rejected,
            edit_not_modified=edit_not_modified,
            delivery_certainty=(
                DeliveryCertainty.UNKNOWN
                if operation == "editMessageText" and code >= 500
                else DeliveryCertainty.REJECTED
            ),
        )

    def _certainty_for_transport(self, operation: str) -> DeliveryCertainty:
        return (
            DeliveryCertainty.UNKNOWN
            if operation
            in {"sendMessage", "sendSticker", "sendVoice", "editMessageText"}
            else DeliveryCertainty.NOT_SENT
        )

    def _message(self, result: dict[str, Any], operation: str) -> SentMessage:
        raw_chat = result.get("chat")
        chat: dict[str, Any] = raw_chat if isinstance(raw_chat, dict) else {}
        raw_sender = result.get("from")
        sender: dict[str, Any] = raw_sender if isinstance(raw_sender, dict) else {}
        date = result.get("date")
        return SentMessage(
            Platform.TELEGRAM,
            self._string(result, "message_id", operation),
            self._string(chat, "id", operation),
            str(sender["id"]) if isinstance(sender.get("id"), str | int) else None,
            str(result["message_thread_id"])
            if isinstance(result.get("message_thread_id"), str | int)
            else None,
            datetime.fromtimestamp(date, UTC) if isinstance(date, int) else None,
        )

    def _string(self, value: dict[str, Any], key: str, operation: str) -> str:
        raw = value.get(key)
        if not isinstance(raw, str | int):
            raise PlatformAdapterError(
                PlatformErrorCategory.MALFORMED_RESPONSE, operation
            )
        return str(raw)

    def _optional_string(
        self, value: dict[str, Any], key: str, operation: str
    ) -> str | None:
        raw = value.get(key)
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise PlatformAdapterError(
                PlatformErrorCategory.MALFORMED_RESPONSE, operation
            )
        return raw

    def _optional_bool(
        self, value: dict[str, Any], key: str, operation: str
    ) -> bool | None:
        raw = value.get(key)
        if raw is None:
            return None
        if not isinstance(raw, bool):
            raise PlatformAdapterError(
                PlatformErrorCategory.MALFORMED_RESPONSE, operation
            )
        return raw

    def _integer(self, value: dict[str, Any], key: str, operation: str) -> int:
        raw = value.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise PlatformAdapterError(
                PlatformErrorCategory.MALFORMED_RESPONSE, operation
            )
        return raw

    def _optional_integer(
        self, value: dict[str, Any], key: str, operation: str
    ) -> int | None:
        raw = value.get(key)
        if raw is None:
            return None
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise PlatformAdapterError(
                PlatformErrorCategory.MALFORMED_RESPONSE, operation
            )
        return int(raw)


def create_telegram_adapter(settings: Settings) -> TelegramAdapter | None:
    """Compose Telegram only when explicitly enabled; construction is network-free."""

    return TelegramAdapter(settings) if settings.telegram_enabled else None
