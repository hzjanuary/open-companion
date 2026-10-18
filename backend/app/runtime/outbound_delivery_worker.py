"""Durable outbound delivery worker with explicit ambiguity handling."""

import asyncio
import hashlib
import logging
import secrets
import socket
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select

from app.application.ports.outbound import StickerAssetResolver
from app.application.ports.platform import (
    EditTextRequest,
    PlatformAdapterError,
    PlatformCapability,
    SendStickerRequest,
    SendTextRequest,
    SendVoiceRequest,
    SentMessage,
)
from app.application.ports.rate_limit import RateLimiter
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.application.rate_limit_rules import delivery_rules
from app.core.config import Settings
from app.domain.ambient import AMBIENT_PROFILES, ParticipationTrigger
from app.domain.conversation import MembershipStatus
from app.domain.outbound import (
    DeliveryAttemptStatus,
    DeliveryCertainty,
    OutboundActionKind,
    OutboundActionStatus,
)
from app.domain.rate_limit import RateLimitDecision, RateLimitOperation
from app.domain.recovery import RecoveryDisposition, RecoveryReason
from app.domain.safety import (
    InteractionKind,
    SafetyDecision,
    SafetyOutcome,
    SafetyPolicyVersion,
    SafetyReasonCode,
    SafetyStage,
)
from app.domain.voice import VOICE_ARTIFACT_MAX_BYTES, VoiceArtifactStatus
from app.infrastructure.database.database import Database
from app.infrastructure.database.governance import SqlAlchemyGovernanceRepository
from app.infrastructure.database.models import (
    ConversationConfigurationRevisionModel,
    ConversationModel,
    GeneratedVoiceArtifactModel,
    MessageModel,
    OutboundActionModel,
    ParticipantModel,
    ResponsePlanModel,
    TelegramVoiceGenerationJobModel,
)
from app.infrastructure.database.outbound import SqlAlchemyOutboundRepository
from app.infrastructure.database.safety import SqlAlchemySafetyRepository
from app.infrastructure.database.tenancy import conversation_authority
from app.infrastructure.rate_limit import RateLimitUnavailable, RedisRateLimiter
from app.infrastructure.telegram.adapter import TelegramAdapter
from app.infrastructure.telegram.assets import TelegramStickerAssetResolver
from app.infrastructure.telegram.rendering import (
    MentionTarget,
    render_text_with_mentions,
)
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.runtime.lifecycle import RuntimeLifecycle

logger = logging.getLogger(__name__)


def worker_name(settings: Settings) -> str:
    return f"{settings.outbound_owner_name}-{socket.gethostname()}"


