"""PostgreSQL authority for private reminders and proactive check-ins."""

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.commands import command_response
from app.application.outbound import compile_outbound_actions
from app.application.response_plan import ResponsePlanCandidate
from app.application.scheduling import (
    DueWindow,
    due_window,
    in_quiet_hours,
    next_recurring_at,
    quiet_hours_end,
)
from app.domain.ambient import ParticipationTrigger
from app.domain.conversation import MembershipStatus
from app.domain.outbound import (
    DeliveryAttemptStatus,
    DeliveryCertainty,
    OutboundActionStatus,
)
from app.domain.persistence import ConversationStatus
from app.domain.planning import PlanReasonCode
from app.domain.scheduling import (
    MaterializationOutcome,
    MaterializationResult,
    OccurrenceClaim,
    OccurrenceStatus,
    RecurrenceKind,
    ScheduleCommandOutcome,
    ScheduleDefinition,
    ScheduleKind,
    ScheduleOperation,
    SchedulePreferences,
    ScheduleReason,
    ScheduleStatus,
    ScheduleView,
)
from app.infrastructure.database.models import (
    ConversationConfigurationRevisionModel,
    ConversationModel,
    OutboundActionModel,
    OutboundDeliveryAttemptModel,
    ParticipantModel,
    ParticipantSchedulePreferenceModel,
    PersonalityProfileVersionModel,
    ProactiveScheduleCommandReceiptModel,
    ProactiveScheduleModel,
    ProactiveScheduleOccurrenceModel,
    ResponsePlanModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.tenancy import conversation_authority


@dataclass(frozen=True, slots=True)
class ScheduleCommandResult:
    outcome: ScheduleCommandOutcome
    schedule_id: UUID | None = None
    public_id: str | None = None


class SqlAlchemySchedulingRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def preferences(
        self, conversation_id: UUID, participant_id: UUID
    ) -> SchedulePreferences:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(ParticipantSchedulePreferenceModel).where(
                    ParticipantSchedulePreferenceModel.conversation_id
                    == conversation_id,
                    ParticipantSchedulePreferenceModel.participant_id == participant_id,
                )
            )
            return _preferences(row)

    async def set_timezone(
        self,
        *,
        command_job_id: UUID,
        conversation_id: UUID,
        participant_id: UUID,
        timezone_name: str,
        now: datetime | None = None,
    ) -> ScheduleCommandResult:
        moment = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                replay = await _lock_and_replay(
                    session, command_job_id, conversation_id, participant_id
                )
                if replay is not None:
                    return replay
                preference = await _locked_preference(
                    session, conversation_id, participant_id
                )
                old = preference.timezone_name
                preference.timezone_name = timezone_name
                if old != timezone_name:
                    preference.revision += 1
                    schedules = list(
                        await session.scalars(
                            select(ProactiveScheduleModel)
                            .where(
                                ProactiveScheduleModel.conversation_id
                                == conversation_id,
                                ProactiveScheduleModel.creator_participant_id
                                == participant_id,
                                ProactiveScheduleModel.status == ScheduleStatus.ACTIVE,
                                ProactiveScheduleModel.recurrence
                                != RecurrenceKind.ONCE,
                            )
                            .with_for_update()
                        )
                    )
                    for schedule in schedules:
                        if (
                            schedule.local_time_minute is None
                            or schedule.weekday_mask is None
                            or schedule.starts_on is None
                        ):
                            raise ValueError("active schedule timing is redacted")
                        next_run = next_recurring_at(
                            after=moment,
                            zone_name=timezone_name,
                            local_time_minute=schedule.local_time_minute,
                            weekday_mask_value=schedule.weekday_mask,
                            starts_on=schedule.starts_on,
                            ends_at=schedule.ends_at,
                        )
                        schedule.timezone_name = timezone_name
                        schedule.next_run_at = next_run
                        schedule.version += 1
                        if next_run is None:
                            schedule.status = ScheduleStatus.COMPLETED
                            schedule.completed_at = moment
                outcome = (
                    ScheduleCommandOutcome.UNCHANGED
                    if old == timezone_name
                    else ScheduleCommandOutcome.UPDATED
                )
                await _receipt(
                    session,
                    command_job_id,
                    conversation_id,
                    participant_id,
                    ScheduleOperation.TIMEZONE_SET,
                    outcome,
                )
                return ScheduleCommandResult(outcome)

    async def set_quiet_hours(
        self,
        *,
        command_job_id: UUID,
        conversation_id: UUID,
        participant_id: UUID,
        enabled: bool,
        start_minute: int = 1320,
        end_minute: int = 480,
    ) -> ScheduleCommandResult:
        async with self._session_factory() as session:
            async with session.begin():
                replay = await _lock_and_replay(
                    session, command_job_id, conversation_id, participant_id
                )
                if replay is not None:
                    return replay
                preference = await _locked_preference(
                    session, conversation_id, participant_id
                )
                before = (
                    preference.quiet_hours_enabled,
                    preference.quiet_start_minute,
                    preference.quiet_end_minute,
                )
                after = (enabled, start_minute, end_minute)
                if before != after:
                    preference.quiet_hours_enabled = enabled
                    preference.quiet_start_minute = start_minute
                    preference.quiet_end_minute = end_minute
                    preference.revision += 1
                outcome = (
                    ScheduleCommandOutcome.UNCHANGED
                    if before == after
                    else ScheduleCommandOutcome.UPDATED
                )
                await _receipt(
                    session,
                    command_job_id,
                    conversation_id,
                    participant_id,
                    ScheduleOperation.QUIET_HOURS_SET,
                    outcome,
                )
                return ScheduleCommandResult(outcome)

    async def create_reminder(
        self,
        *,
        command_job_id: UUID,
        conversation_id: UUID,
        participant_id: UUID,
        definition: ScheduleDefinition,
        active_limit: int,
    ) -> ScheduleCommandResult:
        if definition.kind != ScheduleKind.REMINDER:
            raise ValueError("reminder definition required")
        async with self._session_factory() as session:
            async with session.begin():
                replay = await _lock_and_replay(
                    session, command_job_id, conversation_id, participant_id
                )
                if replay is not None:
                    return replay
                count = await session.scalar(
                    select(func.count())
                    .select_from(ProactiveScheduleModel)
                    .where(
                        ProactiveScheduleModel.conversation_id == conversation_id,
                        ProactiveScheduleModel.creator_participant_id == participant_id,
                        ProactiveScheduleModel.kind == ScheduleKind.REMINDER,
                        ProactiveScheduleModel.status == ScheduleStatus.ACTIVE,
                    )
                )
                if int(count or 0) >= active_limit:
                    await _receipt(
                        session,
                        command_job_id,
                        conversation_id,
                        participant_id,
                        ScheduleOperation.REMINDER_CREATE,
                        ScheduleCommandOutcome.LIMIT_REACHED,
                    )
                    return ScheduleCommandResult(ScheduleCommandOutcome.LIMIT_REACHED)
                schedule = _new_schedule(
                    command_job_id, conversation_id, participant_id, definition
                )
                session.add(schedule)
                await session.flush()
                await _receipt(
                    session,
                    command_job_id,
                    conversation_id,
                    participant_id,
                    ScheduleOperation.REMINDER_CREATE,
                    ScheduleCommandOutcome.CREATED,
                    schedule.id,
                )
                return ScheduleCommandResult(
                    ScheduleCommandOutcome.CREATED, schedule.id, schedule.public_id
                )

    async def enable_checkin(
        self,
        *,
        command_job_id: UUID,
        conversation_id: UUID,
        participant_id: UUID,
        definition: ScheduleDefinition,
    ) -> ScheduleCommandResult:
        if definition.kind != ScheduleKind.CHECK_IN:
            raise ValueError("check-in definition required")
        async with self._session_factory() as session:
            async with session.begin():
                replay = await _lock_and_replay(
                    session, command_job_id, conversation_id, participant_id
                )
                if replay is not None:
                    return replay
                current = await session.scalar(
                    select(ProactiveScheduleModel)
                    .where(
                        ProactiveScheduleModel.conversation_id == conversation_id,
                        ProactiveScheduleModel.creator_participant_id == participant_id,
                        ProactiveScheduleModel.kind == ScheduleKind.CHECK_IN,
                        ProactiveScheduleModel.status == ScheduleStatus.ACTIVE,
                    )
                    .with_for_update()
                )
                if current is None:
                    current = _new_schedule(
                        command_job_id, conversation_id, participant_id, definition
                    )
                    session.add(current)
                    await session.flush()
                    outcome = ScheduleCommandOutcome.CREATED
                else:
                    shape = (
                        current.recurrence,
                        current.timezone_name,
                        current.local_time_minute,
                        current.weekday_mask,
                    )
                    desired = (
                        definition.recurrence,
                        definition.timezone_name,
                        definition.local_time_minute,
                        definition.weekday_mask,
                    )
                    if shape == desired:
                        outcome = ScheduleCommandOutcome.UNCHANGED
                    else:
                        current.recurrence = definition.recurrence
                        current.timezone_name = definition.timezone_name
                        current.local_time_minute = definition.local_time_minute
                        current.weekday_mask = definition.weekday_mask
                        current.starts_on = definition.starts_on
                        current.one_time_at = None
                        current.next_run_at = definition.first_run_at
                        current.ends_at = definition.ends_at
                        current.version += 1
                        outcome = ScheduleCommandOutcome.UPDATED
                await _receipt(
                    session,
                    command_job_id,
                    conversation_id,
                    participant_id,
                    ScheduleOperation.CHECKINS_ENABLE,
                    outcome,
                    current.id,
                )
                return ScheduleCommandResult(outcome, current.id, current.public_id)

    async def disable_checkin(
        self,
        *,
        command_job_id: UUID,
        conversation_id: UUID,
        participant_id: UUID,
        now: datetime | None = None,
    ) -> ScheduleCommandResult:
        moment = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                replay = await _lock_and_replay(
                    session, command_job_id, conversation_id, participant_id
                )
                if replay is not None:
                    return replay
                schedule = await session.scalar(
                    select(ProactiveScheduleModel)
                    .where(
                        ProactiveScheduleModel.conversation_id == conversation_id,
                        ProactiveScheduleModel.creator_participant_id == participant_id,
                        ProactiveScheduleModel.kind == ScheduleKind.CHECK_IN,
                        ProactiveScheduleModel.status == ScheduleStatus.ACTIVE,
                    )
                    .with_for_update()
                )
                outcome = ScheduleCommandOutcome.UNCHANGED
                schedule_id = None
                if schedule is not None:
                    _cancel_schedule(schedule, moment)
                    await _cancel_pre_io(session, schedule.id, moment)
                    outcome = ScheduleCommandOutcome.CANCELLED
                    schedule_id = schedule.id
                await _receipt(
                    session,
                    command_job_id,
                    conversation_id,
                    participant_id,
                    ScheduleOperation.CHECKINS_DISABLE,
                    outcome,
                    schedule_id,
                )
                return ScheduleCommandResult(outcome, schedule_id)

    async def cancel_reminder(
        self,
        *,
        command_job_id: UUID,
        conversation_id: UUID,
        participant_id: UUID,
        public_id: str,
        now: datetime | None = None,
    ) -> ScheduleCommandResult:
        moment = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                replay = await _lock_and_replay(
                    session, command_job_id, conversation_id, participant_id
                )
                if replay is not None:
                    return replay
                schedule = await session.scalar(
                    select(ProactiveScheduleModel)
                    .where(
                        ProactiveScheduleModel.public_id == public_id,
                        ProactiveScheduleModel.conversation_id == conversation_id,
                        ProactiveScheduleModel.creator_participant_id == participant_id,
                        ProactiveScheduleModel.kind == ScheduleKind.REMINDER,
                        ProactiveScheduleModel.status.in_(
                            [ScheduleStatus.ACTIVE, ScheduleStatus.COMPLETED]
                        ),
                    )
                    .with_for_update()
                )
                if schedule is None:
                    outcome = ScheduleCommandOutcome.NOT_FOUND
                    schedule_id = None
                elif (
                    schedule.status == ScheduleStatus.COMPLETED
                    and not await session.scalar(
                        select(
                            select(ProactiveScheduleOccurrenceModel.id)
                            .where(
                                ProactiveScheduleOccurrenceModel.schedule_id
                                == schedule.id,
                                ProactiveScheduleOccurrenceModel.status.in_(
                                    [
                                        OccurrenceStatus.PENDING,
                                        OccurrenceStatus.LEASED,
                                        OccurrenceStatus.ENQUEUED,
                                    ]
                                ),
                            )
                            .exists()
                        )
                    )
                ):
                    outcome = ScheduleCommandOutcome.TOO_LATE
                    schedule_id = schedule.id
                else:
                    _cancel_schedule(schedule, moment)
                    await _cancel_pre_io(session, schedule.id, moment)
                    outcome = ScheduleCommandOutcome.CANCELLED
                    schedule_id = schedule.id
                await _receipt(
                    session,
                    command_job_id,
                    conversation_id,
                    participant_id,
                    ScheduleOperation.REMINDER_CANCEL,
                    outcome,
                    schedule_id,
                )
                return ScheduleCommandResult(outcome, schedule_id, public_id)

    async def list_active(
        self, conversation_id: UUID, participant_id: UUID, limit: int = 11
    ) -> list[ScheduleView]:
        async with self._session_factory() as session:
            rows = list(
                await session.scalars(
                    select(ProactiveScheduleModel)
                    .where(
                        ProactiveScheduleModel.conversation_id == conversation_id,
                        ProactiveScheduleModel.creator_participant_id == participant_id,
                        ProactiveScheduleModel.status == ScheduleStatus.ACTIVE,
                    )
                    .order_by(
                        ProactiveScheduleModel.next_run_at,
                        ProactiveScheduleModel.created_at,
                        ProactiveScheduleModel.id,
                    )
                    .limit(limit)
                )
            )
            return [_view(row) for row in rows]

    async def materialize_due(self, now: datetime, limit: int) -> MaterializationResult:
        """Create at most one latest occurrence per bounded due schedule."""

        async with self._session_factory() as session:
            async with session.begin():
                rows = list(
                    await session.scalars(
                        select(ProactiveScheduleModel)
                        .where(
                            ProactiveScheduleModel.status == ScheduleStatus.ACTIVE,
                            ProactiveScheduleModel.next_run_at.is_not(None),
                            ProactiveScheduleModel.next_run_at <= now,
                        )
                        .order_by(
                            ProactiveScheduleModel.next_run_at,
                            ProactiveScheduleModel.created_at,
                            ProactiveScheduleModel.id,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                created = 0
                events: list[tuple[ScheduleKind, MaterializationOutcome]] = []
                for schedule in rows:
                    if (
                        schedule.timezone_name is None
                        or schedule.local_time_minute is None
                        or schedule.weekday_mask is None
                        or schedule.starts_on is None
                    ):
                        raise ValueError("active schedule timing is redacted")
                    window: DueWindow | None
                    if schedule.recurrence == RecurrenceKind.ONCE:
                        if schedule.one_time_at is None:
                            raise ValueError(
                                "one-time schedule has no resolved instant"
                            )
                        window = DueWindow(
                            schedule.one_time_at,
                            schedule.starts_on,
                            None,
                        )
                    else:
                        window = due_window(
                            now=now,
                            zone_name=schedule.timezone_name,
                            local_time_minute=schedule.local_time_minute,
                            weekday_mask_value=schedule.weekday_mask,
                            starts_on=schedule.starts_on,
                            ends_at=schedule.ends_at,
                        )
                    if window is None:
                        schedule.status = ScheduleStatus.COMPLETED
                        schedule.next_run_at = None
                        schedule.completed_at = now
                        continue
                    existing = await session.scalar(
                        select(ProactiveScheduleOccurrenceModel.id).where(
                            ProactiveScheduleOccurrenceModel.schedule_id == schedule.id,
                            ProactiveScheduleOccurrenceModel.local_date
                            == window.latest_local_date,
                        )
                    )
                    if existing is None:
                        privacy_revision = await session.scalar(
                            select(ConversationModel.memory_privacy_revision).where(
                                ConversationModel.id == schedule.conversation_id
                            )
                        )
                        stale_after = timedelta(
                            hours=6 if schedule.kind == ScheduleKind.REMINDER else 24
                        )
                        stale = now - window.latest_due_at > stale_after
                        session.add(
                            ProactiveScheduleOccurrenceModel(
                                schedule_id=schedule.id,
                                conversation_id=schedule.conversation_id,
                                participant_id=schedule.creator_participant_id,
                                scheduled_for=window.latest_due_at,
                                local_date=window.latest_local_date,
                                status=(
                                    OccurrenceStatus.SKIPPED
                                    if stale
                                    else OccurrenceStatus.PENDING
                                ),
                                reason_code=(
                                    ScheduleReason.STALE
                                    if stale
                                    else ScheduleReason.NONE
                                ),
                                available_at=now,
                                schedule_version=schedule.version,
                                privacy_revision=int(privacy_revision or 0),
                                completed_at=now if stale else None,
                            )
                        )
                        created += 1
                        events.append(
                            (
                                schedule.kind,
                                MaterializationOutcome.STALE
                                if stale
                                else MaterializationOutcome.MATERIALIZED,
                            )
                        )
                    if schedule.recurrence == RecurrenceKind.ONCE:
                        schedule.status = ScheduleStatus.COMPLETED
                        schedule.next_run_at = None
                        schedule.completed_at = now
                    else:
                        schedule.next_run_at = window.next_run_at
                        if window.next_run_at is None:
                            schedule.status = ScheduleStatus.COMPLETED
                            schedule.completed_at = now
                return MaterializationResult(created, tuple(events))

    async def claim(
        self, owner: str, now: datetime, limit: int, lease_seconds: int
    ) -> list[OccurrenceClaim]:
        async with self._session_factory() as session:
            async with session.begin():
                rows = list(
                    await session.scalars(
                        select(ProactiveScheduleOccurrenceModel)
                        .where(
                            or_(
                                (
                                    ProactiveScheduleOccurrenceModel.status
                                    == OccurrenceStatus.PENDING
                                )
                                & (
                                    ProactiveScheduleOccurrenceModel.available_at <= now
                                ),
                                (
                                    ProactiveScheduleOccurrenceModel.status
                                    == OccurrenceStatus.LEASED
                                )
                                & (
                                    ProactiveScheduleOccurrenceModel.lease_expires_at
                                    < now
                                ),
                            )
                        )
                        .order_by(
                            ProactiveScheduleOccurrenceModel.available_at,
                            ProactiveScheduleOccurrenceModel.scheduled_for,
                            ProactiveScheduleOccurrenceModel.id,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                claims: list[OccurrenceClaim] = []
                for row in rows:
                    token = uuid4()
                    row.status = OccurrenceStatus.LEASED
                    row.lease_owner = owner
                    row.lease_token = token
                    row.lease_expires_at = now + timedelta(seconds=lease_seconds)
                    row.attempt_count += 1
                    schedule = await session.get(
                        ProactiveScheduleModel, row.schedule_id
                    )
                    participant = await session.get(
                        ParticipantModel, row.participant_id
                    )
                    if schedule is None or participant is None:
                        continue
                    if row.scheduled_for is None or row.local_date is None:
                        raise ValueError("claimable occurrence timing is redacted")
                    conversation = await session.get(
                        ConversationModel, row.conversation_id
                    )
                    revision = (
                        await session.get(
                            ConversationConfigurationRevisionModel,
                            conversation.current_configuration_revision_id,
                        )
                        if conversation is not None
                        and conversation.current_configuration_revision_id is not None
                        else None
                    )
                    profile = (
                        await session.get(
                            PersonalityProfileVersionModel,
                            revision.personality_profile_version_id,
                        )
                        if revision is not None
                        else None
                    )
                    language = (
                        "en"
                        if profile is not None and profile.primary_language == "en"
                        else "vi"
                    )
                    claims.append(
                        OccurrenceClaim(
                            row.id,
                            schedule.id,
                            row.conversation_id,
                            row.participant_id,
                            schedule.kind,
                            schedule.reminder_text,
                            row.scheduled_for,
                            row.local_date,
                            row.attempt_count,
                            token,
                            row.schedule_version,
                            row.privacy_revision,
                            language,
                        )
                    )
                return claims

    async def backlog_counts(self, limit: int) -> dict[tuple[str, str], int]:
        """Return a capped signal without scanning an unbounded occurrence set."""

        counts: dict[tuple[str, str], int] = {}
        async with self._session_factory() as session:
            for kind in (ScheduleKind.REMINDER, ScheduleKind.CHECK_IN):
                for status in (OccurrenceStatus.PENDING, OccurrenceStatus.LEASED):
                    bounded = (
                        select(ProactiveScheduleOccurrenceModel.id)
                        .join(
                            ProactiveScheduleModel,
                            ProactiveScheduleModel.id
                            == ProactiveScheduleOccurrenceModel.schedule_id,
                        )
                        .where(
                            ProactiveScheduleModel.kind == kind,
                            ProactiveScheduleOccurrenceModel.status == status,
                        )
                        .order_by(
                            ProactiveScheduleOccurrenceModel.available_at,
                            ProactiveScheduleOccurrenceModel.id,
                        )
                        .limit(limit + 1)
                        .subquery()
                    )
                    count = await session.scalar(
                        select(func.count()).select_from(bounded)
                    )
                    counts[(kind.value, status.value)] = int(count or 0)
        return counts

    async def enqueue_claim(
        self, claim: OccurrenceClaim, owner: str, now: datetime
    ) -> str:
        """Fence a claim, apply no-I/O policy, and create the normal outbox action."""

        async with self._session_factory() as session:
            async with session.begin():
                occurrence = await session.get(
                    ProactiveScheduleOccurrenceModel,
                    claim.occurrence_id,
                    with_for_update=True,
                )
                if not _owns(occurrence, claim, owner, now):
                    return "stale_lease"
                assert occurrence is not None
                schedule = await session.get(
                    ProactiveScheduleModel, occurrence.schedule_id, with_for_update=True
                )
                conversation = await session.get(
                    ConversationModel, occurrence.conversation_id
                )
                participant = await session.get(
                    ParticipantModel, occurrence.participant_id
                )
                if (
                    schedule is None
                    or conversation is None
                    or participant is None
                    or schedule.status
                    not in {ScheduleStatus.ACTIVE, ScheduleStatus.COMPLETED}
                    or schedule.version != occurrence.schedule_version
                ):
                    _finish_occurrence(
                        occurrence,
                        OccurrenceStatus.SKIPPED,
                        ScheduleReason.CANCELLED,
                        now,
                    )
                    return "cancelled"
                authority = await conversation_authority(
                    session, occurrence.conversation_id
                )
                if authority is None or not authority[1].permits_external_io:
                    _finish_occurrence(
                        occurrence,
                        OccurrenceStatus.SKIPPED,
                        ScheduleReason.PAUSED,
                        now,
                    )
                    return "paused"
                if (
                    conversation.status != ConversationStatus.ACTIVE
                    or conversation.conversation_type.value != "private"
                    or participant.conversation_id != conversation.id
                    or participant.membership_status != MembershipStatus.MEMBER
                ):
                    _finish_occurrence(
                        occurrence,
                        OccurrenceStatus.SKIPPED,
                        ScheduleReason.MEMBERSHIP,
                        now,
                    )
                    return "membership"
                if (
                    participant.privacy_deleted_at is not None
                    or conversation.memory_privacy_revision != claim.privacy_revision
                ):
                    _finish_occurrence(
                        occurrence,
                        OccurrenceStatus.SKIPPED,
                        ScheduleReason.PRIVACY,
                        now,
                    )
                    return "privacy"
                preferences = _preferences(
                    await session.scalar(
                        select(ParticipantSchedulePreferenceModel).where(
                            ParticipantSchedulePreferenceModel.participant_id
                            == participant.id
                        )
                    )
                )
                if schedule.kind == ScheduleKind.CHECK_IN:
                    if participant.protected_at is not None:
                        _finish_occurrence(
                            occurrence,
                            OccurrenceStatus.SKIPPED,
                            ScheduleReason.PAUSED,
                            now,
                        )
                        return "paused"
                    if occurrence.scheduled_for is None:
                        raise ValueError("enqueued occurrence timing is redacted")
                    if in_quiet_hours(now, preferences):
                        end = quiet_hours_end(now, preferences)
                        if end - occurrence.scheduled_for <= timedelta(hours=24):
                            occurrence.status = OccurrenceStatus.PENDING
                            occurrence.available_at = end
                            occurrence.reason_code = ScheduleReason.QUIET_HOURS
                            _clear_lease(occurrence)
                            return "deferred"
                        _finish_occurrence(
                            occurrence,
                            OccurrenceStatus.SKIPPED,
                            ScheduleReason.STALE,
                            now,
                        )
                        return "stale"
                    if (
                        participant.last_seen_at is not None
                        and now - participant.last_seen_at < timedelta(hours=24)
                    ):
                        _finish_occurrence(
                            occurrence,
                            OccurrenceStatus.SKIPPED,
                            ScheduleReason.RECENT_ACTIVITY,
                            now,
                        )
                        return "recent_activity"
                text = (
                    command_response(
                        "schedule_reminder",
                        language=claim.language,
                        detail=schedule.reminder_text,
                    )
                    if schedule.kind == ScheduleKind.REMINDER
                    else command_response("schedule_checkin", language=claim.language)
                )
                candidate = ResponsePlanCandidate(
                    should_respond=True,
                    reason_code=PlanReasonCode.ACKNOWLEDGEMENT,
                    text=text,
                    confidence=1.0,
                    language=claim.language,
                )
                plan = ResponsePlanModel(
                    schedule_occurrence_id=occurrence.id,
                    should_respond=True,
                    reason_code=candidate.reason_code,
                    text=candidate.text,
                    reply_to_message_id=None,
                    mention_participant_ids=[],
                    sticker_intent=None,
                    confidence=1.0,
                    language=claim.language,
                    prompt_version="proactive-schedule-v1",
                    schema_version="response-plan-v2",
                )
                session.add(plan)
                await session.flush()
                for action in compile_outbound_actions(plan.id, candidate):
                    session.add(
                        OutboundActionModel(
                            response_plan_id=plan.id,
                            conversation_id=conversation.id,
                            sequence_number=action.sequence_number,
                            sequence_count=action.sequence_count,
                            idempotency_key=action.idempotency_key,
                            kind=action.kind,
                            origin=ParticipationTrigger.SCHEDULED,
                            status=OutboundActionStatus.PENDING,
                            available_at=now,
                            reply_to_message_id=None,
                            message_thread_id=None,
                            text=action.text,
                            mention_participant_ids=[],
                            sticker_intent=None,
                        )
                    )
                occurrence.status = OccurrenceStatus.ENQUEUED
                occurrence.reason_code = ScheduleReason.NONE
                occurrence.completed_at = now
                _clear_lease(occurrence)
                return "enqueued"


async def _lock_and_replay(
    session: AsyncSession,
    command_job_id: UUID,
    conversation_id: UUID,
    participant_id: UUID,
) -> ScheduleCommandResult | None:
    job = await session.scalar(
        select(TelegramCommandJobModel)
        .where(
            TelegramCommandJobModel.id == command_job_id,
            TelegramCommandJobModel.conversation_id == conversation_id,
            TelegramCommandJobModel.participant_id == participant_id,
        )
        .with_for_update()
    )
    if job is None:
        raise ValueError("command scope is invalid")
    participant = await session.scalar(
        select(ParticipantModel)
        .where(
            ParticipantModel.id == participant_id,
            ParticipantModel.conversation_id == conversation_id,
        )
        .with_for_update()
    )
    if participant is None:
        raise ValueError("participant scope is invalid")
    conversation = await session.get(ConversationModel, conversation_id)
    if (
        conversation is None
        or conversation.status != ConversationStatus.ACTIVE
        or conversation.conversation_type.value != "private"
    ):
        raise ValueError("private active conversation scope is required")
    receipt = await session.scalar(
        select(ProactiveScheduleCommandReceiptModel).where(
            ProactiveScheduleCommandReceiptModel.command_job_id == command_job_id
        )
    )
    if receipt is None:
        return None
    public_id = None
    if receipt.schedule_id is not None:
        public_id = await session.scalar(
            select(ProactiveScheduleModel.public_id).where(
                ProactiveScheduleModel.id == receipt.schedule_id
            )
        )
    return ScheduleCommandResult(receipt.outcome, receipt.schedule_id, public_id)


async def _locked_preference(
    session: AsyncSession, conversation_id: UUID, participant_id: UUID
) -> ParticipantSchedulePreferenceModel:
    row = await session.scalar(
        select(ParticipantSchedulePreferenceModel)
        .where(
            ParticipantSchedulePreferenceModel.conversation_id == conversation_id,
            ParticipantSchedulePreferenceModel.participant_id == participant_id,
        )
        .with_for_update()
    )
    if row is None:
        row = ParticipantSchedulePreferenceModel(
            conversation_id=conversation_id,
            participant_id=participant_id,
            timezone_name=None,
        )
        session.add(row)
        await session.flush()
    return row


async def _receipt(
    session: AsyncSession,
    command_job_id: UUID,
    conversation_id: UUID,
    participant_id: UUID,
    operation: ScheduleOperation,
    outcome: ScheduleCommandOutcome,
    schedule_id: UUID | None = None,
) -> None:
    session.add(
        ProactiveScheduleCommandReceiptModel(
            command_job_id=command_job_id,
            conversation_id=conversation_id,
            participant_id=participant_id,
            schedule_id=schedule_id,
            operation=operation,
            outcome=outcome,
        )
    )


def _new_schedule(
    command_job_id: UUID,
    conversation_id: UUID,
    participant_id: UUID,
    definition: ScheduleDefinition,
) -> ProactiveScheduleModel:
    identifier = uuid4()
    public_id = base64.b32encode(identifier.bytes).decode("ascii")[:12]
    return ProactiveScheduleModel(
        id=identifier,
        public_id=public_id,
        conversation_id=conversation_id,
        creator_participant_id=participant_id,
        source_command_job_id=command_job_id,
        kind=definition.kind,
        status=ScheduleStatus.ACTIVE,
        recurrence=definition.recurrence,
        timezone_name=definition.timezone_name,
        local_time_minute=definition.local_time_minute,
        weekday_mask=definition.weekday_mask,
        starts_on=definition.starts_on,
        one_time_at=(
            definition.first_run_at
            if definition.recurrence == RecurrenceKind.ONCE
            else None
        ),
        next_run_at=definition.first_run_at,
        ends_at=definition.ends_at,
        reminder_text=definition.reminder_text,
        version=1,
    )


def _preferences(
    row: ParticipantSchedulePreferenceModel | None,
) -> SchedulePreferences:
    if row is None:
        return SchedulePreferences(None, True, 1320, 480, 1)
    return SchedulePreferences(
        row.timezone_name,
        row.quiet_hours_enabled,
        row.quiet_start_minute,
        row.quiet_end_minute,
        row.revision,
    )


def _view(row: ProactiveScheduleModel) -> ScheduleView:
    if (
        row.timezone_name is None
        or row.local_time_minute is None
        or row.weekday_mask is None
    ):
        raise ValueError("active schedule timing is redacted")
    return ScheduleView(
        row.public_id,
        row.kind,
        row.recurrence,
        row.timezone_name,
        row.local_time_minute,
        row.weekday_mask,
        row.next_run_at,
        row.ends_at,
        row.reminder_text,
    )


def _cancel_schedule(schedule: ProactiveScheduleModel, now: datetime) -> None:
    schedule.status = ScheduleStatus.CANCELLED
    schedule.next_run_at = None
    schedule.cancelled_at = now
    schedule.version += 1


async def _cancel_pre_io(
    session: AsyncSession, schedule_id: UUID, now: datetime
) -> None:
    claimed = list(
        await session.scalars(
            select(ProactiveScheduleOccurrenceModel)
            .where(
                ProactiveScheduleOccurrenceModel.schedule_id == schedule_id,
                ProactiveScheduleOccurrenceModel.status.in_(
                    [OccurrenceStatus.PENDING, OccurrenceStatus.LEASED]
                ),
            )
            .with_for_update()
        )
    )
    for occurrence in claimed:
        _finish_occurrence(
            occurrence, OccurrenceStatus.SKIPPED, ScheduleReason.CANCELLED, now
        )
    enqueued_ids = list(
        await session.scalars(
            select(ProactiveScheduleOccurrenceModel.id).where(
                ProactiveScheduleOccurrenceModel.schedule_id == schedule_id,
                ProactiveScheduleOccurrenceModel.status == OccurrenceStatus.ENQUEUED,
            )
        )
    )
    for occurrence_id in enqueued_ids:
        plan = await session.scalar(
            select(ResponsePlanModel).where(
                ResponsePlanModel.schedule_occurrence_id == occurrence_id
            )
        )
        actions = (
            list(
                await session.scalars(
                    select(OutboundActionModel)
                    .where(
                        OutboundActionModel.response_plan_id == plan.id,
                        OutboundActionModel.status.in_(
                            [OutboundActionStatus.PENDING, OutboundActionStatus.LEASED]
                        ),
                    )
                    .with_for_update()
                )
            )
            if plan is not None
            else []
        )
        enqueued_occurrence = await session.get(
            ProactiveScheduleOccurrenceModel, occurrence_id, with_for_update=True
        )
        if (
            enqueued_occurrence is None
            or enqueued_occurrence.status != OccurrenceStatus.ENQUEUED
        ):
            continue
        external_started = False
        for action in actions:
            attempt = (
                await session.scalar(
                    select(OutboundDeliveryAttemptModel)
                    .where(
                        OutboundDeliveryAttemptModel.outbound_action_id == action.id,
                        OutboundDeliveryAttemptModel.attempt_number
                        == action.attempt_count,
                    )
                    .with_for_update()
                )
                if action.status == OutboundActionStatus.LEASED
                else None
            )
            if attempt is not None and attempt.external_started_at is not None:
                external_started = True
                continue
            if attempt is not None:
                attempt.status = DeliveryAttemptStatus.REJECTED
                attempt.certainty = DeliveryCertainty.NOT_SENT
                attempt.error_category = "scheduled_cancelled"
                attempt.finished_at = now
            action.status = OutboundActionStatus.SKIPPED
            action.lease_owner = None
            action.lease_expires_at = None
            action.completed_at = now
            action.last_error_category = "scheduled_cancelled"
            action.last_error_at = now
        if not external_started:
            _finish_occurrence(
                enqueued_occurrence,
                OccurrenceStatus.SKIPPED,
                ScheduleReason.CANCELLED,
                now,
            )


def _owns(
    occurrence: ProactiveScheduleOccurrenceModel | None,
    claim: OccurrenceClaim,
    owner: str,
    now: datetime,
) -> bool:
    return bool(
        occurrence is not None
        and occurrence.status == OccurrenceStatus.LEASED
        and occurrence.lease_owner == owner
        and occurrence.lease_token == claim.lease_token
        and occurrence.attempt_count == claim.attempt_count
        and occurrence.schedule_version == claim.schedule_version
        and occurrence.privacy_revision == claim.privacy_revision
        and occurrence.lease_expires_at is not None
        and occurrence.lease_expires_at >= now
    )


def _clear_lease(occurrence: ProactiveScheduleOccurrenceModel) -> None:
    occurrence.lease_owner = None
    occurrence.lease_token = None
    occurrence.lease_expires_at = None


def _finish_occurrence(
    occurrence: ProactiveScheduleOccurrenceModel,
    status: OccurrenceStatus,
    reason: ScheduleReason,
    now: datetime,
) -> None:
    occurrence.status = status
    occurrence.reason_code = reason
    occurrence.completed_at = now
    _clear_lease(occurrence)
