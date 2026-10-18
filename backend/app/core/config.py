"""Typed runtime settings loaded from the environment."""

import json
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

from app.domain.planning import ProviderId, StickerIntent


class Settings(BaseSettings):
    """Configuration that is safe to load without external dependencies."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="JANUARY_",
        extra="ignore",
    )

    app_name: str = Field(default="January", min_length=1, max_length=100)
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    metrics_enabled: bool = False
    metrics_export_enabled: bool = False
    metrics_bind_host: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    metrics_port: int = Field(default=9464, ge=1, le=65535)
    planning_metrics_port: int = Field(default=9465, ge=1, le=65535)
    summary_metrics_port: int = Field(default=9466, ge=1, le=65535)
    semantic_memory_metrics_port: int = Field(default=9467, ge=1, le=65535)
    provider_governance_metrics_port: int = Field(default=9468, ge=1, le=65535)
    metrics_provider_pricing: dict[str, dict[str, int]] = Field(default_factory=dict)
    provider_governance_mode: Literal["legacy", "observe", "enforce"] = "legacy"
    provider_governance_worker_enabled: bool = False
    provider_governance_owner_name: str = Field(
        default="provider-governance", min_length=1, max_length=255
    )
    provider_governance_batch_size: int = Field(default=50, ge=1, le=500)
    provider_governance_poll_interval_seconds: float = Field(default=5, gt=0, le=3600)
    provider_reservation_lease_seconds: int = Field(default=60, ge=5, le=3600)
    database_host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(default="january", min_length=1, max_length=63)
    database_user: str = Field(default="january", min_length=1, max_length=63)
    database_password: SecretStr = SecretStr("january-local")
    database_url: SecretStr | None = None
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_connect_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    database_echo: bool = False
    telegram_enabled: bool = False
    telegram_media_enabled: bool = False
    telegram_media_photo_max_bytes: int = Field(
        default=5 * 1024 * 1024, ge=1, le=10 * 1024 * 1024
    )
    telegram_media_audio_max_bytes: int = Field(
        default=5 * 1024 * 1024, ge=1, le=10 * 1024 * 1024
    )
    telegram_media_photo_max_side: int = Field(default=1280, ge=1, le=4096)
    telegram_media_audio_max_duration_seconds: int = Field(default=120, ge=1, le=300)
    telegram_media_transcript_max_characters: int = Field(default=4000, ge=1, le=8000)
    telegram_media_download_timeout_seconds: float = Field(default=15, gt=0, le=60)
    telegram_media_transcription_timeout_seconds: float = Field(default=20, gt=0, le=60)
    telegram_voice_tts_enabled: bool = False
    telegram_voice_tts_model: str = Field(
        default="gpt-4o-mini-tts", min_length=1, max_length=255
    )
    telegram_voice_tts_voice: Literal["alloy"] = "alloy"
    telegram_voice_tts_source_max_characters: int = Field(
        default=4000, ge=4000, le=4000
    )
    telegram_voice_tts_output_max_bytes: int = Field(
        default=5_242_880, ge=5_242_880, le=5_242_880
    )
    telegram_voice_tts_timeout_seconds: float = Field(default=30, gt=0, le=30)
    telegram_voice_artifact_grace_hours: int = Field(default=24, ge=24, le=24)
    telegram_voice_artifact_hard_retention_days: int = Field(default=7, ge=7, le=7)
    telegram_bot_token: SecretStr | None = None
    telegram_api_base_url: str = "https://api.telegram.org"
    telegram_timeout_seconds: float = Field(default=10, gt=0, le=60)
    telegram_connect_timeout_seconds: float = Field(default=5, gt=0, le=30)
    telegram_connection_limit: int = Field(default=10, ge=1, le=100)
    telegram_user_agent: str = Field(
        default="january/0.1", min_length=1, max_length=128
    )
    telegram_delivery_mode: Literal["disabled", "webhook", "polling"] = "disabled"
    telegram_tenant_id: UUID | None = None
    telegram_platform_connection_id: UUID | None = None
    telegram_allowed_updates: tuple[
        Literal["message", "edited_message", "my_chat_member", "chat_member"], ...
    ] = ("message", "edited_message", "my_chat_member", "chat_member")
    telegram_webhook_secret_token: SecretStr | None = None
    telegram_webhook_public_base_url: str | None = None
    telegram_webhook_body_limit_bytes: int = Field(
        default=1_048_576, ge=1024, le=10_485_760
    )
    telegram_webhook_max_connections: int = Field(default=40, ge=1, le=100)
    telegram_poll_timeout_seconds: int = Field(default=30, ge=1, le=50)
    telegram_poll_batch_limit: int = Field(default=100, ge=1, le=100)
    telegram_poll_retry_backoff_seconds: float = Field(default=1, gt=0, le=60)
    telegram_poll_max_backoff_seconds: float = Field(default=30, gt=0, le=300)
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    redis_stream_name: str = Field(
        default="january:incoming-updates", min_length=1, max_length=255
    )
    redis_consumer_group: str = Field(
        default="january-ingress", min_length=1, max_length=255
    )
    redis_block_timeout_ms: int = Field(default=1000, ge=1, le=60_000)
    redis_batch_size: int = Field(default=10, ge=1, le=100)
    redis_reclaim_idle_ms: int = Field(default=60_000, ge=1_000, le=86_400_000)
    rate_limit_enabled: bool = False
    rate_limit_generation_deployment_per_minute: int = Field(
        default=60, ge=1, le=100_000
    )
    rate_limit_generation_connection_per_minute: int = Field(
        default=30, ge=1, le=100_000
    )
    rate_limit_generation_conversation_per_minute: int = Field(
        default=12, ge=1, le=100_000
    )
    rate_limit_generation_participant_per_minute: int = Field(
        default=6, ge=1, le=100_000
    )
    rate_limit_generation_provider_per_minute: int = Field(default=40, ge=1, le=100_000)
    rate_limit_delivery_deployment_per_second: int = Field(default=20, ge=1, le=10_000)
    rate_limit_delivery_connection_per_second: int = Field(default=10, ge=1, le=10_000)
    rate_limit_delivery_conversation_per_second: int = Field(default=2, ge=1, le=10_000)
    rate_limit_redis_failure_retry_seconds: int = Field(default=5, ge=1, le=300)
    rate_limit_cooldown_notice_seconds: int = Field(default=60, ge=1, le=3600)
    provider_concurrency_enabled: bool = False
    provider_concurrency_limits: dict[str, int] = Field(default_factory=dict)
    provider_concurrency_lease_seconds: int = Field(default=60, ge=5, le=3600)
    ingress_outbox_batch_size: int = Field(default=50, ge=1, le=500)
    ingress_outbox_poll_interval_seconds: float = Field(default=1, gt=0, le=60)
    ingress_event_schema_version: int = Field(default=1, ge=1, le=100)
    conversation_consumer_name: str | None = None
    conversation_worker_poll_interval_seconds: float = Field(default=1, gt=0, le=60)
    context_recent_message_limit: int = Field(default=20, ge=1, le=100)
    context_reply_chain_depth: int = Field(default=1, ge=0, le=1)
    context_token_budget: int = Field(default=1200, ge=64, le=32_000)
    context_message_character_limit: int = Field(default=2000, ge=64, le=20_000)
    context_max_history_age_days: int = Field(default=30, ge=1, le=365)
    memory_context_limit: int = Field(default=10, ge=1, le=10)
    memory_context_character_budget: int = Field(default=1200, ge=1, le=1200)
    personal_context_limit: int = Field(default=5, ge=1, le=5)
    personal_context_character_budget: int = Field(default=600, ge=1, le=600)
    memory_control_batch_size: int = Field(default=100, ge=1, le=1000)
    semantic_memory_enabled: bool = False
    semantic_memory_worker_enabled: bool = False
    embedding_provider: Literal["ollama"] | None = None
    embedding_model: str | None = None
    embedding_dimension: int = Field(default=768, ge=1, le=8192)
    embedding_rate_per_minute: int = Field(default=40, ge=1, le=100_000)
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection_prefix: str = Field(
        default="january_explicit_memory", min_length=1, max_length=64
    )
    semantic_memory_top_k: int = Field(default=6, ge=1, le=20)
    semantic_memory_context_limit: int = Field(default=6, ge=1, le=10)
    semantic_memory_character_budget: int = Field(default=1200, ge=1, le=10_000)
    semantic_memory_query_timeout_seconds: float = Field(default=1, gt=0, le=5)
    semantic_memory_min_score: float | None = Field(default=None, ge=-1, le=1)
    semantic_memory_job_lease_seconds: int = Field(default=60, ge=5, le=3600)
    semantic_memory_job_batch_size: int = Field(default=10, ge=1, le=100)
    semantic_memory_max_attempts: int = Field(default=5, ge=1, le=20)
    semantic_memory_retry_min_delay_seconds: float = Field(default=1, gt=0, le=60)
    semantic_memory_retry_max_delay_seconds: float = Field(default=60, gt=0, le=3600)
    knowledge_rag_enabled: bool = False
    knowledge_index_worker_enabled: bool = False
    knowledge_qdrant_collection_prefix: str = Field(
        default="january_knowledge", min_length=1, max_length=64
    )
    knowledge_top_k: int = Field(default=20, ge=1, le=20)
    knowledge_context_limit: int = Field(default=6, ge=1, le=6)
    knowledge_context_character_budget: int = Field(default=6000, ge=1, le=6000)
    knowledge_query_timeout_seconds: float = Field(default=1, gt=0, le=5)
    knowledge_min_score: float | None = Field(default=None, ge=-1, le=1)
    knowledge_job_lease_seconds: int = Field(default=60, ge=5, le=3600)
    knowledge_job_batch_size: int = Field(default=10, ge=1, le=100)
    knowledge_max_attempts: int = Field(default=5, ge=1, le=20)
    knowledge_retry_min_delay_seconds: float = Field(default=1, gt=0, le=60)
    knowledge_retry_max_delay_seconds: float = Field(default=60, gt=0, le=3600)
    conversation_summaries_enabled: bool = False
    summary_worker_enabled: bool = False
    summary_min_source_messages: int = Field(default=20, ge=2, le=500)
    summary_max_source_messages: int = Field(default=50, ge=2, le=500)
    summary_max_output_tokens: int = Field(default=300, ge=32, le=1024)
    summary_lease_seconds: int = Field(default=60, ge=5, le=3600)
    summary_batch_size: int = Field(default=4, ge=1, le=100)
    summary_max_attempts: int = Field(default=5, ge=1, le=20)
    raw_content_retention_days: int = Field(default=30, ge=1, le=30)
    retention_batch_size: int = Field(default=100, ge=1, le=1000)
    retention_worker_enabled: bool = False
    retention_worker_poll_interval_seconds: float = Field(default=60, gt=0, le=3600)
    llm_enabled: bool = False
    llm_primary_provider: Literal[
        "openai", "gemini", "groq", "openrouter", "ollama"
    ] = "openai"
    llm_fallback_provider: (
        Literal["openai", "gemini", "groq", "openrouter", "ollama"] | None
    ) = None
    llm_openai_model: str | None = None
    llm_gemini_model: str | None = None
    llm_groq_model: str | None = None
    llm_openrouter_model: str | None = None
    llm_ollama_model: str | None = None
    llm_openai_base_url: str = "https://api.openai.com/v1"
    llm_gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    llm_groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_ollama_base_url: str = "http://127.0.0.1:11434"
    llm_openai_api_key: SecretStr | None = None
    llm_gemini_api_key: SecretStr | None = None
    llm_groq_api_key: SecretStr | None = None
    llm_openrouter_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=20, gt=0, le=120)
    llm_connect_timeout_seconds: float = Field(default=5, gt=0, le=30)
    llm_max_output_tokens: int = Field(default=300, ge=32, le=4096)
    llm_temperature: float = Field(default=0.4, ge=0, le=2)
    llm_max_transport_attempts: int = Field(default=2, ge=1, le=5)
    llm_max_correction_attempts: int = Field(default=1, ge=0, le=1)
    llm_retry_min_delay_seconds: float = Field(default=0.25, gt=0, le=30)
    llm_retry_max_delay_seconds: float = Field(default=2, gt=0, le=120)
    planning_job_batch_size: int = Field(default=10, ge=1, le=100)
    planning_owner_name: str = Field(default="planning", min_length=1, max_length=255)
    planning_job_poll_interval_seconds: float = Field(default=1, gt=0, le=60)
    planning_job_lease_seconds: int = Field(default=60, ge=5, le=3600)
    command_worker_enabled: bool = False
    command_owner_name: str = Field(default="commands", min_length=1, max_length=255)
    command_batch_size: int = Field(default=10, ge=1, le=100)
    command_poll_interval_seconds: float = Field(default=1, gt=0, le=60)
    command_lease_seconds: int = Field(default=60, ge=5, le=3600)
    command_max_authorization_attempts: int = Field(default=3, ge=1, le=10)
    command_retry_min_delay_seconds: float = Field(default=1, gt=0, le=300)
    command_retry_max_delay_seconds: float = Field(default=60, gt=0, le=3600)
    command_max_argument_length: int = Field(default=500, ge=0, le=500)
    command_max_profiles_shown: int = Field(default=8, ge=1, le=20)
    proactive_scheduling_enabled: bool = False
    scheduler_worker_enabled: bool = False
    scheduler_owner_name: str = Field(default="scheduler", min_length=1, max_length=255)
    scheduler_batch_size: int = Field(default=20, ge=1, le=200)
    scheduler_poll_interval_seconds: float = Field(default=5, gt=0, le=3600)
    scheduler_lease_seconds: int = Field(default=60, ge=5, le=3600)
    scheduler_active_reminder_limit: int = Field(default=10, ge=1, le=10)
    scheduler_minimum_lead_seconds: int = Field(default=60, ge=1, le=3600)
    scheduler_horizon_days: int = Field(default=365, ge=1, le=365)
    scheduler_reminder_text_limit: int = Field(default=100, ge=1, le=100)
    scheduler_history_retention_days: int = Field(default=30, ge=1, le=90)
    ambient_selective_enabled: bool = False
    command_menu_live_management_enabled: bool = False
    prompt_version: str = Field(default="spec-012-v1", min_length=1, max_length=64)
    response_plan_schema_version: str = Field(
        default="response-plan-v2", min_length=1, max_length=64
    )
    response_plan_text_limit: int = Field(default=13600, ge=1, le=13600)
    llm_live_verification_enabled: bool = False
    outbound_delivery_enabled: bool = False
    outbound_owner_name: str = Field(default="outbound", min_length=1, max_length=255)
    outbound_batch_size: int = Field(default=10, ge=1, le=100)
    outbound_poll_interval_seconds: float = Field(default=1, gt=0, le=60)
    outbound_lease_seconds: int = Field(default=60, ge=5, le=3600)
    outbound_max_confirmed_rejection_attempts: int = Field(default=3, ge=1, le=20)
    outbound_retry_min_delay_seconds: float = Field(default=1, gt=0, le=300)
    outbound_retry_max_delay_seconds: float = Field(default=60, gt=0, le=3600)
    telegram_text_limit: int = Field(default=4096, ge=1, le=4096)
    telegram_disable_notification: bool = False
    telegram_protect_content: bool = False
    telegram_sticker_mapping: dict[str, str] = Field(default_factory=dict)
    telegram_delivery_test_chat_id: str | None = None
    telegram_live_delivery_verification_enabled: bool = False
    demo_live_enabled: bool = False
    demo_live_telegram_verification_enabled: bool = False
    demo_allowed_chat_ids: tuple[str, ...] = ()
    demo_runtime_directory: str = ".runtime/january-demo"
    control_plane_enabled: bool = False
    control_plane_jwt_secret: SecretStr | None = None
    control_plane_jwt_issuer: str | None = None
    control_plane_jwt_audience: str | None = None
    control_plane_session_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)
    control_plane_deployment_bootstrap_subjects: tuple[str, ...] = ()
    safety_moderation_enabled: bool = False
    safety_signal_window_seconds: int = Field(default=3600, ge=60, le=86_400)
    safety_review_retention_days: int = Field(default=30, ge=1, le=90)
    safety_default_teasing_cap: int = Field(default=3, ge=0, le=10)
    safety_threshold_participant_refusals: int = Field(default=5, ge=1, le=100)
    safety_threshold_mention_frequency: int = Field(default=12, ge=1, le=100)
    safety_threshold_teasing_frequency: int = Field(default=4, ge=1, le=100)
    safety_threshold_rate_limit_violations: int = Field(default=6, ge=1, le=100)
    safety_threshold_memory_extraction: int = Field(default=2, ge=1, le=100)
    safety_threshold_dangerous_instruction: int = Field(default=2, ge=1, le=100)
    safety_threshold_prompt_injection: int = Field(default=3, ge=1, le=100)
    safety_threshold_manipulation: int = Field(default=3, ge=1, le=100)
    safety_pause_after_actions: int = Field(default=2, ge=1, le=10)
    safety_fail_closed_alert_burst_window_seconds: int = Field(
        default=900, ge=60, le=86_400
    )
    data_governance_enabled: bool = False
    governance_worker_enabled: bool = False
    governance_export_ttl_days: int = Field(default=2, ge=1, le=7)
    governance_audit_retention_days: int = Field(default=90, ge=30, le=365)
    governance_export_lease_seconds: int = Field(default=60, ge=5, le=3600)
    governance_export_batch_size: int = Field(default=5, ge=1, le=100)
    governance_export_max_attempts: int = Field(default=5, ge=1, le=20)
    governance_owner_name: str = Field(
        default="governance", min_length=1, max_length=255
    )
    governance_worker_poll_interval_seconds: float = Field(default=5, gt=0, le=3600)

    @field_validator("telegram_sticker_mapping")
    @classmethod
    def validate_sticker_mapping(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {intent.value for intent in StickerIntent}
        invalid = set(value) - allowed
        if invalid:
            raise ValueError("telegram_sticker_mapping has unsupported intent keys")
        if any(
            not reference.strip() or len(reference) > 255
            for reference in value.values()
        ):
            raise ValueError(
                "telegram_sticker_mapping values must be nonblank and <=255"
            )
        return value

    @field_validator("metrics_provider_pricing", mode="before")
    @classmethod
    def validate_metrics_provider_pricing(
        cls, value: object
    ) -> dict[str, dict[str, int]]:
        if value is None or value == "":
            return {}
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, dict):
            raise ValueError("metrics_provider_pricing must be a JSON mapping")
        normalized: dict[str, dict[str, int]] = {}
        for key, rates in parsed.items():
            if (
                not isinstance(key, str)
                or ":" not in key
                or not isinstance(rates, dict)
            ):
                raise ValueError("pricing keys must be provider:model mappings")
            input_rate, output_rate = (
                rates.get("input_microusd_per_million"),
                rates.get("output_microusd_per_million"),
            )
            if (
                not isinstance(input_rate, int)
                or not isinstance(output_rate, int)
                or input_rate < 0
                or output_rate < 0
            ):
                raise ValueError(
                    "pricing rates must be nonnegative integer micro-USD values"
                )
            normalized[key] = {
                "input_microusd_per_million": input_rate,
                "output_microusd_per_million": output_rate,
            }
        return normalized

    @field_validator("provider_concurrency_limits", mode="before")
    @classmethod
    def validate_provider_concurrency_limits(cls, value: object) -> dict[str, int]:
        if value is None or value == "":
            return {}
        parsed = json.loads(value) if isinstance(value, str) else value
        allowed = {provider.value for provider in ProviderId}
        if (
            not isinstance(parsed, dict)
            or set(parsed) - allowed
            or any(
                not isinstance(limit, int) or not 1 <= limit <= 10_000
                for limit in parsed.values()
            )
        ):
            raise ValueError(
                "provider_concurrency_limits must map supported providers to 1..10000"
            )
        return parsed

    @field_validator("demo_allowed_chat_ids", mode="before")
    @classmethod
    def validate_demo_allowed_chat_ids(cls, value: object) -> tuple[str, ...]:
        if value is None or value == "":
            return ()
        raw = value.split(",") if isinstance(value, str) else value
        if not isinstance(raw, list | tuple):
            raise ValueError(
                "demo_allowed_chat_ids must be a list or comma-separated IDs"
            )
        ids = tuple(str(item).strip() for item in raw)
        if not ids:
            return ()
        if any(not item or not item.lstrip("-").isdigit() for item in ids):
            raise ValueError("demo_allowed_chat_ids must contain nonblank numeric IDs")
        if len(set(ids)) != len(ids):
            raise ValueError("demo_allowed_chat_ids must not contain duplicates")
        return ids

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        url = make_url(value)
        if url.drivername != "postgresql+asyncpg":
            raise ValueError("database_url must use the postgresql+asyncpg driver")
        return value

    @field_validator("telegram_api_base_url")
    @classmethod
    def validate_telegram_api_base_url(cls, value: str) -> str:
        url = urlparse(value)
        if url.scheme not in {"http", "https"} or not url.netloc:
            raise ValueError("telegram_api_base_url must be an absolute HTTP(S) URL")
        return value.rstrip("/")

    @field_validator(
        "llm_openai_base_url",
        "llm_gemini_base_url",
        "llm_groq_base_url",
        "llm_openrouter_base_url",
        "llm_ollama_base_url",
    )
    @classmethod
    def validate_llm_base_url(cls, value: str) -> str:
        url = urlparse(value)
        if url.scheme not in {"http", "https"} or not url.netloc:
            raise ValueError("LLM base URL must be an absolute HTTP(S) URL")
        return value.rstrip("/")

    @field_validator("qdrant_url")
    @classmethod
    def validate_qdrant_url(cls, value: str) -> str:
        url = urlparse(value)
        if url.scheme not in {"http", "https"} or not url.netloc:
            raise ValueError("qdrant_url must be an absolute HTTP(S) URL")
        return value.rstrip("/")

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        url = urlparse(value.get_secret_value())
        if url.scheme not in {"redis", "rediss"} or not url.hostname:
            raise ValueError("redis_url must be an absolute redis:// or rediss:// URL")
        return value

    @field_validator(
        "telegram_bot_token",
        "telegram_webhook_secret_token",
        "telegram_tenant_id",
        "telegram_platform_connection_id",
        "telegram_delivery_test_chat_id",
        "embedding_provider",
        "embedding_model",
        "semantic_memory_min_score",
        "knowledge_min_score",
        "llm_fallback_provider",
        "llm_openai_model",
        "llm_gemini_model",
        "llm_groq_model",
        "llm_openrouter_model",
        "llm_ollama_model",
        "llm_openai_api_key",
        "llm_gemini_api_key",
        "llm_groq_api_key",
        "llm_openrouter_api_key",
        mode="before",
    )
    @classmethod
    def normalize_empty_optional_values(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("telegram_webhook_public_base_url")
    @classmethod
    def validate_webhook_base_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        url = urlparse(value)
        if url.scheme != "https" or not url.netloc:
            raise ValueError(
                "telegram_webhook_public_base_url must be an absolute HTTPS URL"
            )
        return value.rstrip("/")

    @field_validator("telegram_webhook_secret_token")
    @classmethod
    def validate_webhook_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value()
        if not 1 <= len(secret) <= 256 or not all(
            char.isascii() and (char.isalnum() or char in "_-") for char in secret
        ):
            raise ValueError(
                "telegram_webhook_secret_token must use 1-256 safe ASCII characters"
            )
        return value

    @model_validator(mode="after")
    def validate_delivery_configuration(self) -> "Settings":
        if self.metrics_export_enabled and not self.metrics_enabled:
            raise ValueError("metrics_export_enabled requires metrics_enabled")
        if self.provider_governance_mode != "legacy" and self.metrics_provider_pricing:
            raise ValueError(
                "metrics_provider_pricing is legacy-only when provider governance "
                "is enabled"
            )
        if (
            self.provider_governance_worker_enabled
            and self.provider_governance_mode == "legacy"
        ):
            raise ValueError(
                "provider_governance_worker_enabled requires observe or enforce mode"
            )
        if (
            self.provider_governance_mode != "legacy"
            and not self.provider_governance_worker_enabled
        ):
            raise ValueError(
                "provider governance observe/enforce mode requires its recovery worker"
            )
        if self.provider_governance_mode != "legacy" and not self.control_plane_enabled:
            raise ValueError(
                "provider governance observe/enforce mode requires the control plane"
            )
        if self.provider_governance_mode != "legacy" and (
            self.provider_reservation_lease_seconds <= max(self.llm_timeout_seconds, 20)
        ):
            raise ValueError(
                "provider reservation lease must exceed every provider call timeout"
            )
        if self.telegram_media_enabled:
            longest_media_call = max(
                self.telegram_media_download_timeout_seconds,
                self.telegram_media_transcription_timeout_seconds,
                self.llm_timeout_seconds,
            )
            if self.planning_job_lease_seconds <= longest_media_call + 5:
                raise ValueError("planning lease must cover bounded media calls")
            if self.provider_governance_mode == "enforce" and (
                self.provider_reservation_lease_seconds <= longest_media_call
                or self.provider_concurrency_lease_seconds <= longest_media_call
            ):
                raise ValueError("provider leases must exceed media call timeouts")
        if self.telegram_voice_tts_enabled:
            if self.provider_governance_mode != "enforce":
                raise ValueError("voice TTS requires enforced provider governance")
            if not self.rate_limit_enabled or not self.provider_concurrency_enabled:
                raise ValueError("voice TTS requires rate and concurrency coordination")
            if self.llm_openai_api_key is None:
                raise ValueError("voice TTS requires the OpenAI credential")
            if not self.command_worker_enabled or not self.outbound_delivery_enabled:
                raise ValueError("voice TTS requires command and outbound workers")
            if (
                self.provider_reservation_lease_seconds
                <= self.telegram_voice_tts_timeout_seconds
            ):
                raise ValueError("provider reservation lease must exceed TTS timeout")
            if self.command_lease_seconds <= self.telegram_voice_tts_timeout_seconds:
                raise ValueError("command lease must exceed TTS timeout")
            if (
                self.provider_concurrency_lease_seconds
                <= self.telegram_voice_tts_timeout_seconds
            ):
                raise ValueError("provider concurrency lease must exceed TTS timeout")
        if self.control_plane_enabled:
            if self.control_plane_jwt_secret is None:
                raise ValueError("control_plane_jwt_secret is required when enabled")
            if len(self.control_plane_jwt_secret.get_secret_value()) < 32:
                raise ValueError(
                    "control_plane_jwt_secret must contain at least 32 characters"
                )
            if not self.control_plane_jwt_issuer or not self.control_plane_jwt_audience:
                raise ValueError(
                    "control plane issuer and audience are required when enabled"
                )
        if self.telegram_enabled and self.telegram_bot_token is None:
            raise ValueError(
                "telegram_bot_token is required when telegram_enabled is true"
            )
        if (
            self.telegram_poll_retry_backoff_seconds
            > self.telegram_poll_max_backoff_seconds
        ):
            raise ValueError("telegram poll retry backoff cannot exceed its maximum")
        if self.telegram_delivery_mode != "disabled":
            if not self.telegram_enabled or self.telegram_bot_token is None:
                raise ValueError(
                    "Telegram enabled mode and bot token are required for delivery"
                )
            if self.telegram_platform_connection_id is None:
                raise ValueError(
                    "telegram_platform_connection_id is required for delivery"
                )
        if self.telegram_delivery_mode == "webhook":
            if self.telegram_webhook_secret_token is None:
                raise ValueError(
                    "telegram_webhook_secret_token is required for webhook delivery"
                )
            if self.telegram_webhook_public_base_url is None:
                raise ValueError(
                    "telegram_webhook_public_base_url is required for webhook delivery"
                )
        if self.llm_retry_min_delay_seconds > self.llm_retry_max_delay_seconds:
            raise ValueError("LLM retry minimum delay cannot exceed maximum delay")
        if self.command_retry_min_delay_seconds > self.command_retry_max_delay_seconds:
            raise ValueError("command retry minimum delay cannot exceed maximum delay")
        if self.llm_fallback_provider == self.llm_primary_provider:
            raise ValueError("LLM fallback provider must differ from primary provider")
        if self.summary_worker_enabled and not self.conversation_summaries_enabled:
            raise ValueError(
                "summary_worker_enabled requires conversation_summaries_enabled"
            )
        if self.semantic_memory_worker_enabled and not self.semantic_memory_enabled:
            raise ValueError(
                "semantic_memory_worker_enabled requires semantic_memory_enabled"
            )
        if self.knowledge_index_worker_enabled and not self.knowledge_rag_enabled:
            raise ValueError(
                "knowledge_index_worker_enabled requires knowledge_rag_enabled"
            )
        if self.governance_worker_enabled and not self.data_governance_enabled:
            raise ValueError(
                "governance_worker_enabled requires data_governance_enabled"
            )
        if self.scheduler_worker_enabled and not self.proactive_scheduling_enabled:
            raise ValueError(
                "scheduler_worker_enabled requires proactive_scheduling_enabled"
            )
        if self.scheduler_worker_enabled and not self.outbound_delivery_enabled:
            raise ValueError(
                "scheduler_worker_enabled requires outbound_delivery_enabled"
            )
        if self.semantic_memory_enabled and (
            self.embedding_provider is None or not self.embedding_model
        ):
            raise ValueError(
                "embedding_provider and embedding_model are required when "
                "semantic memory is enabled"
            )
        if self.knowledge_rag_enabled and (
            self.embedding_provider is None or not self.embedding_model
        ):
            raise ValueError(
                "embedding_provider and embedding_model are required when "
                "knowledge RAG is enabled"
            )
        if (
            self.knowledge_retry_min_delay_seconds
            > self.knowledge_retry_max_delay_seconds
        ):
            raise ValueError(
                "knowledge retry minimum delay cannot exceed maximum delay"
            )
        if (
            self.semantic_memory_retry_min_delay_seconds
            > self.semantic_memory_retry_max_delay_seconds
        ):
            raise ValueError(
                "semantic memory retry minimum delay cannot exceed maximum delay"
            )
        if self.summary_min_source_messages > self.summary_max_source_messages:
            raise ValueError(
                "summary_min_source_messages cannot exceed summary_max_source_messages"
            )
        if self.llm_enabled:
            for provider in filter(
                None, (self.llm_primary_provider, self.llm_fallback_provider)
            ):
                model = getattr(self, f"llm_{provider}_model")
                if not model:
                    raise ValueError(
                        f"llm_{provider}_model is required when LLM is enabled"
                    )
                if (
                    provider != "ollama"
                    and getattr(self, f"llm_{provider}_api_key") is None
                ):
                    raise ValueError(
                        f"llm_{provider}_api_key is required when LLM is enabled"
                    )
        if (
            self.outbound_retry_min_delay_seconds
            > self.outbound_retry_max_delay_seconds
        ):
            raise ValueError("outbound retry minimum delay cannot exceed maximum delay")
        if self.outbound_delivery_enabled:
            if not self.telegram_enabled or self.telegram_bot_token is None:
                raise ValueError(
                    "Telegram enabled mode and bot token are required "
                    "for outbound delivery"
                )
            if self.telegram_platform_connection_id is None:
                raise ValueError(
                    "telegram_platform_connection_id is required for outbound delivery"
                )
        if self.demo_live_enabled:
            if self.telegram_delivery_mode != "polling":
                raise ValueError(
                    "demo live mode requires telegram_delivery_mode=polling"
                )
            if not self.demo_allowed_chat_ids:
                raise ValueError("demo live mode requires demo_allowed_chat_ids")
            if not self.llm_enabled or not self.outbound_delivery_enabled:
                raise ValueError("demo live mode requires LLM and outbound delivery")
        if self.environment in {"staging", "production"}:
            if self.log_level == "DEBUG":
                raise ValueError("DEBUG logging is not allowed outside local/test")
            if self.database_echo:
                raise ValueError("database_echo is not allowed outside local/test")
            database_url = self.resolved_database_url
            if not database_url.password or database_url.password == "january-local":
                raise ValueError("a non-local database credential is required")
            if database_url.host in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("staging/production database must not use loopback")
            redis_host = urlparse(self.redis_url.get_secret_value()).hostname
            if redis_host in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("staging/production redis_url must not use loopback")
            if (
                self.telegram_enabled
                and urlparse(self.telegram_api_base_url).scheme != "https"
            ):
                raise ValueError(
                    "staging/production Telegram API base URL must use HTTPS"
                )
            for production_provider in filter(
                None, (self.llm_primary_provider, self.llm_fallback_provider)
            ):
                if self.llm_enabled and production_provider != "ollama":
                    provider_url = getattr(self, f"llm_{production_provider}_base_url")
                    if urlparse(provider_url).scheme != "https":
                        raise ValueError(
                            "staging/production remote provider base URLs must use "
                            "HTTPS"
                        )
            if self.environment == "production" and self.demo_live_enabled:
                raise ValueError("demo_live_enabled is not allowed in production")
        return self

    def safe_configuration_fingerprint(self) -> dict[str, str | bool | int]:
        """Return allowlisted configuration metadata without secret material."""

        return {
            "environment": self.environment,
            "log_level": self.log_level,
            "telegram_enabled": self.telegram_enabled,
            "telegram_delivery_mode": self.telegram_delivery_mode,
            "llm_enabled": self.llm_enabled,
            "llm_primary_provider": self.llm_primary_provider,
            "outbound_delivery_enabled": self.outbound_delivery_enabled,
            "command_worker_enabled": self.command_worker_enabled,
            "proactive_scheduling_enabled": self.proactive_scheduling_enabled,
            "scheduler_worker_enabled": self.scheduler_worker_enabled,
            "conversation_summaries_enabled": self.conversation_summaries_enabled,
            "semantic_memory_enabled": self.semantic_memory_enabled,
            "telegram_voice_tts_enabled": self.telegram_voice_tts_enabled,
            "metrics_enabled": self.metrics_enabled,
            "rate_limit_enabled": self.rate_limit_enabled,
            "provider_concurrency_enabled": self.provider_concurrency_enabled,
            "safety_moderation_enabled": self.safety_moderation_enabled,
            "data_governance_enabled": self.data_governance_enabled,
            "database_pool_size": self.database_pool_size,
        }

    @property
    def resolved_database_url(self) -> URL:
        """Build the only database URL used by engines and migrations."""

        if self.database_url is not None:
            return make_url(self.database_url.get_secret_value())
        return URL.create(
            "postgresql+asyncpg",
            username=self.database_user,
            password=self.database_password.get_secret_value(),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )


@lru_cache
def get_settings() -> Settings:
    """Return process settings once; tests may clear this cache between cases."""

    return Settings()
