"""SPEC-023 content-safe alert rule catalog and evaluation.

The rule catalog is declarative and content-safe. Evaluation is pure,
deterministic computation over bounded inputs (exported metric series and
durable recovery state). It never runs inside the webhook acknowledgement
path, never supervises workers, and renders only content-free verdicts.
Debounce, severity caps, acknowledgement expiry, and escalation follow
FR-03/NFR-03 and the approved per-severity policy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Final

from app.application.observability.content_safety import assert_content_safe
from app.application.observability.slos import (
    APPROVED_LATENCY_TARGETS,
    DEFAULT_RECOVERY_OBJECTIVE,
    LatencyObjective,
    evaluate_latency,
    recovery_counts,
)

FAST_BURN_THRESHOLD: Final = 14.4
SLOW_BURN_THRESHOLD: Final = 6.0
STALENESS_THRESHOLD_SECONDS: Final = 900.0

DEFAULT_OWNERS: Final = ("operating_owner", "incident_contact", "rollback_authority")


@dataclass(frozen=True)
class SafetyAlertObjective:
    """Content-free safety escalation thresholds (SPEC-024 FR-11).

    All values are bounded counts/ages over the fail-closed burst window; they
    never reference participants, messages, or content.
    """

    fail_closed_threshold: int = 3
    protective_actions_threshold: int = 5
    review_queue_depth_threshold: int = 20
    oldest_open_review_max_age_seconds: int = 4 * 3600
    high_severity_threshold: int = 3


SAFETY_ALERT_OBJECTIVE: Final = SafetyAlertObjective()


class Severity(IntEnum):
    SEV1 = 1
    SEV2 = 2
    SEV3 = 3
    SEV4 = 4


ACK_EXPIRY_SECONDS: Final = {
    Severity.SEV1: 900.0,
    Severity.SEV2: 3600.0,
    Severity.SEV3: 86400.0,
    Severity.SEV4: None,
}


@dataclass(frozen=True)
class AlertRule:
    name: str
    rule_class: str
    description: str
    natural_severity: Severity
    severity_cap: Severity
    debounce_seconds: float
    detection_latency_seconds: float
    sli: str | None = None
    fast_severity: Severity | None = None
    slow_severity: Severity | None = None
    base_severity: Severity | None = None
    burn_fast_threshold: float | None = None
    burn_slow_threshold: float | None = None


ALERT_RULES: Final = (
    AlertRule(
        name="burn_mention_response",
        rule_class="burn_rate",
        description="Sustained burn on the end-to-end mention response latency SLO.",
        natural_severity=Severity.SEV1,
        severity_cap=Severity.SEV1,
        debounce_seconds=300.0,
        detection_latency_seconds=300.0,
        sli="mention_response_latency",
        fast_severity=Severity.SEV1,
        slow_severity=Severity.SEV2,
        base_severity=Severity.SEV3,
        burn_fast_threshold=FAST_BURN_THRESHOLD,
        burn_slow_threshold=SLOW_BURN_THRESHOLD,
    ),
    AlertRule(
        name="burn_webhook_ack",
        rule_class="burn_rate",
        description="Sustained burn on webhook acknowledgement latency SLO.",
        natural_severity=Severity.SEV2,
        severity_cap=Severity.SEV2,
        debounce_seconds=900.0,
        detection_latency_seconds=900.0,
        sli="webhook_ack_latency",
        fast_severity=Severity.SEV2,
        slow_severity=Severity.SEV2,
        base_severity=Severity.SEV3,
        burn_fast_threshold=FAST_BURN_THRESHOLD,
        burn_slow_threshold=SLOW_BURN_THRESHOLD,
    ),
    AlertRule(
        name="burn_health_readiness",
        rule_class="burn_rate",
        description="Sustained burn on health/readiness latency SLO.",
        natural_severity=Severity.SEV3,
        severity_cap=Severity.SEV3,
        debounce_seconds=900.0,
        detection_latency_seconds=86400.0,
        sli="health_readiness_latency",
        fast_severity=Severity.SEV3,
        slow_severity=Severity.SEV3,
        base_severity=Severity.SEV4,
        burn_fast_threshold=FAST_BURN_THRESHOLD,
        burn_slow_threshold=SLOW_BURN_THRESHOLD,
    ),
    AlertRule(
        name="burn_command_response",
        rule_class="burn_rate",
        description="Sustained burn on non-LLM command response latency SLO.",
        natural_severity=Severity.SEV3,
        severity_cap=Severity.SEV3,
        debounce_seconds=900.0,
        detection_latency_seconds=86400.0,
        sli="command_response_latency",
        fast_severity=Severity.SEV3,
        slow_severity=Severity.SEV3,
        base_severity=Severity.SEV4,
        burn_fast_threshold=FAST_BURN_THRESHOLD,
        burn_slow_threshold=SLOW_BURN_THRESHOLD,
    ),
    AlertRule(
        name="recovery_dead_letter_backlog",
        rule_class="recovery_risk",
        description="Dead-letter accumulation above the approved backlog cap.",
        natural_severity=Severity.SEV2,
        severity_cap=Severity.SEV2,
        debounce_seconds=900.0,
        detection_latency_seconds=900.0,
    ),
    AlertRule(
        name="recovery_quarantine_accumulation",
        rule_class="recovery_risk",
        description="Quarantine accumulation above the approved backlog cap.",
        natural_severity=Severity.SEV2,
        severity_cap=Severity.SEV2,
        debounce_seconds=900.0,
        detection_latency_seconds=900.0,
    ),
    AlertRule(
        name="recovery_stale_leases",
        rule_class="recovery_risk",
        description="Expired durable-work leases accumulating without reclaim.",
        natural_severity=Severity.SEV2,
        severity_cap=Severity.SEV2,
        debounce_seconds=900.0,
        detection_latency_seconds=900.0,
    ),
    AlertRule(
        name="worker_backlog_oldest_pending",
        rule_class="recovery_risk",
        description="Oldest pending durable work exceeding the worker-backlog age cap.",
        natural_severity=Severity.SEV3,
        severity_cap=Severity.SEV3,
        debounce_seconds=1800.0,
        detection_latency_seconds=86400.0,
    ),
    AlertRule(
        name="readiness_dependency",
        rule_class="readiness",
        description="A bounded required dependency failed; /ready reports unready.",
        natural_severity=Severity.SEV1,
        severity_cap=Severity.SEV1,
        debounce_seconds=60.0,
        detection_latency_seconds=300.0,
    ),
    AlertRule(
        name="readiness_recovery",
        rule_class="readiness",
        description="Readiness recovered after a dependency degradation.",
        natural_severity=Severity.SEV4,
        severity_cap=Severity.SEV4,
        debounce_seconds=0.0,
        detection_latency_seconds=300.0,
    ),
    AlertRule(
        name="alerting_staleness",
        rule_class="staleness",
        description="The metrics exporter or collection path is stale or lost.",
        natural_severity=Severity.SEV2,
        severity_cap=Severity.SEV2,
        debounce_seconds=900.0,
        detection_latency_seconds=900.0,
    ),
    AlertRule(
        name="safety_fail_closed_surge",
        rule_class="safety_risk",
        description="Rate of fail-closed stricter defaults exceeds threshold.",
        natural_severity=Severity.SEV2,
        severity_cap=Severity.SEV2,
        debounce_seconds=900.0,
        detection_latency_seconds=900.0,
    ),
    AlertRule(
        name="safety_protective_actions_surge",
        rule_class="safety_risk",
        description="Sustained protective enforcement bursts require review.",
        natural_severity=Severity.SEV2,
        severity_cap=Severity.SEV2,
        debounce_seconds=900.0,
        detection_latency_seconds=900.0,
    ),
    AlertRule(
        name="safety_review_queue_growth",
        rule_class="safety_risk",
        description="Review queue depth or oldest pending item grows.",
        natural_severity=Severity.SEV3,
        severity_cap=Severity.SEV3,
        debounce_seconds=1800.0,
        detection_latency_seconds=3600.0,
    ),
    AlertRule(
        name="safety_escalation_high_severity",
        rule_class="safety_risk",
        description="Sustained high-severity signals toward a member.",
        natural_severity=Severity.SEV1,
        severity_cap=Severity.SEV1,
        debounce_seconds=300.0,
        detection_latency_seconds=900.0,
    ),
)

ALERT_RULES_BY_NAME: Final = {rule.name: rule for rule in ALERT_RULES}


def rule_by_name(name: str) -> AlertRule:
    return ALERT_RULES_BY_NAME[name]


@dataclass(frozen=True)
class AlertInputs:
    latency_observations: dict[str, tuple[float, ...]]
    recovery: dict[str, object]
    readiness_ready: bool
    readiness_was_down: bool = False
    metrics_exporter_stale: bool = False
    metrics_exporter_last_seen_age_seconds: float | None = None
    safety: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AlertVerdict:
    rule: str
    state: str
    severity: Severity
    fired_at: datetime
    metric_values: dict[str, float | int | str | bool | None]
    owner: str
    escalation_step: int


def evaluate_alerts(inputs: AlertInputs, now: datetime) -> list[AlertVerdict]:
    verdicts: list[AlertVerdict] = []
    for rule in ALERT_RULES:
        if rule.rule_class == "burn_rate":
            verdict = _evaluate_burn_rule(rule, inputs, now)
        elif rule.rule_class == "recovery_risk":
            verdict = _evaluate_recovery_rule(rule, inputs, now)
        elif rule.rule_class == "safety_risk":
            verdict = _evaluate_safety_rule(rule, inputs, now)
        elif rule.name == "readiness_dependency":
            verdict = _evaluate_readiness_dependency(inputs, now)
        elif rule.name == "readiness_recovery":
            verdict = _evaluate_readiness_recovery(inputs, now)
        elif rule.name == "alerting_staleness":
            verdict = _evaluate_staleness(inputs, now)
        else:
            verdict = None
        if verdict is not None:
            verdicts.append(verdict)
    return verdicts


def render_alert_payload(verdict: AlertVerdict) -> dict[str, object]:
    payload: dict[str, object] = {
        "rule": verdict.rule,
        "severity": verdict.severity.name,
        "state": verdict.state,
        "timestamp": verdict.fired_at.isoformat(),
        "metric_values": verdict.metric_values,
        "owner": verdict.owner,
        "escalation_step": verdict.escalation_step,
    }
    assert_content_safe(payload)
    return payload


def escalation_step(
    acked_at: datetime | None, now: datetime, severity: Severity
) -> int:
    if acked_at is None:
        return 0
    expiry = ACK_EXPIRY_SECONDS[severity]
    if expiry is None or now <= acked_at:
        return 0
    steps = int((now - acked_at).total_seconds() // expiry)
    return min(steps, len(DEFAULT_OWNERS) - 1)


def escalate_verdict(
    verdict: AlertVerdict, acked_at: datetime | None, now: datetime
) -> AlertVerdict:
    step = escalation_step(acked_at, now, verdict.severity)
    return AlertVerdict(
        rule=verdict.rule,
        state=verdict.state,
        severity=verdict.severity,
        fired_at=verdict.fired_at,
        metric_values=dict(verdict.metric_values),
        owner=DEFAULT_OWNERS[step],
        escalation_step=step,
    )


class DebounceGate:
    def __init__(self) -> None:
        self._last: dict[str, tuple[datetime, Severity]] = {}

    def filter(
        self, verdicts: Sequence[AlertVerdict], now: datetime
    ) -> list[AlertVerdict]:
        filtered: list[AlertVerdict] = []
        for verdict in verdicts:
            if verdict.state != "alerting":
                self._last.pop(verdict.rule, None)
                filtered.append(verdict)
                continue
            previous = self._last.get(verdict.rule)
            if previous is None:
                self._last[verdict.rule] = (now, verdict.severity)
                filtered.append(verdict)
                continue
            rule = rule_by_name(verdict.rule)
            not_worsening = verdict.severity >= previous[1]
            within_debounce = (
                now - previous[0]
            ).total_seconds() < rule.debounce_seconds
            if within_debounce and not_worsening:
                continue
            self._last[verdict.rule] = (now, verdict.severity)
            filtered.append(verdict)
        return filtered


def _cap(severity: Severity, cap: Severity) -> Severity:
    return severity if severity >= cap else cap


def _latency_objective(sli: str) -> LatencyObjective | None:
    for objective in APPROVED_LATENCY_TARGETS:
        if objective.sli == sli:
            return objective
    return None


def _evaluate_burn_rule(
    rule: AlertRule, inputs: AlertInputs, now: datetime
) -> AlertVerdict | None:
    if (
        rule.sli is None
        or rule.fast_severity is None
        or rule.slow_severity is None
        or rule.base_severity is None
        or rule.burn_fast_threshold is None
        or rule.burn_slow_threshold is None
    ):
        return None
    objective = _latency_objective(rule.sli)
    if objective is None:
        return None
    evaluation = evaluate_latency(
        inputs.latency_observations.get(rule.sli, ()), objective
    )
    if evaluation.status != "breached" or evaluation.burn_rate is None:
        return None
    if evaluation.burn_rate >= rule.burn_fast_threshold:
        severity = rule.fast_severity
    elif evaluation.burn_rate >= rule.burn_slow_threshold:
        severity = rule.slow_severity
    else:
        severity = rule.base_severity
    severity = _cap(severity, rule.severity_cap)
    return AlertVerdict(
        rule=rule.name,
        state="alerting",
        severity=severity,
        fired_at=now,
        metric_values={
            "p95_seconds": evaluation.p95_seconds,
            "bound_seconds": objective.bound_seconds,
            "bad_ratio": evaluation.bad_ratio,
            "burn_rate": evaluation.burn_rate,
            "sample_count": evaluation.sample_count,
        },
        owner=DEFAULT_OWNERS[0],
        escalation_step=0,
    )


def _evaluate_recovery_rule(
    rule: AlertRule, inputs: AlertInputs, now: datetime
) -> AlertVerdict | None:
    counts = recovery_counts(inputs.recovery)
    objective = DEFAULT_RECOVERY_OBJECTIVE
    if rule.name == "recovery_dead_letter_backlog":
        if counts.dead_letter <= objective.dead_letter_cap:
            return None
        severity = _cap(rule.natural_severity, rule.severity_cap)
        return AlertVerdict(
            rule=rule.name,
            state="alerting",
            severity=severity,
            fired_at=now,
            metric_values={
                "dead_letter": counts.dead_letter,
                "cap": objective.dead_letter_cap,
            },
            owner=DEFAULT_OWNERS[0],
            escalation_step=0,
        )
    if rule.name == "recovery_quarantine_accumulation":
        if counts.quarantine <= objective.quarantine_cap:
            return None
        severity = _cap(rule.natural_severity, rule.severity_cap)
        return AlertVerdict(
            rule=rule.name,
            state="alerting",
            severity=severity,
            fired_at=now,
            metric_values={
                "quarantine": counts.quarantine,
                "cap": objective.quarantine_cap,
            },
            owner=DEFAULT_OWNERS[0],
            escalation_step=0,
        )
    if rule.name == "recovery_stale_leases":
        if counts.stale_leases <= objective.stale_lease_cap:
            return None
        severity = _cap(rule.natural_severity, rule.severity_cap)
        return AlertVerdict(
            rule=rule.name,
            state="alerting",
            severity=severity,
            fired_at=now,
            metric_values={
                "stale_leases": counts.stale_leases,
                "cap": objective.stale_lease_cap,
            },
            owner=DEFAULT_OWNERS[0],
            escalation_step=0,
        )
    if rule.name == "worker_backlog_oldest_pending":
        age = counts.oldest_pending_age_seconds
        if age is None or age <= objective.oldest_pending_max_age_seconds:
            return None
        severity = _cap(rule.natural_severity, rule.severity_cap)
        return AlertVerdict(
            rule=rule.name,
            state="alerting",
            severity=severity,
            fired_at=now,
            metric_values={
                "oldest_pending_age_seconds": age,
                "cap_seconds": objective.oldest_pending_max_age_seconds,
            },
            owner=DEFAULT_OWNERS[0],
            escalation_step=0,
        )
    return None


def _safety_int(safety: dict[str, object], key: str) -> int:
    value = safety.get(key)
    return int(value) if isinstance(value, int | float) else 0


def _evaluate_safety_rule(
    rule: AlertRule, inputs: AlertInputs, now: datetime
) -> AlertVerdict | None:
    objective = SAFETY_ALERT_OBJECTIVE
    safety = inputs.safety
    if rule.name == "safety_fail_closed_surge":
        count = _safety_int(safety, "fail_closed_count")
        if count < objective.fail_closed_threshold:
            return None
        return AlertVerdict(
            rule=rule.name,
            state="alerting",
            severity=_cap(rule.natural_severity, rule.severity_cap),
            fired_at=now,
            metric_values={
                "fail_closed_count": count,
                "threshold": objective.fail_closed_threshold,
            },
            owner=DEFAULT_OWNERS[0],
            escalation_step=0,
        )
    if rule.name == "safety_protective_actions_surge":
        count = _safety_int(safety, "protective_actions_count")
        if count < objective.protective_actions_threshold:
            return None
        return AlertVerdict(
            rule=rule.name,
            state="alerting",
            severity=_cap(rule.natural_severity, rule.severity_cap),
            fired_at=now,
            metric_values={
                "protective_actions_count": count,
                "threshold": objective.protective_actions_threshold,
            },
            owner=DEFAULT_OWNERS[0],
            escalation_step=0,
        )
    if rule.name == "safety_review_queue_growth":
        depth = _safety_int(safety, "open_review_items")
        age = safety.get("oldest_open_review_age_seconds")
        oldest_age = int(age) if isinstance(age, int | float) else None
        if depth < objective.review_queue_depth_threshold and (
            oldest_age is None
            or oldest_age < objective.oldest_open_review_max_age_seconds
        ):
            return None
        return AlertVerdict(
            rule=rule.name,
            state="alerting",
            severity=_cap(rule.natural_severity, rule.severity_cap),
            fired_at=now,
            metric_values={
                "open_review_items": depth,
                "depth_threshold": objective.review_queue_depth_threshold,
                "oldest_open_age_seconds": oldest_age,
                "age_threshold_seconds": objective.oldest_open_review_max_age_seconds,
            },
            owner=DEFAULT_OWNERS[0],
            escalation_step=0,
        )
    if rule.name == "safety_escalation_high_severity":
        count = _safety_int(safety, "high_severity_signals")
        if count < objective.high_severity_threshold:
            return None
        return AlertVerdict(
            rule=rule.name,
            state="alerting",
            severity=_cap(rule.natural_severity, rule.severity_cap),
            fired_at=now,
            metric_values={
                "high_severity_signals": count,
                "threshold": objective.high_severity_threshold,
            },
            owner=DEFAULT_OWNERS[0],
            escalation_step=0,
        )
    return None


def _evaluate_readiness_dependency(
    inputs: AlertInputs, now: datetime
) -> AlertVerdict | None:
    if inputs.readiness_ready:
        return None
    return AlertVerdict(
        rule="readiness_dependency",
        state="alerting",
        severity=Severity.SEV1,
        fired_at=now,
        metric_values={"ready": False},
        owner=DEFAULT_OWNERS[0],
        escalation_step=0,
    )


def _evaluate_readiness_recovery(
    inputs: AlertInputs, now: datetime
) -> AlertVerdict | None:
    if not (inputs.readiness_ready and inputs.readiness_was_down):
        return None
    return AlertVerdict(
        rule="readiness_recovery",
        state="recovered",
        severity=Severity.SEV4,
        fired_at=now,
        metric_values={"ready": True},
        owner=DEFAULT_OWNERS[0],
        escalation_step=0,
    )


def _evaluate_staleness(inputs: AlertInputs, now: datetime) -> AlertVerdict | None:
    if not inputs.metrics_exporter_stale:
        return None
    return AlertVerdict(
        rule="alerting_staleness",
        state="alerting",
        severity=Severity.SEV2,
        fired_at=now,
        metric_values={
            "exporter_last_seen_age_seconds": (
                inputs.metrics_exporter_last_seen_age_seconds
            )
        },
        owner=DEFAULT_OWNERS[0],
        escalation_step=0,
    )
