import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.application.model_provider import (
    ProviderCapabilities,
    ProviderError,
    ProviderUsage,
    TranscriptionRequest,
    TranscriptionResult,
)
from app.application.ports.provider_governance import ProviderWorkSource
from app.application.provider_governance import (
    capability_matches,
    work_requirements_match,
)
from app.core.config import Settings
from app.domain.media import EphemeralMedia, MediaKind
from app.domain.planning import ProviderId
from app.domain.provider_governance import (
    BudgetMeasurement,
    EstimateQuality,
    UsageObservation,
    WorkloadClass,
)
from app.infrastructure.database.models import ProviderPriceRevisionModel
from app.infrastructure.database.provider_governance import (
    _actual_estimate,
    _reservation_amounts,
)
from app.infrastructure.governed_provider import GovernedTranscriptionProvider
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.interface.http.provider_governance_control import BudgetInput, CapabilityInput

from .test_provider_governance import (
    _Concurrency,
    _Limiter,
    _Repository,
    _route,
)


def transcription_metadata():
    return {
        "speech_to_text": True,
        "audio_formats": ["audio/ogg", "audio/mpeg"],
        "maximum_audio_bytes": 5 * 1024 * 1024,
        "maximum_audio_duration_seconds": 120,
    }


def test_only_additional_media_constraints_are_allowed():
    published = {"json_schema": True, "maximum_output_tokens": 300}
    assert work_requirements_match(
        published, published | {"image_input": True}, WorkloadClass.CHAT_GENERATION
    )
    for requested in (
        {"image_input": True},
        published | {"json_schema": False},
        published | {"image_input": False},
    ):
        assert not work_requirements_match(
            published, requested, WorkloadClass.CHAT_GENERATION
        )
    assert not work_requirements_match(
        {}, {"image_input": True}, WorkloadClass.EMBEDDING
    )
    assert not capability_matches(
        _route({}), WorkloadClass.EMBEDDING, {"image_input": True}
    ).eligible
    assert not capability_matches(
        _route({}), WorkloadClass.CHAT_GENERATION, {"speech_to_text": True}
    ).eligible


def test_media_telemetry_rejects_content_and_open_values():
    from app.runtime.telegram_media import record_media_operation

    recorder = InMemoryMetricsRecorder()
    record_media_operation(
        recorder,
        "voice",
        "transcription",
        "ambiguous",
        reason="ambiguous",
        duration=0.1,
    )
    for key in ("file_id", "caption", "transcript", "bot_token", "download_path"):
        with pytest.raises(ValueError):
            recorder.increment(
                "january_telegram_media_operations_total",
                kind="voice",
                stage="prepare",
                outcome="completed",
                reason="none",
                **{key: "forbidden"},
            )
    with pytest.raises(ValueError):
        record_media_operation(recorder, "synthetic-file-id", "prepare", "completed")
    with pytest.raises(ValueError):
        recorder.increment(
            "january_provider_estimated_cost_microusd_total",
            provider="groq",
            workload="unbounded-user-value",
        )


def test_media_recall_embedding_checks_fresh_authority_before_io():
    from app.application.semantic_memory import EmbeddingError
    from app.domain.provider_governance import ProviderOperation
    from app.infrastructure.governed_provider import GovernedEmbeddingProvider

    events = []

    class Embedding:
        provider_id = "ollama"
        model = "local"
        dimension = 2

        async def embed_text(self, text):
            raise AssertionError("erased media must not enter an embedding provider")

        async def aclose(self):
            pass

    async def deny():
        events.append("privacy")
        return False

    governed = GovernedEmbeddingProvider(
        Embedding(),
        replace(
            _route({}), provider_id=ProviderId.OLLAMA, adapter_key=ProviderId.OLLAMA
        ),
        ProviderWorkSource(
            "planning:media", planning_job_id=uuid4(), execution_owner="worker"
        ),
        ProviderOperation.SEMANTIC_QUERY,
        _Repository(events),
        Settings(),
        _Limiter(events),
        _Concurrency(events, provider=ProviderId.OLLAMA),
        InMemoryMetricsRecorder(),
        before_io=deny,
    )
    with pytest.raises(EmbeddingError):
        asyncio.run(governed.embed_text("derived user content"))
    assert "privacy" in events and "release_concurrency" in events
    assert "released" in events and "io_started" not in events


