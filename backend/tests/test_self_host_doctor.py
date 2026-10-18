"""Hermetic Docker-only preflight proof; fake CLI rejects every live/mutating call."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCTOR = ROOT / "scripts/self-host-doctor.sh"
COMPOSE = ROOT / "scripts/self-host-compose.sh"
CANARY = "CLOSED-DOCTOR-CANARY-SECRET-32-PLUS"
TOKEN = "999999999:closed_offline_token"
TENANT = "71000000-0000-4000-8000-000000000001"
CONNECTION = "71000000-0000-4000-8000-000000000003"


@pytest.fixture
def operator_files(tmp_path: Path) -> tuple[Path, Path]:
    source = (ROOT / ".env.self-host.example").read_text()
    updates = {
        "JANUARY_DATABASE_PASSWORD": CANARY,
        "JANUARY_CONTROL_PLANE_JWT_SECRET": CANARY,
        "JANUARY_CONTROL_PLANE_DEPLOYMENT_BOOTSTRAP_SUBJECTS": "[]",
        "JANUARY_TELEGRAM_BOT_TOKEN": TOKEN,
        "JANUARY_TELEGRAM_TENANT_ID": TENANT,
        "JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID": CONNECTION,
        "JANUARY_LLM_OPENAI_MODEL": "fixture-schema-model",
        "JANUARY_LLM_OPENAI_API_KEY": CANARY,
    }
    for key, value in updates.items():
        source = (
            "\n".join(
                f"{key}={value}" if line.startswith(f"{key}=") else line
                for line in source.splitlines()
            )
            + "\n"
        )
    config = tmp_path / ".env.self-host"
    config.write_text(source)
    config.chmod(0o600)
    # Static doctor deliberately does not claim complete JSON/Settings typing;
    # the explicit image check uses the real setup helper for that contract.
    policy = tmp_path / "policy.json"
    source = json.loads(
        (ROOT / "docs/examples/self-host-provider-policy.json").read_text()
    )
    source.update(
        json_schema_supported=True,
        input_microusd_per_million=1_000_000,
        output_microusd_per_million=2_000_000,
        health={
            "observation_window_seconds": 300,
            "degraded_threshold": 3,
            "unavailable_threshold": 5,
            "recovery_success_threshold": 2,
            "stale_after_seconds": 3600,
        },
        budgets=[
            {
                "measurement": "requests",
                "window_kind": "daily_utc",
                "amount": 10,
                "alert_threshold_bps": 8000,
            }
        ],
    )
    policy.write_text(json.dumps(source))
    return config, policy


@pytest.fixture
def fake_docker(tmp_path: Path) -> tuple[Path, Path]:
    directory = tmp_path / "bin"
    directory.mkdir()
    log = tmp_path / "docker-calls.txt"
    fake = directory / "docker"
    fake.write_text("""#!/usr/bin/env bash
set -euo pipefail
case "$1:${2:-}" in
  compose:version)
    printf '%s\\n' version >> "$DOCTOR_LOG"
    [[ "${COMPOSE_MISSING:-0}" == 0 ]] ;;
  compose:*)
    [[ "$*" == *' config --quiet' || "${ALLOW_EXPORT:-0}" == 1 ]] || exit 91
    [[ "$*" == *'--env-file /dev/null'* ]] || exit 92
    [[ -z "${JANUARY_TELEGRAM_BOT_TOKEN+x}" ]] || exit 93
    if [[ -n "${EXPECTED_PASSWORD+x}" ]]; then
      [[ "${JANUARY_DATABASE_PASSWORD:-}" == "$EXPECTED_PASSWORD" ]] || exit 94
    fi
    [[ "${JANUARY_HOST_PORT:-8000}" == 8000 ]] || exit 95
    printf '%s\\n' config >> "$DOCTOR_LOG"
    if [[ "${COMPOSE_FAILURE:-0}" == 1 ]]; then
      printf '%s\\n' "$DOCTOR_CANARY" >&2
      exit 1
    fi ;;
  image:inspect)
    printf '%s\\n' inspect >> "$DOCTOR_LOG"
    [[ "${IMAGE_MISSING:-0}" == 0 ]] ;;
  run:*)
    [[ "${TYPED_ALLOWED:-0}" == 1 ]] || exit 96
    for required in '--pull never' '--network none' '--read-only' \\
      '--cap-drop ALL' '--security-opt no-new-privileges'; do
      [[ "$*" == *"$required"* ]] || exit 97
    done
    [[ "$*" != *'--user 0:'* ]] || exit 98
    [[ "$*" == *'setup_operator.py check --phase '* ]] || exit 99
    printf '%s\\n' run >> "$DOCTOR_LOG"
    if [[ "${TYPED_FAILURE:-0}" == 1 ]]; then
      printf '%s\\n' "$DOCTOR_CANARY" >&2
      exit 1
    fi ;;
  *) exit 90 ;;
