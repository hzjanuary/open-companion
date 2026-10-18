"""Construct typed internal-only limiter scopes from durable identifiers."""

from uuid import UUID

from app.core.config import Settings
from app.domain.rate_limit import RateLimitRule, RateLimitScope


def generation_rules(
    settings: Settings,
    *,
    connection_id: UUID,
    conversation_id: UUID,
    participant_id: UUID | None,
    provider_id: str | None = None,
) -> tuple[RateLimitRule, ...]:
    rules = [
        RateLimitRule(
            RateLimitScope.DEPLOYMENT,
            "deployment",
            settings.rate_limit_generation_deployment_per_minute,
            60,
        ),
        RateLimitRule(
            RateLimitScope.CONNECTION,
            str(connection_id),
            settings.rate_limit_generation_connection_per_minute,
            60,
        ),
        RateLimitRule(
            RateLimitScope.CONVERSATION,
            str(conversation_id),
            settings.rate_limit_generation_conversation_per_minute,
            60,
        ),
    ]
    if participant_id is not None:
        rules.append(
            RateLimitRule(
                RateLimitScope.PARTICIPANT,
                str(participant_id),
                settings.rate_limit_generation_participant_per_minute,
                60,
            )
        )
    if provider_id is not None:
        rules.append(provider_rule(settings, provider_id))
    return tuple(rules)


def provider_rule(settings: Settings, provider_id: str) -> RateLimitRule:
    return RateLimitRule(
        RateLimitScope.PROVIDER,
        provider_id,
        settings.rate_limit_generation_provider_per_minute,
        60,
    )


def text_to_speech_rules(
    settings: Settings,
    *,
    connection_id: UUID,
    conversation_id: UUID,
    participant_id: UUID,
    provider_id: str,
) -> tuple[RateLimitRule, ...]:
    """Use the authorized generation quotas at distinct TTS limiter keys."""

    return generation_rules(
        settings,
        connection_id=connection_id,
        conversation_id=conversation_id,
        participant_id=participant_id,
        provider_id=provider_id,
    )


def embedding_provider_rule(settings: Settings, provider_id: str) -> RateLimitRule:
    return RateLimitRule(
        RateLimitScope.PROVIDER,
        provider_id,
        settings.embedding_rate_per_minute,
        60,
    )


def delivery_rules(
    settings: Settings, *, connection_id: UUID, conversation_id: UUID
) -> tuple[RateLimitRule, ...]:
    return (
        RateLimitRule(
            RateLimitScope.DEPLOYMENT,
            "deployment",
            settings.rate_limit_delivery_deployment_per_second,
            1,
        ),
        RateLimitRule(
            RateLimitScope.CONNECTION,
            str(connection_id),
            settings.rate_limit_delivery_connection_per_second,
            1,
        ),
        RateLimitRule(
            RateLimitScope.CONVERSATION,
            str(conversation_id),
            settings.rate_limit_delivery_conversation_per_second,
            1,
        ),
    )
