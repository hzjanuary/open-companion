from datetime import UTC, datetime, timedelta

import pytest

from app.application.observability import (
    ALERT_RULES,
    DEFAULT_OWNERS,
    ContentSafetyViolation,
    Severity,
    TimelineEntry,
    assert_content_safe,
    build_incident_evidence,
    build_post_incident_review,
    escalate_verdict,
    evaluate_alerts,
    render_alert_payload,
    rule_by_name,
)
from app.application.observability.alerts import (
    ACK_EXPIRY_SECONDS,
    AlertInputs,
    AlertVerdict,
    DebounceGate,
    escalation_step,
)

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _fast_burn_series(bound: float, n: int = 1000, bad: int = 800) -> tuple[float, ...]:
    return tuple([bound * 0.5] * (n - bad) + [bound * 2.0] * bad)


def _inputs(
    *,
    mention: tuple[float, ...] | None = None,
    webhook: tuple[float, ...] | None = None,
    health: tuple[float, ...] | None = None,
    command: tuple[float, ...] | None = None,
    readiness_ready: bool = True,
    readiness_was_down: bool = False,
    exporter_stale: bool = False,
    recovery: dict[str, object] | None = None,
    safety: dict[str, object] | None = None,
) -> AlertInputs:
    observations: dict[str, tuple[float, ...]] = {}
    if mention is not None:
        observations["mention_response_latency"] = mention
    if webhook is not None:
        observations["webhook_ack_latency"] = webhook
    if health is not None:
        observations["health_readiness_latency"] = health
    if command is not None:
        observations["command_response_latency"] = command
    return AlertInputs(
        latency_observations=observations,
        recovery=recovery or {"recovery": {}},
        readiness_ready=readiness_ready,
        readiness_was_down=readiness_was_down,
        metrics_exporter_stale=exporter_stale,
        metrics_exporter_last_seen_age_seconds=1800.0 if exporter_stale else None,
        safety=safety or {},
    )


def _verdicts(inputs: AlertInputs) -> dict[str, AlertVerdict]:
    return {verdict.rule: verdict for verdict in evaluate_alerts(inputs, NOW)}


def test_alert_rule_catalog_declares_bounded_policy() -> None:
    assert len(ALERT_RULES) == 15
    for rule in ALERT_RULES:
        assert rule.name and rule.description
        assert rule.rule_class in {
            "burn_rate",
            "recovery_risk",
            "readiness",
            "staleness",
            "safety_risk",
        }
        assert rule.detection_latency_seconds > 0
        assert rule.debounce_seconds >= 0
        assert rule.severity_cap <= rule.natural_severity


def test_burn_rate_fast_slow_base_severities() -> None:
    fast_mention = _verdicts(_inputs(mention=_fast_burn_series(8.0)))
    assert fast_mention["burn_mention_response"].severity == Severity.SEV1
    assert fast_mention["burn_mention_response"].metric_values[
        "burn_rate"
    ] == pytest.approx(16.0)

    fast_webhook = _verdicts(_inputs(webhook=_fast_burn_series(0.5)))
    assert fast_webhook["burn_webhook_ack"].severity == Severity.SEV2

    slow_mention = _verdicts(_inputs(mention=_fast_burn_series(8.0, bad=400)))
    assert slow_mention["burn_mention_response"].severity == Severity.SEV2

    base_command = _verdicts(_inputs(command=_fast_burn_series(1.0, bad=200)))
    assert base_command["burn_command_response"].severity == Severity.SEV4

    fast_command = _verdicts(_inputs(command=_fast_burn_series(1.0)))
    assert fast_command["burn_command_response"].severity == Severity.SEV3


def test_burn_rule_silent_on_unknown_and_met_windows() -> None:
    assert "burn_mention_response" not in _verdicts(_inputs())
    healthy = _verdicts(_inputs(mention=(0.1,) * 100))
    assert "burn_mention_response" not in healthy