async def consume_once(
    settings: Settings,
    database: Database,
    adapter: TelegramAdapter | None = None,
    rate_limiter: RateLimiter | None = None,
    telemetry: MetricsRecorder | None = None,
) -> int:
    if not settings.outbound_delivery_enabled:
        return 0
    owner = worker_name(settings)
    repository = SqlAlchemyOutboundRepository(database.session_factory)
    actions = await repository.claim(
        owner, settings.outbound_batch_size, settings.outbound_lease_seconds
    )
    owns_adapter = adapter is None
    owns_limiter = rate_limiter is None and settings.rate_limit_enabled
    limiter = (
        rate_limiter
        if rate_limiter is not None
        else RedisRateLimiter(settings)
        if settings.rate_limit_enabled
        else None
    )
    safety_repository = SqlAlchemySafetyRepository(database.session_factory)
    recorder = telemetry or NoOpMetricsRecorder()
    for action in actions:
        recorder.increment(
            "january_outbound_actions_total", kind=action.kind.value, outcome="claimed"
        )
    sender = adapter or TelegramAdapter(settings)
    asset_resolver = TelegramStickerAssetResolver(settings)
    try:
        for action in actions:
            try:
                if action.payload_redacted_at is not None:
                    await repository.finalize(
                        action.id,
                        owner,
                        OutboundActionStatus.SKIPPED,
                        DeliveryAttemptStatus.REJECTED,
                        DeliveryCertainty.NOT_SENT,
                        error_category="payload_redacted",
                    )
                    continue
                resolved = await _resolve(database, action.conversation_id, action)
                if resolved is None:
                    await repository.finalize(
                        action.id,
                        owner,
                        OutboundActionStatus.SKIPPED,
                        DeliveryAttemptStatus.REJECTED,
                        DeliveryCertainty.NOT_SENT,
                        error_category="outbound_precondition_failed",
                    )
                    continue
                conversation, reply, participants, voice_bytes = resolved
                # The demo allowlist is a defense in depth boundary.  Inbound
                # processing normally prevents these actions from existing,
                # but a queued action must never escape after configuration or
                # data changes.
                if (
                    settings.demo_live_enabled
                    and conversation.platform_conversation_id
                    not in settings.demo_allowed_chat_ids
                ):
                    await repository.finalize(
                        action.id,
                        owner,
                        OutboundActionStatus.SKIPPED,
                        DeliveryAttemptStatus.REJECTED,
                        DeliveryCertainty.NOT_SENT,
                        error_category="conversation_not_allowed",
                    )
                    continue
                if (
                    action.kind == OutboundActionKind.STICKER
                    and not await _stickers_allowed(database, conversation)
                ):
                    await repository.finalize(
                        action.id,
                        owner,
                        OutboundActionStatus.SKIPPED,
                        DeliveryAttemptStatus.REJECTED,
                        DeliveryCertainty.NOT_SENT,
                        error_category="stickers_disabled",
                    )
                    continue
                capability = (
                    PlatformCapability.EDIT_TEXT
                    if action.kind == OutboundActionKind.EDIT_TEXT
                    else PlatformCapability.SEND_TEXT
                    if action.kind == OutboundActionKind.TEXT
                    else PlatformCapability.SEND_VOICE
                    if action.kind == OutboundActionKind.VOICE
                    else PlatformCapability.SEND_STICKER
                )
                if capability not in sender.capabilities:
                    await repository.finalize(
                        action.id,
                        owner,
                        OutboundActionStatus.SKIPPED,
                        DeliveryAttemptStatus.REJECTED,
                        DeliveryCertainty.NOT_SENT,
                        error_category="unsupported_platform_capability",
                    )
                    continue
                if action.kind == OutboundActionKind.STICKER and (
                    action.sticker_intent is None
                    or asset_resolver.resolve(action.sticker_intent) is None
                ):
                    await repository.finalize(
                        action.id,
                        owner,
                        OutboundActionStatus.SKIPPED,
                        DeliveryAttemptStatus.REJECTED,
                        DeliveryCertainty.NOT_SENT,
                        error_category="sticker_not_configured",
                    )
                    continue
                if (
                    reason := await _safety_recheck(database, action, settings)
                ) is not None:
                    await safety_repository.record_decision(
                        planning_job_id=None,
                        response_plan_id=action.response_plan_id,
                        conversation_id=action.conversation_id,
                        decision=SafetyDecision(
                            SafetyPolicyVersion.V1,
                            SafetyStage.PRE_DELIVERY,
                            SafetyOutcome.SILENT,
                            reason,
                        ),
                    )
                    recorder.increment(
                        "january_safety_decisions_total",
                        stage=SafetyStage.PRE_DELIVERY.value,
                        outcome=SafetyOutcome.SILENT.value,
                        reason=reason.value,
                    )
                    await repository.finalize(
                        action.id,
                        owner,
                        OutboundActionStatus.SKIPPED,
                        DeliveryAttemptStatus.REJECTED,
                        DeliveryCertainty.NOT_SENT,
                        error_category="stale_safety_boundary",
                    )
                    continue
                if not await _ambient_delivery_allowed(database, settings, action):
                    await repository.finalize(
                        action.id,
                        owner,
                        OutboundActionStatus.SKIPPED,
                        DeliveryAttemptStatus.REJECTED,
                        DeliveryCertainty.NOT_SENT,
                        error_category="ambient_policy_suppressed",
                    )
                    continue
                if limiter is not None:
                    try:
                        decision = await limiter.check(
                            RateLimitOperation.DELIVERY,
                            delivery_rules(
                                settings,
                                connection_id=conversation.platform_connection_id,
                                conversation_id=conversation.id,
                            ),
                        )
                    except RateLimitUnavailable:
                        decision = RateLimitDecision(
                            False,
                            retry_after_seconds=settings.rate_limit_redis_failure_retry_seconds,
                        )
                    await safety_repository.record_rate_limit(
                        planning_job_id=None,
                        outbound_action_id=action.id,
                        operation=RateLimitOperation.DELIVERY,
                        decision=decision,
                        provider_id=None,
                        configuration_version=SafetyPolicyVersion.V1.value,
                    )
                    if not decision.allowed:
                        recorder.increment(
                            "january_rate_limit_events_total",
                            operation="delivery",
                            scope=(
                                decision.limiting_scope.value
                                if decision.limiting_scope is not None
                                else "unavailable"
                            ),
                            result="denied",
                        )
                        logger.info(
                            "rate_limit_denied operation=delivery "
                            "outbound_action_id=%s scope=%s retry_after_seconds=%s",
                            action.id,
                            decision.limiting_scope,
                            decision.retry_after_seconds,
                        )
                        delay = (
                            decision.retry_after_seconds
                            or settings.rate_limit_redis_failure_retry_seconds
                        )
                        await repository.finalize(
                            action.id,
                            owner,
                            OutboundActionStatus.PENDING,
                            DeliveryAttemptStatus.REJECTED,
                            DeliveryCertainty.NOT_SENT,
                            error_category="rate_limited",
                            retry_after_seconds=float(delay),
                            available_at=datetime.now(UTC) + timedelta(seconds=delay),
                        )
                        continue
                await safety_repository.record_decision(
                    planning_job_id=None,
                    response_plan_id=action.response_plan_id,
                    conversation_id=action.conversation_id,
                    decision=SafetyDecision(
                        SafetyPolicyVersion.V1,
                        SafetyStage.PRE_DELIVERY,
                        SafetyOutcome.ALLOW,
                    ),
                )
                recorder.increment(
                    "january_safety_decisions_total",
                    stage=SafetyStage.PRE_DELIVERY.value,
                    outcome=SafetyOutcome.ALLOW.value,
                    reason="none",
                )
                delivery_text = action.text
                if action.governance_export_request_id is not None:
                    credential = secrets.token_urlsafe(32)
                    issued = await SqlAlchemyGovernanceRepository(
                        database.session_factory
                    ).issue_export_token(
                        action.governance_export_request_id,
                        hashlib.sha256(credential.encode("ascii")).hexdigest(),
                    )
                    if not issued:
                        await repository.finalize(
                            action.id,
                            owner,
                            OutboundActionStatus.SKIPPED,
                            DeliveryAttemptStatus.REJECTED,
                            DeliveryCertainty.NOT_SENT,
                            error_category="export_credential_unavailable",
                        )
                        continue
                    delivery_text = (
                        f"{action.text or ''}\nSingle-use retrieval credential: "
                        f"{credential}\nSend it in the Authorization: Bearer header to "
                        "POST /api/v1/governance/exports/retrieve."
                    )
                if not await repository.mark_external_started(action.id, owner):
                    if action.origin == ParticipationTrigger.SCHEDULED:
                        recorder.increment(
                            "january_schedule_delivery_total",
                            outcome=await repository.scheduled_preflight_outcome(
                                action.id
                            ),
                        )
                    continue
                try:
                    sent = await _send(
                        sender,
                        settings,
                        asset_resolver,
                        action,
                        conversation,
                        reply,
                        participants,
                        voice_bytes,
                        text_override=delivery_text,
                    )
                except PlatformAdapterError as error:
                    if (
                        action.kind == OutboundActionKind.EDIT_TEXT
                        and error.edit_not_modified
                    ):
                        await repository.finalize_edit_success(
                            action.id, owner, not_modified=True
                        )
                        recorder.increment(
                            "january_telegram_edit_results_total",
                            outcome="not_modified",
                        )
                        continue
                    if (
                        action.kind == OutboundActionKind.EDIT_TEXT
                        and error.edit_target_rejected
                    ):
                        await repository.activate_edit_fallback(
                            action.id,
                            owner,
                            str(error.telegram_error_code or 400),
                        )
                        recorder.increment(
                            "january_telegram_edit_results_total",
                            outcome="fallback_activated",
                        )
                        continue
                    if not error.reply_target_rejected or reply is None:
                        raise
                    recorded = await repository.mark_reply_fallback(
                        action.id,
                        owner,
                        str(error.telegram_error_code or 400),
                    )
                    if not recorded:
                        raise
                    sent = await _send(
                        sender,
                        settings,
                        asset_resolver,
                        action,
                        conversation,
                        reply,
                        participants,
                        voice_bytes,
                        text_override=delivery_text,
                        suppress_reply=True,
                    )
            except PlatformAdapterError as error:
                recorder.increment(
                    "january_outbound_actions_total",
                    kind=action.kind.value,
                    outcome="unknown"
                    if error.delivery_certainty == DeliveryCertainty.UNKNOWN
                    else "failed",
                )
                if error.delivery_certainty != DeliveryCertainty.UNKNOWN:
                    recorder.increment(
                        "january_telegram_send_failures_total",
                        kind=action.kind.value,
                        error_class=error.category.value,
                    )
                if action.origin == ParticipationTrigger.SCHEDULED:
                    recorder.increment(
                        "january_schedule_delivery_total",
                        outcome=(
                            "unknown"
                            if error.delivery_certainty == DeliveryCertainty.UNKNOWN
                            else "failed"
                        ),
                    )
                await _record_error(
                    repository,
                    action.id,
                    owner,
                    action.attempt_count,
                    settings,
                    error,
                    recorder,
                )
            else:
                recorder.increment(
                    "january_outbound_actions_total",
                    kind=action.kind.value,
                    outcome="completed",
                )
                finalized = (
                    await repository.finalize_edit_success(action.id, owner)
                    if action.kind == OutboundActionKind.EDIT_TEXT
                    else await repository.finalize(
                        action.id,
                        owner,
                        OutboundActionStatus.DELIVERED,
                        DeliveryAttemptStatus.CONFIRMED,
                        DeliveryCertainty.CONFIRMED,
                        delivered_platform_message_id=sent.platform_message_id,
                        delivered_thread_id=sent.message_thread_id,
                    )
                )
                if finalized and action.kind == OutboundActionKind.EDIT_TEXT:
                    recorder.increment(
                        "january_telegram_edit_results_total", outcome="edited"
                    )
                if finalized and action.governance_export_request_id is not None:
                    await SqlAlchemyGovernanceRepository(
                        database.session_factory
                    ).record_export_delivered(action.governance_export_request_id)
                if finalized and action.origin == ParticipationTrigger.SCHEDULED:
                    recorder.increment(
                        "january_schedule_delivery_total", outcome="delivered"
                    )
        return len(actions)
    finally:
        if owns_adapter:
            await sender.aclose()
        if owns_limiter and limiter is not None:
            await limiter.aclose()


