import pytest

from app.application.observability import (
    APPROVED_LATENCY_TARGETS,
    DEFAULT_RECOVERY_OBJECTIVE,
    PROPOSED_OPERATOR_OBJECTIVES,
    SLI_CATALOG,
    BacklogObjective,
    LatencyObjective,
    evaluate_backlog,
    evaluate_good_ratio,
    evaluate_latency,
    percentile,
    validate_sli_catalog,
)
from app.infrastructure.telemetry import METRICS, PROHIBITED_LABEL_NAMES


def test_sli_catalog_is_closed_and_maps_to_existing_metrics() -> None:
    validate_sli_catalog()
    assert len(SLI_CATALOG) == 10
    names = [sli.name for sli in SLI_CATALOG]
    assert len(names) == len(set(names))
    for sli in SLI_CATALOG:
        assert sli.metric is None or sli.metric in METRICS
    assert all(
        not definition.labels & PROHIBITED_LABEL_NAMES
        for definition in METRICS.values()
    )


def test_latency_slo_met_and_breached() -> None:
    objective = LatencyObjective(
        "webhook_ack_latency", percentile=0.95, bound_seconds=0.5
    )
    met = evaluate_latency([0.4] * 95 + [0.7] * 5, objective)
    assert met.status == "met"
    assert met.sample_count == 100
    assert met.p95_seconds == 0.4
    assert met.bad_ratio == pytest.approx(0.05)
    assert met.budget_remaining_ratio == pytest.approx(0.0)

    breached = evaluate_latency([0.4] * 90 + [0.7] * 10, objective)
    assert breached.status == "breached"
    assert breached.p95_seconds == 0.7
    assert breached.bad_ratio == pytest.approx(0.1)
    assert breached.burn_rate == pytest.approx(2.0)


def test_latency_slo_unknown_window_never_zero() -> None:
    objective = LatencyObjective(
        "webhook_ack_latency", percentile=0.95, bound_seconds=0.5
    )
    empty = evaluate_latency([], objective)
    assert empty.status == "unknown"
    assert empty.budget_remaining_ratio is None
    assert empty.error_budget_ratio == pytest.approx(0.05)

    too_few = evaluate_latency([0.4] * 10, objective)
    assert too_few.status == "unknown"
    assert too_few.budget_remaining_ratio is None

    invalid = evaluate_latency([0.4, -1.0], objective)
    assert invalid.status == "unknown"


def test_percentile_uses_nearest_rank() -> None:
    assert percentile(list(range(100)), 0.95) == 94
    assert percentile([1.0], 0.95) == 1.0


def test_good_ratio_slo_met_and_unknown() -> None:
    objective = PROPOSED_OPERATOR_OBJECTIVES[1]
    met = evaluate_good_ratio(good_count=99, bad_count=1, objective=objective)
    assert met.status == "met"
    breached = evaluate_good_ratio(good_count=90, bad_count=10, objective=objective)
    assert breached.status == "breached"
    assert breached.burn_rate == pytest.approx(10.0)
    unknown = evaluate_good_ratio(good_count=0, bad_count=0, objective=objective)
    assert unknown.status == "unknown"
    assert unknown.budget_remaining_ratio is None


def test_recovery_backlog_breached_by_quarantine() -> None:
    recovery = {
        "recovery": {
            "planning.dead_letter": 3,
            "planning.quarantine": 1,
            "outbound.dead_letter": 2,
            "outbound.quarantine": 60,
        },
        "planning": {
            "count_by_state": {"pending": 1},
            "oldest_pending_age_seconds": 120,
            "active_lease_count": 1,
            "stale_lease_count": 0,
        },
        "outbound": {
            "count_by_state": {"pending": 0},
            "oldest_pending_age_seconds": None,
            "active_lease_count": 0,
            "stale_lease_count": 0,
        },
    }
    evaluation = evaluate_backlog(recovery, DEFAULT_RECOVERY_OBJECTIVE)
    assert evaluation.status == "breached"
    assert evaluation.sample_count == 66


def test_recovery_backlog_met_within_caps() -> None:
    recovery = {
        "recovery": {"planning.dead_letter": 3, "planning.quarantine": 1},
        "planning": {
            "count_by_state": {"pending": 2},
            "oldest_pending_age_seconds": 60,
            "active_lease_count": 1,
            "stale_lease_count": 1,
        },
        "outbound": {
            "count_by_state": {},
            "oldest_pending_age_seconds": None,
            "active_lease_count": 0,
            "stale_lease_count": 0,
        },
    }
    assert evaluate_backlog(recovery, DEFAULT_RECOVERY_OBJECTIVE).status == "met"


def test_operator_defaults_are_recorded_not_approved() -> None:
    for objective in APPROVED_LATENCY_TARGETS:
        assert objective.approved is True
    assert len(APPROVED_LATENCY_TARGETS) == 4
    for objective in PROPOSED_OPERATOR_OBJECTIVES:
        assert objective.approved is False
    assert isinstance(PROPOSED_OPERATOR_OBJECTIVES[-1], BacklogObjective)
    assert isinstance(DEFAULT_RECOVERY_OBJECTIVE, BacklogObjective)