def test_no_verdict_more_severe_than_rule_cap() -> None:
    inputs = _inputs(
        mention=_fast_burn_series(8.0),
        webhook=_fast_burn_series(0.5),
        health=_fast_burn_series(0.25),
        command=_fast_burn_series(1.0),
        readiness_ready=False,
        exporter_stale=True,
    )
    for verdict in evaluate_alerts(inputs, NOW):
        assert verdict.severity >= rule_by_name(verdict.rule).severity_cap


def test_recovery_risk_alerts() -> None:
    recovery = {
        "recovery": {"planning.quarantine": 60, "outbound.dead_letter": 3},
        "planning": {
            "count_by_state": {"pending": 1},
            "oldest_pending_age_seconds": 3000,
            "active_lease_count": 0,
            "stale_lease_count": 6,
        },
        "outbound": {
            "count_by_state": {},
            "oldest_pending_age_seconds": None,
            "active_lease_count": 0,
            "stale_lease_count": 0,
        },
    }
    verdicts = _verdicts(_inputs(recovery=recovery))
    assert verdicts["recovery_quarantine_accumulation"].severity == Severity.SEV2
    assert verdicts["recovery_stale_leases"].severity == Severity.SEV2
    assert verdicts["worker_backlog_oldest_pending"].severity == Severity.SEV3
    assert "recovery_dead_letter_backlog" not in verdicts


def test_safety_risk_alerts() -> None:
    quiet = _verdicts(_inputs(safety={"fail_closed_count": 0}))
    assert "safety_fail_closed_surge" not in quiet
    assert "safety_protective_actions_surge" not in quiet
    assert "safety_escalation_high_severity" not in quiet

    surge = _verdicts(
        _inputs(
            safety={
                "fail_closed_count": 4,
                "protective_actions_count": 6,
                "high_severity_signals": 3,
            }
        )
    )
    assert surge["safety_fail_closed_surge"].severity == Severity.SEV2
    assert surge["safety_protective_actions_surge"].severity == Severity.SEV2
    assert surge["safety_escalation_high_severity"].severity == Severity.SEV1

    review_growth = _verdicts(
        _inputs(
            safety={
                "open_review_items": 25,
                "oldest_open_review_age_seconds": 5 * 3600,
            }
        )
    )
    assert review_growth["safety_review_queue_growth"].severity == Severity.SEV3
    assert "safety_review_queue_growth" not in _verdicts(
        _inputs(safety={"open_review_items": 3})
    )


def test_safety_alert_payloads_are_content_safe() -> None:
    verdict = _verdicts(_inputs(safety={"protective_actions_count": 6}))[
        "safety_protective_actions_surge"
    ]
    payload = render_alert_payload(verdict)
    assert_content_safe(payload)


def test_readiness_and_recovery_alerts() -> None:
    down = _verdicts(_inputs(readiness_ready=False, readiness_was_down=True))
    assert down["readiness_dependency"].severity == Severity.SEV1
    assert down["readiness_dependency"].metric_values == {"ready": False}
    assert "readiness_recovery" not in down

    recovered = _verdicts(_inputs(readiness_ready=True, readiness_was_down=True))
    assert recovered["readiness_recovery"].state == "recovered"
    assert recovered["readiness_recovery"].severity == Severity.SEV4
    assert "readiness_dependency" not in recovered


def test_alerting_staleness_is_alertable() -> None:
    stale = _verdicts(_inputs(exporter_stale=True))
    assert stale["alerting_staleness"].severity == Severity.SEV2
    assert (
        stale["alerting_staleness"].metric_values["exporter_last_seen_age_seconds"]
        == 1800.0
    )
    assert "alerting_staleness" not in _verdicts(_inputs())


def test_debounce_suppresses_repeats_and_releases_after_window() -> None:
    gate = DebounceGate()
    verdict = _verdicts(_inputs(mention=_fast_burn_series(8.0)))[
        "burn_mention_response"
    ]
    first = gate.filter([verdict], NOW)
    assert len(first) == 1
    assert gate.filter([verdict], NOW + timedelta(minutes=2)) == []
    released = gate.filter(
        [verdict],
        NOW + timedelta(seconds=rule_by_name(verdict.rule).debounce_seconds + 1),
    )
    assert len(released) == 1


