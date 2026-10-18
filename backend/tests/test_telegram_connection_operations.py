import asyncio
import json
from uuid import uuid4

from app.application.ports.platform import BotIdentity, WebhookInfo
from app.core.config import Settings
from app.domain.persistence import Platform
from app.runtime.telegram_connection_operations import (
    assess_exclusivity,
    delete_webhook,
    expected_webhook_url,
    mode_verify,
    register_webhook,
    verify_connection,
)

TOKEN = "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
BASE_URL = "https://hooks.example.invalid"


def bot_identity() -> BotIdentity:
    return BotIdentity(
        Platform.TELEGRAM,
        "123456789",
        "january_bot",
        "January",
        True,
        True,
        False,
    )


def webhook_info(url: str = "", allowed_updates: tuple[str, ...] = ()) -> WebhookInfo:
    return WebhookInfo(
        url=url,
        pending_update_count=0,
        allowed_updates=allowed_updates,
        max_connections=None,
        last_error_at=None,
        last_error_message=None,
        ip_address=None,
        has_custom_certificate=False,
    )


def settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "environment": "test",
        "telegram_enabled": True,
        "telegram_bot_token": TOKEN,
        "telegram_platform_connection_id": uuid4(),
    }
    base.update(overrides)
    return Settings(**base)


def webhook_settings() -> Settings:
    return settings(
        telegram_delivery_mode="webhook",
        telegram_webhook_secret_token="test-secret",
        telegram_webhook_public_base_url=BASE_URL,
    )


class FakeAdapter:
    def __init__(
        self,
        identity: BotIdentity | None = None,
        url: str = "",
        allowed_updates: tuple[str, ...] = (),
        ignore_registration: bool = False,
    ) -> None:
        self.identity = identity or bot_identity()
        self.url = url
        self.allowed_updates = allowed_updates
        self.ignore_registration = ignore_registration
        self.set_calls: list[dict[str, object]] = []
        self.delete_calls: list[bool] = []

    async def verify_identity(self) -> BotIdentity:
        return self.identity

    async def get_webhook_info(self) -> WebhookInfo:
        return webhook_info(self.url, self.allowed_updates)

    async def set_webhook(
        self,
        *,
        url: str,
        secret_token: str,
        allowed_updates: tuple[str, ...],
        max_connections: int,
        drop_pending_updates: bool = False,
    ) -> None:
        self.set_calls.append(
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": allowed_updates,
                "max_connections": max_connections,
            }
        )
        if not self.ignore_registration:
            self.url = url
            self.allowed_updates = tuple(allowed_updates)

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        self.delete_calls.append(drop_pending_updates)
        self.url = ""


class WrongAllowedUpdatesAdapter(FakeAdapter):
    async def get_webhook_info(self) -> WebhookInfo:
        return webhook_info(self.url, ("chat_member",))


def test_expected_webhook_url_uses_approved_connection_path() -> None:
    cfg = webhook_settings()
    assert cfg.telegram_platform_connection_id is not None
    assert expected_webhook_url(cfg) == (
        f"{BASE_URL}/api/v1/platforms/telegram/webhook/"
        f"{cfg.telegram_platform_connection_id}"
    )


def test_verify_connection_passes_for_consistent_webhook_mode() -> None:
    async def scenario() -> None:
        cfg = webhook_settings()
        adapter = FakeAdapter(url=expected_webhook_url(cfg))
        result = await verify_connection(cfg, adapter, approved_bot_id="123456789")
        assert result.ok
        assert result.exclusivity is not None
        assert result.exclusivity.consistent
        assert result.identity is not None
        assert result.identity["external_bot_id"] == "123456789"
        assert result.webhook["url_matches_expected"] is True
        assert TOKEN not in json.dumps(result.evidence())

    asyncio.run(scenario())


def test_verify_connection_fails_closed_on_polling_with_active_webhook() -> None:
    async def scenario() -> None:
        cfg = settings(telegram_delivery_mode="polling")
        adapter = FakeAdapter(url="https://hooks.example.invalid/foreign")
        result = await verify_connection(cfg, adapter, approved_bot_id="123456789")
        assert not result.ok
        assert result.exclusivity is not None
        assert not result.exclusivity.consistent
        assert any("active webhook" in item for item in result.observations)

    asyncio.run(scenario())


def test_verify_connection_fails_when_identity_mismatches_approved_record() -> None:
    async def scenario() -> None:
        cfg = webhook_settings()
        adapter = FakeAdapter(url=expected_webhook_url(cfg))
        result = await verify_connection(cfg, adapter, approved_bot_id="987654321")
        assert not result.ok
        assert any("approved connection record" in item for item in result.observations)

    asyncio.run(scenario())