def test_image_reservation_includes_model_bound_before_denied_io():
    from app.domain.provider_governance import ProviderOperation
    from app.infrastructure.governed_provider import GovernedModelProvider

    from .test_provider_governance import _generation_request, _Provider

    events = []

    class Repository(_Repository):
        async def reserve_attempt(self, *args, **kwargs):
            assert args[6] == 1010  # UTF-8 system/user (10) plus image bound.
            return await super().reserve_attempt(*args, **kwargs)

    async def before_io():
        return True

    raw = _Provider(events)
    raw.capabilities = replace(raw.capabilities, image_input=True)
    settings = Settings(
        provider_governance_mode="enforce",
        provider_governance_worker_enabled=True,
        control_plane_enabled=True,
        control_plane_jwt_secret="x" * 32,
        control_plane_jwt_issuer="issuer",
        control_plane_jwt_audience="audience",
    )
    model = GovernedModelProvider(
        raw,
        _route({"image_input": True, "maximum_image_input_tokens": 1000}),
        ProviderWorkSource(
            "planning:photo", planning_job_id=uuid4(), execution_owner="worker"
        ),
        ProviderOperation.RESPONSE_PLANNING,
        Repository(events, False),
        settings,
        _Limiter(events),
        _Concurrency(events),
        before_io=before_io,
    )
    with pytest.raises(ProviderError):
        asyncio.run(
            model.generate(
                replace(
                    _generation_request(),
                    current_image=EphemeralMedia(
                        MediaKind.PHOTO, "image/jpeg", b"bounded", 1, 1
                    ),
                )
            )
        )
    assert events == ["budget"] and raw.calls == 0


@pytest.mark.parametrize("bound", [None, 0, -1, True, "10", 1_000_001])
def test_image_requires_valid_reservation_bound(bound):
    route = _route({"image_input": True, "maximum_image_input_tokens": bound})
    assert not capability_matches(
        route, WorkloadClass.CHAT_GENERATION, {"image_input": True}
    ).eligible


def test_image_capability_excludes_unimplemented_adapters():
    route = _route({"image_input": True, "maximum_image_input_tokens": 1000})
    assert capability_matches(
        route, WorkloadClass.CHAT_GENERATION, {"image_input": True}
    ).eligible
    for adapter in (ProviderId.OLLAMA, ProviderId.GEMINI):
        assert not capability_matches(
            replace(route, adapter_key=adapter),
            WorkloadClass.CHAT_GENERATION,
            {"image_input": True},
        ).eligible


def test_transcription_matches_format_limits_and_existing_vendor_only():
    route = replace(_route(transcription_metadata()), adapter_key=ProviderId.GROQ)
    required = {
        "speech_to_text": True,
        "audio_format": "audio/ogg",
        "maximum_audio_bytes": 1000,
        "maximum_audio_duration_seconds": 60,
    }
    assert capability_matches(route, WorkloadClass.TRANSCRIPTION, required).eligible
    assert not capability_matches(
        replace(route, adapter_key=ProviderId.OPENAI),
        WorkloadClass.TRANSCRIPTION,
        required,
    ).eligible
    assert not capability_matches(
        route,
        WorkloadClass.TRANSCRIPTION,
        required | {"maximum_audio_duration_seconds": 121},
    ).eligible
    route = replace(
        route,
        capability_metadata=transcription_metadata()
        | {"audio_formats": ["audio/mpeg"]},
    )
    assert not capability_matches(route, WorkloadClass.TRANSCRIPTION, required).eligible


