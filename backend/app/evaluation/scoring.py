"""Optional soft-quality scoring contract; unknown quality stays unknown."""

from __future__ import annotations

from typing import Protocol

from app.evaluation.models import (
    EvalDimensionResult,
    EvalObservation,
    EvalRubric,
    EvalScenario,
    EvalStatus,
    JudgeOutput,
)


class Judge(Protocol):
    """Future explicit judge seam; no network implementation exists in v1."""

    version: str

    async def score(
        self, scenario: EvalScenario, observation: EvalObservation
    ) -> JudgeOutput: ...


def unevaluated_dimensions(
    rubric: EvalRubric,
) -> tuple[EvalDimensionResult, ...]:
    return tuple(
        EvalDimensionResult(
            dimension=item.dimension,
            status=EvalStatus.NOT_EVALUATED,
            score=None,
            reason="judge disabled",
        )
        for item in rubric.dimensions
    )


def score_dimensions(
    rubric: EvalRubric,
    output: JudgeOutput,
    *,
    expected_judge_version: str,
) -> tuple[tuple[EvalDimensionResult, ...], float | None]:
    if output.judge_version != expected_judge_version:
        return _unknown_for(rubric, "incompatible judge version"), None
    by_dimension = {item.dimension: item for item in output.scores}
    if any(item.dimension not in by_dimension for item in rubric.dimensions):
        return _unknown_for(rubric, "required judge score missing"), None
    results = tuple(
        EvalDimensionResult(
            dimension=item.dimension,
            status=EvalStatus.PASS,
            score=by_dimension[item.dimension].score,
            reason=by_dimension[item.dimension].reason,
        )
        for item in rubric.dimensions
    )
    numerator = sum(
        by_dimension[item.dimension].score * item.weight for item in rubric.dimensions
    )
    denominator = sum(item.weight for item in rubric.dimensions)
    return results, round(numerator / denominator, 4)


def _unknown_for(rubric: EvalRubric, reason: str) -> tuple[EvalDimensionResult, ...]:
    return tuple(
        EvalDimensionResult(
            dimension=item.dimension,
            status=EvalStatus.NOT_EVALUATED,
            score=None,
            reason=reason,
        )
        for item in rubric.dimensions
    )