async def _resolve(
    database: Database, conversation_id: UUID, action: OutboundActionModel
) -> (
    tuple[ConversationModel, MessageModel | None, list[ParticipantModel], bytes | None]
    | None
):
    async with database.session_factory() as session:
        resolved = await conversation_authority(session, conversation_id)
        if resolved is None:
            return None
        conversation, authority = resolved
        if conversation.status.value != "active" or not authority.permits_external_io:
            return None
        invalid_membership = conversation.assistant_membership_status in {
            MembershipStatus.LEFT,
            MembershipStatus.KICKED,
            MembershipStatus.RESTRICTED,
        }
        if invalid_membership:
            return None
        reply_id = action.reply_to_message_id
        reply = await session.get(MessageModel, reply_id) if reply_id else None
        if reply_id is not None and (
            reply is None or reply.conversation_id != conversation.id
        ):
            return None
        if action.kind == OutboundActionKind.EDIT_TEXT:
            target = (
                await session.get(MessageModel, action.edit_target_message_id)
                if action.edit_target_message_id is not None
                else None
            )
            if (
                target is None
                or target.conversation_id != conversation.id
                or target.platform_message_id != action.edit_target_platform_message_id
                or target.content_redacted_at is not None
                or target.direction.value != "outgoing"
                or target.message_type.value != "text"
            ):
                return None
        identifiers = [UUID(value) for value in action.mention_participant_ids]
        fetched = list(
            await session.scalars(
                select(ParticipantModel).where(
                    ParticipantModel.conversation_id == conversation.id,
                    ParticipantModel.id.in_(identifiers),
                    ParticipantModel.mention_allowed.is_(True),
                    ParticipantModel.privacy_deleted_at.is_(None),
                    ParticipantModel.protected_at.is_(None),
                )
            )
        )
        by_id = {participant.id: participant for participant in fetched}
        participants = [
            by_id[identifier] for identifier in identifiers if identifier in by_id
        ]
        voice_bytes: bytes | None = None
        if action.kind == OutboundActionKind.VOICE:
            artifact = (
                await session.get(
                    GeneratedVoiceArtifactModel,
                    action.generated_voice_artifact_id,
                )
                if action.generated_voice_artifact_id is not None
                else None
            )
            generation_job = (
                await session.get(
                    TelegramVoiceGenerationJobModel, artifact.generation_job_id
                )
                if artifact is not None
                else None
            )
            source_plan = (
                await session.get(ResponsePlanModel, artifact.source_response_plan_id)
                if artifact is not None
                else None
            )
            now = datetime.now(UTC)
            if (
                artifact is None
                or generation_job is None
                or source_plan is None
                or artifact.conversation_id != conversation.id
                or generation_job.conversation_id != conversation.id
                or generation_job.privacy_revision
                != conversation.memory_privacy_revision
                or artifact.status != VoiceArtifactStatus.READY
                or artifact.expires_at <= now
                or artifact.audio_bytes is None
                or not 1 <= len(artifact.audio_bytes) <= VOICE_ARTIFACT_MAX_BYTES
                or not artifact.audio_bytes.startswith(b"OggS")
                or source_plan.content_redacted_at is not None
                or source_plan.text is None
            ):
                return None
            voice_bytes = bytes(artifact.audio_bytes)
        return conversation, reply, participants, voice_bytes


