import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.ports.platform import BotIdentity, WebhookInfo
from app.core.config import Settings
from app.domain.persistence import Platform
from app.runtime.acceptance_evidence import (
    ContentSafetyViolation,
    assert_content_safe,
    build_evidence,
)
from app.runtime.telegram_connection_operations import (
    ConnectionVerification,
    expected_webhook_url,
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


def webhook_info(url: str = "") -> WebhookInfo:
    return WebhookInfo(
        url=url,
        pending_update_count=0,
        allowed_updates=(),
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


class FakeAdapter:
    def __init__(self, url: str = "") -> None:
        self.url = url

    async def verify_identity(self) -> BotIdentity:
        return bot_identity()

    async def get_webhook_info(self) -> WebhookInfo:
        return webhook_info(self.url)


async def passing_verification() -> ConnectionVerification:
    cfg = settings(
        telegram_delivery_mode="webhook",
        telegram_webhook_secret_token="test-secret",
        telegram_webhook_public_base_url=BASE_URL,
    )
    adapter = FakeAdapter(url=expected_webhook_url(cfg))
    result = await verify_connection(cfg, adapter, approved_bot_id="123456789")
    assert result.ok
    return result


def sample_bundle(verification: ConnectionVerification) -> dict[str, object]:
    return build_evidence(
        verification=verification,
        durable_state={
            "worker_lifecycle": {"latest_ingress_at": "2026-08-07T10:00:00+00:00"},
            "duplicate_retry_outcomes": {
                "incoming_total": 2,
                "distinct_platform_updates": 1,
                "duplicate_ingress": 1,
            },
        },
        health_readiness={
            "ready": {"status_code": 200, "database": {"status": "ok"}},
            "health": {"status_code": 200, "status": "ok"},
        },
        run_id="run-1",
        started_at=datetime(2026, 8, 7, 9, 0, 0, tzinfo=UTC),
        operator="ops-lead",
        incident_contact="incident-oncall",
        rollback_authority="release-owner",
        test_group="staging-group",
        cleanup_confirmed=True,
    )


def test_assert_content_safe_rejects_bot_token_shaped_strings() -> None:
    with pytest.raises(ContentSafetyViolation):
        assert_content_safe({"bot_identity": {"token": TOKEN}})
    with pytest.raises(ContentSafetyViolation):
        assert_content_safe({"note": f"creds {TOKEN} here"})


def test_assert_content_safe_rejects_forbidden_keys() -> None:
    with pytest.raises(ContentSafetyViolation):
        assert_content_safe({"duplicate_retry_outcomes": {"raw_payload": {}}})
    with pytest.raises(ContentSafetyViolation):
        assert_content_safe({"webhook_state": {"secret_token": "test-secret"}})


def test_assert_content_safe_rejects_authorization_headers() -> None:
    with pytest.raises(ContentSafetyViolation):
        assert_content_safe({"health_readiness": {"Authorization": "Bearer xyz"}})


def test_assert_content_safe_accepts_metadata_only_values() -> None:
    bundle: dict[str, object] = {
        "webhook_state": {
            "url": "https://hooks.example.invalid/webhook",
            "configured": True,
        },
        "timestamps": {"started_at": "2026-08-07T09:00:00+00:00"},
        "observations": ["webhook mode configured but no Telegram webhook is active"],
    }
    assert_content_safe(bundle)


def test_build_evidence_includes_required_fields() -> None:
    async def scenario() -> None:
        bundle = sample_bundle(await passing_verification())
        for key in (
            "environment",
            "connection",
            "bot_identity",
            "webhook_state",
            "mode_exclusivity",
            "timestamps",
            "result_classification",
            "health_readiness",
            "worker_lifecycle",
            "duplicate_retry_outcomes",
            "cleanup",
        ):
            assert key in bundle, f"evidence bundle is missing {key}"
        assert bundle["cleanup"] == {"confirmed": True}
        assert bundle["result_classification"] == "accepted"
        assert bundle["connection"]["delivery_mode"] == "webhook"

    asyncio.run(scenario())


def test_build_evidence_contains_no_secrets_or_content() -> None:
    async def scenario() -> None:
        bundle = sample_bundle(await passing_verification())
        serialized = json.dumps(bundle)
        assert TOKEN not in serialized
        assert "test-secret" not in serialized
        assert_content_safe(bundle)

    asyncio.run(scenario())


def test_evidence_records_redacted_identity_metadata() -> None:
    async def scenario() -> None:
        bundle = sample_bundle(await passing_verification())
        identity = bundle["bot_identity"]
        assert isinstance(identity, dict)
        assert identity["external_bot_id"] == "123456789"
        assert identity["username"] == "january_bot"
        assert set(identity) == {
            "platform",
            "external_bot_id",
            "username",
            "display_name",
            "is_bot",
            "can_join_groups",
            "can_read_all_group_messages",
        }

    asyncio.run(scenario())