def test_verify_connection_reports_inactive_webhook_without_conflict() -> None:
    async def scenario() -> None:
        cfg = webhook_settings()
        adapter = FakeAdapter()
        result = await verify_connection(cfg, adapter, approved_bot_id="123456789")
        assert result.ok
        assert result.exclusivity is not None
        assert result.exclusivity.consistent
        assert any(
            "no Telegram webhook is active" in item for item in result.observations
        )

    asyncio.run(scenario())


def test_register_webhook_fails_closed_when_mode_is_not_webhook() -> None:
    async def scenario() -> None:
        cfg = settings(telegram_delivery_mode="polling")
        try:
            await register_webhook(cfg, FakeAdapter(), approved_bot_id="123456789")
        except RuntimeError as error:
            assert "telegram_delivery_mode=webhook" in str(error)
            return
        raise AssertionError("register_webhook must refuse non-webhook mode")

    asyncio.run(scenario())


def test_register_webhook_verifies_telegram_state_after_registration() -> None:
    async def scenario() -> None:
        cfg = webhook_settings()
        adapter = FakeAdapter()
        result = await register_webhook(cfg, adapter, approved_bot_id="123456789")
        assert result["status"] == "registered"
        assert result["webhook_url"] == expected_webhook_url(cfg)
        assert len(adapter.set_calls) == 1
        assert adapter.set_calls[0]["secret_token"] == "test-secret"
        assert adapter.set_calls[0]["url"] == expected_webhook_url(cfg)
        assert set(adapter.set_calls[0]["allowed_updates"]) == set(
            cfg.telegram_allowed_updates
        )
        assert TOKEN not in json.dumps(result)

    asyncio.run(scenario())


def test_register_webhook_fails_closed_when_telegram_reports_wrong_url() -> None:
    async def scenario() -> None:
        cfg = webhook_settings()
        adapter = FakeAdapter(ignore_registration=True)
        try:
            await register_webhook(cfg, adapter, approved_bot_id="123456789")
        except RuntimeError as error:
            assert "did not confirm the expected webhook URL" in str(error)
            return
        raise AssertionError("register_webhook must fail closed on URL mismatch")

    asyncio.run(scenario())


def test_register_webhook_fails_closed_when_telegram_reports_wrong_update_set() -> None:
    async def scenario() -> None:
        cfg = webhook_settings()
        adapter = WrongAllowedUpdatesAdapter()
        try:
            await register_webhook(cfg, adapter, approved_bot_id="123456789")
        except RuntimeError as error:
            assert "allowed update set" in str(error)
            return
        raise AssertionError("register_webhook must fail closed on update-set mismatch")

    asyncio.run(scenario())


def test_delete_webhook_verifies_telegram_state() -> None:
    async def scenario() -> None:
        cfg = webhook_settings()
        adapter = FakeAdapter(url=expected_webhook_url(cfg))
        result = await delete_webhook(cfg, adapter, drop_pending_updates=True)
        assert result["status"] == "deleted"
        assert adapter.delete_calls == [True]
        assert TOKEN not in json.dumps(result)

    asyncio.run(scenario())


def test_delete_webhook_fails_closed_when_webhook_remains() -> None:
    async def scenario() -> None:
        cfg = webhook_settings()
        adapter = FakeAdapter(url=expected_webhook_url(cfg))

        async def stubborn_delete_webhook(
            *, drop_pending_updates: bool = False
        ) -> None:
            return None

        adapter.delete_webhook = stubborn_delete_webhook  # type: ignore[method-assign]
        try:
            await delete_webhook(cfg, adapter)
        except RuntimeError as error:
            assert "still reports a configured webhook" in str(error)
            return
        raise AssertionError("delete_webhook must fail closed if Telegram keeps a URL")

    asyncio.run(scenario())


def test_mode_verify_gates_polling_with_active_webhook() -> None:
    async def scenario() -> None:
        cfg = settings(telegram_delivery_mode="polling")
        adapter = FakeAdapter(url="https://hooks.example.invalid/foreign")
        result = await mode_verify(cfg, adapter)
        exclusivity = result["mode_exclusivity"]
        assert isinstance(exclusivity, dict)
        assert exclusivity["consistent"] is False
        assert exclusivity["configured_mode"] == "polling"
        assert exclusivity["telegram_webhook_active"] is True

    asyncio.run(scenario())


def test_assess_exclusivity_is_consistent_when_disabled_and_no_webhook() -> None:
    cfg = settings(telegram_delivery_mode="disabled")
    exclusivity = assess_exclusivity(cfg, webhook_info())
    assert exclusivity.consistent
    assert exclusivity.polling_allowed is True