async def _safety_recheck(
    database: Database, action: OutboundActionModel, settings: Settings
) -> SafetyReasonCode | None:
    """Recheck persisted teasing targets immediately before Telegram I/O.

    Returns the deterministic reason when the action must not be delivered, or
    None when targeting is still safe. Rechecks opt-out, privacy deletion,
    protection (FR-03/FR-10), and the per-group teasing cap (FR-09).
    """

    async with database.session_factory() as session:
        plan = await session.get(ResponsePlanModel, action.response_plan_id)
        if plan is None or plan.interaction_kind.value != "teasing":
            return None
        identifiers = [UUID(value) for value in plan.teasing_target_participant_ids]
        identifier_strings = [str(identifier) for identifier in identifiers]
        if not identifiers:
            return SafetyReasonCode.TEASING_TARGET_OPTED_OUT
        targets = list(
            await session.scalars(
                select(ParticipantModel).where(
                    ParticipantModel.conversation_id == action.conversation_id,
                    ParticipantModel.id.in_(identifiers),
                )
            )
        )
        by_id = {participant.id: participant for participant in targets}
        if len(by_id) != len(identifiers):
            return SafetyReasonCode.TEASING_TARGET_OPTED_OUT
        if any(
            by_id[identifier].privacy_deleted_at is not None
            or not by_id[identifier].teasing_allowed
            for identifier in identifiers
        ):
            return SafetyReasonCode.TEASING_TARGET_OPTED_OUT
        if any(
            by_id[identifier].protected_at is not None for identifier in identifiers
        ):
            return SafetyReasonCode.TARGET_PROTECTED
        if not settings.safety_moderation_enabled:
            return None
        revision = None
        conversation = await session.get(ConversationModel, action.conversation_id)
        if (
            conversation is not None
            and conversation.current_configuration_revision_id is not None
        ):
            revision = await session.get(
                ConversationConfigurationRevisionModel,
                conversation.current_configuration_revision_id,
            )
        cap = revision.teasing_cap if revision is not None else None
        if cap is None or cap < 0:
            return None
        window_start = datetime.now(UTC) - timedelta(
            seconds=settings.safety_signal_window_seconds
        )
        delivered_toward = await session.scalar(
            select(func.count())
            .select_from(OutboundActionModel)
            .join(
                ResponsePlanModel,
                OutboundActionModel.response_plan_id == ResponsePlanModel.id,
            )
            .where(
                OutboundActionModel.conversation_id == action.conversation_id,
                OutboundActionModel.status == OutboundActionStatus.DELIVERED,
                OutboundActionModel.id != action.id,
                OutboundActionModel.completed_at.is_not(None),
                OutboundActionModel.completed_at >= window_start,
                ResponsePlanModel.interaction_kind == InteractionKind.TEASING,
                or_(
                    *(
                        ResponsePlanModel.teasing_target_participant_ids.contains(
                            [identifier_string]
                        )
                        for identifier_string in identifier_strings
                    )
                ),
            )
        )
        if int(delivered_toward or 0) >= cap:
            return SafetyReasonCode.TEASING_CAP_EXCEEDED
        return None


