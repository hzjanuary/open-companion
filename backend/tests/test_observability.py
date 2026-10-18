import asyncio
import logging

import pytest

from app.application.telemetry import record_provider_usage
from app.core.config import Settings
from app.core.logging import operational_event
from app.core.telemetry_context import (
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from app.infrastructure.telemetry import (
    METRICS,
    PROHIBITED_LABEL_NAMES,
    InMemoryMetricsRecorder,
    MetricsHttpExporter,
)
from app.main import create_app
from tests.conftest import AppClient, FakeDatabase


def test_registry_isolated_and_rejects_high_cardinality_labels() -> None:
    first = InMemoryMetricsRecorder()
    second = InMemoryMetricsRecorder()
    labels = {"route": "/health", "method": "GET", "status": "2xx"}
    first.increment("january_http_requests_total", **labels)

    assert first.counter_value("january_http_requests_total", **labels) == 1
    assert second.counter_value("january_http_requests_total", **labels) == 0
    assert not set().intersection(PROHIBITED_LABEL_NAMES)
    assert all(
        not (definition.labels & PROHIBITED_LABEL_NAMES)
        for definition in METRICS.values()
    )
    with pytest.raises(ValueError, match="prohibited"):
        first.increment(
            "january_http_requests_total",
            route="/health",
            method="GET",
            status="2xx",
            request_id="unsafe",
        )


def test_reaction_metrics_are_closed_and_identity_free() -> None:
    recorder = InMemoryMetricsRecorder()
    recorder.increment(
        "january_telegram_reaction_decisions_total",
        decision="selected",
        kind="heart",
    )
    recorder.increment(
        "january_telegram_reaction_delivery_total",
        outcome="failure",
        reason="rate_limited",
    )
    exposition = recorder.exposition()
    assert "january_telegram_reaction_decisions_total" in exposition
    assert "january_telegram_reaction_delivery_total" in exposition
    with pytest.raises(ValueError, match="invalid label value"):
        recorder.increment(
            "january_telegram_reaction_decisions_total",
            decision="selected",
            kind="user-specific-emoji",
        )
    with pytest.raises(ValueError, match="prohibited"):
        recorder.increment(
            "january_telegram_reaction_delivery_total",
            outcome="failure",
            reason="rate_limited",
            telegram_message_id="42",
        )


def test_schedule_backlog_gauge_is_bounded_and_content_free() -> None:
    recorder = InMemoryMetricsRecorder()
    recorder.set_gauge(
        "january_schedule_backlog", 11, kind="reminder", status="pending"
    )
    assert (
        recorder.gauge_value(
            "january_schedule_backlog", kind="reminder", status="pending"
        )
        == 11
    )
    assert (
        'january_schedule_backlog{kind="reminder",status="pending"} 11'
        in recorder.exposition()
    )
    with pytest.raises(ValueError, match="invalid label value"):
        recorder.set_gauge(
            "january_schedule_backlog", 1, kind="private-user", status="pending"
        )
    with pytest.raises(ValueError, match="prohibited"):
        recorder.set_gauge(
            "january_schedule_backlog",
            1,
            kind="reminder",
            status="pending",
            participant_id="unsafe",
        )


def test_recovery_and_concurrency_metrics_use_only_bounded_labels() -> None:
    recorder = InMemoryMetricsRecorder()
    recorder.increment(
        "january_recovery_events_total",
        work_kind="planning",
        operation="replay",
        outcome="accepted",
        reason="operator_replay",
    )
    recorder.increment(
        "january_provider_concurrency_events_total",
        provider="openai",
        outcome="denied",
    )
    assert "january_recovery_events_total" in recorder.exposition()
    with pytest.raises(ValueError, match="prohibited"):
        recorder.increment(
            "january_recovery_events_total",
            work_kind="planning",
            operation="replay",
            outcome="accepted",
            reason="operator_replay",
            planning_job_id="unsafe",
        )


def test_summary_metrics_are_content_free() -> None:
    recorder = InMemoryMetricsRecorder()
    recorder.increment(
        "january_summary_generation_total",
        outcome="completed",
        provider="ollama",
        schema="v1",
    )
    recorder.increment(
        "january_summary_context_usage_total", outcome="used", schema="v1"
    )
    with pytest.raises(ValueError, match="prohibited"):
        recorder.increment(
            "january_summary_generation_total",
            outcome="completed",
            provider="ollama",
            schema="v1",
            text="unsafe-summary",
        )


def test_memory_control_metrics_have_only_closed_content_free_labels() -> None:
    recorder = InMemoryMetricsRecorder()
    recorder.increment(
        "january_memory_control_operations_total",
        operation="recall_disable",
        outcome="success",
        record_kind="recall_policy",
        conversation_type="private",
    )
    assert "january_memory_control_operations_total" in recorder.exposition()
    with pytest.raises(ValueError, match="invalid label value"):
        recorder.increment(
            "january_memory_control_operations_total",
            operation="create",
            outcome="success",
            record_kind="secret memory text",
            conversation_type="private",
        )
    with pytest.raises(ValueError, match="prohibited"):
        recorder.increment(
            "january_memory_control_operations_total",
            operation="create",
            outcome="success",
            record_kind="personal_context",
            conversation_type="private",
            participant_id="unsafe",
        )


def test_semantic_metrics_are_content_free_and_version_bounded() -> None:
    recorder = InMemoryMetricsRecorder()
    recorder.increment(
        "january_semantic_memory_index_operations_total",
        operation="upsert",
        outcome="success",
        embedding_version="e3c614853e2dd6a1",
    )
    recorder.increment(
        "january_semantic_memory_fallback_total", reason="qdrant_unavailable"
    )
    exposition = recorder.exposition()
    assert "e3c614853e2dd6a1" in exposition
    with pytest.raises(ValueError, match="prohibited"):
        recorder.increment(
            "january_semantic_memory_index_operations_total",
            operation="upsert",
            outcome="success",
            embedding_version="e3c614853e2dd6a1",
            memory_id="unsafe-memory-id",
        )


def test_governance_metrics_catalog_matches_emissions() -> None:
    recorder = InMemoryMetricsRecorder()
    recorder.increment(
        "january_governance_export_requests_total",
        scope="subject",
        outcome="complete",
    )
    recorder.increment(
        "january_governance_export_retrievals_total",
        scope="subject",
        outcome="retrieved",
    )
    recorder.increment(
        "january_governance_erasure_requests_total",
        scope="group",
        outcome="complete",
    )
    recorder.increment(
        "january_governance_packages_cleared_total",
        outcome="expired",
    )
    recorder.increment(
        "january_governance_audit_retention_total",
        outcome="purged",
    )
    exposition = recorder.exposition()
    assert "january_governance_export_requests_total" in exposition
    assert "january_governance_export_retrievals_total" in exposition
    assert "january_governance_erasure_requests_total" in exposition
    assert "january_governance_packages_cleared_total" in exposition
    assert "january_governance_audit_retention_total" in exposition
    assert 'january_governance_audit_retention_total{outcome="purged"}' in exposition
    with pytest.raises(ValueError, match="invalid labels"):
        recorder.increment(
            "january_governance_export_requests_total", outcome="complete"
        )
    with pytest.raises(ValueError, match="invalid label value"):
        recorder.increment(
            "january_governance_export_requests_total",
            scope="subject-id-123",
            outcome="complete",
        )
    with pytest.raises(ValueError, match="invalid label value"):
        recorder.increment(
            "january_governance_erasure_requests_total",
            scope="subject",
            outcome="unexpected",
        )
    recorder.observe(
        "january_worker_operation_duration_seconds",
        0.1,
        runtime="governance",
        operation="export_batch",
        outcome="failed",
    )
    with pytest.raises(ValueError, match="invalid label value"):
        recorder.observe(
            "january_worker_operation_duration_seconds",
            0.1,
            runtime="governance-user-123",
            operation="export_batch",
            outcome="failed",
        )


def test_usage_cost_is_reported_or_unknown_without_fabrication() -> None:
    recorder = InMemoryMetricsRecorder()
    record_provider_usage(
        recorder,
        provider="openai",
        model="test-model",
        input_tokens=100,
        output_tokens=25,
        total_tokens=125,
        pricing={
            "openai:test-model": {
                "input_microusd_per_million": 2_000_000,
                "output_microusd_per_million": 4_000_000,
            }
        },
    )
    record_provider_usage(
        recorder,
        provider="openai",
        model="unknown",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        pricing={},
    )

    assert (
        recorder.counter_value(
            "january_model_tokens_total", provider="openai", token_type="input"
        )
        == 100
    )
    assert recorder.counter_value(
        "january_model_estimated_cost_usd_total", provider="openai"
    ) == pytest.approx(0.0003)
    assert (
        recorder.counter_value(
            "january_model_cost_estimate_total",
            provider="openai",
            outcome="unavailable",
        )
        == 1
    )


def test_operational_log_is_allowlisted_and_correlation_restores() -> None:
    logger = logging.getLogger("january.test.observability")
    record = logging.LogRecord(
        logger.name, logging.INFO, __file__, 1, "ignored", (), None
    )
    token = set_correlation_id("correlation-1")
    try:
        logger.handle(record)
        operational_event(
            logger, "provider_result", provider="openai", outcome="success"
        )
        nested = set_correlation_id("correlation-2")
        reset_correlation_id(nested)
        assert get_correlation_id() == "correlation-1"
    finally:
        reset_correlation_id(token)
    assert get_correlation_id() is None
    with pytest.raises(ValueError, match="unsupported"):
        operational_event(logger, "unsafe", text="fixture-message-text")


def test_http_metrics_use_route_template_and_request_ids_still_work() -> None:
    app = create_app(Settings(environment="test", metrics_enabled=True))
    app.state.database = FakeDatabase(ready=True)
    response = AppClient(app).get("/health", headers={"X-Request-ID": "request-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-1"
    body = app.state.telemetry.exposition()
    assert 'route="/health"' in body
    assert "request-1" not in body


def test_schedule_metrics_have_closed_content_safe_labels() -> None:
    recorder = InMemoryMetricsRecorder()
    recorder.increment(
        "january_schedule_commands_total",
        operation="reminder_daily",
        outcome="created",
    )
    recorder.increment(
        "january_schedule_occurrences_total",
        kind="check_in",
        outcome="deferred",
    )
    recorder.increment("january_schedule_delivery_total", outcome="delivered")
    with pytest.raises(ValueError, match="invalid label value"):
        recorder.increment(
            "january_schedule_commands_total",
            operation="user-controlled-value",
            outcome="created",
        )
    with pytest.raises(ValueError, match="prohibited metric label name"):
        recorder.increment(
            "january_schedule_occurrences_total",
            kind="reminder",
            outcome="enqueued",
            participant_id="secret",
        )
    exposition = recorder.exposition()
    assert "user-controlled-value" not in exposition
    assert "secret" not in exposition


def test_voice_tts_metrics_are_closed_and_identity_free() -> None:
    recorder = InMemoryMetricsRecorder()
    recorder.increment("january_tts_admission_total", outcome="allowed")
    recorder.increment(
        "january_tts_results_total", outcome="success", provider="openai"
    )
    exposition = recorder.exposition()
    assert 'january_tts_admission_total{outcome="allowed"} 1' in exposition
    assert (
        'january_tts_results_total{outcome="success",provider="openai"} 1' in exposition
    )
    with pytest.raises(ValueError, match="invalid label value"):
        recorder.increment("january_tts_admission_total", outcome="tenant-specific")
    for prohibited in (
        "tenant_id",
        "assistant_id",
        "connection_id",
        "conversation_id",
        "voice_generation_job_id",
        "artifact_id",
        "source_text",
        "audio_bytes",
    ):
        with pytest.raises(ValueError, match="prohibited metric label name"):
            recorder.increment(
                "january_tts_results_total",
                outcome="failed",
                provider="openai",
                **{prohibited: "sensitive"},
            )
    assert "sensitive" not in recorder.exposition()


def test_loopback_exporter_exposes_prometheus_text_only() -> None:
    async def scenario() -> str:
        recorder = InMemoryMetricsRecorder()
        recorder.increment(
            "january_http_requests_total", route="/health", method="GET", status="2xx"
        )
        exporter = MetricsHttpExporter(recorder, "127.0.0.1", 0)
        await exporter.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", exporter.port)
            writer.write(b"GET /metrics HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            response = await reader.read()
            writer.close()
            await writer.wait_closed()
            return response.decode()
        finally:
            await exporter.close()

    response = asyncio.run(scenario())
    assert "200 OK" in response
    assert "january_http_requests_total" in response
    assert "fixture-message-text" not in response