def test_control_plane_transcription_and_image_capability_contract():
    payload = dict(
        provider_id="groq",
        adapter_key="groq",
        workload_class="transcription",
        model="operator-model",
        capability_metadata=transcription_metadata(),
        data_class="approved_external",
        credential_slot="groq",
        credential_configured=True,
        reservation_strategy="request_count",
    )
    CapabilityInput(**payload)
    for changed in (
        {"provider_id": "openai", "adapter_key": "openai", "credential_slot": "openai"},
        {
            "capability_metadata": transcription_metadata()
            | {"maximum_audio_bytes": True}
        },
        {
            "capability_metadata": transcription_metadata()
            | {"audio_formats": ["audio/wav"]}
        },
        {"reservation_strategy": "utf8_byte_upper_bound"},
    ):
        with pytest.raises(ValidationError):
            CapabilityInput(**(payload | changed))


def test_transcription_budget_does_not_invent_token_measurements():
    payload = dict(
        workload_class="transcription",
        window_kind="daily_utc",
        amount=10,
        mode="hard",
        alert_threshold_bps=8000,
        effective_at=datetime.now(UTC),
    )
    BudgetInput(**payload, measurement="requests")
    BudgetInput(**payload, measurement="estimated_cost_microusd")
    for measurement in ("input_tokens", "output_tokens", "total_tokens"):
        with pytest.raises(ValidationError):
            BudgetInput(**payload, measurement=measurement)
    price = ProviderPriceRevisionModel(
        unit_basis="transcription_request", request_rate=12
    )
    reserved = _reservation_amounts(None, None, price)
    assert reserved[BudgetMeasurement.ESTIMATED_COST_MICROUSD] == 12
    assert reserved[BudgetMeasurement.TOTAL_TOKENS] is None
    missing = UsageObservation.classify(None, None, None)
    assert _actual_estimate(missing, price) == (12, EstimateQuality.ESTIMATED)
    assert _actual_estimate(missing, None) == (None, EstimateQuality.UNAVAILABLE)


@pytest.mark.parametrize("denial", [None, "budget", "rate", "privacy", "concurrency"])
def test_transcription_uses_shared_admission_in_order(denial):
    events = []

    class Provider:
        provider_id = ProviderId.GROQ
        model = "approved"
        capabilities = ProviderCapabilities(False, False, None, False, True)

        async def transcribe(self, request):
            events.append("provider_io")
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

    class Repository(_Repository):
        async def reserve_attempt(self, *args, **kwargs):
            assert args[2] == WorkloadClass.TRANSCRIPTION
            assert args[3].value == "media_transcription"
            assert args[5] == 1  # Stable even after a planning worker reclaim.
            assert args[6:8] == (None, None)
            return await super().reserve_attempt(*args, **kwargs)

    async def before_io():
        events.append("privacy")
        return denial != "privacy"

    class Concurrency(_Concurrency):
        async def acquire(self, provider):
            if denial == "concurrency":
                events.append("concurrency")
                return None
            return await super().acquire(provider)

    settings = Settings(
        provider_governance_mode="enforce",
        provider_governance_worker_enabled=True,
        control_plane_enabled=True,
        control_plane_jwt_secret="x" * 32,
        control_plane_jwt_issuer="issuer",
        control_plane_jwt_audience="audience",
    )
    route = replace(
        _route(transcription_metadata()),
        provider_id=ProviderId.GROQ,
        adapter_key=ProviderId.GROQ,
    )
    model = GovernedTranscriptionProvider(
        Provider(),
        route,
        ProviderWorkSource(
            "planning:test",
            planning_job_id=uuid4(),
            execution_owner="worker",
            execution_ordinal=3,
        ),
        Repository(events, denial != "budget"),
        settings,
        _Limiter(events, denial != "rate"),
        Concurrency(events, provider=ProviderId.GROQ),
        before_io,
        InMemoryMetricsRecorder(),
    )

    async def scenario():
        request = TranscriptionRequest(
            EphemeralMedia(MediaKind.VOICE, "audio/ogg", b"bounded")
        )
        if denial is not None:
            with pytest.raises(ProviderError):
                await model.transcribe(request)
        else:
            result = await model.transcribe(request)
            assert result.usage.total_tokens is None

    asyncio.run(scenario())
    if denial is not None:
        assert "provider_io" not in events
        assert "io_started" not in events
    else:
        assert events == [
            "budget",
            "rate",
            "rate_audit",
            "concurrency",
            "privacy",
            "io_started",
            "provider_io",
            "release_concurrency",
            "reconciled",
        ]
