"""Stable machine and concise human reporting for evaluation runs."""

from __future__ import annotations

import json

from app.evaluation.models import EvalRun, EvalStatus


def render_json(run: EvalRun) -> str:
    payload = run.model_dump(mode="json")
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def render_terminal(run: EvalRun) -> str:
    counts = " ".join(
        f"{status.value}={run.counts.get(status, 0)}" for status in EvalStatus
    )
    lines = [
        f"AI eval suite {run.suite_id} v{run.suite_version}: "
        f"{run.status.value} ({counts})"
    ]
    for result in run.results:
        if result.status == EvalStatus.PASS:
            continue
        lines.append(
            f"- {result.scenario_id}: {result.status.value}"
            + (f" — {result.failure_reason}" if result.failure_reason else "")
        )
        for gate in result.hard_gates:
            if gate.status == EvalStatus.FAIL:
                lines.append(
                    f"  {gate.gate.value}: expected {gate.expected}; "
                    f"observed {gate.observed}"
                )
        if (
            result.status == EvalStatus.FAIL
            and result.normalized_score is not None
            and result.soft_threshold is not None
        ):
            lines.append(
                "  soft_quality: expected at least "
                f"{result.soft_threshold}; observed {result.normalized_score}"
            )
        for dimension in result.dimensions:
            if dimension.status == EvalStatus.NOT_EVALUATED:
                lines.append(
                    f"  {dimension.dimension.value}: NOT_EVALUATED — {dimension.reason}"
                )
    return "\n".join(lines) + "\n"