def test_ack_expiry_and_escalation() -> None:
    assert escalation_step(None, NOW, Severity.SEV1) == 0
    assert escalation_step(NOW, NOW + timedelta(minutes=10), Severity.SEV1) == 0
    assert escalation_step(NOW, NOW + timedelta(minutes=20), Severity.SEV1) == 1
    assert escalation_step(NOW, NOW + timedelta(hours=3), Severity.SEV1) == 2
    assert escalation_step(NOW, NOW + timedelta(hours=3), Severity.SEV4) == 0
    assert ACK_EXPIRY_SECONDS[Severity.SEV1] == 900.0

    verdict = _verdicts(_inputs(mention=_fast_burn_series(8.0)))[
        "burn_mention_response"
    ]
    escalated = escalate_verdict(verdict, NOW, NOW + timedelta(minutes=20))
    assert escalated.owner == DEFAULT_OWNERS[1]
    assert escalated.escalation_step == 1


def test_alert_payload_is_content_safe() -> None:
    verdict = _verdicts(_inputs(mention=_fast_burn_series(8.0)))[
        "burn_mention_response"
    ]
    payload = render_alert_payload(verdict)
    assert_content_safe(payload)
    assert set(payload) == {
        "rule",
        "severity",
        "state",
        "timestamp",
        "metric_values",
        "owner",
        "escalation_step",
    }
    assert payload["severity"] == "SEV1"
    assert payload["rule"] == "burn_mention_response"


def test_content_safety_rejects_forbidden_keys_and_credentials() -> None:
    with pytest.raises(ContentSafetyViolation):
        render_alert_payload(
            AlertVerdict(
                rule="readiness_dependency",
                state="alerting",
                severity=Severity.SEV1,
                fired_at=NOW,
                metric_values={"prompt": "forbidden"},
                owner="operating_owner",
                escalation_step=0,
            )
        )
    with pytest.raises(ContentSafetyViolation):
        assert_content_safe(
            {"metric_values": {"token": "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"}}
        )
    with pytest.raises(ContentSafetyViolation):
        assert_content_safe({"note": "bearer abc"})


def test_incident_evidence_and_review_are_content_safe() -> None:
    timeline = [
        TimelineEntry(phase="detection", at=NOW, outcome="alert_fired"),
        TimelineEntry(
            phase="acknowledgement",
            at=NOW + timedelta(minutes=2),
            outcome="acknowledged",
        ),
    ]
    evidence = build_incident_evidence(
        environment="staging",
        severity=Severity.SEV2,
        incident_id="incident-0001",
        correlation_id="correlation-0001",
        run_id="run-0001",
        owners={
            "operator": "owner-a",
            "incident_contact": "contact-a",
            "rollback_authority": "rb-a",
        },
        timeline=timeline,
        metric_values={"burn_rate": 8.0},
        result_classification="active",
        recovery_outcome="dead_letter_replayed",
        remediation_state="open",
    )
    assert_content_safe(evidence)
    assert evidence["severity"] == "SEV2"

    review = build_post_incident_review(
        incident_id="incident-0001",
        severity=Severity.SEV2,
        timeline=timeline,
        root_cause_class="provider_outage",
        error_budget_impact="0.3% of 28-day latency budget consumed",
        corrective_actions=["add provider retry budget"],
        remediation_owner="owner-a",
    )
    assert_content_safe(review)
    assert review["root_cause_class"] == "provider_outage"

    with pytest.raises(ValueError, match="root cause"):
        build_post_incident_review(
            incident_id="incident-0001",
            severity=Severity.SEV2,
            timeline=timeline,
            root_cause_class="not-a-class",
            error_budget_impact="none",
            corrective_actions=[],
            remediation_owner="owner-a",
        )
    with pytest.raises(ContentSafetyViolation):
        build_incident_evidence(
            environment="staging",
            severity=Severity.SEV2,
            incident_id="incident-0001",
            correlation_id="correlation-0001",
            run_id="run-0001",
            owners={},
            timeline=timeline,
            metric_values={"prompt": "forbidden"},
            result_classification="active",
            recovery_outcome=None,
            remediation_state="open",
        )
