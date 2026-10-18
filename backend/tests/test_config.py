import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "January"
    assert settings.environment == "local"
    assert settings.log_level == "INFO"
    assert settings.resolved_database_url.drivername == "postgresql+asyncpg"
    assert settings.telegram_delivery_mode == "disabled"
    assert settings.context_recent_message_limit == 20
    assert settings.llm_enabled is False
    assert settings.outbound_delivery_enabled is False
    assert settings.command_worker_enabled is False
    assert settings.raw_content_retention_days == 30
    assert settings.retention_worker_enabled is False
    assert settings.rate_limit_enabled is False
    assert settings.rate_limit_generation_conversation_per_minute == 12
    assert settings.semantic_memory_enabled is False
    assert settings.control_plane_deployment_bootstrap_subjects == ()


def test_complete_env_example_loads_with_local_safe_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in tuple(os.environ):
        if name.startswith("JANUARY_"):
            monkeypatch.delenv(name)
    env_example = Path(__file__).parents[2] / ".env.example"

    settings = Settings(_env_file=env_example)

    assert settings.environment == "local"
    assert settings.telegram_enabled is False
    assert settings.llm_enabled is False
    assert settings.context_reply_chain_depth == 1
    assert settings.response_plan_text_limit == 13_600
    assert settings.llm_openai_api_key is None


def test_blank_remote_provider_credential_fails_closed() -> None:
    with pytest.raises(ValidationError, match="llm_openai_api_key"):
        Settings(
            _env_file=None,
            llm_enabled=True,
            llm_openai_model="approved-model",
            llm_openai_api_key="",
        )


def test_redis_url_requires_supported_absolute_url() -> None:
    with pytest.raises(ValidationError, match="redis_url"):
        Settings(_env_file=None, redis_url="not-a-redis-url")
    assert Settings(_env_file=None, redis_url="rediss://cache.example:6380/0")


def test_rate_limit_settings_are_typed_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JANUARY_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("JANUARY_RATE_LIMIT_GENERATION_PROVIDER_PER_MINUTE", "17")
    settings = Settings(_env_file=None)
    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_generation_provider_per_minute == 17
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rate_limit_delivery_conversation_per_second=0)


def test_provider_concurrency_settings_are_typed_and_reject_unknown_provider() -> None:
    settings = Settings(
        _env_file=None,
        provider_concurrency_enabled=True,
        provider_concurrency_limits='{"openai": 2}',
    )
    assert settings.provider_concurrency_limits == {"openai": 2}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, provider_concurrency_limits='{"unknown": 2}')


def test_command_settings_validate_retry_bounds_and_limits() -> None:
    settings = Settings(_env_file=None, command_max_argument_length=500)
    assert settings.command_max_argument_length == 500
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            command_retry_min_delay_seconds=10,
            command_retry_max_delay_seconds=1,
        )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, command_max_authorization_attempts=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, command_max_argument_length=501)


def test_scheduler_settings_are_bounded_and_worker_requires_delivery() -> None:
    assert Settings(_env_file=None).proactive_scheduling_enabled is False
    with pytest.raises(ValidationError, match="proactive_scheduling_enabled"):
        Settings(_env_file=None, scheduler_worker_enabled=True)
    with pytest.raises(ValidationError, match="outbound_delivery_enabled"):
        Settings(
            _env_file=None,
            proactive_scheduling_enabled=True,
            scheduler_worker_enabled=True,
        )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, scheduler_active_reminder_limit=11)


def test_governance_settings_are_bounded_and_worker_requires_feature() -> None:
    settings = Settings(
        _env_file=None,
        data_governance_enabled=True,
        governance_worker_enabled=True,
        governance_export_ttl_days=2,
        governance_export_batch_size=5,
        governance_export_lease_seconds=60,
        governance_export_max_attempts=5,
        governance_audit_retention_days=90,
        retention_batch_size=100,
    )
    assert settings.governance_worker_enabled is True
    with pytest.raises(ValidationError):
        Settings(_env_file=None, governance_worker_enabled=True)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, governance_export_ttl_days=8)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, governance_audit_retention_days=29)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, retention_batch_size=0)


def test_deployment_authority_bootstrap_subjects_are_explicit() -> None:
    settings = Settings(
        _env_file=None,
        control_plane_deployment_bootstrap_subjects=("root-operator",),
    )
    assert settings.control_plane_deployment_bootstrap_subjects == ("root-operator",)


def test_llm_settings_require_remote_credentials_and_allow_keyless_ollama() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_enabled=True, llm_openai_model="fake")
    settings = Settings(
        _env_file=None,
        llm_enabled=True,
        llm_primary_provider="ollama",
        llm_ollama_model="fake-local",
    )
    assert settings.llm_ollama_model == "fake-local"
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            llm_enabled=True,
            llm_primary_provider="ollama",
            llm_ollama_model="fake",
            llm_fallback_provider="ollama",
        )


