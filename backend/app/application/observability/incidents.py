"""SPEC-023 content-safe incident evidence and post-incident review.

Evidence and review artifacts are metadata-only, following the SPEC-022
evidence-bundle convention and the SPEC-021 content-safe audit discipline.
They carry opaque incident/correlation/run identifiers, closed severity and
root-cause classes, metric values, owners, and remediation state — never
product content, prompts, memories, vectors, provider bodies, or credentials.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from app.application.observability.alerts import Severity
from app.application.observability.content_safety import assert_content_safe

INCIDENT_PHASES: Final = frozenset(
    {
        "detection",
        "acknowledgement",
        "classification",
        "response",
        "communication",
        "mitigation",
        "resolution",
        "review",
    }
)

ROOT_CAUSE_CLASSES: Final = frozenset(
    {
        "provider_outage",
        "dependency_outage",
        "capacity_exhaustion",
        "deployment_rollout",
        "configuration_error",
        "secret_rotation",
        "recovery_backlog",
        "alerting_failure",
        "unknown",
    }
)


@dataclass(frozen=True)
class TimelineEntry:
    phase: str
    at: datetime
    outcome: str


def _validate_timeline(timeline: Sequence[TimelineEntry]) -> None:
    for entry in timeline:
        if entry.phase not in INCIDENT_PHASES:
            raise ValueError(f"unknown incident phase: {entry.phase!r}")


def build_incident_evidence(
    *,
    environment: str,
    severity: Severity,
    incident_id: str,
    correlation_id: str,
    run_id: str,
    owners: Mapping[str, str],
    timeline: Sequence[TimelineEntry],
    metric_values: Mapping[str, object],
    result_classification: str,
    recovery_outcome: str | None,
    remediation_state: str,
) -> dict[str, object]:
    _validate_timeline(timeline)
    bundle: dict[str, object] = {
        "evidence_schema_version": 1,
        "artifact": "incident_evidence",
        "environment": environment,
        "severity": severity.name,
        "incident_id": incident_id,
        "correlation_id": correlation_id,
        "run_id": run_id,
        "owners": dict(owners),
        "timeline": [
            {"phase": entry.phase, "at": entry.at.isoformat(), "outcome": entry.outcome}
            for entry in timeline
        ],
        "metric_values": dict(metric_values),
        "result_classification": result_classification,
        "recovery_outcome": recovery_outcome,
        "remediation_state": remediation_state,
    }
    assert_content_safe(bundle)
    return bundle


def build_post_incident_review(
    *,
    incident_id: str,
    severity: Severity,
    timeline: Sequence[TimelineEntry],
    root_cause_class: str,
    error_budget_impact: str,
    corrective_actions: Sequence[str],
    remediation_owner: str,
) -> dict[str, object]:
    if root_cause_class not in ROOT_CAUSE_CLASSES:
        raise ValueError(f"unknown root cause class: {root_cause_class!r}")
    _validate_timeline(timeline)
    bundle: dict[str, object] = {
        "artifact": "post_incident_review",
        "incident_id": incident_id,
        "severity": severity.name,
        "timeline": [
            {"phase": entry.phase, "at": entry.at.isoformat(), "outcome": entry.outcome}
            for entry in timeline
        ],
        "root_cause_class": root_cause_class,
        "error_budget_impact": error_budget_impact,
        "corrective_actions": list(corrective_actions),
        "remediation_owner": remediation_owner,
    }
    assert_content_safe(bundle)
    return bundle
