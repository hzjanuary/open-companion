"""SPEC-023 declarative SLI/SLO, alerting, and incident operations.

This application-layer module defines the Product-Owner-approved observability
contract: a closed SLI catalog mapped to existing content-free measurement
sources, SLO targets with a rolling 28-day error budget, a content-safe alert
rule catalog, and content-safe incident evidence and review templates. It is
pure, deterministic computation over bounded inputs; it never runs inside the
webhook acknowledgement path, never supervises workers, and never mutates
production.
"""

from app.application.observability.alerts import (
    ACK_EXPIRY_SECONDS,
    ALERT_RULES,
    DEFAULT_OWNERS,
    FAST_BURN_THRESHOLD,
    SLOW_BURN_THRESHOLD,
    STALENESS_THRESHOLD_SECONDS,
    AlertInputs,
    AlertRule,
    AlertVerdict,
    DebounceGate,
    Severity,
    escalate_verdict,
    evaluate_alerts,
    render_alert_payload,
    rule_by_name,
)
from app.application.observability.content_safety import (
    ContentSafetyViolation,
    assert_content_safe,
)
from app.application.observability.incidents import (
    INCIDENT_PHASES,
    ROOT_CAUSE_CLASSES,
    TimelineEntry,
    build_incident_evidence,
    build_post_incident_review,
)
from app.application.observability.slis import (
    SLI_BY_NAME,
    SLI_CATALOG,
    Sli,
    validate_sli_catalog,
)
from app.application.observability.slos import (
    APPROVED_LATENCY_TARGETS,
    DEFAULT_RECOVERY_OBJECTIVE,
    PROPOSED_OPERATOR_OBJECTIVES,
    WINDOW_DAYS,
    BacklogObjective,
    GoodRatioObjective,
    LatencyObjective,
    RecoveryCounts,
    SloEvaluation,
    evaluate_backlog,
    evaluate_good_ratio,
    evaluate_latency,
    percentile,
    recovery_counts,
)

__all__ = [
    "ACK_EXPIRY_SECONDS",
    "ALERT_RULES",
    "APPROVED_LATENCY_TARGETS",
    "AlertInputs",
    "AlertRule",
    "AlertVerdict",
    "BacklogObjective",
    "ContentSafetyViolation",
    "DEFAULT_OWNERS",
    "DEFAULT_RECOVERY_OBJECTIVE",
    "DebounceGate",
    "FAST_BURN_THRESHOLD",
    "GoodRatioObjective",
    "INCIDENT_PHASES",
    "LatencyObjective",
    "PROPOSED_OPERATOR_OBJECTIVES",
    "ROOT_CAUSE_CLASSES",
    "RecoveryCounts",
    "SLI_BY_NAME",
    "SLI_CATALOG",
    "SLOW_BURN_THRESHOLD",
    "STALENESS_THRESHOLD_SECONDS",
    "Severity",
    "Sli",
    "SloEvaluation",
    "TimelineEntry",
    "WINDOW_DAYS",
    "assert_content_safe",
    "build_incident_evidence",
    "build_post_incident_review",
    "escalate_verdict",
    "evaluate_alerts",
    "evaluate_backlog",
    "evaluate_good_ratio",
    "evaluate_latency",
    "percentile",
    "recovery_counts",
    "render_alert_payload",
    "rule_by_name",
    "validate_sli_catalog",
]
