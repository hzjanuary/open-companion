"""SPEC-023 closed SLI catalog mapped to existing content-free sources.

Every SLI maps to an existing measurement source (a ``january_`` metric or
durable recovery state) and carries an unambiguous definition, a validity
rule, and a unit. No SLI introduces a new measurement source; the 34-metric
catalog stays authoritative (SPEC-015/018/019).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Sli:
    name: str
    definition: str
    source: str
    validity: str
    unit: str
    metric: str | None


SLI_CATALOG: Final = (
    Sli(
        name="webhook_ack_latency",
        definition="Time to acknowledged durable ingress for valid Telegram updates.",
        source="january_http_request_duration_seconds on the webhook route template "
        "/api/v1/platforms/telegram/webhook/{platform_connection_id}",
        validity="At least 30 finite nonnegative observations in the window with "
        "closed 2xx/4xx/5xx status labels.",
        unit="seconds",
        metric="january_http_request_duration_seconds",
    ),
    Sli(
        name="health_readiness_latency",
        definition="Time to /live, /health, /ready response.",
        source="january_http_request_duration_seconds on routes /live, /health, /ready",
        validity="At least 30 finite nonnegative observations in the window.",
        unit="seconds",
        metric="january_http_request_duration_seconds",
    ),
    Sli(
        name="mention_response_latency",
        definition="End-to-end addressed response time when measured; otherwise "
        "component histograms, not asserted cross-process.",
        source="Persisted end-to-end timestamp when available; otherwise "
        "january_worker_operation_duration_seconds component histograms.",
        validity="At least 30 finite nonnegative observations in the window; never "
        "asserted cross-process from component series alone.",
        unit="seconds",
        metric="january_worker_operation_duration_seconds",
    ),
    Sli(
        name="command_response_latency",
        definition="Non-LLM command completion time.",
        source="january_worker_operation_duration_seconds (runtime=commands).",
        validity="At least 30 finite nonnegative observations in the window.",
        unit="seconds",
        metric="january_worker_operation_duration_seconds",
    ),
    Sli(
        name="ingress_ack_durability",
        definition="Share of valid updates acknowledged after durable commit.",
        source="january_telegram_updates_total (accepted/duplicate by transport) and "
        "durable ingress status counts.",
        validity="Nonnegative counts; denominator is the valid accepted-update count "
        "in the window.",
        unit="fraction",
        metric="january_telegram_updates_total",
    ),
    Sli(
        name="delivery_confirmation_rate",
        definition="Share of outbound actions reaching confirmed delivery.",
        source="Delivery-certainty counts (SPEC-007/016) and "
        "january_outbound_actions_total.",
        validity="Nonnegative counts; confirmed share computed over the window "
        "denominator.",
        unit="fraction",
        metric="january_outbound_actions_total",
    ),
    Sli(
        name="recovery_backlog",
        definition="Dead-letter and quarantine accumulation and stale durable leases.",
        source="january_recovery_events_total, january_dead_letter_events_total, "
        "january_quarantine_events_total, and operations inspect durable counts.",
        validity="Nonnegative counts with closed work_kind/disposition labels; "
        "durable counts from operational_recovery_items.",
        unit="count",
        metric="january_recovery_events_total",
    ),
    Sli(
        name="provider_error_rate",
        definition="Provider request failures and timeouts as a share of "
        "provider requests.",
        source="january_model_requests_total and "
        "january_model_request_duration_seconds.",
        validity="Nonnegative counts; denominator is provider requests in the window.",
        unit="fraction",
        metric="january_model_requests_total",
    ),
    Sli(
        name="rate_limit_pressure",
        definition="Rate-limit events and retry-after pressure.",
        source="january_rate_limit_events_total.",
        validity="Nonnegative counts with closed operation/scope/result labels.",
        unit="count",
        metric="january_rate_limit_events_total",
    ),
    Sli(
        name="readiness_degraded_time",
        definition="Time /ready reported dependency failure.",
        source="/ready dependency_unavailable 503 status class through the HTTP "
        "request count and duration histogram.",
        validity="Closed status classes; degraded time computed from the 5xx "
        "duration sum over the window.",
        unit="seconds",
        metric="january_http_request_duration_seconds",
    ),
)

SLI_BY_NAME: Final = {sli.name: sli for sli in SLI_CATALOG}


def validate_sli_catalog() -> None:
    names = [sli.name for sli in SLI_CATALOG]
    if not names or len(names) != len(set(names)):
        raise ValueError("SLI catalog names must be nonempty and unique")
    for sli in SLI_CATALOG:
        if not (sli.definition and sli.source and sli.validity and sli.unit):
            raise ValueError(f"SLI {sli.name!r} is incomplete")