async def _ambient_delivery_allowed(
    database: Database, settings: Settings, action: OutboundActionModel
) -> bool:
    """Recheck opt-in and confirmed-delivery cooldown before Telegram I/O."""
    if action.origin != ParticipationTrigger.AMBIENT:
        return True
    if not settings.ambient_selective_enabled:
        return False
    async with database.session_factory() as session:
        conversation = await session.get(ConversationModel, action.conversation_id)
        if (
            conversation is None
            or conversation.current_configuration_revision_id is None
        ):
            return False
        revision = await session.get(
            ConversationConfigurationRevisionModel,
            conversation.current_configuration_revision_id,
        )
        if revision is None or revision.response_mode.value != "ambient_selective":
            return False
        last = await session.scalar(
            select(func.max(OutboundActionModel.completed_at)).where(
                OutboundActionModel.conversation_id == action.conversation_id,
                OutboundActionModel.origin == ParticipationTrigger.AMBIENT,
                OutboundActionModel.status == OutboundActionStatus.DELIVERED,
                OutboundActionModel.id != action.id,
            )
        )
    return (
        last is None
        or (datetime.now(UTC) - last).total_seconds()
        >= AMBIENT_PROFILES[revision.ambient_frequency].cooldown_seconds
    )


async def _stickers_allowed(
    database: Database, conversation: ConversationModel
) -> bool:
    """Use the current safety projection immediately before external delivery."""
    if conversation.current_configuration_revision_id is None:
        return False
    async with database.session_factory() as session:
        revision = await session.get(
            ConversationConfigurationRevisionModel,
            conversation.current_configuration_revision_id,
        )
        return revision.stickers_enabled if revision is not None else False


