"""Deterministic sequential SPEC-032 evaluation runner."""

from __future__ import annotations

from dataclasses import dataclass

from app.evaluation.evaluators import (
    AmbientEvaluator,
    ContextEvaluator,
    EvaluatorRegistry,
    FeedbackEvaluator,
    KnowledgeEvaluator,
    MediaEvaluator,
    PlanningEvaluator,
    PresenceEvaluator,
    ReactionEvaluator,
    RegenerationEvaluator,
    SchedulingEvaluator,
    TelegramUXEvaluator,
    VoiceEvaluator,
)
from app.evaluation.gates import evaluate_hard_gates
from app.evaluation.models import (
    EvalCategory,
    EvalDimensionResult,
    EvalResult,
    EvalRun,
    EvalScenario,
    EvalStatus,
    EvalSuite,
)
from app.evaluation.scoring import Judge, score_dimensions, unevaluated_dimensions


class SelectionError(ValueError):
    """Requested scenario selection matched no canonical case."""


@dataclass(frozen=True, slots=True)
class EvalSelection:
    category: EvalCategory | None = None
    scenario_id: str | None = None


def default_registry() -> EvaluatorRegistry:
    return {
        PlanningEvaluator.kind: PlanningEvaluator(),
        ContextEvaluator.kind: ContextEvaluator(),
        AmbientEvaluator.kind: AmbientEvaluator(),
        SchedulingEvaluator.kind: SchedulingEvaluator(),
        MediaEvaluator.kind: MediaEvaluator(),
        KnowledgeEvaluator.kind: KnowledgeEvaluator(),
        TelegramUXEvaluator.kind: TelegramUXEvaluator(),
        PresenceEvaluator.kind: PresenceEvaluator(),
        RegenerationEvaluator.kind: RegenerationEvaluator(),
        ReactionEvaluator.kind: ReactionEvaluator(),
        VoiceEvaluator.kind: VoiceEvaluator(),
        FeedbackEvaluator.kind: FeedbackEvaluator(),
    }


async def run_suite(
    suite: EvalSuite,
    *,
    registry: EvaluatorRegistry | None = None,
    selection: EvalSelection | None = None,
    judge: Judge | None = None,
) -> EvalRun:
    selected = _select(suite, selection or EvalSelection())
    available = default_registry() if registry is None else registry
    results: list[EvalResult] = []
    for scenario in selected:
        evaluator = available.get(scenario.evaluator)
        if evaluator is None:
            results.append(
                _error_result(suite, scenario, "evaluator is not registered")
            )
            continue
        try:
            observation = await evaluator.evaluate(scenario.execution_case())
        except Exception:
            # Drivers are an extension boundary. Any fault becomes bounded ERROR;
            # fixture content and exception text must never escape into reports.
            results.append(
                _error_result(suite, scenario, "evaluator input or execution failed")
            )
            continue
        hard_gates = evaluate_hard_gates(scenario.hard_expectations, observation)
        hard_failed = any(item.status == EvalStatus.FAIL for item in hard_gates)
        dimensions: tuple[EvalDimensionResult, ...] = ()
        score: float | None = None
        rubric = scenario.rubric
        if rubric is not None:
            if judge is None:
                dimensions = unevaluated_dimensions(rubric)
            else:
                try:
                    judge_output = await judge.score(scenario, observation)
                except Exception:
                    # The optional judge follows the same fail-closed report rule.
                    results.append(
                        _error_result(suite, scenario, "judge execution failed")
                    )
                    continue
                dimensions, score = score_dimensions(
                    rubric,
                    judge_output,
                    expected_judge_version=judge.version,
                )
        if hard_failed:
            status = EvalStatus.FAIL
            reason = "one or more hard gates failed"
        elif score is not None and rubric is not None and score < rubric.threshold:
            status = EvalStatus.FAIL
            reason = "soft quality threshold not met"
        elif dimensions and any(
            item.status == EvalStatus.NOT_EVALUATED for item in dimensions
        ):
            status = EvalStatus.NOT_EVALUATED
            reason = "soft quality not evaluated"
        else:
            status = EvalStatus.PASS
            reason = None
        results.append(
            EvalResult(
                suite_id=suite.suite_id,
                suite_version=suite.suite_version,
                scenario_id=scenario.id,
                category=scenario.category,
                evaluator=scenario.evaluator,
                status=status,
                hard_gates=hard_gates,
                dimensions=dimensions,
                normalized_score=score,
                soft_threshold=rubric.threshold if rubric is not None else None,
                failure_reason=reason,
            )
        )
    counts = {status: 0 for status in EvalStatus}
    for result in results:
        counts[result.status] += 1
    run_status = (
        EvalStatus.ERROR
        if counts[EvalStatus.ERROR]
        else EvalStatus.FAIL
        if counts[EvalStatus.FAIL]
        else EvalStatus.PASS
    )
    return EvalRun(
        suite_id=suite.suite_id,
        suite_version=suite.suite_version,
        status=run_status,
        results=tuple(results),
        counts=counts,
        judge=judge.version if judge is not None else "disabled",
    )


def _select(suite: EvalSuite, selection: EvalSelection) -> tuple[EvalScenario, ...]:
    selected = tuple(
        scenario
        for scenario in suite.scenarios
        if (selection.category is None or scenario.category == selection.category)
        and (selection.scenario_id is None or scenario.id == selection.scenario_id)
    )
    if not selected:
        raise SelectionError("selection matched no evaluation scenarios")
    return selected


def _error_result(suite: EvalSuite, scenario: EvalScenario, reason: str) -> EvalResult:
    return EvalResult(
        suite_id=suite.suite_id,
        suite_version=suite.suite_version,
        scenario_id=scenario.id,
        category=scenario.category,
        evaluator=scenario.evaluator,
        status=EvalStatus.ERROR,
        hard_gates=(),
        dimensions=(),
        normalized_score=None,
        soft_threshold=scenario.rubric.threshold if scenario.rubric else None,
        failure_reason=reason,
    )