esac
""")
    fake.chmod(0o755)
    return directory, log


def _change(path: Path, key: str, value: str) -> None:
    source = path.read_text()
    if f"{key}=" not in source:
        source += f"{key}={value}\n"
    else:
        source = (
            "\n".join(
                f"{key}={value}" if line.startswith(f"{key}=") else line
                for line in source.splitlines()
            )
            + "\n"
        )
    path.write_text(source)


def _run(
    files: tuple[Path, Path],
    fake: tuple[Path, Path],
    *arguments: str,
    environment: dict[str, str] | None = None,
    trace: bool = False,
) -> subprocess.CompletedProcess[str]:
    selected_environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("JANUARY_")
    }
    selected_environment.update(
        PATH=f"{fake[0]}:{os.environ['PATH']}",
        DOCTOR_LOG=str(fake[1]),
        DOCTOR_CANARY=CANARY,
        # A dirty caller must not override the selected raw file for rendering.
        JANUARY_HOST_PORT="broken-port-canary",
        JANUARY_TELEGRAM_BOT_TOKEN=CANARY,
    )
    selected_environment.update(environment or {})
    command = (["bash", "-x", str(DOCTOR)] if trace else [str(DOCTOR)]) + [
        "--offline",
        "--config",
        str(files[0]),
        "--policy",
        str(files[1]),
        *arguments,
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=selected_environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert CANARY not in result.stdout + result.stderr
    assert TOKEN not in result.stdout + result.stderr
    return result


def test_polling_without_https_or_optional_keys_is_static_only_and_read_only(
    operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path]
) -> None:
    before = operator_files[0].read_bytes()
    result = _run(operator_files, fake_docker)
    assert result.returncode == 0
    assert "offline static polling/runtime" in result.stdout
    assert "typed Settings/policy NOT verified" in result.stdout
    assert "Not verified: persisted authority/policies" in result.stdout
    assert fake_docker[1].read_text().splitlines() == ["version", "config"]
    assert operator_files[0].read_bytes() == before


@pytest.mark.parametrize("phase", ["template", "setup"])
def test_phase_specific_checks_do_not_require_missing_runtime_ids(
    phase: str, operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path]
) -> None:
    for name in (
        "JANUARY_TELEGRAM_TENANT_ID",
        "JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID",
    ):
        _change(operator_files[0], name, "")
    if phase == "template":
        for name in (
            "JANUARY_DATABASE_PASSWORD",
            "JANUARY_CONTROL_PLANE_JWT_SECRET",
            "JANUARY_TELEGRAM_BOT_TOKEN",
            "JANUARY_LLM_OPENAI_API_KEY",
        ):
            _change(operator_files[0], name, "")
    result = _run(operator_files, fake_docker, "--phase", phase)
    assert result.returncode == 0
    assert f"polling/{phase}" in result.stdout
    runtime = _run(operator_files, fake_docker)
    assert runtime.returncode == 1


def test_missing_config_stops_before_docker(
    tmp_path: Path, fake_docker: tuple[Path, Path]
) -> None:
    result = _run((tmp_path / "missing", tmp_path / "policy.json"), fake_docker)
    assert result.returncode == 1
    assert "regular private configuration" in result.stderr
    assert not fake_docker[1].exists()


@pytest.mark.parametrize(
    "key,value,message",
    [
        ("JANUARY_TELEGRAM_BOT_TOKEN", "your_bot_token", "placeholder"),
        ("JANUARY_LLM_OPENAI_API_KEY", "", "JANUARY_LLM_OPENAI_API_KEY"),
        ("JANUARY_LLM_OPENAI_MODEL", "", "JANUARY_LLM_OPENAI_MODEL"),
        ("JANUARY_LLM_ENABLED", "false", "guarded text chat"),
        ("JANUARY_TELEGRAM_ENABLED", "false", "guarded text chat"),
        (
            "JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID",
            "private-invalid-id",
            "canonical UUID",
        ),
        (
            "JANUARY_CONTROL_PLANE_DEPLOYMENT_BOOTSTRAP_SUBJECTS",
            '["self-host-operator"]',
            "clear initial bootstrap",
        ),
        ("JANUARY_CONVERSATION_SUMMARIES_ENABLED", "true", "enabled/disabled together"),
        ("JANUARY_PROACTIVE_SCHEDULING_ENABLED", "true", "enabled/disabled together"),
        ("JANUARY_TELEGRAM_VOICE_TTS_ENABLED", "invalid-canary", "true/false"),
    ],
)
def test_static_blockers_are_actionable_without_values(
    key: str,
    value: str,
    message: str,
    operator_files: tuple[Path, Path],
    fake_docker: tuple[Path, Path],
) -> None:
    _change(operator_files[0], key, value)
    result = _run(operator_files, fake_docker)
    assert result.returncode == 1 and message in result.stderr
    assert not fake_docker[1].exists()


@pytest.mark.parametrize("missing", ["url", "secret", "http"])
def test_webhook_requires_its_conditional_https_and_secret(
    missing: str, operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path]
) -> None:
    _change(operator_files[0], "JANUARY_TELEGRAM_DELIVERY_MODE", "webhook")
    _change(
        operator_files[0],
        "JANUARY_TELEGRAM_WEBHOOK_PUBLIC_BASE_URL",
        "https://bot.example.org",
    )
    _change(operator_files[0], "JANUARY_TELEGRAM_WEBHOOK_SECRET_TOKEN", CANARY)
    if missing == "url":
        _change(operator_files[0], "JANUARY_TELEGRAM_WEBHOOK_PUBLIC_BASE_URL", "")
    elif missing == "secret":
        _change(operator_files[0], "JANUARY_TELEGRAM_WEBHOOK_SECRET_TOKEN", "")
    else:
        _change(
            operator_files[0],
            "JANUARY_TELEGRAM_WEBHOOK_PUBLIC_BASE_URL",
            "http://bot.example.org",
        )
    result = _run(operator_files, fake_docker, "--profile", "webhook")
    assert result.returncode == 1
    assert not fake_docker[1].exists()


def test_complete_webhook_statically_renders_without_public_network(
    operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path]
) -> None:
    _change(operator_files[0], "JANUARY_TELEGRAM_DELIVERY_MODE", "webhook")
    _change(
        operator_files[0],
        "JANUARY_TELEGRAM_WEBHOOK_PUBLIC_BASE_URL",
        "https://bot.example.org",
    )
    _change(operator_files[0], "JANUARY_TELEGRAM_WEBHOOK_SECRET_TOKEN", CANARY)
    assert _run(operator_files, fake_docker, "--profile", "webhook").returncode == 0


@pytest.mark.parametrize("provider", ["gemini", "groq", "openrouter"])
def test_non_openai_text_provider_needs_only_its_key_not_tts_credentials(
    provider: str, operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path]
) -> None:
    _change(operator_files[0], "JANUARY_LLM_PRIMARY_PROVIDER", provider)
    _change(operator_files[0], "JANUARY_LLM_OPENAI_API_KEY", "")
    _change(
        operator_files[0],
        f"JANUARY_LLM_{provider.upper()}_MODEL",
        "fixture-schema-model",
    )
    _change(operator_files[0], f"JANUARY_LLM_{provider.upper()}_API_KEY", CANARY)
    assert _run(operator_files, fake_docker).returncode == 0


def test_fallback_still_requires_actual_selected_credentials_and_distinct_provider(
    operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path]
) -> None:
    _change(operator_files[0], "JANUARY_LLM_FALLBACK_PROVIDER", "gemini")
    assert _run(operator_files, fake_docker).returncode == 1
    _change(operator_files[0], "JANUARY_LLM_GEMINI_MODEL", "fixture-schema-model")
    _change(operator_files[0], "JANUARY_LLM_GEMINI_API_KEY", CANARY)
    assert _run(operator_files, fake_docker).returncode == 0
    _change(operator_files[0], "JANUARY_LLM_FALLBACK_PROVIDER", "openai")
    assert _run(operator_files, fake_docker).returncode == 1


@pytest.mark.parametrize(
    "feature,worker,profile",
    [
        (
            "JANUARY_SEMANTIC_MEMORY_ENABLED",
            "JANUARY_SEMANTIC_MEMORY_WORKER_ENABLED",
            "semantic-memory",
        ),
        (
            "JANUARY_KNOWLEDGE_RAG_ENABLED",
            "JANUARY_KNOWLEDGE_INDEX_WORKER_ENABLED",
            "knowledge-rag",
        ),
    ],
)
def test_enabled_qdrant_feature_requires_profile_embedding_and_reachable_address(
    feature: str,
    worker: str,
    profile: str,
    operator_files: tuple[Path, Path],
    fake_docker: tuple[Path, Path],
) -> None:
    _change(operator_files[0], feature, "true")
    _change(operator_files[0], worker, "true")
    assert _run(operator_files, fake_docker).returncode == 1
    result = _run(operator_files, fake_docker, "--enable", profile)
    assert result.returncode == 1 and "Ollama embedding" in result.stderr
    _change(operator_files[0], "JANUARY_EMBEDDING_PROVIDER", "ollama")
    _change(operator_files[0], "JANUARY_EMBEDDING_MODEL", "fixture-embedding")
    assert (
        "Container-local Ollama"
        in _run(operator_files, fake_docker, "--enable", profile).stderr
    )
    _change(
        operator_files[0], "JANUARY_LLM_OLLAMA_BASE_URL", "http://model-server:11434"
    )
    assert _run(operator_files, fake_docker, "--enable", profile).returncode == 0


def test_ollama_text_needs_no_cloud_or_tts_key_but_not_container_loopback(
    operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path]
) -> None:
    _change(operator_files[0], "JANUARY_LLM_PRIMARY_PROVIDER", "ollama")
    _change(operator_files[0], "JANUARY_LLM_OPENAI_API_KEY", "")
    _change(operator_files[0], "JANUARY_LLM_OLLAMA_MODEL", "fixture-schema-model")
    policy = json.loads(operator_files[1].read_text())
    policy["data_class"] = "local"
    operator_files[1].write_text(json.dumps(policy))
    assert _run(operator_files, fake_docker).returncode == 1
    _change(
        operator_files[0], "JANUARY_LLM_OLLAMA_BASE_URL", "http://model-server:11434"
    )
    assert _run(operator_files, fake_docker).returncode == 0
    _change(operator_files[0], "JANUARY_TELEGRAM_VOICE_TTS_ENABLED", "true")
    result = _run(operator_files, fake_docker)
    assert result.returncode == 1 and "JANUARY_LLM_OPENAI_API_KEY" in result.stderr


def test_raw_literal_dollars_are_not_expanded_or_executed(
    operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path], tmp_path: Path
) -> None:
    marker = tmp_path / "no-execution"
    literal = f"$DOCTOR_CANARY$(touch {marker})"
    _change(operator_files[0], "JANUARY_DATABASE_PASSWORD", literal)
    result = _run(
        operator_files,
        fake_docker,
        environment={"EXPECTED_PASSWORD": literal},
        trace=True,
    )
    assert result.returncode == 0
    assert not marker.exists()


@pytest.mark.parametrize(
    "issue", ["permissions", "duplicate", "symlink", "unknown", "crlf", "quoted"]
)
def test_private_raw_file_shape_blocks_before_cli(
    issue: str,
    operator_files: tuple[Path, Path],
    fake_docker: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    config = operator_files[0]
    if issue == "permissions":
        config.chmod(0o644)
    elif issue == "duplicate":
        config.write_text(config.read_text() + f"JANUARY_TELEGRAM_BOT_TOKEN={CANARY}\n")
    elif issue == "symlink":
        link = tmp_path / "linked"
        link.symlink_to(config)
        operator_files = link, operator_files[1]
    elif issue == "unknown":
        config.write_text(
            config.read_text() + f"JANUARY_NONEXISTENT_SETTING={CANARY}\n"
        )
    elif issue == "crlf":
        config.write_bytes(config.read_bytes().replace(b"\n", b"\r\n"))
    else:
        _change(config, "JANUARY_TELEGRAM_BOT_TOKEN", f'"{CANARY}"')
    assert _run(operator_files, fake_docker).returncode == 1
    assert not fake_docker[1].exists()


@pytest.mark.parametrize(
    "failure", ["COMPOSE_FAILURE", "TYPED_FAILURE", "IMAGE_MISSING"]
)
def test_cli_errors_are_redacted_and_never_report_success(
    failure: str, operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path]
) -> None:
    args = () if failure == "COMPOSE_FAILURE" else ("--typed",)
    result = _run(
        operator_files,
        fake_docker,
        *args,
        environment={failure: "1", "TYPED_ALLOWED": "1"},
    )
    assert result.returncode == 1
    assert "PASS:" not in result.stdout


def test_typed_mode_is_explicit_network_disabled_and_no_auto_pull_build(
    operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path]
) -> None:
    result = _run(
        operator_files, fake_docker, "--typed", environment={"TYPED_ALLOWED": "1"}
    )
    assert result.returncode == 0 and "offline typed polling/runtime" in result.stdout
    assert fake_docker[1].read_text().splitlines() == [
        "version",
        "config",
        "inspect",
        "run",
    ]


def test_compose_wrapper_exports_only_literal_interpolation_fields(
    operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path]
) -> None:
    literal = "$UNDEFINED_PRIVATE_LITERAL"
    _change(operator_files[0], "JANUARY_DATABASE_PASSWORD", literal)
    environment = dict(os.environ)
    environment.update(
        PATH=f"{fake_docker[0]}:{os.environ['PATH']}",
        DOCTOR_LOG=str(fake_docker[1]),
        DOCTOR_CANARY=CANARY,
        JANUARY_TELEGRAM_BOT_TOKEN=CANARY,
        JANUARY_HOST_PORT="broken-port-canary",
        EXPECTED_PASSWORD=literal,
        ALLOW_EXPORT="1",
    )
    result = subprocess.run(
        [
            str(COMPOSE),
            "--config",
            str(operator_files[0]),
            "--profile",
            "polling",
            "config",
            "--quiet",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    assert CANARY not in result.stdout + result.stderr
    assert fake_docker[1].read_text().splitlines() == ["config"]


def _host_tools_only(directory: Path, fake: Path | None = None) -> str:
    directory.mkdir()
    for name in ("bash", "dirname", "basename", "stat", "wc", "awk", "tr", "id"):
        tool = shutil.which(name)
        assert tool is not None
        (directory / name).symlink_to(tool)
    if fake is not None:
        (directory / "docker").symlink_to(fake / "docker")
    return str(directory)


def test_default_needs_no_host_python_uv_or_git(
    operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path], tmp_path: Path
) -> None:
    selected_path = _host_tools_only(tmp_path / "minimal-host", fake_docker[0])
    result = _run(operator_files, fake_docker, environment={"PATH": selected_path})
    assert result.returncode == 0
    assert fake_docker[1].read_text().splitlines() == ["version", "config"]


def test_missing_docker_is_actionable_without_attempting_install(
    operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path], tmp_path: Path
) -> None:
    selected_path = _host_tools_only(tmp_path / "no-docker")
    result = _run(operator_files, fake_docker, environment={"PATH": selected_path})
    assert result.returncode == 1 and "Install Docker Engine/CLI" in result.stderr
    assert not fake_docker[1].exists()


def test_missing_compose_is_actionable_without_daemon_calls(
    operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path]
) -> None:
    result = _run(operator_files, fake_docker, environment={"COMPOSE_MISSING": "1"})
    assert result.returncode == 1 and "Docker Compose plugin" in result.stderr
    assert fake_docker[1].read_text().splitlines() == ["version"]


def test_unfilled_policy_is_not_reported_ready(
    operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path]
) -> None:
    operator_files[1].write_text(
        (ROOT / "docs/examples/self-host-provider-policy.json").read_text()
    )
    result = _run(operator_files, fake_docker)
    assert result.returncode == 1 and "intentionally incomplete" in result.stderr
    assert not fake_docker[1].exists()


def test_additional_static_migration_head_is_a_blocker(
    operator_files: tuple[Path, Path], fake_docker: tuple[Path, Path], tmp_path: Path
) -> None:
    candidate = tmp_path / "candidate"
    (candidate / "scripts/lib").mkdir(parents=True)
    shutil.copy(DOCTOR, candidate / "scripts/self-host-doctor.sh")
    shutil.copy(
        ROOT / "scripts/lib/self-host-env.sh",
        candidate / "scripts/lib/self-host-env.sh",
    )
    shutil.copy(ROOT / ".env.example", candidate / ".env.example")
    shutil.copytree(ROOT / "alembic/versions", candidate / "alembic/versions")
    (candidate / "alembic/versions/unexpected.py").write_text(
        'revision: str = "unexpected"\n'
        'down_revision: str | None = "0026_conversation_feedback"\n'
    )
    environment = dict(os.environ)
    environment.update(
        PATH=f"{fake_docker[0]}:{os.environ['PATH']}", DOCTOR_LOG=str(fake_docker[1])
    )
    result = subprocess.run(
        [
            str(candidate / "scripts/self-host-doctor.sh"),
            "--config",
            str(operator_files[0]),
            "--policy",
            str(operator_files[1]),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 1 and "single expected 0026 head" in result.stderr
    assert not fake_docker[1].exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["config"],
        ["config", "--format", "json"],
        ["config", "--quiet", "--environment"],
        ["config", "--output", "private-dump"],
    ],
)
def test_wrapper_refuses_accidental_secret_bearing_config_dumps(
    arguments: list[str],
    operator_files: tuple[Path, Path],
    fake_docker: tuple[Path, Path],
) -> None:
    environment = dict(os.environ)
    environment.update(
        PATH=f"{fake_docker[0]}:{os.environ['PATH']}", DOCTOR_LOG=str(fake_docker[1])
    )
    result = subprocess.run(
        [
            str(COMPOSE),
            "--config",
            str(operator_files[0]),
            "--profile",
            "polling",
            *arguments,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 1 and "dumps can expose secrets" in result.stderr
    assert CANARY not in result.stdout + result.stderr
    assert not fake_docker[1].exists()
