"""Explicit Telegram connection and webhook lifecycle operations.

Every operation requires an explicit ``--confirm-live-telegram`` flag and never
prints the bot token. Registration and deletion verify the resulting Telegram
state and fail closed on any mismatch.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from app.application.ports.platform import (
    BotIdentity,
    PlatformAdapterError,
    WebhookInfo,
)
from app.core.config import Settings
from app.infrastructure.telegram.adapter import TelegramAdapter

WEBHOOK_PATH = "/api/v1/platforms/telegram/webhook/"


def expected_webhook_url(settings: Settings) -> str:
    if settings.telegram_webhook_public_base_url is None:
        raise RuntimeError(
            "telegram_webhook_public_base_url is required for webhook delivery"
        )
    if settings.telegram_platform_connection_id is None:
        raise RuntimeError("telegram_platform_connection_id is required")
    return (
        f"{settings.telegram_webhook_public_base_url}{WEBHOOK_PATH}"
        f"{settings.telegram_platform_connection_id}"
    )


def identity_evidence(identity: BotIdentity) -> dict[str, object]:
    return {
        "platform": identity.platform.value,
        "external_bot_id": identity.external_bot_id,
        "username": identity.username,
        "display_name": identity.display_name,
        "is_bot": identity.is_bot,
        "can_join_groups": identity.can_join_groups,
        "can_read_all_group_messages": identity.can_read_all_group_messages,
    }


def webhook_evidence(settings: Settings, info: WebhookInfo) -> dict[str, object]:
    try:
        expected = expected_webhook_url(settings)
    except RuntimeError:
        expected = None
    return {
        "configured": bool(info.url),
        "url": info.url,
        "expected_url": expected,
        "url_matches_expected": info.url == expected if expected is not None else None,
        "pending_update_count": info.pending_update_count,
        "allowed_updates": list(info.allowed_updates),
        "max_connections": info.max_connections,
        "has_custom_certificate": info.has_custom_certificate,
        "last_error_at": info.last_error_at.isoformat() if info.last_error_at else None,
        "last_error_message": info.last_error_message,
        "ip_address_present": info.ip_address is not None,
    }


@dataclass(frozen=True, slots=True)
class ModeExclusivity:
    configured_mode: str
    telegram_webhook_active: bool
    polling_allowed: bool
    consistent: bool
    observations: tuple[str, ...] = field(default_factory=tuple)

    def evidence(self) -> dict[str, object]:
        return {
            "configured_mode": self.configured_mode,
            "telegram_webhook_active": self.telegram_webhook_active,
            "polling_allowed": self.polling_allowed,
            "consistent": self.consistent,
            "observations": list(self.observations),
        }


def assess_exclusivity(settings: Settings, info: WebhookInfo) -> ModeExclusivity:
    configured = settings.telegram_delivery_mode
    webhook_active = bool(info.url)
    observations: list[str] = []
    conflict = False
    if configured == "webhook":
        if not webhook_active:
            observations.append(
                "webhook mode configured but no Telegram webhook is active"
            )
        elif info.url != expected_webhook_url(settings):
            conflict = True
            observations.append(
                "Telegram webhook URL does not match the approved configuration"
            )
    elif webhook_active:
        conflict = True
        observations.append(
            f"{configured} mode configured but Telegram reports an active webhook"
        )
    return ModeExclusivity(
        configured_mode=configured,
        telegram_webhook_active=webhook_active,
        polling_allowed=not webhook_active,
        consistent=not conflict,
        observations=tuple(observations),
    )


@dataclass(frozen=True, slots=True)
class ConnectionVerification:
    ok: bool
    environment: str
    platform_connection_id: str
    delivery_mode: str
    identity: dict[str, object] | None
    webhook: dict[str, object]
    exclusivity: ModeExclusivity | None
    observations: tuple[str, ...]

    def evidence(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "environment": self.environment,
            "connection": {
                "platform_connection_id": self.platform_connection_id,
                "delivery_mode": self.delivery_mode,
            },
            "bot_identity": self.identity,
            "webhook_state": self.webhook,
            "mode_exclusivity": (
                self.exclusivity.evidence() if self.exclusivity is not None else None
            ),
            "observations": list(self.observations),
        }


async def verify_connection(
    settings: Settings,
    adapter: TelegramAdapter,
    *,
    approved_bot_id: str | None = None,
) -> ConnectionVerification:
    errors: list[str] = []
    observations: list[str] = []
    identity: dict[str, object] | None = None
    webhook: dict[str, object] = {"configured": False, "unavailable": True}
    exclusivity: ModeExclusivity | None = None
    if not settings.telegram_enabled:
        errors.append("telegram_enabled must be true for live acceptance")
    if settings.telegram_platform_connection_id is None:
        errors.append("telegram_platform_connection_id is required for live acceptance")
    if settings.telegram_delivery_mode == "disabled":
        observations.append("delivery mode is disabled; no ingress source is active")
    try:
        bot = await adapter.verify_identity()
        identity = identity_evidence(bot)
        if bot.is_bot is not True:
            errors.append("getMe did not confirm a bot account")
        if approved_bot_id is not None and bot.external_bot_id != approved_bot_id:
            errors.append(
                "verified bot identity does not match the approved connection record"
            )
    except PlatformAdapterError as error:
        errors.append(f"bot identity verification failed ({error.category.value})")
    try:
        info = await adapter.get_webhook_info()
        webhook = webhook_evidence(settings, info)
        exclusivity = assess_exclusivity(settings, info)
        observations.extend(exclusivity.observations)
        if not exclusivity.consistent:
            errors.append(
                "Telegram mode state conflicts with the configured delivery mode"
            )
    except PlatformAdapterError as error:
        errors.append(f"webhook state inspection failed ({error.category.value})")
    return ConnectionVerification(
        ok=not errors,
        environment=settings.environment,
        platform_connection_id=str(settings.telegram_platform_connection_id or ""),
        delivery_mode=settings.telegram_delivery_mode,
        identity=identity,
        webhook=webhook,
        exclusivity=exclusivity,
        observations=tuple([*observations, *errors]),
    )


async def register_webhook(
    settings: Settings,
    adapter: TelegramAdapter,
    *,
    approved_bot_id: str | None = None,
) -> dict[str, object]:
    if settings.telegram_delivery_mode != "webhook":
        raise RuntimeError(
            "webhook registration requires telegram_delivery_mode=webhook"
        )
    if settings.telegram_webhook_secret_token is None:
        raise RuntimeError(
            "telegram_webhook_secret_token is required for webhook registration"
        )
    url = expected_webhook_url(settings)
    verification = await verify_connection(
        settings, adapter, approved_bot_id=approved_bot_id
    )
    if not verification.ok:
        raise RuntimeError(
            f"connection readiness failed: {'; '.join(verification.observations)}"
        )
    await adapter.set_webhook(
        url=url,
        secret_token=settings.telegram_webhook_secret_token.get_secret_value(),
        allowed_updates=settings.telegram_allowed_updates,
        max_connections=settings.telegram_webhook_max_connections,
    )
    confirmed = await adapter.get_webhook_info()
    if confirmed.url != url:
        raise RuntimeError(
            "Telegram did not confirm the expected webhook URL after registration"
        )
    if set(confirmed.allowed_updates) != set(settings.telegram_allowed_updates):
        raise RuntimeError(
            "Telegram did not confirm the expected allowed update set "
            "after registration"
        )
    return {
        "status": "registered",
        "activated_at": datetime.now(UTC).isoformat(),
        "webhook_url": url,
        "allowed_updates": list(settings.telegram_allowed_updates),
    }


async def delete_webhook(
    settings: Settings,
    adapter: TelegramAdapter,
    *,
    drop_pending_updates: bool = False,
) -> dict[str, object]:
    await adapter.delete_webhook(drop_pending_updates=drop_pending_updates)
    confirmed = await adapter.get_webhook_info()
    if confirmed.url != "":
        raise RuntimeError("Telegram still reports a configured webhook after deletion")
    return {
        "status": "deleted",
        "removed_at": datetime.now(UTC).isoformat(),
        "drop_pending_updates": drop_pending_updates,
    }


async def mode_verify(
    settings: Settings, adapter: TelegramAdapter
) -> dict[str, object]:
    info = await adapter.get_webhook_info()
    exclusivity = assess_exclusivity(settings, info)
    return {"mode_exclusivity": exclusivity.evidence()}


async def load_approved_bot_id(settings: Settings) -> str | None:
    if settings.telegram_platform_connection_id is None:
        return None
    from app.infrastructure.database.database import Database
    from app.infrastructure.database.tenancy import connection_authority

    database = Database(settings)
    await database.start()
    try:
        async with database.session_factory() as session:
            authority = await connection_authority(
                session, settings.telegram_platform_connection_id
            )
            if authority is None:
                return None
            if not authority.permits_external_io:
                raise RuntimeError("tenant, assistant, or connection is not active")
            return authority.connection.external_bot_id
    finally:
        await database.stop()


def emit(result: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, sort_keys=True))
        return
    for key, value in result.items():
        if isinstance(value, dict | list | tuple):
            print(f"{key}={json.dumps(value, sort_keys=True)}")
        else:
            print(f"{key}={value}")


def required_confirmation(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    if not args.confirm_live_telegram:
        parser.error(
            "--confirm-live-telegram is required; no Telegram request was made"
        )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("verify", "verify connection readiness (identity, webhook state, mode)"),
        ("webhook-inspect", "inspect redacted bot identity and Telegram webhook state"),
        ("webhook-register", "register the approved webhook and verify Telegram state"),
        ("webhook-delete", "delete the webhook and verify Telegram state"),
        ("mode-verify", "verify exactly one ingress mode is active"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("--confirm-live-telegram", action="store_true")
        sub.add_argument("--json", action="store_true")
        if name == "webhook-delete":
            sub.add_argument("--confirm-delete-webhook", action="store_true")
            sub.add_argument("--drop-pending-updates", action="store_true")
    args = parser.parse_args()
    required_confirmation(parser, args)
    settings = Settings()
    if not settings.telegram_enabled or settings.telegram_bot_token is None:
        parser.error(
            "Set JANUARY_TELEGRAM_ENABLED=true and JANUARY_TELEGRAM_BOT_TOKEN first."
        )
    adapter = TelegramAdapter(settings)
    try:
        approved = await load_approved_bot_id(settings)
        if approved is None:
            raise RuntimeError(
                "no approved connection record found; reconcile the connection first"
            )
        if args.command == "verify":
            verification = await verify_connection(
                settings, adapter, approved_bot_id=approved
            )
            result = verification.evidence()
        elif args.command == "webhook-inspect":
            verification = await verify_connection(
                settings, adapter, approved_bot_id=approved
            )
            result = verification.evidence()
        elif args.command == "webhook-register":
            result = await register_webhook(settings, adapter, approved_bot_id=approved)
        elif args.command == "webhook-delete":
            if not args.confirm_delete_webhook:
                parser.error(
                    "--confirm-delete-webhook is required; no webhook was deleted"
                )
            result = await delete_webhook(
                settings, adapter, drop_pending_updates=args.drop_pending_updates
            )
        else:
            result = await mode_verify(settings, adapter)
            if not cast(dict[str, object], result["mode_exclusivity"])["consistent"]:
                emit(result, as_json=bool(args.json))
                return 1
    except (RuntimeError, PlatformAdapterError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        await adapter.aclose()
    emit(result, as_json=bool(args.json))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
