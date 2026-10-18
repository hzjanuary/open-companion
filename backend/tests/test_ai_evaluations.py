"""Executable proof for the SPEC-032 offline evaluation framework."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest

from app.evaluation.fixtures import FixtureError, load_suite
from app.evaluation.gates import evaluate_hard_gates
from app.evaluation.models import (
    EvalCategory,
    EvalExecutionCase,
    EvalObservation,
    EvalRun,
    EvalScenario,
    EvalStatus,
    EvaluatorKind,
    HardExpectation,
    HardGate,
    JudgeOutput,
    JudgeScore,
    QualityDimension,
)
from app.evaluation.reporting import render_json, render_terminal
from app.evaluation.runner import (
    EvalSelection,
    SelectionError,
    default_registry,
    run_suite,
)
from app.runtime.ai_evaluations import main

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = PROJECT_ROOT / "evals/fixtures/telegram-core-v1.json"


def _raw_suite() -> dict[str, object]:
    return cast(dict[str, object], json.loads(FIXTURE.read_text(encoding="utf-8")))


def _write_fixture(tmp_path: Path, raw: dict[str, object]) -> Path:
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def _run(**kwargs: Any) -> EvalRun:
    return asyncio.run(run_suite(load_suite(FIXTURE), **kwargs))


def test_canonical_suite_has_reviewed_coverage_and_passes_hard_gate() -> None:
    suite = load_suite(FIXTURE)
    assert len(suite.scenarios) == 130
    assert {scenario.category for scenario in suite.scenarios} == set(EvalCategory)
    assert len(suite.scenarios[0].turns) == 3

    run = asyncio.run(run_suite(suite))

    assert run.status == EvalStatus.PASS
    assert run.counts == {
        EvalStatus.PASS: 125,
        EvalStatus.FAIL: 0,
        EvalStatus.NOT_EVALUATED: 5,
        EvalStatus.ERROR: 0,
    }
    assert all(
        gate.status == EvalStatus.PASS
        for result in run.results
        for gate in result.hard_gates
    )


def test_regeneration_presentation_mutation_fails_edit_hard_gate() -> None:
    suite = load_suite(FIXTURE)
    original = next(
        scenario
        for scenario in suite.scenarios
        if scenario.id == "regeneration.single-edit-eligible"
    )
    raw = original.model_dump(mode="json")
    raw["input"]["original_action_count"] = 2
    mutated = EvalScenario.model_validate_json(json.dumps(raw), strict=True)
    changed = suite.model_copy(update={"scenarios": (mutated,)})

    run = asyncio.run(run_suite(changed))

    assert run.status == EvalStatus.FAIL
    failed = {
        item.gate
        for item in run.results[0].hard_gates
        if item.status == EvalStatus.FAIL
    }
    assert failed == {
        HardGate.PRESENTATION_MODE,
        HardGate.EDIT_CALLS,
        HardGate.SEND_CALLS,
    }


def test_reaction_policy_mutation_fails_independent_hard_gates() -> None:
    suite = load_suite(FIXTURE)
    original = next(
        scenario
        for scenario in suite.scenarios
        if scenario.id == "reaction.eligible-thanks"
    )
    raw = original.model_dump(mode="json")
    raw["input"]["text"] = "How does deployment work?"
    mutated = EvalScenario.model_validate_json(json.dumps(raw), strict=True)
    changed = suite.model_copy(update={"scenarios": (mutated,)})

    run = asyncio.run(run_suite(changed))

    assert run.status == EvalStatus.FAIL
    failed = {
        item.gate
        for item in run.results[0].hard_gates
        if item.status == EvalStatus.FAIL
    }
    assert failed == {
        HardGate.REACTION_ALLOWED,
        HardGate.REACTION_KIND,
        HardGate.REACTION_ATTEMPTS,
    }


def test_voice_delivery_mutation_fails_independent_hard_gate() -> None:
    suite = load_suite(FIXTURE)
    original = next(
        scenario
        for scenario in suite.scenarios
        if scenario.id == "voice.ambiguous-delivery-no-resend"
    )
    raw = original.model_dump(mode="json")
    raw["input"]["telegram_result"] = "retryable_then_success"
    mutated = EvalScenario.model_validate_json(json.dumps(raw), strict=True)
    changed = suite.model_copy(update={"scenarios": (mutated,)})

    run = asyncio.run(run_suite(changed))

    assert run.status == EvalStatus.FAIL
    failed = {
        item.gate
        for item in run.results[0].hard_gates
        if item.status == EvalStatus.FAIL
    }
    assert failed == {HardGate.TELEGRAM_VOICE_ATTEMPTS}


def test_feedback_target_mutation_fails_independent_hard_gates() -> None:
    suite = load_suite(FIXTURE)
    original = next(
        scenario
        for scenario in suite.scenarios
        if scenario.id == "feedback.valid-helpful"
    )
    raw = original.model_dump(mode="json")
    raw["input"]["target"] = "user_message"
    mutated = EvalScenario.model_validate_json(json.dumps(raw), strict=True)
    changed = suite.model_copy(update={"scenarios": (mutated,)})

    run = asyncio.run(run_suite(changed))

    assert run.status == EvalStatus.FAIL
    failed = {
        item.gate
        for item in run.results[0].hard_gates
        if item.status == EvalStatus.FAIL
    }
    assert failed == {
        HardGate.FEEDBACK_TARGET_AUTHORIZED,
        HardGate.FEEDBACK_CURRENT_STATE,
        HardGate.FEEDBACK_EVENT_DELTA,
        HardGate.FEEDBACK_REVISION,
    }


def test_canonical_execution_has_no_external_or_production_side_effects() -> None:
    suite = load_suite(FIXTURE)
    registry = default_registry()

    for scenario in suite.scenarios:
        observation = asyncio.run(
            registry[scenario.evaluator].evaluate(scenario.execution_case())
        )
        assert not hasattr(scenario.execution_case(), "hard_expectations")
        assert observation.external_provider_calls == 0
        assert observation.telegram_calls == 0
        assert observation.memory_writes == 0
        assert observation.semantic_index_writes == 0
        assert observation.schedule_writes == 0
        assert observation.routing_mutations == 0
        assert observation.knowledge_writes == 0
        assert observation.vision_calls == 0
        assert not observation.telegram_credential_required
        assert not observation.live_provider_requested
        assert not observation.raw_media_persisted

    planning_calls = {
        scenario.id: asyncio.run(
            registry[scenario.evaluator].evaluate(scenario.execution_case())
        ).mock_provider_calls
        for scenario in suite.scenarios
        if scenario.evaluator == EvaluatorKind.PLANNING
    }
    assert planning_calls["planning.governance-denied"] == 1
    assert planning_calls["planning.malformed-output"] == 2
    assert planning_calls["planning.timeout-bounded"] == 2
    assert planning_calls["planning.authorized-fallback"] == 2


def test_evaluation_package_has_no_production_runtime_or_client_imports() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((PROJECT_ROOT / "backend/app/evaluation").glob("*.py"))
    )

    for forbidden in (
        "app.core.config",
        "app.infrastructure.database",
        "app.infrastructure.providers",
        "app.infrastructure.queue",
        "TelegramBotApi",
        "sqlalchemy",
        "redis",
        "qdrant_client",
        "app.infrastructure.knowledge",
    ):
        assert forbidden not in sources


def test_report_is_byte_stable_and_excludes_response_text() -> None:
    first = render_json(_run())
    second = render_json(_run())

    assert first == second
    assert first.endswith("\n")
    assert "response_text" not in first
    assert "structured_text" not in first


def test_category_and_scenario_selection_preserve_fixture_order() -> None:
    category = _run(selection=EvalSelection(category=EvalCategory.MEDIA))
    one = _run(selection=EvalSelection(scenario_id="planning.authorized-fallback"))

    assert [result.category for result in category.results] == [EvalCategory.MEDIA] * 7
    assert [result.scenario_id for result in one.results] == [
        "planning.authorized-fallback"
    ]


def test_empty_selection_fails_closed() -> None:
    with pytest.raises(SelectionError, match="matched no"):
        _run(selection=EvalSelection(scenario_id="missing.scenario"))


def test_missing_evaluator_is_error_and_fails_suite() -> None:
    run = _run(registry={})

    assert run.status == EvalStatus.ERROR
    assert all(result.status == EvalStatus.ERROR for result in run.results)
    assert all(
        result.failure_reason == "evaluator is not registered" for result in run.results
    )


def test_missing_judge_is_not_soft_pass() -> None:
    run = _run(selection=EvalSelection(scenario_id="personality.concise-answer"))

    assert run.status == EvalStatus.PASS
    assert run.results[0].status == EvalStatus.NOT_EVALUATED
    assert run.results[0].normalized_score is None
    assert all(
        item.status == EvalStatus.NOT_EVALUATED for item in run.results[0].dimensions
    )


class _MappedJudge:
    version = "judge.mapped-v1"

    def __init__(
        self,
        scores: dict[QualityDimension, float],
        *,
        output_version: str | None = None,
    ) -> None:
        self.scores = scores
        self.output_version = output_version or self.version

    async def score(
        self, scenario: EvalScenario, observation: EvalObservation
    ) -> JudgeOutput:
        del observation
        assert scenario.rubric is not None
        return JudgeOutput(
            judge_version=self.output_version,
            scores=tuple(
                JudgeScore(
                    dimension=item.dimension,
                    score=self.scores[item.dimension],
                    reason="explicit bounded test score",
                )
                for item in scenario.rubric.dimensions
                if item.dimension in self.scores
            ),
        )


def test_hard_privacy_failure_cannot_be_averaged_by_perfect_soft_score() -> None:
    suite = load_suite(FIXTURE)
    raw = suite.scenarios[0].model_dump(mode="json")
    for expectation in raw["hard_expectations"]:
        if expectation["gate"] == "assistant_scope":
            expectation["expected"] = "00000000-0000-4000-8000-000000000102"
    scenario = EvalScenario.model_validate_json(json.dumps(raw), strict=True)
    changed = suite.model_copy(update={"scenarios": (scenario,)})

    run = asyncio.run(
        run_suite(
            changed,
            judge=_MappedJudge(
                {
                    QualityDimension.PERSONALITY_ADHERENCE: 4.0,
                    QualityDimension.CONCISION: 4.0,
                }
            ),
        )
    )

    assert run.results[0].normalized_score == 4.0
    assert run.results[0].status == EvalStatus.FAIL
    assert run.status == EvalStatus.FAIL


def test_deliberately_poor_quality_fails_only_the_soft_threshold() -> None:
    run = asyncio.run(
        run_suite(
            load_suite(FIXTURE),
            selection=EvalSelection(scenario_id="context.recent-local-selected"),
            judge=_MappedJudge(
                {
                    QualityDimension.CONTEXT_USE: 0.0,
                    QualityDimension.RELEVANCE: 0.0,
                }
            ),
        )
    )

    assert run.results[0].normalized_score == 0.0
    assert run.results[0].status == EvalStatus.FAIL
    assert all(gate.status == EvalStatus.PASS for gate in run.results[0].hard_gates)
    terminal = render_terminal(run)
    assert "soft_quality: expected at least 3.0; observed 0.0" in terminal


def test_missing_required_judge_dimension_is_not_evaluated() -> None:
    missing = asyncio.run(
        run_suite(
            load_suite(FIXTURE),
            selection=EvalSelection(scenario_id="personality.concise-answer"),
            judge=_MappedJudge({QualityDimension.PERSONALITY_ADHERENCE: 4.0}),
        )
    )
    incompatible = asyncio.run(
        run_suite(
            load_suite(FIXTURE),
            selection=EvalSelection(scenario_id="personality.concise-answer"),
            judge=_MappedJudge(
                {
                    QualityDimension.PERSONALITY_ADHERENCE: 4.0,
                    QualityDimension.CONCISION: 4.0,
                },
                output_version="judge.incompatible-v1",
            ),
        )
    )

    assert missing.status == EvalStatus.PASS
    assert missing.results[0].status == EvalStatus.NOT_EVALUATED
    assert missing.results[0].normalized_score is None
    assert incompatible.results[0].status == EvalStatus.NOT_EVALUATED
    assert all(
        item.reason == "incompatible judge version"
        for item in incompatible.results[0].dimensions
    )


def test_weighted_soft_score_uses_declared_dimension_weights() -> None:
    run = asyncio.run(
        run_suite(
            load_suite(FIXTURE),
            selection=EvalSelection(scenario_id="personality.concise-answer"),
            judge=_MappedJudge(
                {
                    QualityDimension.PERSONALITY_ADHERENCE: 4.0,
                    QualityDimension.CONCISION: 2.0,
                }
            ),
        )
    )

    assert run.results[0].normalized_score == 3.3333
    assert run.results[0].status == EvalStatus.PASS


class _ExplodingEvaluator:
    kind = EvaluatorKind.PLANNING

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation:
        del scenario
        raise RuntimeError("sensitive synthetic detail must not escape")


class _ExplodingJudge:
    version = "judge.error-v1"

    async def score(
        self, scenario: EvalScenario, observation: EvalObservation
    ) -> JudgeOutput:
        del scenario, observation
        raise RuntimeError("sensitive synthetic detail must not escape")


def test_unexpected_evaluator_and_judge_errors_fail_closed_without_detail() -> None:
    evaluator_run = _run(
        registry={EvaluatorKind.PLANNING: _ExplodingEvaluator()},
        selection=EvalSelection(scenario_id="planning.governance-denied"),
    )
    judge_run = asyncio.run(
        run_suite(
            load_suite(FIXTURE),
            selection=EvalSelection(scenario_id="personality.concise-answer"),
            judge=_ExplodingJudge(),
        )
    )

    assert evaluator_run.status == EvalStatus.ERROR
    assert evaluator_run.results[0].failure_reason == (
        "evaluator input or execution failed"
    )
    assert judge_run.status == EvalStatus.ERROR
    assert judge_run.results[0].failure_reason == "judge execution failed"
    assert "sensitive synthetic detail" not in render_json(evaluator_run)
    assert "sensitive synthetic detail" not in render_json(judge_run)


def test_duplicate_scenario_ids_are_rejected(tmp_path: Path) -> None:
    raw = _raw_suite()
    scenarios = raw["scenarios"]
    assert isinstance(scenarios, list)
    scenarios[-1] = scenarios[0]

    with pytest.raises(FixtureError, match="scenario IDs must be unique"):
        load_suite(_write_fixture(tmp_path, raw))


def test_versions_empty_suite_and_malformed_json_are_rejected(
    tmp_path: Path,
) -> None:
    raw = _raw_suite()
    raw["schema_version"] = "ai-eval-suite-v2"
    with pytest.raises(FixtureError, match="schema_version"):
        load_suite(_write_fixture(tmp_path, raw))

    raw = _raw_suite()
    raw["scenarios"] = []
    with pytest.raises(FixtureError, match="scenarios"):
        load_suite(_write_fixture(tmp_path, raw))

    path = tmp_path / "malformed.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(FixtureError, match="not valid JSON"):
        load_suite(path)


def test_rubric_bounds_and_unknown_dimension_are_rejected(tmp_path: Path) -> None:
    raw = _raw_suite()
    raw["scenarios"][0]["rubric"]["threshold"] = 4.1  # type: ignore[index]
    with pytest.raises(FixtureError, match="threshold"):
        load_suite(_write_fixture(tmp_path, raw))

    raw = _raw_suite()
    raw["scenarios"][0]["rubric"]["dimensions"][0]["dimension"] = (  # type: ignore[index]
        "warmth_guess"
    )
    with pytest.raises(FixtureError, match="rubric"):
        load_suite(_write_fixture(tmp_path, raw))


def test_implicit_live_provider_mode_is_rejected(tmp_path: Path) -> None:
    raw = _raw_suite()
    raw["scenarios"][0]["provider_mode"] = "live"  # type: ignore[index]

    with pytest.raises(FixtureError, match="provider_mode"):
        load_suite(_write_fixture(tmp_path, raw))


def test_unknown_evaluator_and_unknown_gate_are_rejected(tmp_path: Path) -> None:
    raw = _raw_suite()
    raw["scenarios"][0]["evaluator"] = "dynamic.module"  # type: ignore[index]
    with pytest.raises(FixtureError, match="evaluator"):
        load_suite(_write_fixture(tmp_path, raw))

    raw = _raw_suite()
    raw["scenarios"][0]["hard_expectations"][0]["gate"] = "maybe_safe"  # type: ignore[index]
    with pytest.raises(FixtureError, match="hard_expectations"):
        load_suite(_write_fixture(tmp_path, raw))


def test_secret_fields_and_credential_shapes_are_rejected(tmp_path: Path) -> None:
    raw = _raw_suite()
    raw["scenarios"][0]["input"]["bot_token"] = "synthetic"  # type: ignore[index]
    with pytest.raises(FixtureError, match="prohibited"):
        load_suite(_write_fixture(tmp_path, raw))

    raw = _raw_suite()
    raw["scenarios"][0]["turns"][0]["content"] = (  # type: ignore[index]
        "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
    )
    with pytest.raises(FixtureError, match="credential-shaped"):
        load_suite(_write_fixture(tmp_path, raw))


def test_canonical_loader_rejects_non_synthetic_provenance(tmp_path: Path) -> None:
    raw = _raw_suite()
    raw["scenarios"][0]["provenance"] = {  # type: ignore[index]
        "kind": "manually_sanitized",
        "source": "explicit future review record",
    }
    path = _write_fixture(tmp_path, raw)

    with pytest.raises(FixtureError, match="repository synthetic"):
        load_suite(path)
    assert load_suite(path, canonical=False).scenarios[0].provenance.source


def test_foreign_assistant_and_tenant_data_remain_excluded() -> None:
    run = _run()
    by_id = {result.scenario_id: result for result in run.results}

    for scenario_id in (
        "personality.foreign-assistant-rejected",
        "memory.foreign-assistant-excluded",
        "multi-tenant.foreign-tenant-history",
        "multi-tenant.sibling-assistant-memory",
    ):
        assert by_id[scenario_id].status == EvalStatus.PASS
        assert all(
            gate.status == EvalStatus.PASS for gate in by_id[scenario_id].hard_gates
        )


def test_presence_hard_scenarios_are_bounded_and_offline() -> None:
    suite = load_suite(FIXTURE)
    run = _run()
    results = {result.scenario_id: result for result in run.results}
    presence = [item for item in suite.scenarios if item.id.startswith("presence.")]

    assert len(presence) == 10
    for scenario in presence:
        assert scenario.evaluator == EvaluatorKind.PRESENCE
        assert results[scenario.id].status == EvalStatus.PASS
        assert all(
            gate.status == EvalStatus.PASS for gate in results[scenario.id].hard_gates
        )


def test_presence_hard_gate_mutations_turn_red() -> None:
    suite = load_suite(FIXTURE)
    scenario = next(
        item for item in suite.scenarios if item.id == "presence.direct-bounded"
    )
    observed = asyncio.run(
        default_registry()[EvaluatorKind.PRESENCE].evaluate(scenario.execution_case())
    )
    mutated = observed.model_copy(
        update={
            "presence_attempts": 6,
            "presence_after_terminal": 1,
            "heartbeat_bound": False,
        }
    )
    results = evaluate_hard_gates(scenario.hard_expectations, mutated)
    by_gate = {result.gate: result for result in results}

    assert by_gate[HardGate.PRESENCE_ATTEMPTS].status == EvalStatus.FAIL
    assert by_gate[HardGate.PRESENCE_AFTER_TERMINAL].status == EvalStatus.FAIL
    assert by_gate[HardGate.HEARTBEAT_BOUND].status == EvalStatus.FAIL


def test_hard_gate_failure_reports_bounded_facts_without_response() -> None:
    scenario = load_suite(FIXTURE).scenarios[0]
    observation = EvalObservation(
        tenant_id=scenario.scope.tenant_id,
        assistant_id=scenario.scope.assistant_id,
        should_respond=False,
        response_text="private synthetic output",
    )
    results = evaluate_hard_gates(
        (
            HardExpectation(gate=HardGate.MUST_RESPOND, expected=True),
            HardExpectation(gate=HardGate.FORBIDDEN_PHRASE, expected="private"),
        ),
        observation,
    )

    assert results[0].status == EvalStatus.FAIL
    assert results[0].observed == "false"
    assert results[1].status == EvalStatus.FAIL
    assert all("private synthetic output" not in result.observed for result in results)


def test_not_evaluated_terminal_output_identifies_dimensions() -> None:
    run = _run(selection=EvalSelection(scenario_id="personality.concise-answer"))

    terminal = render_terminal(run)
    assert "personality_adherence: NOT_EVALUATED — judge disabled" in terminal
    assert "concision: NOT_EVALUATED — judge disabled" in terminal


def test_conflicting_and_mistyped_hard_expectations_are_rejected(
    tmp_path: Path,
) -> None:
    raw = _raw_suite()
    raw["scenarios"][0]["hard_expectations"] = [  # type: ignore[index]
        {"gate": "must_respond", "expected": True},
        {"gate": "must_not_respond", "expected": True},
    ]
    with pytest.raises(FixtureError, match="both require response and silence"):
        load_suite(_write_fixture(tmp_path, raw))

    raw = _raw_suite()
    raw["scenarios"][0]["hard_expectations"][0]["expected"] = 1  # type: ignore[index]
    with pytest.raises(FixtureError, match="expects a boolean"):
        load_suite(_write_fixture(tmp_path, raw))


def test_cli_runs_without_telegram_or_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in (
        "JANUARY_TELEGRAM_BOT_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    assert main(["--scenario", "planning.governance-denied"]) == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_json_stdout_is_machine_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--scenario", "planning.authorized-fallback", "--json", "-"]) == 0
    output = capsys.readouterr().out

    assert json.loads(output)["status"] == "PASS"
    assert not output.startswith("AI eval suite")


def test_cli_writes_report_and_returns_two_for_bad_selection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = tmp_path / "report.json"
    assert main(["--category", "media", "--json", str(report)]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "PASS"

    assert main(["--scenario", "missing.scenario"]) == 2
    assert "configuration error" in capsys.readouterr().err


def test_cli_rejects_live_judge_before_execution() -> None:
    with pytest.raises(SystemExit) as error:
        main(["--judge", "live"])

    assert error.value.code == 2