def test_outbound_settings_require_telegram_and_validate_stickers() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, outbound_delivery_enabled=True)
    settings = Settings(
        _env_file=None,
        telegram_enabled=True,
        telegram_bot_token="fake-token",
        telegram_platform_connection_id=uuid4(),
        outbound_delivery_enabled=True,
        telegram_sticker_mapping={"laugh": "file-id"},
    )
    assert settings.telegram_sticker_mapping == {"laugh": "file-id"}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, telegram_sticker_mapping={"unknown": "file-id"})
    with pytest.raises(ValidationError):
        Settings(_env_file=None, telegram_sticker_mapping={"laugh": " "})


def test_demo_mode_requires_polling_allowlist_and_live_components() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, demo_live_enabled=True)
    settings = Settings(
        _env_file=None,
        demo_live_enabled=True,
        demo_allowed_chat_ids=("-1000000000001", "123"),
        telegram_enabled=True,
        telegram_bot_token="fake-token",
        telegram_delivery_mode="polling",
        telegram_platform_connection_id=uuid4(),
        llm_enabled=True,
        llm_primary_provider="ollama",
        llm_ollama_model="fake",
        outbound_delivery_enabled=True,
    )
    assert settings.demo_allowed_chat_ids == ("-1000000000001", "123")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, demo_allowed_chat_ids=("1", "1"))


def test_demo_allowlist_parses_environment_json_and_rejects_non_numeric_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JANUARY_DEMO_ALLOWED_CHAT_IDS", '["-1000000000001", "123"]')
    assert Settings(_env_file=None).demo_allowed_chat_ids == ("-1000000000001", "123")

    monkeypatch.setenv("JANUARY_DEMO_ALLOWED_CHAT_IDS", '["not-a-chat"]')
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_webhook_delivery_requires_complete_redacted_configuration() -> None:
    connection_id = uuid4()
    settings = Settings(
        _env_file=None,
        telegram_enabled=True,
        telegram_bot_token="fake-token",
        telegram_delivery_mode="webhook",
        telegram_platform_connection_id=connection_id,
        telegram_webhook_secret_token="safe-secret_123",
        telegram_webhook_public_base_url="https://example.invalid",
    )

    assert settings.telegram_platform_connection_id == connection_id
    assert "safe-secret_123" not in repr(settings)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, telegram_delivery_mode="polling")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JANUARY_TELEGRAM_WEBHOOK_BODY_LIMIT_BYTES", "1"),
        ("JANUARY_TELEGRAM_POLL_TIMEOUT_SECONDS", "0"),
        ("JANUARY_REDIS_BATCH_SIZE", "0"),
        ("JANUARY_REDIS_RECLAIM_IDLE_MS", "1"),
        ("JANUARY_INGRESS_EVENT_SCHEMA_VERSION", "0"),
    ],
)
def test_invalid_ingress_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JANUARY_CONTEXT_RECENT_MESSAGE_LIMIT", "0"),
        ("JANUARY_CONTEXT_REPLY_CHAIN_DEPTH", "-1"),
        ("JANUARY_CONTEXT_TOKEN_BUDGET", "1"),
        ("JANUARY_CONTEXT_MESSAGE_CHARACTER_LIMIT", "1"),
    ],
)
def test_invalid_context_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JANUARY_MEMORY_CONTEXT_LIMIT", "11"),
        ("JANUARY_MEMORY_CONTEXT_CHARACTER_BUDGET", "0"),
        ("JANUARY_RAW_CONTENT_RETENTION_DAYS", "31"),
        ("JANUARY_RETENTION_BATCH_SIZE", "0"),
        ("JANUARY_RETENTION_WORKER_POLL_INTERVAL_SECONDS", "0"),
    ],
)
def test_invalid_memory_and_retention_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_semantic_memory_settings_require_a_separate_embedding_capability() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, semantic_memory_enabled=True)
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            semantic_memory_worker_enabled=True,
        )
    settings = Settings(
        _env_file=None,
        semantic_memory_enabled=True,
        embedding_provider="ollama",
        embedding_model="nomic-embed-text",
        embedding_dimension=768,
    )
    assert settings.embedding_model == "nomic-embed-text"
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            semantic_memory_retry_min_delay_seconds=2,
            semantic_memory_retry_max_delay_seconds=1,
        )


