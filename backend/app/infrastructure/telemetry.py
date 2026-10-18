"""Owned, bounded Prometheus-compatible telemetry registry and exporter."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from math import isfinite
from typing import Any, Final, cast

from app.application.ports.telemetry import MetricsRecorder

PROHIBITED_LABEL_NAMES: Final = frozenset(
    {
        "request_id",
        "correlation_id",
        "tenant_id",
        "assistant_id",
        "connection_id",
        "conversation_id",
        "participant_id",
        "message_id",
        "memory_id",
        "planning_job_id",
        "response_plan_id",
        "outbound_action_id",
        "command_job_id",
        "voice_generation_job_id",
        "artifact_id",
        "feedback_id",
        "telegram_update_id",
        "telegram_chat_id",
        "telegram_user_id",
        "telegram_message_id",
        "username",
        "text",
        "prompt",
        "memory",
        "query",
        "vector",
        "qdrant_body",
        "provider_body",
        "url",
        "exception",
        "secret",
        "token",
        "model",
        "provider_request_id",
        "file_id",
        "file_unique_id",
        "download_path",
        "transcript",
        "caption",
        "raw_media",
        "bot_token",
        "media_content",
        "source_text",
        "audio_bytes",
    }
)


@dataclass(frozen=True)
class MetricDefinition:
    kind: str
    labels: frozenset[str]
    allowed_values: dict[str, frozenset[str]] | None = None


MEDIA_LABEL_VALUES: Final = {
    "kind": frozenset({"photo", "voice", "audio", "unsupported"}),
    "stage": frozenset(
        {"prepare", "download", "transcription", "generation", "cleanup"}
    ),
    "outcome": frozenset({"completed", "failed", "ambiguous", "reused", "cancelled"}),
    "reason": frozenset(
        {
            "none",
            "unsupported",
            "invalid_format",
            "too_large",
            "disabled",
            "unavailable",
            "timeout",
            "ambiguous",
            "privacy_changed",
            "stale_lease",
            "budget_denied",
            "rate_limited",
            "concurrency_limited",
        }
    ),
}

METRICS: Final[dict[str, MetricDefinition]] = {
    "january_conversation_feedback_total": MetricDefinition(
        "counter",
        frozenset({"outcome"}),
        {
            "outcome": frozenset(
                {
                    "helpful",
                    "unhelpful",
                    "no_change",
                    "limit_reached",
                    "target_unavailable",
                }
            )
        },
    ),
    "january_tts_admission_total": MetricDefinition(
        "counter",
        frozenset({"outcome"}),
        {
            "outcome": frozenset(
                {
                    "allowed",
                    "unsupported",
                    "target_unavailable",
                    "too_long",
                    "uncertain",
                    "budget_denied",
                    "rate_limited",
                    "concurrency_limited",
                    "governance_unavailable",
                    "no_eligible_route",
                    "refused",
                }
            )
        },
    ),
    "january_tts_results_total": MetricDefinition(
        "counter",
        frozenset({"outcome", "provider"}),
        {
            "outcome": frozenset({"success", "failed", "uncertain", "stale"}),
            "provider": frozenset({"openai"}),
        },
    ),
    "january_telegram_reaction_decisions_total": MetricDefinition(
        "counter",
        frozenset({"decision", "kind"}),
        {
            "decision": frozenset({"selected", "none"}),
            "kind": frozenset({"thumbs_up", "heart", "none"}),
        },
    ),
    "january_telegram_reaction_delivery_total": MetricDefinition(
        "counter",
        frozenset({"outcome", "reason"}),
        {
            "outcome": frozenset({"success", "failure"}),
            "reason": frozenset(
                {
                    "none",
                    "configuration",
                    "authentication",
                    "permission",
                    "invalid_request",
                    "not_found",
                    "conflict",
                    "rate_limited",
                    "server",
                    "timeout",
                    "network",
                    "malformed_response",
                    "unsupported_response",
                }
            ),
        },
    ),
    "january_telegram_presence_calls_total": MetricDefinition(
        "counter",
        frozenset({"outcome", "reason"}),
        {
            "outcome": frozenset({"success", "failure"}),
            "reason": frozenset(
                {
                    "none",
                    "configuration",
                    "authentication",
                    "permission",
                    "invalid_request",
                    "not_found",
                    "conflict",
                    "rate_limited",
                    "server",
                    "timeout",
                    "network",
                    "malformed_response",
                    "unsupported_response",
                }
            ),
        },
    ),
    "january_telegram_presence_lifecycle_total": MetricDefinition(
        "counter",
        frozenset({"outcome"}),
        {
            "outcome": frozenset(
                {
                    "stopped",
                    "exhausted",
                    "authority_lost",
                    "initial_failure",
                    "failure",
                }
            )
        },
    ),
    "january_schedule_backlog": MetricDefinition(
        "gauge",
        frozenset({"kind", "status"}),
        {
            "kind": frozenset({"reminder", "check_in"}),
            "status": frozenset({"pending", "leased"}),
        },
    ),
    "january_schedule_commands_total": MetricDefinition(
        "counter",
        frozenset({"operation", "outcome"}),
        {
            "operation": frozenset(
                {
                    "timezone_status",
                    "timezone_set",
                    "quiet_status",
                    "quiet_set",
                    "quiet_off",
                    "reminder_once",
                    "reminder_daily",
                    "reminder_weekly",
                    "reminders_list",
                    "reminder_cancel",
                    "checkins_status",
                    "checkins_daily",
                    "checkins_weekly",
                    "checkins_off",
                }
            ),
            "outcome": frozenset(
                {
                    "success",
                    "created",
                    "updated",
                    "cancelled",
                    "unchanged",
                    "not_found",
                    "limit_reached",
                    "too_late",
                    "invalid",
                    "denied",
                }
            ),
        },
    ),
    "january_schedule_occurrences_total": MetricDefinition(
        "counter",
        frozenset({"kind", "outcome"}),
        {
            "kind": frozenset({"reminder", "check_in"}),
            "outcome": frozenset(
                {
                    "materialized",
                    "enqueued",
                    "deferred",
                    "stale",
                    "stale_lease",
                    "recent_activity",
                    "paused",
                    "cancelled",
                    "privacy",
                    "membership",
                    "claimed",
                    "reclaimed",
                }
            ),
        },
    ),
    "january_schedule_delivery_total": MetricDefinition(
        "counter",
        frozenset({"outcome"}),
        {
            "outcome": frozenset(
                {"delivered", "failed", "unknown", "skipped", "deferred"}
            )
        },
    ),
    "january_telegram_media_operations_total": MetricDefinition(
        "counter",
        frozenset(MEDIA_LABEL_VALUES),
        MEDIA_LABEL_VALUES,
    ),
    "january_telegram_media_operation_duration_seconds": MetricDefinition(
        "histogram",
        frozenset(MEDIA_LABEL_VALUES),
        MEDIA_LABEL_VALUES,
    ),
    "january_http_requests_total": MetricDefinition(
        "counter", frozenset({"route", "method", "status"})
    ),
    "january_http_request_duration_seconds": MetricDefinition(
        "histogram", frozenset({"route", "method", "status"})
    ),
    "january_telegram_updates_total": MetricDefinition(
        "counter", frozenset({"outcome", "transport"})
    ),
    "january_conversation_eligibility_total": MetricDefinition(
        "counter", frozenset({"eligible", "reason"})
    ),
    "january_planning_jobs_total": MetricDefinition("counter", frozenset({"outcome"})),
    "january_model_requests_total": MetricDefinition(
        "counter", frozenset({"provider", "outcome"})
    ),
    "january_model_request_duration_seconds": MetricDefinition(
        "histogram", frozenset({"provider", "outcome"})
    ),
    "january_model_tokens_total": MetricDefinition(
        "counter", frozenset({"provider", "token_type"})
    ),
    "january_model_usage_reports_total": MetricDefinition(
        "counter", frozenset({"provider", "outcome"})
    ),
    "january_model_estimated_cost_usd_total": MetricDefinition(
        "counter", frozenset({"provider"})
    ),
    "january_model_cost_estimate_total": MetricDefinition(
        "counter", frozenset({"provider", "outcome"})
    ),
    "january_response_plan_validation_total": MetricDefinition(
        "counter", frozenset({"outcome"})
    ),
    "january_outbound_actions_total": MetricDefinition(
        "counter", frozenset({"kind", "outcome"})
    ),
    "january_telegram_send_failures_total": MetricDefinition(
        "counter", frozenset({"kind", "error_class"})
    ),
    "january_delivery_duration_seconds": MetricDefinition(
        "histogram", frozenset({"kind", "outcome"})
    ),
    "january_safety_decisions_total": MetricDefinition(
        "counter", frozenset({"stage", "outcome", "reason"})
    ),
    "january_safety_protective_actions_total": MetricDefinition(
        "counter", frozenset({"action"})
    ),
    "january_rate_limit_events_total": MetricDefinition(
        "counter", frozenset({"operation", "scope", "result"})
    ),
    "january_recovery_events_total": MetricDefinition(
        "counter", frozenset({"work_kind", "operation", "outcome", "reason"})
    ),
    "january_dead_letter_events_total": MetricDefinition(
        "counter", frozenset({"work_kind", "reason"})
    ),
    "january_quarantine_events_total": MetricDefinition(
        "counter", frozenset({"work_kind", "reason"})
    ),
    "january_provider_concurrency_events_total": MetricDefinition(
        "counter",
        frozenset({"provider", "outcome"}),
        {
            "provider": frozenset({"openai", "gemini", "groq", "openrouter", "ollama"}),
            "outcome": frozenset({"acquired", "denied", "released", "unavailable"}),
        },
    ),
    "january_ambient_decisions_total": MetricDefinition(
        "counter", frozenset({"outcome", "profile", "policy"})
    ),
    "january_summary_jobs_total": MetricDefinition(
        "counter", frozenset({"outcome", "schema"})
    ),
    "january_summary_generation_total": MetricDefinition(
        "counter", frozenset({"outcome", "provider", "schema"})
    ),
    "january_summary_context_usage_total": MetricDefinition(
        "counter", frozenset({"outcome", "schema"})
    ),
    "january_summary_retention_events_total": MetricDefinition(
        "counter", frozenset({"outcome"})
    ),
    "january_semantic_memory_queries_total": MetricDefinition(
        "counter", frozenset({"outcome", "provider"})
    ),
    "january_semantic_memory_index_jobs_total": MetricDefinition(
        "counter", frozenset({"operation", "outcome"})
    ),
    "january_semantic_memory_index_operations_total": MetricDefinition(
        "counter", frozenset({"operation", "outcome", "embedding_version"})
    ),
    "january_semantic_memory_fallback_total": MetricDefinition(
        "counter", frozenset({"reason"})
    ),
    "january_knowledge_queries_total": MetricDefinition(
        "counter",
        frozenset({"outcome"}),
        {"outcome": frozenset({"success", "fallback"})},
    ),
    "january_knowledge_fallback_total": MetricDefinition(
        "counter",
        frozenset({"reason"}),
        {
            "reason": frozenset(
                {
                    "governance_unavailable",
                    "derived_unavailable",
                    "authority_changed",
                }
            )
        },
    ),
    "january_knowledge_index_jobs_total": MetricDefinition(
        "counter",
        frozenset({"operation", "outcome"}),
        {
            "operation": frozenset({"upsert", "delete"}),
            "outcome": frozenset({"completed", "no_op", "released", "failed"}),
        },
    ),
    "january_knowledge_retrieval_items": MetricDefinition(
        "histogram",
        frozenset({"kind"}),
        {"kind": frozenset({"candidate", "accepted"})},
    ),
    "january_knowledge_retrieval_duration_seconds": MetricDefinition(
        "histogram",
        frozenset({"outcome"}),
        {"outcome": frozenset({"success", "fallback"})},
    ),
    "january_embedding_requests_total": MetricDefinition(
        "counter", frozenset({"provider", "outcome"})
    ),
    "january_embedding_request_duration_seconds": MetricDefinition(
        "histogram", frozenset({"provider", "outcome"})
    ),
    "january_worker_operations_total": MetricDefinition(
        "counter",
        frozenset({"runtime", "operation", "outcome"}),
        {
            "runtime": frozenset(
                {
                    "conversation",
                    "ingress_dispatcher",
                    "commands",
                    "retention",
                    "governance",
                    "provider_governance",
                    "scheduler",
                }
            ),
            "operation": frozenset(
                {
                    "process",
                    "publish_batch",
                    "command_job",
                    "redaction_batch",
                    "export_batch",
                    "provider_recovery_batch",
                    "schedule_batch",
                }
            ),
            "outcome": frozenset(
                {
                    "message_created",
                    "message_edited",
                    "membership_applied",
                    "ignored",
                    "rejected_malformed",
                    "completed",
                    "failed",
                    "no_op",
                }
            ),
        },
    ),
    "january_worker_operation_duration_seconds": MetricDefinition(
        "histogram",
        frozenset({"runtime", "operation", "outcome"}),
        {
            "runtime": frozenset(
                {
                    "conversation",
                    "ingress_dispatcher",
                    "commands",
                    "retention",
                    "governance",
                    "provider_governance",
                    "scheduler",
                }
            ),
            "operation": frozenset(
                {
                    "process",
                    "publish_batch",
                    "command_job",
                    "redaction_batch",
                    "export_batch",
                    "provider_recovery_batch",
                    "schedule_batch",
                }
            ),
            "outcome": frozenset(
                {
                    "message_created",
                    "message_edited",
                    "membership_applied",
                    "ignored",
                    "rejected_malformed",
                    "completed",
                    "failed",
                    "no_op",
                }
            ),
        },
    ),
    "january_governance_export_requests_total": MetricDefinition(
        "counter",
        frozenset({"scope", "outcome"}),
        {
            "scope": frozenset({"subject", "group", "deployment"}),
            "outcome": frozenset({"requested", "complete", "failed"}),
        },
    ),
    "january_governance_export_retrievals_total": MetricDefinition(
        "counter",
        frozenset({"scope", "outcome"}),
        {
            "scope": frozenset({"subject", "group", "deployment"}),
            "outcome": frozenset({"retrieved", "rejected"}),
        },
    ),
    "january_governance_erasure_requests_total": MetricDefinition(
        "counter",
        frozenset({"scope", "outcome"}),
        {
            "scope": frozenset({"subject", "group"}),
            "outcome": frozenset(
                {"requested", "in_progress", "complete", "partial", "failed"}
            ),
        },
    ),
    "january_governance_packages_cleared_total": MetricDefinition(
        "counter",
        frozenset({"outcome"}),
        {"outcome": frozenset({"expired", "retrieved"})},
    ),
    "january_governance_audit_retention_total": MetricDefinition(
        "counter",
        frozenset({"outcome"}),
        {"outcome": frozenset({"purged"})},
    ),
    "january_memory_control_operations_total": MetricDefinition(
        "counter",
        frozenset({"operation", "outcome", "record_kind", "conversation_type"}),
        {
            "operation": frozenset(
                {
                    "status",
                    "list",
                    "create",
                    "update",
                    "delete",
                    "clear",
                    "recall_disable",
                    "recall_enable",
                }
            ),
            "outcome": frozenset(
                {
                    "success",
                    "unchanged",
                    "conflict",
                    "missing",
                    "denied",
                    "scope_denied",
                    "invalid",
                    "failed",
                }
            ),
            "record_kind": frozenset(
                {"explicit_fact", "personal_context", "recall_policy", "none"}
            ),
            "conversation_type": frozenset({"private", "group"}),
        },
    ),
    "january_provider_routing_decisions_total": MetricDefinition(
        "counter",
        frozenset({"workload", "operation", "route_role", "outcome", "reason"}),
        {
            "workload": frozenset({"chat_generation", "embedding", "transcription"}),
            "operation": frozenset(
                {
                    "response_planning",
                    "summary_generation",
                    "semantic_query",
                    "semantic_index",
                    "semantic_rebuild",
                    "media_transcription",
                }
            ),
            "route_role": frozenset({"primary", "retry", "correction", "fallback"}),
            "outcome": frozenset({"selected", "skipped", "denied"}),
            "reason": frozenset(
                {
                    "eligible",
                    "unsupported_capability",
                    "unhealthy",
                    "disabled",
                    "data_ineligible",
                    "budget_denied",
                    "rate_limited",
                    "concurrency_limited",
                    "invalid_policy",
                    "no_route",
                }
            ),
        },
    ),
    "january_provider_attempts_total": MetricDefinition(
        "counter",
        frozenset({"provider", "workload", "operation", "route_role", "outcome"}),
        {
            "provider": frozenset({"openai", "gemini", "groq", "openrouter", "ollama"}),
            "workload": frozenset({"chat_generation", "embedding", "transcription"}),
            "operation": frozenset(
                {
                    "response_planning",
                    "summary_generation",
                    "semantic_query",
                    "semantic_index",
                    "semantic_rebuild",
                    "media_transcription",
                }
            ),
            "route_role": frozenset({"primary", "retry", "correction", "fallback"}),
            "outcome": frozenset(
                {"success", "refused", "provider_error", "unexpected_error"}
            ),
        },
    ),
    "january_provider_attempt_duration_seconds": MetricDefinition(
        "histogram",
        frozenset({"provider", "workload", "operation", "route_role", "outcome"}),
        {
            "provider": frozenset({"openai", "gemini", "groq", "openrouter", "ollama"}),
            "workload": frozenset({"chat_generation", "embedding", "transcription"}),
            "operation": frozenset(
                {
                    "response_planning",
                    "summary_generation",
                    "semantic_query",
                    "semantic_index",
                    "semantic_rebuild",
                    "media_transcription",
                }
            ),
            "route_role": frozenset({"primary", "retry", "correction", "fallback"}),
            "outcome": frozenset(
                {"success", "refused", "provider_error", "unexpected_error"}
            ),
        },
    ),
    "january_provider_usage_quality_total": MetricDefinition(
        "counter",
        frozenset({"provider", "workload", "usage_quality"}),
        {
            "provider": frozenset({"openai", "gemini", "groq", "openrouter", "ollama"}),
            "workload": frozenset({"chat_generation", "embedding", "transcription"}),
            "usage_quality": frozenset({"complete", "partial", "missing", "invalid"}),
        },
    ),
    "january_provider_estimate_outcomes_total": MetricDefinition(
        "counter",
        frozenset({"provider", "workload", "estimate_quality"}),
        {
            "provider": frozenset({"openai", "gemini", "groq", "openrouter", "ollama"}),
            "workload": frozenset({"chat_generation", "embedding", "transcription"}),
            "estimate_quality": frozenset(
                {"estimated", "partial", "reservation_estimate", "unavailable"}
            ),
        },
    ),
    "january_provider_estimated_cost_microusd_total": MetricDefinition(
        "counter",
        frozenset({"provider", "workload"}),
        {
            "provider": frozenset({"openai", "gemini", "groq", "openrouter", "ollama"}),
            "workload": frozenset({"chat_generation", "embedding", "transcription"}),
        },
    ),
    "january_provider_budget_decisions_total": MetricDefinition(
        "counter",
        frozenset({"workload", "scope", "mode", "outcome"}),
        {
            "workload": frozenset({"chat_generation", "embedding", "transcription"}),
            "scope": frozenset({"deployment", "assistant", "platform_connection"}),
            "mode": frozenset({"hard", "soft"}),
            "outcome": frozenset({"within", "exceeded", "denied", "unavailable"}),
        },
    ),
    "january_provider_budget_reservations_total": MetricDefinition(
        "counter",
        frozenset({"workload", "scope", "outcome"}),
        {
            "workload": frozenset({"chat_generation", "embedding", "transcription"}),
            "scope": frozenset({"deployment", "assistant", "platform_connection"}),
            "outcome": frozenset({"reserved", "released", "consumed", "ambiguous"}),
        },
    ),
    "january_provider_health_transitions_total": MetricDefinition(
        "counter",
        frozenset({"provider", "from_state", "to_state", "reason"}),
        {
            "provider": frozenset({"openai", "gemini", "groq", "openrouter", "ollama"}),
            "from_state": frozenset({"unknown", "ready", "degraded", "unavailable"}),
            "to_state": frozenset({"unknown", "ready", "degraded", "unavailable"}),
            "reason": frozenset(
                {
                    "success_threshold",
                    "failure_threshold",
                    "stale",
                    "administrative",
                    "configuration",
                }
            ),
        },
    ),
    "january_provider_governance_recovery_total": MetricDefinition(
        "counter",
        frozenset({"operation", "outcome"}),
        {
            "operation": frozenset({"reservation", "io_possible", "health_evaluation"}),
            "outcome": frozenset({"completed", "failed", "no_op"}),
        },
    ),
}


class InMemoryMetricsRecorder:
    """A registry owned by one application/runtime instance, never global."""

    def __init__(self) -> None:
        self._counters: defaultdict[tuple[str, tuple[tuple[str, str], ...]], float] = (
            defaultdict(float)
        )
        self._histograms: defaultdict[
            tuple[str, tuple[tuple[str, str], ...]], list[float]
        ] = defaultdict(list)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    def increment(self, metric: str, amount: float = 1.0, /, **labels: str) -> None:
        definition, normalized = self._validate(metric, labels)
        if definition.kind != "counter":
            raise ValueError(f"{metric} is not a counter")
        if not isfinite(amount) or amount < 0:
            raise ValueError("metric counter amount must be finite and nonnegative")
        self._counters[(metric, normalized)] += amount

    def observe(self, metric: str, value: float, /, **labels: str) -> None:
        definition, normalized = self._validate(metric, labels)
        if definition.kind != "histogram":
            raise ValueError(f"{metric} is not a histogram")
        if not isfinite(value) or value < 0:
            raise ValueError("metric observation must be finite and nonnegative")
        self._histograms[(metric, normalized)].append(value)

    def set_gauge(self, metric: str, value: float, /, **labels: str) -> None:
        definition, normalized = self._validate(metric, labels)
        if definition.kind != "gauge":
            raise ValueError(f"{metric} is not a gauge")
        if not isfinite(value) or value < 0:
            raise ValueError("metric gauge value must be finite and nonnegative")
        self._gauges[(metric, normalized)] = value

    def counter_value(self, metric: str, /, **labels: str) -> float:
        _, normalized = self._validate(metric, labels)
        return self._counters[(metric, normalized)]

    def histogram_values(self, metric: str, /, **labels: str) -> tuple[float, ...]:
        _, normalized = self._validate(metric, labels)
        return tuple(self._histograms[(metric, normalized)])

    def gauge_value(self, metric: str, /, **labels: str) -> float:
        _, normalized = self._validate(metric, labels)
        return self._gauges.get((metric, normalized), 0.0)

    def exposition(self) -> str:
        lines: list[str] = []
        for metric, definition in METRICS.items():
            lines.append(f"# TYPE {metric} {definition.kind}")
            if definition.kind == "counter":
                for (name, labels), raw in sorted(self._counters.items()):
                    if name != metric:
                        continue
                    rendered = _render_labels(labels)
                    lines.append(f"{metric}{rendered} {raw:g}")
            elif definition.kind == "gauge":
                for (name, labels), raw in sorted(self._gauges.items()):
                    if name != metric:
                        continue
                    rendered = _render_labels(labels)
                    lines.append(f"{metric}{rendered} {raw:g}")
            else:
                for (name, labels), observations in sorted(self._histograms.items()):
                    if name != metric:
                        continue
                    rendered = _render_labels(labels)
                    lines.append(f"{metric}_count{rendered} {len(observations)}")
                    lines.append(f"{metric}_sum{rendered} {sum(observations):g}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _validate(
        metric: str, labels: dict[str, str]
    ) -> tuple[MetricDefinition, tuple[tuple[str, str], ...]]:
        definition = METRICS.get(metric)
        if definition is None:
            raise ValueError(f"unknown metric: {metric}")
        names = set(labels)
        if names & PROHIBITED_LABEL_NAMES:
            raise ValueError("prohibited metric label name")
        if names != definition.labels:
            raise ValueError(f"invalid labels for {metric}")
        if any(not value or len(value) > 80 for value in labels.values()):
            raise ValueError("metric label values must be bounded and nonblank")
        if definition.allowed_values is not None and any(
            value not in definition.allowed_values.get(name, frozenset({value}))
            for name, value in labels.items()
        ):
            raise ValueError(f"invalid label value for {metric}")
        return definition, tuple(sorted(labels.items()))


def _render_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    values = ",".join(
        f'{name}="{value.replace("\\", "\\\\").replace(chr(34), '\\\\"')}"'
        for name, value in labels
    )
    return "{" + values + "}"


class MetricsHttpExporter:
    """Small loopback-only HTTP exporter for one owned registry."""

    def __init__(self, recorder: MetricsRecorder, host: str, port: int) -> None:
        self._recorder = recorder
        self._host = host
        self._port = port
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._serve, self._host, self._port)
        sockets = cast(Any, self._server).sockets
        if sockets:
            self._port = int(sockets[0].getsockname()[1])

    @property
    def port(self) -> int:
        return self._port

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _serve(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request = await reader.readline()
            while await reader.readline() not in {b"\r\n", b"\n", b""}:
                pass
            if request.startswith(b"GET /metrics "):
                body = self._recorder.exposition().encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/plain; version=0.0.4\r\n"
                    + f"Content-Length: {len(body)}\r\n\r\n".encode()
                    + body
                )
            else:
                writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
