"""SPEC-023 SLO targets and error-budget computation.

Latency targets are Product-Owner-approved. Availability, delivery-confirmation,
and recovery-backlog objectives are proposed operating-owner defaults that must
be explicitly approved before production reliance; they are never claimed as
approved policy. All computation happens over a rolling window in the approved
environment; missing metric or exporter data reports a window as ``unknown``,
never as zero budget remaining.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import ceil, isfinite
from typing import Final

WINDOW_DAYS: Final = 28
MIN_LATENCY_SAMPLES: Final = 30


@dataclass(frozen=True)
class LatencyObjective:
    sli: str
    percentile: float
    bound_seconds: float
    window_days: int = WINDOW_DAYS
    approved: bool = True


@dataclass(frozen=True)
class GoodRatioObjective:
    sli: str
    good_ratio: float
    window_days: int = WINDOW_DAYS
    approved: bool = False


@dataclass(frozen=True)
class BacklogObjective:
    sli: str
    dead_letter_cap: int
    quarantine_cap: int
    stale_lease_cap: int
    oldest_pending_max_age_seconds: float
    window_days: int = WINDOW_DAYS
    approved: bool = False


APPROVED_LATENCY_TARGETS: Final = (
    LatencyObjective("webhook_ack_latency", percentile=0.95, bound_seconds=0.500),
    LatencyObjective("health_readiness_latency", percentile=0.95, bound_seconds=0.250),
    LatencyObjective("command_response_latency", percentile=0.95, bound_seconds=1.0),
    LatencyObjective("mention_response_latency", percentile=0.95, bound_seconds=8.0),
)

DEFAULT_RECOVERY_OBJECTIVE: Final = BacklogObjective(
    "recovery_backlog",
    dead_letter_cap=50,
    quarantine_cap=50,
    stale_lease_cap=5,
    oldest_pending_max_age_seconds=900.0,
)

PROPOSED_OPERATOR_OBJECTIVES: Final = (
    GoodRatioObjective("availability", good_ratio=0.999),
    GoodRatioObjective("delivery_confirmation_rate", good_ratio=0.99),
    DEFAULT_RECOVERY_OBJECTIVE,
)


@dataclass(frozen=True)
class SloEvaluation:
    sli: str
    objective: str
    window_days: int
    status: str
    sample_count: int | None = None
    p95_seconds: float | None = None
    bad_ratio: float | None = None
    error_budget_ratio: float | None = None
    budget_remaining_ratio: float | None = None
    burn_rate: float | None = None


def percentile(values: Sequence[float], p: float) -> float:
    if not 0 < p <= 1:
        raise ValueError("percentile must be in (0, 1]")
    if not values:
        raise ValueError("cannot compute a percentile from an empty series")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, ceil(p * len(ordered)) - 1))
    return ordered[index]


def _valid_latency_series(observations: Sequence[float]) -> bool:
    return all(isfinite(value) and value >= 0 for value in observations)


def evaluate_latency(
    observations: Sequence[float], objective: LatencyObjective
) -> SloEvaluation:
    budget_ratio = 1 - objective.percentile
    if (
        not _valid_latency_series(observations)
        or len(observations) < MIN_LATENCY_SAMPLES
    ):
        return SloEvaluation(
            sli=objective.sli,
            objective=_describe_latency(objective),
            window_days=objective.window_days,
            status="unknown",
            error_budget_ratio=budget_ratio,
        )
    p95 = percentile(observations, objective.percentile)
    bad_ratio = sum(
        1 for value in observations if value > objective.bound_seconds
    ) / len(observations)
    burn_rate = bad_ratio / budget_ratio if budget_ratio > 0 else None
    return SloEvaluation(
        sli=objective.sli,
        objective=_describe_latency(objective),
        window_days=objective.window_days,
        status="met" if p95 <= objective.bound_seconds else "breached",
        sample_count=len(observations),
        p95_seconds=p95,
        bad_ratio=bad_ratio,
        error_budget_ratio=budget_ratio,
        budget_remaining_ratio=budget_ratio - bad_ratio,
        burn_rate=burn_rate,
    )


def evaluate_good_ratio(
    good_count: int, bad_count: int, objective: GoodRatioObjective
) -> SloEvaluation:
    total = good_count + bad_count
    budget_ratio = 1 - objective.good_ratio
    if total <= 0 or good_count < 0 or bad_count < 0:
        return SloEvaluation(
            sli=objective.sli,
            objective=_describe_good_ratio(objective),
            window_days=objective.window_days,
            status="unknown",
            error_budget_ratio=budget_ratio,
        )
    observed_ratio = good_count / total
    return SloEvaluation(
        sli=objective.sli,
        objective=_describe_good_ratio(objective),
        window_days=objective.window_days,
        status="met" if observed_ratio >= objective.good_ratio else "breached",
        sample_count=total,
        bad_ratio=1 - observed_ratio,
        error_budget_ratio=budget_ratio,
        budget_remaining_ratio=budget_ratio - (1 - observed_ratio),
        burn_rate=(1 - observed_ratio) / budget_ratio if budget_ratio > 0 else None,
    )


@dataclass(frozen=True)
class RecoveryCounts:
    dead_letter: int = 0
    quarantine: int = 0
    stale_leases: int = 0
    oldest_pending_age_seconds: float | None = None


def recovery_counts(recovery: Mapping[str, object]) -> RecoveryCounts:
    raw = recovery.get("recovery")
    dead_letter = 0
    quarantine = 0
    if isinstance(raw, dict):
        for key, value in raw.items():
            if not isinstance(value, int):
                continue
            if key.endswith(".dead_letter"):
                dead_letter += value
            elif key.endswith(".quarantine"):
                quarantine += value
    stale_leases = 0
    oldest_pending: list[float] = []
    for kind in ("planning", "outbound"):
        summary = recovery.get(kind)
        if not isinstance(summary, dict):
            continue
        stale = summary.get("stale_lease_count")
        if isinstance(stale, int):
            stale_leases += stale
        age = summary.get("oldest_pending_age_seconds")
        if isinstance(age, int | float) and age is not None:
            oldest_pending.append(float(age))
    return RecoveryCounts(
        dead_letter=dead_letter,
        quarantine=quarantine,
        stale_leases=stale_leases,
        oldest_pending_age_seconds=max(oldest_pending) if oldest_pending else None,
    )


def evaluate_backlog(
    recovery: Mapping[str, object], objective: BacklogObjective
) -> SloEvaluation:
    counts = recovery_counts(recovery)
    breached = (
        counts.dead_letter > objective.dead_letter_cap
        or counts.quarantine > objective.quarantine_cap
        or counts.stale_leases > objective.stale_lease_cap
        or (
            counts.oldest_pending_age_seconds is not None
            and counts.oldest_pending_age_seconds
            > objective.oldest_pending_max_age_seconds
        )
    )
    return SloEvaluation(
        sli=objective.sli,
        objective=_describe_backlog(objective),
        window_days=objective.window_days,
        status="breached" if breached else "met",
        sample_count=counts.dead_letter + counts.quarantine,
    )


def _describe_latency(objective: LatencyObjective) -> str:
    return (
        f"{objective.sli} p{objective.percentile * 100:g} "
        f"<= {objective.bound_seconds * 1000:g} ms over "
        f"{objective.window_days} days"
    )


def _describe_good_ratio(objective: GoodRatioObjective) -> str:
    return (
        f"{objective.sli} good ratio >= {objective.good_ratio:g} over "
        f"{objective.window_days} days"
    )


def _describe_backlog(objective: BacklogObjective) -> str:
    return (
        f"{objective.sli} dead_letter <= {objective.dead_letter_cap}, "
        f"quarantine <= {objective.quarantine_cap}, "
        f"stale_leases <= {objective.stale_lease_cap}, "
        f"oldest_pending <= {objective.oldest_pending_max_age_seconds:g} s"
    )
