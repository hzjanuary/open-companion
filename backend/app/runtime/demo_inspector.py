"""Read-only durable status for the guarded local demo."""

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import func, select

from app.core.config import Settings
from app.domain.persistence import MemoryStatus
from app.domain.summary import ConversationSummaryStatus
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import (
    ConversationConfigurationRevisionModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    ConversationSummaryJobModel,
    ConversationSummaryModel,
    IncomingPlatformUpdateModel,
    IngressOutboxEventModel,
    MemoryEventModel,
    MemoryItemModel,
    MessageModel,
    ModelGenerationAttemptModel,
    OutboundActionModel,
    OutboundDeliveryAttemptModel,
    OutboundRecoveryEventModel,
    PersonalityProfileVersionModel,
    PlatformConnectionModel,
    RateLimitEventModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
    SafetyPolicyDecisionModel,
    TelegramCommandJobModel,
)

RECOVERY_COMMAND_PREFIX = "uv run python -m app.runtime.outbound_recovery "


async def inspect_latest(
    settings: Settings,
    *,
    platform_update_id: str | None = None,
    incoming_update_id: UUID | None = None,
    conversation_id: UUID | None = None,
    platform_chat_id: str | None = None,
) -> dict[str, object]:
    """Return identifiers and state only; message and provider contents stay private."""
    database = Database(settings)
    await database.start()
    try:
        async with database.session_factory() as session:
            update_query = select(IncomingPlatformUpdateModel)
            if platform_update_id is not None:
                update_query = update_query.where(
                    IncomingPlatformUpdateModel.platform_update_id == platform_update_id
                )
            if incoming_update_id is not None:
                update_query = update_query.where(
                    IncomingPlatformUpdateModel.id == incoming_update_id
                )
            if conversation_id is not None:
                update_query = update_query.join(
                    ConversationProcessingRecordModel
                ).where(
                    ConversationProcessingRecordModel.conversation_id == conversation_id
                )
            if platform_chat_id is not None:
                update_query = (
                    update_query.join(ConversationProcessingRecordModel)
                    .join(ConversationModel)
                    .where(
                        ConversationModel.platform_conversation_id == platform_chat_id
                    )
                )
            update = await session.scalar(
                update_query.order_by(
                    IncomingPlatformUpdateModel.received_at.desc()
                ).limit(1)
            )
            counts = {
                "incoming_updates": await session.scalar(
                    select(func.count(IncomingPlatformUpdateModel.id))
                ),
                "conversation_records": await session.scalar(
                    select(func.count(ConversationProcessingRecordModel.id))
                ),
                "planning_jobs": await session.scalar(
                    select(func.count(ResponsePlanningJobModel.id))
                ),
                "command_jobs": await session.scalar(
                    select(func.count(TelegramCommandJobModel.id))
                ),
                "response_plans": await session.scalar(
                    select(func.count(ResponsePlanModel.id))
                ),
                "outbound_actions": await session.scalar(
                    select(func.count(OutboundActionModel.id))
                ),
            }
            action_status_rows = (
                await session.execute(
                    select(
                        OutboundActionModel.status, func.count(OutboundActionModel.id)
                    )
                    .group_by(OutboundActionModel.status)
                    .order_by(OutboundActionModel.status)
                )
            ).all()
            action_statuses = {
                status.value: count for status, count in action_status_rows
            }
            latest_error = await session.scalar(
                select(OutboundActionModel.last_error_category)
                .where(OutboundActionModel.last_error_category.is_not(None))
                .order_by(OutboundActionModel.last_error_at.desc())
                .limit(1)
            )
            connection = await session.scalar(
                select(PlatformConnectionModel)
                .where(
                    PlatformConnectionModel.id
                    == settings.telegram_platform_connection_id
                )
                .limit(1)
            )
            summary = {
                "counts": counts,
                "outbound_statuses": action_statuses,
                "latest_outbound_error_category": latest_error,
                "bot_identity": {
                    "external_bot_id": connection.external_bot_id,
                    "username": connection.configuration.get("username"),
                }
                if connection is not None
                else None,
            }
            configuration_summary: dict[str, object] | None = None
            if conversation_id is not None:
                conversation = await session.get(ConversationModel, conversation_id)
                revision = (
                    await session.get(
                        ConversationConfigurationRevisionModel,
                        conversation.current_configuration_revision_id,
                    )
                    if conversation is not None
                    and conversation.current_configuration_revision_id is not None
                    else None
                )
                version = (
                    await session.get(
                        PersonalityProfileVersionModel,
                        revision.personality_profile_version_id,
                    )
                    if revision is not None
                    else None
                )
                if revision is not None and version is not None:
                    configuration_summary = {
                        "configuration_revision_id": str(revision.id),
                        "configuration_revision_number": revision.revision_number,
                        "personality_profile_version_id": str(version.id),
                        "personality_profile_version_number": version.version_number,
                        "response_mode": revision.response_mode.value,
                        "stickers_enabled": revision.stickers_enabled,
                    }
            summary["personality_configuration"] = configuration_summary
            memory_query = select(MemoryItemModel).order_by(
                MemoryItemModel.created_at.desc(), MemoryItemModel.id
            )
            if conversation_id is not None:
                memory_query = memory_query.where(
                    MemoryItemModel.conversation_id == conversation_id
                )
            memory_items = list(await session.scalars(memory_query.limit(20)))
            memory_events = list(
                await session.scalars(
                    select(MemoryEventModel)
                    .order_by(MemoryEventModel.created_at.desc(), MemoryEventModel.id)
                    .limit(20)
                )
            )
            summary["memory_privacy"] = {
                "active_memory_count": await session.scalar(
                    select(func.count(MemoryItemModel.id)).where(
                        MemoryItemModel.status == MemoryStatus.ACTIVE
                    )
                ),
                "memory_items": [
                    {
                        "public_id": item.public_id,
                        "kind": item.kind.value,
                        "scope": item.scope.value,
                        "visibility": item.visibility.value,
                        "status": item.status.value,
                        "created_at": item.created_at.isoformat(),
                        "deleted_at": item.deleted_at.isoformat()
                        if item.deleted_at
                        else None,
                        "expires_at": item.expires_at.isoformat()
                        if item.expires_at
                        else None,
                        "content_retained": item.content is not None,
                    }
                    for item in memory_items
                ],
                "latest_event_codes": [event.action_code for event in memory_events],
            }
            summary_statuses = (
                await session.execute(
                    select(
                        ConversationSummaryModel.status,
                        func.count(ConversationSummaryModel.id),
                    ).group_by(ConversationSummaryModel.status)
                )
            ).all()
            job_statuses = (
                await session.execute(
                    select(
                        ConversationSummaryJobModel.status,
                        func.count(ConversationSummaryJobModel.id),
                    ).group_by(ConversationSummaryJobModel.status)
                )
            ).all()
            summary["conversation_summaries"] = {
                "enabled": settings.conversation_summaries_enabled,
                "worker_enabled": settings.summary_worker_enabled,
                "summary_statuses": {
                    status.value: count for status, count in summary_statuses
                },
                "job_statuses": {status.value: count for status, count in job_statuses},
                "oldest_pending_at": await session.scalar(
                    select(func.min(ConversationSummaryJobModel.created_at)).where(
                        ConversationSummaryJobModel.status
                        == ConversationSummaryStatus.PENDING
                    )
                ),
                "nearest_expiry": await session.scalar(
                    select(func.min(ConversationSummaryModel.expires_at)).where(
                        ConversationSummaryModel.status
                        == ConversationSummaryStatus.COMPLETED
                    )
                ),
            }
            safety_decisions = list(
                await session.scalars(
                    select(SafetyPolicyDecisionModel)
                    .order_by(SafetyPolicyDecisionModel.created_at.desc())
                    .limit(20)
                )
            )
            rate_events = list(
                await session.scalars(
                    select(RateLimitEventModel)
                    .order_by(RateLimitEventModel.created_at.desc())
                    .limit(20)
                )
            )
            summary["safety_rate_limiting"] = {
                "enabled": settings.rate_limit_enabled,
                "safety_decisions": [
                    {
                        "planning_job_id": str(item.planning_job_id)
                        if item.planning_job_id
                        else None,
                        "response_plan_id": str(item.response_plan_id)
                        if item.response_plan_id
                        else None,
                        "policy_version": item.policy_version.value,
                        "stage": item.stage.value,
                        "outcome": item.outcome.value,
                        "reason_code": item.reason_code.value
                        if item.reason_code
                        else None,
                        "transformed": item.transformed,
                    }
                    for item in safety_decisions
                ],
                "rate_limit_events": [
                    {
                        "planning_job_id": str(item.planning_job_id)
                        if item.planning_job_id
                        else None,
                        "outbound_action_id": str(item.outbound_action_id)
                        if item.outbound_action_id
                        else None,
                        "operation": item.operation.value,
                        "limiting_scope": item.limiting_scope.value
                        if item.limiting_scope
                        else None,
                        "provider_id": item.provider_id,
                        "allowed": item.allowed,
                        "retry_after_seconds": item.retry_after_seconds,
                        "configuration_version": item.configuration_version,
                    }
                    for item in rate_events
                ],
            }
            if update is None:
                return {"latest_update": None, **summary}
            record = await session.scalar(
                select(ConversationProcessingRecordModel).where(
                    ConversationProcessingRecordModel.incoming_update_id == update.id
                )
            )
            outbox = await session.scalar(
                select(IngressOutboxEventModel).where(
                    IngressOutboxEventModel.incoming_update_id == update.id
                )
            )
            message = (
                await session.get(MessageModel, record.message_id)
                if record and record.message_id
                else None
            )
            jobs = (
                list(
                    await session.scalars(
                        select(ResponsePlanningJobModel)
                        .where(
                            ResponsePlanningJobModel.conversation_processing_record_id
                            == record.id
                        )
                        .order_by(ResponsePlanningJobModel.created_at)
                    )
                )
                if record
                else []
            )
            command_jobs = (
                list(
                    await session.scalars(
                        select(TelegramCommandJobModel)
                        .where(
                            TelegramCommandJobModel.conversation_processing_record_id
                            == record.id
                        )
                        .order_by(TelegramCommandJobModel.created_at)
                    )
                )
                if record
                else []
            )
            job_ids = [job.id for job in jobs]
            attempts = (
                list(
                    await session.scalars(
                        select(ModelGenerationAttemptModel)
                        .where(ModelGenerationAttemptModel.planning_job_id.in_(job_ids))
                        .order_by(
                            ModelGenerationAttemptModel.planning_job_id,
                            ModelGenerationAttemptModel.attempt_number,
                        )
                    )
                )
                if job_ids
                else []
            )
            plans = (
                list(
                    await session.scalars(
                        select(ResponsePlanModel)
                        .where(ResponsePlanModel.planning_job_id.in_(job_ids))
                        .order_by(ResponsePlanModel.created_at)
                    )
                )
                if job_ids
                else []
            )
            command_plan_ids = [job.id for job in command_jobs]
            if command_plan_ids:
                plans.extend(
                    list(
                        await session.scalars(
                            select(ResponsePlanModel)
                            .where(
                                ResponsePlanModel.command_job_id.in_(command_plan_ids)
                            )
                            .order_by(ResponsePlanModel.created_at)
                        )
                    )
                )
            plan_ids = [plan.id for plan in plans]
            actions = (
                list(
                    await session.scalars(
                        select(OutboundActionModel)
                        .where(OutboundActionModel.response_plan_id.in_(plan_ids))
                        .order_by(
                            OutboundActionModel.response_plan_id,
                            OutboundActionModel.sequence_number,
                        )
                    )
                )
                if plan_ids
                else []
            )
            action_ids = [action.id for action in actions]
            deliveries = (
                list(
                    await session.scalars(
                        select(OutboundDeliveryAttemptModel)
                        .where(
                            OutboundDeliveryAttemptModel.outbound_action_id.in_(
                                action_ids
                            )
                        )
                        .order_by(
                            OutboundDeliveryAttemptModel.outbound_action_id,
                            OutboundDeliveryAttemptModel.attempt_number,
                        )
                    )
                )
                if action_ids
                else []
            )
            recoveries = (
                list(
                    await session.scalars(
                        select(OutboundRecoveryEventModel)
                        .where(
                            OutboundRecoveryEventModel.outbound_action_id.in_(
                                action_ids
                            )
                        )
                        .order_by(OutboundRecoveryEventModel.created_at)
                    )
                )
                if action_ids
                else []
            )
            return {
                "latest_update": {
                    "id": str(update.id),
                    "platform_update_id": update.platform_update_id,
                    "received_at": update.received_at.isoformat(),
                    "conversation_outcome": record.outcome.value if record else None,
                    "conversation_id": str(record.conversation_id)
                    if record and record.conversation_id
                    else None,
                },
                "trace": {
                    "ingress_outbox": {
                        "id": str(outbox.id),
                        "status": outbox.status.value,
                        "attempt_count": outbox.attempt_count,
                        "error_category": outbox.last_error_category,
                    }
                    if outbox
                    else {"status": "not_created"},
                    "message": {
                        "id": str(message.id),
                        "platform_message_id": message.platform_message_id,
                        "direction": message.direction.value,
                        "thread_id": message.platform_thread_id,
                        "eligible": message.eligible,
                        "eligibility_reason": message.eligibility_reason.value
                        if message.eligibility_reason
                        else None,
                    }
                    if message
                    else {"status": "not_created"},
                    "planning_jobs": [
                        {
                            "id": str(job.id),
                            "status": job.status.value,
                            "attempt_count": job.attempt_count,
                            "provider": job.selected_provider.value
                            if job.selected_provider
                            else None,
                            "model": job.selected_model,
                            "personality_profile_version_id": str(
                                job.personality_profile_version_id
                            )
                            if job.personality_profile_version_id
                            else None,
                            "configuration_revision_id": str(
                                job.configuration_revision_id
                            )
                            if job.configuration_revision_id
                            else None,
                            "error_category": job.last_error_category.value
                            if job.last_error_category
                            else None,
                        }
                        for job in jobs
                    ],
                    "command_jobs": [
                        {
                            "id": str(job.id),
                            "name": job.command_name,
                            "status": job.status.value,
                            "authorization_outcome": job.authorization_outcome.value
                            if job.authorization_outcome
                            else None,
                            "result_code": job.result_code,
                        }
                        for job in command_jobs
                    ],
                    "generation_attempts": [
                        {
                            "id": str(attempt.id),
                            "planning_job_id": str(attempt.planning_job_id),
                            "attempt_number": attempt.attempt_number,
                            "provider": attempt.provider.value,
                            "model": attempt.model,
                            "status": attempt.status.value,
                            "error_category": attempt.error_category.value
                            if attempt.error_category
                            else None,
                        }
                        for attempt in attempts
                    ],
                    "response_plans": [
                        {
                            "id": str(plan.id),
                            "planning_job_id": str(plan.planning_job_id)
                            if plan.planning_job_id
                            else None,
                            "command_job_id": str(plan.command_job_id)
                            if plan.command_job_id
                            else None,
                            "should_respond": plan.should_respond,
                            "reason_code": plan.reason_code.value,
                            "reply_to_message_id": str(plan.reply_to_message_id)
                            if plan.reply_to_message_id
                            else None,
                        }
                        for plan in plans
                    ],
                    "outbound_actions": [
                        {
                            "id": str(action.id),
                            "sequence": action.sequence_number,
                            "kind": action.kind.value,
                            "status": action.status.value,
                            "error_category": action.last_error_category,
                            "delivered_message_id": str(action.delivered_message_id)
                            if action.delivered_message_id
                            else None,
                            "recovery_command": RECOVERY_COMMAND_PREFIX
                            + f"{action.id} --confirm-possible-duplicate"
                            if action.status.value == "delivery_unknown"
                            else None,
                        }
                        for action in actions
                    ],
                    "delivery_attempts": [
                        {
                            "id": str(delivery.id),
                            "outbound_action_id": str(delivery.outbound_action_id),
                            "attempt_number": delivery.attempt_number,
                            "status": delivery.status.value,
                            "certainty": delivery.certainty.value,
                            "error_category": delivery.error_category,
                        }
                        for delivery in deliveries
                    ],
                    "recovery_events": [
                        {
                            "id": str(recovery.id),
                            "outbound_action_id": str(recovery.outbound_action_id),
                            "event_type": recovery.event_type,
                        }
                        for recovery in recoveries
                    ],
                },
                **summary,
            }
    finally:
        await database.stop()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--telegram-update-id")
    parser.add_argument("--incoming-update-id", type=UUID)
    parser.add_argument("--conversation-id", type=UUID)
    parser.add_argument("--chat-id")
    args = parser.parse_args()
    result = await inspect_latest(
        Settings(),
        platform_update_id=args.telegram_update_id,
        incoming_update_id=args.incoming_update_id,
        conversation_id=args.conversation_id,
        platform_chat_id=args.chat_id,
    )
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