async def _send(
    sender: TelegramAdapter,
    settings: Settings,
    asset_resolver: StickerAssetResolver,
    action: OutboundActionModel,
    conversation: ConversationModel,
    reply: MessageModel | None,
    participants: list[ParticipantModel],
    voice_bytes: bytes | None,
    *,
    text_override: str | None = None,
    suppress_reply: bool = False,
) -> SentMessage:
    reply_id = reply.platform_message_id if reply and not suppress_reply else None
    thread_id = (
        reply.platform_thread_id
        if reply is not None and not suppress_reply
        else action.message_thread_id
    )
    if action.kind in {OutboundActionKind.TEXT, OutboundActionKind.EDIT_TEXT}:
        rendered, entities = render_text_with_mentions(
            text_override if text_override is not None else action.text or "",
            tuple(MentionTarget(item.id, item.username) for item in participants),
        )
        if action.kind == OutboundActionKind.EDIT_TEXT:
            if action.edit_target_platform_message_id is None:
                raise RuntimeError("edit action is missing its target")
            return await sender.edit_text(
                EditTextRequest(
                    conversation_id=conversation.platform_conversation_id,
                    platform_message_id=action.edit_target_platform_message_id,
                    text=rendered,
                    entities=entities,
                )
            )
        return await sender.send_text(
            SendTextRequest(
                conversation_id=conversation.platform_conversation_id,
                text=rendered,
                reply_to_message_id=reply_id,
                message_thread_id=thread_id,
                entities=entities,
                disable_notification=settings.telegram_disable_notification,
                protect_content=settings.telegram_protect_content,
            )
        )
    if action.kind == OutboundActionKind.VOICE:
        if voice_bytes is None:
            raise RuntimeError("voice action is missing its bounded artifact")
        return await sender.send_voice(
            SendVoiceRequest(
                conversation_id=conversation.platform_conversation_id,
                audio_bytes=voice_bytes,
                reply_to_message_id=reply_id,
                message_thread_id=thread_id,
                disable_notification=settings.telegram_disable_notification,
                protect_content=settings.telegram_protect_content,
            )
        )
    intent = action.sticker_intent
    asset = asset_resolver.resolve(intent) if intent else None
    if asset is None:
        raise RuntimeError("configured sticker action reached send without an asset")
    return await sender.send_sticker(
        SendStickerRequest(
            conversation_id=conversation.platform_conversation_id,
            asset_reference=asset,
            reply_to_message_id=reply_id,
            message_thread_id=thread_id,
            disable_notification=settings.telegram_disable_notification,
            protect_content=settings.telegram_protect_content,
        )
    )


