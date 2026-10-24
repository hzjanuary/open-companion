"""Hermetic proof of the operational worker launcher, not new product behavior."""

import importlib.util
import json
import logging
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolate_operational_loggers(monkeypatch: pytest.MonkeyPatch) -> None:
    # A launcher owns fresh process loggers in production. Preserve other tests'
    # handlers and streams while proving that fresh operational setup here.
    for name in ("january", "__main__"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "handlers", [])
        monkeypatch.setattr(logger, "level", logging.NOTSET)
        monkeypatch.setattr(logger, "propagate", True)


@pytest.fixture
def launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "self_host_runtime_under_test", ROOT / "scripts/self_host/runtime.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def acceptance_harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "self_host_acceptance_under_test",
        ROOT / "backend/tests/integration/test_self_host_runtime.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "executable,status,category",
    [
        ("curl", 7, "connection_failed"),
        ("curl", 22, "http_error"),
        ("curl", 28, "timeout"),
        ("docker", 1, "command_failure"),
    ],
)
def test_acceptance_failure_keeps_exit_category_without_private_details(
    executable: str,
    status: int,
    category: str,
    acceptance_harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "SYNTHETIC-PRIVATE-COMMAND-DETAIL"
    command = [executable, canary]
    monkeypatch.setattr(
        acceptance_harness.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            command, status, stdout=canary, stderr=canary
        ),
    )
    with pytest.raises(AssertionError) as error:
        acceptance_harness.execute(command)
    message = str(error.value)
    assert f"{executable} exit={status} category={category}" in message
    assert canary not in message


def test_acceptance_success_preserves_command_output(
    acceptance_harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        acceptance_harness.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            ["docker"], 0, stdout="safe-metadata", stderr=""
        ),
    )
    assert acceptance_harness.execute(["docker"]) == "safe-metadata"


WORKERS = (
    "telegram_poller",
    "ingress_outbox_dispatcher",
    "conversation_worker",
    "response_planning_worker",
    "telegram_command_worker",
    "outbound_delivery_worker",
    "provider_governance_worker",
    "governance_worker",
    "retention_worker",
    "proactive_scheduler_worker",
    "conversation_summary_worker",
    "semantic_memory_index_worker",
    "knowledge_index_worker",
)


@pytest.mark.parametrize("worker", WORKERS)
def test_launcher_only_runs_existing_module_after_safe_logging(
    worker: str, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, object]] = []

    def settings(**kwargs: object) -> SimpleNamespace:
        assert kwargs == {"_env_file": None}
        calls.append(("settings", None))
        return SimpleNamespace(log_level="INFO")

    def run_module(module: str, *, run_name: str) -> None:
        assert run_name == "__main__"
        assert sys.argv == [module]
        assert (ROOT / "backend/app/runtime" / f"{worker}.py").is_file()
        calls.append(("worker", module))

    monkeypatch.setattr(launcher, "Settings", settings)
    monkeypatch.setattr(
        launcher, "configure_logging", lambda level: calls.append(("logging", level))
    )
    monkeypatch.setattr(launcher.runpy, "run_module", run_module)
    monkeypatch.setattr(sys, "argv", ["runtime.py", worker])
    assert launcher.main() == 0
    assert calls == [
        ("settings", None),
        ("logging", "INFO"),
        ("worker", f"app.runtime.{worker}"),
    ]


@pytest.mark.parametrize("worker", ["unknown", "os", "../telegram_poller"])
def test_launcher_rejects_unapproved_entrypoints_before_settings(
    worker: str, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_settings(**_: object) -> None:
        pytest.fail("Settings must not load for an unapproved entrypoint")

    monkeypatch.setattr(launcher, "Settings", forbidden_settings)
    monkeypatch.setattr(sys, "argv", ["runtime.py", worker])
    with pytest.raises(SystemExit) as result:
        launcher.main()
    assert result.value.code == 2


def test_launcher_redacts_configuration_failure_and_runs_no_worker(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    canary = "SYNTHETIC-DO-NOT-LEAK-LAUNCHER"

    def invalid_settings(**_: object) -> None:
        raise ValidationError.from_exception_data(
            "Settings",
            [{"type": "missing", "loc": ("secret",), "input": canary}],
        )

    def forbidden_run(*_: object, **__: object) -> None:
        pytest.fail("Invalid settings must never start a worker")

    monkeypatch.setattr(launcher, "Settings", invalid_settings)
    monkeypatch.setattr(launcher.runpy, "run_module", forbidden_run)
    monkeypatch.setattr(sys, "argv", ["runtime.py", "telegram_poller"])
    assert launcher.main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Worker configuration invalid (values redacted).\n"
    assert canary not in output.out + output.err


def test_launcher_preserves_worker_failure_exit(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        launcher, "Settings", lambda **_: SimpleNamespace(log_level="INFO")
    )
    monkeypatch.setattr(launcher, "configure_logging", lambda _: None)

    def failed_worker(*_: object, **__: object) -> None:
        raise SystemExit(7)

    monkeypatch.setattr(launcher.runpy, "run_module", failed_worker)
    monkeypatch.setattr(sys, "argv", ["runtime.py", "telegram_poller"])
    with pytest.raises(SystemExit) as result:
        launcher.main()
    assert result.value.code == 7


def test_existing_logging_configuration_does_not_enable_http_client_logs(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = logging.getLogger()
    httpx = logging.getLogger("httpx")
    httpcore = logging.getLogger("httpcore")
    before = [
        (logger.level, tuple(logger.handlers)) for logger in (root, httpx, httpcore)
    ]
    monkeypatch.setattr(
        launcher, "Settings", lambda **_: SimpleNamespace(log_level="INFO")
    )
    monkeypatch.setattr(launcher.runpy, "run_module", lambda *_, **__: None)
    monkeypatch.setattr(sys, "argv", ["runtime.py", "telegram_poller"])
    assert launcher.main() == 0
    assert [
        (logger.level, tuple(logger.handlers)) for logger in (root, httpx, httpcore)
    ] == before


def test_runpy_worker_info_uses_existing_json_formatter_without_root_propagation(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(
        launcher, "Settings", lambda **_: SimpleNamespace(log_level="INFO")
    )

    def worker(module: str, *, run_name: str) -> None:
        assert module == "app.runtime.conversation_worker" and run_name == "__main__"
        logger = logging.getLogger(run_name)
        assert logger.propagate is False
        assert logger.handlers == logging.getLogger("january").handlers
        logger.info("conversation event processed")

    monkeypatch.setattr(launcher.runpy, "run_module", worker)
    monkeypatch.setattr(sys, "argv", ["runtime.py", "conversation_worker"])
    assert launcher.main() == 0
    output = capsys.readouterr()
    assert output.out == ""
    record = json.loads(output.err)
    assert record["logger"] == "__main__"
    assert record["level"] == "INFO"
    assert record["message"] == "conversation event processed"
