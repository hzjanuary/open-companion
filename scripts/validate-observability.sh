#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$project_root")"

"$uv_bin" run pytest backend/tests/test_observability.py backend/tests/test_http.py \
  backend/tests/test_planning_service.py backend/tests/test_observability_slos.py \
  backend/tests/test_observability_alerts.py -q
"$uv_bin" run ruff check backend/app/application/observability \
  backend/tests/test_observability_slos.py backend/tests/test_observability_alerts.py
"$uv_bin" run ruff format --check backend/app/application/observability \
  backend/tests/test_observability_slos.py backend/tests/test_observability_alerts.py
"$uv_bin" run mypy backend/app/application/observability
"$uv_bin" run python - "$project_root" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "backend"))

text = (root / "backend/app/infrastructure/telemetry.py").read_text()
required = {
    "january_http_requests_total", "january_http_request_duration_seconds",
    "january_telegram_updates_total", "january_conversation_eligibility_total",
    "january_planning_jobs_total", "january_model_requests_total",
    "january_model_request_duration_seconds", "january_model_tokens_total",
    "january_model_usage_reports_total", "january_response_plan_validation_total",
    "january_outbound_actions_total", "january_telegram_send_failures_total",
    "january_delivery_duration_seconds", "january_safety_decisions_total",
    "january_rate_limit_events_total", "january_worker_operations_total",
    "january_provider_routing_decisions_total",
    "january_provider_attempts_total",
    "january_provider_attempt_duration_seconds",
    "january_provider_usage_quality_total",
    "january_provider_estimate_outcomes_total",
    "january_provider_estimated_cost_microusd_total",
    "january_provider_budget_decisions_total",
    "january_provider_budget_reservations_total",
    "january_provider_health_transitions_total",
    "january_provider_governance_recovery_total",
    "january_memory_control_operations_total",
    "january_telegram_media_operations_total",
    "january_telegram_media_operation_duration_seconds",
    "january_schedule_commands_total",
    "january_schedule_occurrences_total",
    "january_schedule_delivery_total",
    "january_schedule_backlog",
}
missing = sorted(name for name in required if name not in text)
if missing:
    raise SystemExit(f"missing telemetry metric definitions: {', '.join(missing)}")
if any(root.glob("backend/alembic/versions/*015*")):
    raise SystemExit("SPEC-015 must not add a migration")
if any(root.glob("backend/alembic/versions/*023*")):
    raise SystemExit("SPEC-023 must not add a migration")

from datetime import UTC, datetime, timedelta

from app.application.observability import (
    SLI_CATALOG,
    AlertInputs,
    LatencyObjective,
    Severity,
    build_incident_evidence,
    build_post_incident_review,
    evaluate_alerts,
    evaluate_latency,
    render_alert_payload,
    validate_sli_catalog,
)
from app.application.observability.alerts import DebounceGate
from app.application.observability.incidents import TimelineEntry

validate_sli_catalog()
assert all(sli.metric is None or sli.metric in text for sli in SLI_CATALOG)
objective = LatencyObjective("webhook_ack_latency", percentile=0.95, bound_seconds=0.5)
met = evaluate_latency([0.4] * 95 + [0.7] * 5, objective)
assert met.status == "met" and met.burn_rate is not None and met.burn_rate < 1.0
unknown = evaluate_latency([], objective)
assert unknown.status == "unknown" and unknown.budget_remaining_ratio is None

fast = tuple([4.0] * 200 + [16.0] * 800)
inputs = AlertInputs(
    latency_observations={"mention_response_latency": fast},
    recovery={
        "recovery": {"planning.quarantine": 60},
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
    },
    readiness_ready=False,
    metrics_exporter_stale=True,
    metrics_exporter_last_seen_age_seconds=1800.0,
)
now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
verdicts = DebounceGate().filter(evaluate_alerts(inputs, now), now)
severities = {verdict.rule: verdict.severity.name for verdict in verdicts}
assert severities["burn_mention_response"] == "SEV1"
assert severities["recovery_quarantine_accumulation"] == "SEV2"
assert severities["readiness_dependency"] == "SEV1"
assert severities["alerting_staleness"] == "SEV2"
for verdict in verdicts:
    payload = render_alert_payload(verdict)

timeline = [
    TimelineEntry(phase="detection", at=now, outcome="alert_fired"),
    TimelineEntry(phase="acknowledgement", at=now + timedelta(minutes=2), outcome="acknowledged"),
]
evidence = build_incident_evidence(
    environment="staging",
    severity=Severity.SEV2,
    incident_id="incident-0001",
    correlation_id="correlation-0001",
    run_id="run-0001",
    owners={"operator": "owner-a", "incident_contact": "contact-a", "rollback_authority": "rb-a"},
    timeline=timeline,
    metric_values={"burn_rate": 8.0},
    result_classification="active",
    recovery_outcome="dead_letter_replayed",
    remediation_state="open",
)
review = build_post_incident_review(
    incident_id="incident-0001",
    severity=Severity.SEV2,
    timeline=timeline,
    root_cause_class="provider_outage",
    error_budget_impact="0.3% of 28-day latency budget consumed",
    corrective_actions=["add provider retry budget"],
    remediation_owner="owner-a",
)
print("Observability telemetry and SPEC-023 SLI/SLO/alert/incident artifacts: valid")
PY