async def _record_error(
    repository: SqlAlchemyOutboundRepository,
    action_id: UUID,
    owner: str,
    attempts: int,
    settings: Settings,
    error: PlatformAdapterError,
    telemetry: MetricsRecorder | None = None,
) -> None:
    recorder = telemetry or NoOpMetricsRecorder()
    code = str(error.telegram_error_code) if error.telegram_error_code else None
    if error.delivery_certainty == DeliveryCertainty.UNKNOWN:
        await repository.finalize(
            action_id,
            owner,
            OutboundActionStatus.DELIVERY_UNKNOWN,
            DeliveryAttemptStatus.UNKNOWN,
            DeliveryCertainty.UNKNOWN,
            error_category=error.category.value,
            error_code=code,
        )
        classify = getattr(repository, "classify_recovery", None)
        if classify is not None:
            await classify(
                action_id,
                RecoveryDisposition.QUARANTINE,
                RecoveryReason.AMBIGUOUS_EXTERNAL_DELIVERY,
            )
        recorder.increment(
            "january_quarantine_events_total",
            work_kind="outbound",
            reason="ambiguous_external_delivery",
        )
        recorder.increment(
            "january_recovery_events_total",
            work_kind="outbound",
            operation="classify",
            outcome="quarantine",
            reason="ambiguous_external_delivery",
        )
        return
    retryable = error.retryable and (
        attempts < settings.outbound_max_confirmed_rejection_attempts
    )
    if error.replacement_conversation_id is not None and attempts > 1:
        retryable = False
    delay = error.retry_after_seconds or min(
        settings.outbound_retry_max_delay_seconds,
        settings.outbound_retry_min_delay_seconds * (2 ** (attempts - 1)),
    )
    await repository.finalize(
        action_id,
        owner,
        OutboundActionStatus.PENDING
        if retryable
        else OutboundActionStatus.PERMANENTLY_FAILED,
        DeliveryAttemptStatus.REJECTED,
        error.delivery_certainty,
        error_category=error.category.value,
        error_code=code,
        retry_after_seconds=float(delay) if retryable else None,
        migration_conversation_id=error.replacement_conversation_id,
        available_at=datetime.now(UTC) + timedelta(seconds=delay)
        if retryable
        else None,
    )
    if not retryable:
        classify = getattr(repository, "classify_recovery", None)
        if classify is not None:
            await classify(
                action_id,
                RecoveryDisposition.DEAD_LETTER,
                RecoveryReason.DELIVERY_REJECTION_EXHAUSTED,
            )
        recorder.increment(
            "january_dead_letter_events_total",
            work_kind="outbound",
            reason="delivery_rejection_exhausted",
        )
        recorder.increment(
            "january_recovery_events_total",
            work_kind="outbound",
            operation="classify",
            outcome="dead_letter",
            reason="delivery_rejection_exhausted",
        )


async def run() -> None:
    settings = Settings()
    database = Database(settings)
    telemetry = (
        InMemoryMetricsRecorder() if settings.metrics_enabled else NoOpMetricsRecorder()
    )
    await database.start()
    lifecycle = RuntimeLifecycle("outbound_delivery_worker")
    lifecycle.install()
    try:
        while not lifecycle.stopping:
            if await consume_once(settings, database, telemetry=telemetry) == 0:
                await lifecycle.wait(settings.outbound_poll_interval_seconds)
    finally:
        lifecycle.close()
        await database.stop()


if __name__ == "__main__":
    asyncio.run(run())
