"""Live lease, admission, and session-fencing proof for SPEC-035."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from app.application.model_provider import (
    ProviderCapabilities,
    ProviderError,
    ProviderResult,
    ProviderUsage,
)
from app.application.ports.platform import SendChatActionRequest
from app.application.presence import TypingPresenceController
from app.core.config import Settings
from app.domain.persistence import (
    AssistantStatus,
    ConversationStatus,
    PlatformConnectionStatus,
)
from app.domain.planning import PlanningJobStatus, ProviderErrorCategory, ProviderId
from app.domain.recovery import RecoveryDisposition, RecoveryKind, RecoveryReason
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationModel,
    MessageModel,
    OperationalRecoveryItemModel,
    PlatformConnectionModel,
    ProviderBudgetRevisionModel,
    ResponsePlanningJobModel,
)
from app.infrastructure.database.personality import ensure_conversation_configuration
from app.infrastructure.database.planning import SqlAlchemyPlanningRepository
from app.runtime.response_planning_worker import consume_once

from .test_provider_governance_schema import _AllowedRateLimiter, _seed

pytestmark = [pytest.mark.integration, pytest.mark.telegram_presence_integration]


class _Concurrency:
    async def acquire(self, provider: ProviderId) -> SimpleNamespace:
        return SimpleNamespace(provider=provider, token="synthetic")

    async def release(self, lease: object) -> None:
        del lease


async def _prepare_job(database: Database) -> tuple[object, object]:
    job_id, _ = await _seed(database)
    now = datetime.now(UTC)
    async with database.session_factory() as session, session.begin():
        await session.execute(
            update(ProviderBudgetRevisionModel).values(amount=1_000_000)
        )
        job = await session.get(ResponsePlanningJobModel, job_id)
        assert job is not None
        conversation = await session.get(ConversationModel, job.conversation_id)
        assert conversation is not None
        connection = await session.get(
            PlatformConnectionModel, conversation.platform_connection_id
        )
        assert connection is not None
        assistant = await session.get(AssistantModel, connection.assistant_id)
        assert assistant is not None
        configuration = await ensure_conversation_configuration(
            session, assistant, conversation
        )
        message = await session.get(MessageModel, job.message_id)
        assert message is not None
        message.eligible = True
        message.platform_sent_at = now
        message.platform_thread_id = "42"
        job.configuration_revision_id = configuration.id
        job.personality_profile_version_id = (
            configuration.personality_profile_version_id
        )
        job.status = PlanningJobStatus.PENDING
        job.attempt_count = 0
        job.lease_owner = None
        job.lease_expires_at = None
        job.available_at = now
        return job.id, conversation.id


def test_presence_lease_fence_rejects_stale_inactive_and_recovered_work() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            job_id, conversation_id = await _prepare_job(database)
            repository = SqlAlchemyPlanningRepository(database.session_factory)
            claimed = await repository.claim("presence-fence", 1, 60)
            assert [job.id for job in claimed] == [job_id]
            attempt = claimed[0].attempt_count
            assert await repository.presence_authorized(
                job_id, "presence-fence", attempt
            )
            assert not await repository.presence_authorized(
                job_id, "wrong-owner", attempt
            )
            assert not await repository.presence_authorized(
                job_id, "presence-fence", attempt + 1
            )

            async with database.session_factory() as session, session.begin():
                job = await session.get(ResponsePlanningJobModel, job_id)
                assert job is not None
                job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            assert not await repository.presence_authorized(
                job_id, "presence-fence", attempt
            )

            async with database.session_factory() as session, session.begin():
                job = await session.get(ResponsePlanningJobModel, job_id)
                conversation = await session.get(ConversationModel, conversation_id)
                assert job is not None and conversation is not None
                job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=60)
                conversation.status = ConversationStatus.PAUSED
            assert not await repository.presence_authorized(
                job_id, "presence-fence", attempt
            )

            async with database.session_factory() as session, session.begin():
                conversation = await session.get(ConversationModel, conversation_id)
                assert conversation is not None
                conversation.status = ConversationStatus.ACTIVE
                connection = await session.get(
                    PlatformConnectionModel, conversation.platform_connection_id
                )
                assert connection is not None
                assistant = await session.get(AssistantModel, connection.assistant_id)
                assert assistant is not None
                assistant.status = AssistantStatus.DISABLED
            assert not await repository.presence_authorized(
                job_id, "presence-fence", attempt
            )
            raw_calls = 0

            async def raw_send() -> None:
                nonlocal raw_calls
                raw_calls += 1

            async def current_fence() -> bool:
                return await repository.presence_authorized(
                    job_id, "presence-fence", attempt
                )

            disabled_assistant = TypingPresenceController(raw_send, current_fence)
            await disabled_assistant.start()
            await disabled_assistant.stop()
            assert raw_calls == 0

            async with database.session_factory() as session, session.begin():
                conversation = await session.get(ConversationModel, conversation_id)
                assert conversation is not None
                connection = await session.get(
                    PlatformConnectionModel, conversation.platform_connection_id
                )
                assert connection is not None
                assistant = await session.get(AssistantModel, connection.assistant_id)
                assert assistant is not None
                assistant.status = AssistantStatus.ACTIVE
                connection.status = PlatformConnectionStatus.DISABLED
            assert not await repository.presence_authorized(
                job_id, "presence-fence", attempt
            )
            disabled_connection = TypingPresenceController(raw_send, current_fence)
            await disabled_connection.start()
            await disabled_connection.stop()
            assert raw_calls == 0

            async with database.session_factory() as session, session.begin():
                conversation = await session.get(ConversationModel, conversation_id)
                assert conversation is not None
                connection = await session.get(
                    PlatformConnectionModel, conversation.platform_connection_id
                )
                assert connection is not None
                connection.status = PlatformConnectionStatus.ACTIVE
                session.add(
                    OperationalRecoveryItemModel(
                        work_kind=RecoveryKind.PLANNING,
                        work_id=job_id,
                        disposition=RecoveryDisposition.DEAD_LETTER,
                        reason=RecoveryReason.OPERATOR_REPLAY,
                        replayed_at=datetime.now(UTC),
                    )
                )
            assert not await repository.presence_authorized(
                job_id, "presence-fence", attempt
            )
            recovered_job = TypingPresenceController(raw_send, current_fence)
            await recovered_job.start()
            await recovered_job.stop()
            assert raw_calls == 0
            assert database.engine.pool.checkedout() == 0
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_governed_worker_presence_is_after_admission_and_outside_db() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            job_id, _ = await _prepare_job(database)
            events: list[str] = []
            presence_requests: list[SendChatActionRequest] = []

            class Presence:
                async def send_chat_action(
                    self, request: SendChatActionRequest
                ) -> None:
                    assert database.engine.pool.checkedout() == 0
                    events.append("presence")
                    presence_requests.append(request)

            class Generator:
                provider_id = ProviderId.OPENAI
                model = "spec026-model"
                capabilities = ProviderCapabilities(
                    True, True, "max_tokens", True, True
                )

                async def generate(self, request: object) -> ProviderResult:
                    del request
                    events.append("provider")
                    return ProviderResult(
                        self.provider_id,
                        self.model,
                        '{"should_respond":true,"reason_code":"answer","text":"Hello","confidence":1.0}',
                        None,
                        ProviderUsage(None, None, None),
                        timedelta(),
                        "stop",
                    )

                async def aclose(self) -> None:
                    return None

            settings = Settings(
                _env_file=None,
                environment="test",
                telegram_enabled=True,
                telegram_bot_token="synthetic-token",
                llm_enabled=True,
                llm_openai_model="spec026-model",
                llm_openai_api_key="synthetic",
                llm_max_output_tokens=300,
                provider_governance_mode="enforce",
                provider_governance_worker_enabled=True,
                control_plane_enabled=True,
                control_plane_jwt_secret="x" * 32,
                control_plane_jwt_issuer="issuer",
                control_plane_jwt_audience="audience",
            )
            assert (
                await consume_once(
                    settings,
                    database,
                    owner="presence-worker",
                    primary_provider=Generator(),
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_Concurrency(),
                    presence_adapter=Presence(),
                )
                == 1
            )
            assert events == ["presence", "provider"]
            assert presence_requests == [
                SendChatActionRequest("spec026-conversation", "42")
            ]
            async with database.session_factory() as session:
                job = await session.get(ResponsePlanningJobModel, job_id)
                assert job is not None
                assert job.status in {
                    PlanningJobStatus.COMPLETED,
                    PlanningJobStatus.NO_RESPONSE,
                }
            assert database.engine.pool.checkedout() == 0
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("provider_outcome", ["success", "error", "cancelled"])
def test_heartbeat_session_boundary_and_terminal_cleanup(
    provider_outcome: str,
) -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            await _prepare_job(database)
            sleep_started = asyncio.Event()
            wake_refresh = asyncio.Event()
            provider_started = asyncio.Event()
            release_provider = asyncio.Event()
            second_presence = asyncio.Event()
            calls: list[SendChatActionRequest] = []
            now = 0.0

            async def controlled_sleep(seconds: float) -> None:
                assert seconds == 4.0
                sleep_started.set()
                await wake_refresh.wait()

            def clock() -> float:
                return now

            class Presence:
                async def send_chat_action(
                    self, request: SendChatActionRequest
                ) -> None:
                    assert database.engine.pool.checkedout() == 0
                    calls.append(request)
                    if len(calls) == 2:
                        second_presence.set()

            class Generator:
                provider_id = ProviderId.OPENAI
                model = "spec026-model"
                capabilities = ProviderCapabilities(
                    True, True, "max_tokens", True, True
                )

                async def generate(self, request: object) -> ProviderResult:
                    del request
                    provider_started.set()
                    await release_provider.wait()
                    if provider_outcome == "error":
                        raise ProviderError(
                            ProviderErrorCategory.AUTHENTICATION,
                            self.provider_id,
                            self.model,
                            False,
                            "generate",
                            "synthetic provider failure",
                        )
                    return ProviderResult(
                        self.provider_id,
                        self.model,
                        '{"should_respond":true,"reason_code":"answer","text":"Hello","confidence":1.0}',
                        None,
                        ProviderUsage(None, None, None),
                        timedelta(),
                        "stop",
                    )

                async def aclose(self) -> None:
                    return None

            def factory(send, fence, telemetry):  # type: ignore[no-untyped-def]
                return TypingPresenceController(
                    send,
                    fence,
                    telemetry,
                    clock=clock,
                    sleep=controlled_sleep,
                    max_calls=2,
                )

            settings = Settings(
                _env_file=None,
                environment="test",
                telegram_enabled=True,
                telegram_bot_token="synthetic-token",
                llm_enabled=True,
                llm_openai_model="spec026-model",
                llm_openai_api_key="synthetic",
                llm_max_output_tokens=300,
                provider_governance_mode="legacy",
                provider_governance_worker_enabled=False,
                control_plane_enabled=True,
                control_plane_jwt_secret="x" * 32,
                control_plane_jwt_issuer="issuer",
                control_plane_jwt_audience="audience",
            )
            worker = asyncio.create_task(
                consume_once(
                    settings,
                    database,
                    owner="presence-heartbeat",
                    primary_provider=Generator(),
                    rate_limiter=_AllowedRateLimiter(),
                    concurrency_limiter=_Concurrency(),
                    presence_adapter=Presence(),
                    presence_controller_factory=factory,
                )
            )
            await provider_started.wait()
            await sleep_started.wait()
            if provider_outcome == "cancelled":
                worker.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await worker
                assert len(calls) == 1
            else:
                now = 4.0
                wake_refresh.set()
                await second_presence.wait()
                release_provider.set()
                assert await worker == 1
                assert len(calls) == 2
            assert database.engine.pool.checkedout() == 0
            assert not any(
                task.get_name() == "telegram-typing-presence" and not task.done()
                for task in asyncio.all_tasks()
            )
        finally:
            await database.stop()

    asyncio.run(scenario())