def test_settings_read_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JANUARY_APP_NAME", "January Test")
    monkeypatch.setenv("JANUARY_ENVIRONMENT", "test")
    monkeypatch.setenv("JANUARY_LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.app_name == "January Test"
    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"


def test_database_settings_read_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JANUARY_DATABASE_HOST", "database")
    monkeypatch.setenv("JANUARY_DATABASE_PORT", "5433")
    monkeypatch.setenv("JANUARY_DATABASE_NAME", "january_test")
    monkeypatch.setenv("JANUARY_DATABASE_PASSWORD", "not-for-logs")
    monkeypatch.setenv("JANUARY_DATABASE_POOL_SIZE", "7")

    settings = Settings(_env_file=None)

    assert settings.resolved_database_url.host == "database"
    assert settings.resolved_database_url.port == 5433
    assert settings.resolved_database_url.database == "january_test"
    assert settings.database_pool_size == 7
    assert "not-for-logs" not in repr(settings)


def test_production_accepts_complete_database_url_without_component_placeholders() -> (
    None
):
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url="postgresql+asyncpg://service:secret@db.example/january",
        redis_url="rediss://cache.example:6380/0",
    )

    assert settings.resolved_database_url.host == "db.example"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"database_echo": True}, "database_echo"),
        (
            {
                "telegram_enabled": True,
                "telegram_bot_token": "synthetic-token",
                "telegram_api_base_url": "http://telegram.example",
            },
            "Telegram API base URL",
        ),
        (
            {
                "llm_enabled": True,
                "llm_openai_model": "approved-model",
                "llm_openai_api_key": "synthetic-key",
                "llm_openai_base_url": "http://provider.example/v1",
            },
            "remote provider base URLs",
        ),
        (
            {
                "demo_live_enabled": True,
                "demo_allowed_chat_ids": ("1",),
                "telegram_enabled": True,
                "telegram_bot_token": "synthetic-token",
                "telegram_delivery_mode": "polling",
                "telegram_platform_connection_id": uuid4(),
                "llm_enabled": True,
                "llm_primary_provider": "ollama",
                "llm_ollama_model": "local-model",
                "outbound_delivery_enabled": True,
            },
            "demo_live_enabled",
        ),
    ],
)
def test_production_rejects_unsafe_runtime_overrides(
    override: dict[str, object], message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline: dict[str, object] = {
        "environment": "production",
        "database_url": "postgresql+asyncpg://service:secret@db.example/january",
        "redis_url": "rediss://cache.example:6380/0",
    }
    for field, value in (baseline | override).items():
        encoded = json.dumps(value) if isinstance(value, tuple) else str(value)
        monkeypatch.setenv(f"JANUARY_{field.upper()}", encoded)
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None)


def test_invalid_settings_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JANUARY_ENVIRONMENT", "unsupported")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JANUARY_DATABASE_PORT", "0"),
        ("JANUARY_DATABASE_POOL_SIZE", "0"),
        ("JANUARY_DATABASE_CONNECT_TIMEOUT_SECONDS", "0"),
        ("JANUARY_DATABASE_URL", "sqlite:///not-allowed"),
    ],
)
def test_invalid_database_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_personal_context_limits_are_bounded() -> None:
    settings = Settings(_env_file=None)
    assert settings.personal_context_limit == 5
    assert settings.personal_context_character_budget == 600
    assert settings.memory_control_batch_size == 100
    with pytest.raises(ValidationError):
        Settings(_env_file=None, personal_context_limit=6)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, personal_context_character_budget=601)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, memory_context_character_budget=1201)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, memory_control_batch_size=0)


def test_voice_tts_configuration_is_fixed_and_fails_closed() -> None:
    enabled: dict[str, object] = {
        "_env_file": None,
        "telegram_voice_tts_enabled": True,
        "provider_governance_mode": "enforce",
        "provider_governance_worker_enabled": True,
        "control_plane_enabled": True,
        "control_plane_jwt_secret": "x" * 32,
        "control_plane_jwt_issuer": "spec038-test",
        "control_plane_jwt_audience": "spec038-test",
        "rate_limit_enabled": True,
        "provider_concurrency_enabled": True,
        "llm_openai_api_key": "test-only-openai-key",
        "command_worker_enabled": True,
        "outbound_delivery_enabled": True,
        "telegram_enabled": True,
        "telegram_bot_token": "123456:SPEC038_FAKE_TOKEN",
        "telegram_platform_connection_id": uuid4(),
    }
    settings = Settings(**enabled)  # type: ignore[arg-type]
    assert settings.telegram_voice_tts_model == "gpt-4o-mini-tts"
    assert settings.telegram_voice_tts_voice == "alloy"
    assert settings.telegram_voice_tts_source_max_characters == 4000
    assert settings.telegram_voice_tts_output_max_bytes == 5_242_880
    assert settings.telegram_voice_tts_timeout_seconds == 30

    for override in (
        {"provider_governance_mode": "observe"},
        {"rate_limit_enabled": False},
        {"provider_concurrency_enabled": False},
        {"llm_openai_api_key": None},
        {"command_worker_enabled": False},
        {"outbound_delivery_enabled": False},
        {"provider_reservation_lease_seconds": 30},
        {"provider_concurrency_lease_seconds": 30},
        {"command_lease_seconds": 30},
        {"telegram_voice_tts_voice": "user-selected"},
        {"telegram_voice_tts_source_max_characters": 4001},
        {"telegram_voice_tts_output_max_bytes": 5_242_881},
        {"telegram_voice_artifact_grace_hours": 25},
        {"telegram_voice_artifact_hard_retention_days": 8},
    ):
        with pytest.raises(ValidationError):
            Settings(**(enabled | override))  # type: ignore[arg-type]
