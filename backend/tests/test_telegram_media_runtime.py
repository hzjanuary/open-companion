import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from app.application.model_provider import (
    ProviderCapabilities,
    ProviderError,
    ProviderUsage,
    TranscriptionResult,
)
from app.application.ports.provider_governance import ProviderWorkSource
from app.core.config import Settings
from app.domain.media import (
    EphemeralMedia,
    MediaAttachment,
    MediaFailureReason,
    MediaKind,
    MediaStatus,
)
from app.domain.planning import ProviderErrorCategory, ProviderId
from app.infrastructure.database.media import MediaWork
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.runtime.telegram_media import prepare_media

from .test_media_provider_governance import transcription_metadata
from .test_provider_governance import (
    _Concurrency,
    _Limiter,
    _Repository,
    _route,
)


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "complete_replay",
        "disabled",
        "wrong_connection",
        "no_route",
        "budget",
        "timeout",
        "privacy",
    ],
)
def test_preparation_is_bounded_governed_and_replay_safe(case):
    events = []
    connection = uuid4()
    job_id = uuid4()
    work = MediaWork(
        uuid4(),
        uuid4(),
        MediaStatus.COMPLETE if case == "complete_replay" else MediaStatus.PREPARING,
        MediaAttachment(
            MediaKind.VOICE, "file", "unique", "audio/ogg", duration_seconds=10
        ),
        "caption",
        uuid4(),
    )

    class Repository:
        async def claim(self, *args):
            events.append("claim")
            return work

        async def preflight(self, *args):
            events.append("fence")
            return True

        async def finish_transcript(self, *args):
            events.append("persist_transcript")
            assert args[-1] == "derived"
            return True

        async def fail(self, *args):
            events.append("failed")
            return True

    class Governance(_Repository):
        async def planning_source(self, source):
            return ProviderWorkSource(
                "planning:test", planning_job_id=job_id, execution_owner="worker"
            )

        async def resolve_routes(self, source, workload, requirements):
            events.append("route")
            assert workload.value == "transcription"
            assert requirements["speech_to_text"] is True
            return (
                ()
                if case == "no_route"
                else (
                    replace(
                        _route(transcription_metadata()),
                        provider_id=ProviderId.GROQ,
                        adapter_key=ProviderId.GROQ,
                    ),
                )
            )

    class Downloader:
        async def download_media(self, attachment, before_io=None):
            assert before_io is not None
            if not await before_io():
                from app.application.ports.media import MediaError

                raise MediaError(MediaFailureReason.PRIVACY_CHANGED)
            events.append("download")
            return EphemeralMedia(MediaKind.VOICE, "audio/ogg", b"ephemeral")

    class Provider:
        provider_id = ProviderId.GROQ
        model = "model"
        capabilities = ProviderCapabilities(False, False, None, False, True)

        async def transcribe(self, request):
            events.append("transcribe")
            if case == "timeout":
                raise ProviderError(
                    ProviderErrorCategory.TIMEOUT,
                    self.provider_id,
                    self.model,
                    False,
                    "transcribe",
                    "timeout",
                )
            return TranscriptionResult(
                self.provider_id,
                self.model,
                "derived",
                None,
                ProviderUsage(None, None, None),
                timedelta(),
            )

        async def aclose(self):
            pass

    async def safety():
        events.append("safety")
        return case != "privacy"

    settings = Settings(
        telegram_media_enabled=case != "disabled",
        telegram_enabled=True,
        telegram_bot_token="synthetic-token",
        telegram_platform_connection_id=uuid4()
        if case == "wrong_connection"
        else connection,
        provider_governance_mode="enforce",
        provider_governance_worker_enabled=True,
        control_plane_enabled=True,
        control_plane_jwt_secret="x" * 32,
        control_plane_jwt_issuer="issuer",
        control_plane_jwt_audience="audience",
    )
    result = asyncio.run(
        prepare_media(
            settings=settings,
            repository=Repository(),
            governance=Governance(events, case != "budget"),
            job_id=job_id,
            owner="worker",
            attempt=1,
            connection_id=connection,
            rate_limiter=_Limiter(events),
            concurrency_limiter=_Concurrency(events, provider=ProviderId.GROQ),
            telemetry=InMemoryMetricsRecorder(),
            safety_preflight=safety,
            downloader=Downloader(),
            transcription_provider=Provider(),
        )
    )
    if case == "success":
        assert result.transcript_changed and result.failure is None
        assert (
            events.index("budget")
            < events.index("transcribe")
            < events.index("persist_transcript")
        )
        assert events.count("transcribe") == 1
    elif case == "complete_replay":
        assert events == ["claim"] and result.failure is None
    else:
        assert result.failure is not None
        assert "persist_transcript" not in events
        if case != "timeout":
            assert "transcribe" not in events
        else:
            assert result.failure == MediaFailureReason.AMBIGUOUS
    if case in {"disabled", "wrong_connection", "no_route", "privacy"}:
        assert "download" not in events


def test_media_timeouts_cannot_outlive_leases():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(telegram_media_enabled=True, planning_job_lease_seconds=20)
