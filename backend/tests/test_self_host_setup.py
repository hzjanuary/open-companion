"""Offline setup-tool proof with synthetic operator material and fake boundaries."""

import asyncio
import importlib
import json
import sys
from pathlib import Path
from types import ModuleType
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from app.application.bootstrap import BootstrapResult
from app.application.ports.platform import BotIdentity
from app.domain.persistence import Platform

ROOT = Path(__file__).resolve().parents[2]
TENANT_ID = UUID("71000000-0000-4000-8000-000000000001")
ASSISTANT_ID = UUID("71000000-0000-4000-8000-000000000002")
CONNECTION_ID = UUID("71000000-0000-4000-8000-000000000003")
CAPABILITY_ID = UUID("71000000-0000-4000-8000-000000000004")
HEALTH_ID = UUID("71000000-0000-4000-8000-000000000005")
IDENTITY_ID = UUID("71000000-0000-4000-8000-000000000006")


@pytest.fixture
def setup_tool(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(ROOT / "scripts/self_host"))
    return importlib.import_module("setup_operator")


def _values(tool: ModuleType) -> dict[str, str]:
    values = tool.read_config(ROOT / ".env.self-host.example", private=False)
    values.update(
        JANUARY_DATABASE_PASSWORD="SYNTHETIC-DATABASE-SECRET",
        JANUARY_CONTROL_PLANE_JWT_SECRET="SYNTHETIC-OPERATOR-SECRET-THIRTY-TWO-PLUS",
        JANUARY_TELEGRAM_BOT_TOKEN="SYNTHETIC-TELEGRAM-TOKEN",
        JANUARY_LLM_OPENAI_MODEL="synthetic-schema-model",
        JANUARY_LLM_OPENAI_API_KEY="SYNTHETIC-PROVIDER-KEY",
    )
    return values


def _policy_source() -> dict[str, object]:
    return {
        "effective_at": "2000-01-01T00:00:00Z",
        "data_class": "approved_external",
        "json_schema_supported": True,
        "input_microusd_per_million": 1_000_000,
        "output_microusd_per_million": 2_000_000,
        "health": {
            "observation_window_seconds": 300,
            "degraded_threshold": 3,
            "unavailable_threshold": 5,
            "recovery_success_threshold": 2,
            "stale_after_seconds": 3600,
        },
        "budgets": [
            {
                "measurement": "requests",
                "window_kind": "daily_utc",
                "amount": 10,
                "alert_threshold_bps": 8000,
            }
        ],
    }


def _policy(tool: ModuleType, tmp_path: Path, values: dict[str, str]):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(_policy_source()))
    settings = tool.configured_settings(values, setup=True)
    return settings, tool.read_policy(path, settings)


def _identity() -> BotIdentity:
    return BotIdentity(
        Platform.TELEGRAM, "71000001", "synthetic_bot", "Synthetic", True, True, False
    )


def test_raw_reader_does_not_execute_or_expand_and_rejects_duplicates(
    setup_tool: ModuleType, tmp_path: Path
) -> None:
    marker = tmp_path / "must-not-exist"
    path = tmp_path / ".env.self-host"
    payload = f"$(touch {marker})"
    path.write_text(f"JANUARY_APP_NAME={payload}\nJANUARY_LLM_OPENAI_API_KEY=$UNSET\n")
    path.chmod(0o600)
    values = setup_tool.read_config(path)
    assert values["JANUARY_APP_NAME"] == payload
    assert values["JANUARY_LLM_OPENAI_API_KEY"] == "$UNSET"
    assert not marker.exists()
    path.write_text("JANUARY_APP_NAME=one\nJANUARY_APP_NAME=two\n")
    with pytest.raises(setup_tool.SetupError, match="Duplicate"):
        setup_tool.read_config(path)


def test_secret_init_is_private_idempotent_and_preserves_operator_values(
    setup_tool: ModuleType, tmp_path: Path
) -> None:
    path = tmp_path / ".env.self-host"
    original = (ROOT / ".env.self-host.example").read_text()
    path.write_text(
        original.replace(
            "JANUARY_TELEGRAM_BOT_TOKEN=",
            "JANUARY_TELEGRAM_BOT_TOKEN=SYNTHETIC-KEEP-ME",
        )
    )
    setup_tool.initialize(path)
    first = setup_tool.read_config(path)
    assert len(first["JANUARY_DATABASE_PASSWORD"]) == 64
    assert len(first["JANUARY_CONTROL_PLANE_JWT_SECRET"]) == 64
    assert (
        first["JANUARY_DATABASE_PASSWORD"] != first["JANUARY_CONTROL_PLANE_JWT_SECRET"]
    )
    assert first["JANUARY_TELEGRAM_BOT_TOKEN"] == "SYNTHETIC-KEEP-ME"
    assert path.stat().st_mode & 0o777 == 0o600
    before = path.read_bytes()
    setup_tool.initialize(path)
    assert path.read_bytes() == before
    assert "# Minimal guarded text-chat configuration" in path.read_text()


def test_example_and_symlink_never_receive_generated_secrets(
    setup_tool: ModuleType, tmp_path: Path
) -> None:
    path = tmp_path / ".env.self-host.example"
    original = (ROOT / ".env.self-host.example").read_text()
    path.write_text(original)
    with pytest.raises(setup_tool.SetupError, match="never an example"):
        setup_tool.initialize(path)
    assert path.read_text() == original
    link = tmp_path / ".env.self-host"
    link.symlink_to(path)
    with pytest.raises(setup_tool.SetupError, match="not a link"):
        setup_tool.initialize(link)
    assert path.read_text() == original


def test_unignored_local_suffix_is_not_a_secret_output_target(
    setup_tool: ModuleType, tmp_path: Path
) -> None:
    path = tmp_path / "settings.local"
    original = (ROOT / ".env.self-host.example").read_text()
    path.write_text(original)
    with pytest.raises(setup_tool.SetupError, match="ignored local configuration"):
        setup_tool.initialize(path)
    assert path.read_text() == original


def test_setup_rejects_unignored_target_before_any_live_clients(
    setup_tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.local"
    path.write_text((ROOT / ".env.self-host.example").read_text())
    path.chmod(0o600)

    def forbidden(*_, **__):
        pytest.fail("An unignored output target must be rejected before live clients")

    monkeypatch.setattr(setup_tool, "TelegramAdapter", forbidden)
    monkeypatch.setattr(setup_tool.httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "setup_operator.py",
            "setup",
            "--config",
            str(path),
            "--confirm-operator-setup",
            "--confirm-live-telegram",
        ],
    )
    assert asyncio.run(setup_tool.main()) == 1


def test_private_reader_rejects_shared_secret_file(
    setup_tool: ModuleType, tmp_path: Path
) -> None:
    path = tmp_path / ".env.self-host"
    path.write_text("JANUARY_APP_NAME=synthetic\n")
    path.chmod(0o644)
    with pytest.raises(setup_tool.SetupError, match="chmod 600"):
        setup_tool.read_config(path)


def test_setup_phase_is_enforced_and_runtime_phase_requires_real_connection(
    setup_tool: ModuleType, tmp_path: Path
) -> None:
    values = _values(setup_tool)
    settings, policy = _policy(setup_tool, tmp_path, values)
    assert settings.provider_governance_mode == "enforce"
    assert settings.control_plane_enabled and settings.rate_limit_enabled
    assert settings.provider_concurrency_enabled and settings.safety_moderation_enabled
    assert settings.telegram_delivery_mode == "disabled"
    assert not settings.llm_enabled and not settings.outbound_delivery_enabled
    assert policy.budgets[0].mode.value == "hard"
    assert policy.budgets[0].amount == 10
    with pytest.raises(ValidationError):
        setup_tool.configured_settings(values, setup=False)
    values["JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID"] = str(CONNECTION_ID)
    runtime = setup_tool.configured_settings(values, setup=False)
    assert runtime.telegram_delivery_mode == "polling"
    assert runtime.llm_enabled and runtime.outbound_delivery_enabled
    assert not runtime.telegram_voice_tts_enabled and not runtime.knowledge_rag_enabled


def test_configuration_never_inherits_other_shell_credentials_or_features(
    setup_tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JANUARY_LLM_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setenv("JANUARY_LLM_GEMINI_API_KEY", "SYNTHETIC-SHELL-ONLY-KEY")
    monkeypatch.setenv("JANUARY_TELEGRAM_VOICE_TTS_ENABLED", "true")
    configured = setup_tool.configured_settings(_values(setup_tool), setup=True)
    assert configured.llm_fallback_provider is None
    assert configured.llm_gemini_api_key is None
    assert not configured.telegram_voice_tts_enabled


@pytest.mark.parametrize(
    "key,value",
    [
        ("input_microusd_per_million", None),
        ("json_schema_supported", False),
        ("data_class", "local"),
        ("budgets", []),
        ("effective_at", "2999-01-01T00:00:00Z"),
        ("effective_at", None),
        ("effective_at", "2000-01-01T00:00:00+07:00"),
        ("input_microusd_per_million", True),
        ("output_microusd_per_million", "1000000"),
    ],
)
def test_incomplete_or_unapproved_policy_blocks_before_calls(
    key: str, value: object, setup_tool: ModuleType, tmp_path: Path
) -> None:
    values = _values(setup_tool)
    settings = setup_tool.configured_settings(values, setup=True)
    source = _policy_source()
    source[key] = value
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(source))
    with pytest.raises((setup_tool.SetupError, ValidationError)):
        setup_tool.read_policy(path, settings)


def test_budget_has_no_permissive_default_or_soft_mode(
    setup_tool: ModuleType, tmp_path: Path
) -> None:
    settings = setup_tool.configured_settings(_values(setup_tool), setup=True)
    source = _policy_source()
    source["budgets"][0]["amount"] = 0
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(source))
    with pytest.raises(ValidationError):
        setup_tool.read_policy(path, settings)
    source["budgets"][0]["amount"] = 10
    source["budgets"][0]["mode"] = "soft"
    path.write_text(json.dumps(source))
    with pytest.raises(setup_tool.SetupError, match="template"):
        setup_tool.read_policy(path, settings)


@pytest.mark.parametrize("section", ["health", "budgets"])
def test_policy_never_coerces_boolean_operator_limits(
    section: str, setup_tool: ModuleType, tmp_path: Path
) -> None:
    settings = setup_tool.configured_settings(_values(setup_tool), setup=True)
    source = _policy_source()
    if section == "health":
        source["health"]["degraded_threshold"] = True
    else:
        source["budgets"][0]["amount"] = True
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(source))
    with pytest.raises(setup_tool.SetupError, match="JSON integers"):
        setup_tool.read_policy(path, settings)


def test_all_existing_budget_measurement_window_scopes_remain_available(
    setup_tool: ModuleType, tmp_path: Path
) -> None:
    settings = setup_tool.configured_settings(_values(setup_tool), setup=True)
    source = _policy_source()
    source["budgets"] = [
        {
            "measurement": measurement.value,
            "window_kind": window.value,
            "amount": 10,
            "alert_threshold_bps": 8000,
        }
        for measurement in setup_tool.BudgetMeasurement
        for window in setup_tool.BudgetWindowKind
    ]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(source))
    policy = setup_tool.read_policy(path, settings)
    assert len(policy.budgets) == len(source["budgets"]) == 10


def test_control_calls_use_auth_idempotency_revision_and_redacted_errors(
    setup_tool: ModuleType,
) -> None:
    async def scenario() -> None:
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(409, json={"secret": "SYNTHETIC-DO-NOT-LEAK"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="http://operator-api:8000"
        ) as client:
            api = setup_tool.ControlAPI(client, "SYNTHETIC-JWT")
            for _ in range(2):
                with pytest.raises(setup_tool.SetupError, match="HTTP 409") as result:
                    await api.call(
                        "POST",
                        "/control/v1/deployment/provider-budgets",
                        {"amount": 10},
                        expected=0,
                    )
                assert "DO-NOT-LEAK" not in str(result.value)
            assert requests[0].headers["Authorization"] == "Bearer SYNTHETIC-JWT"
            assert requests[0].headers["If-Match"] == "0"
            assert (
                requests[0].headers["X-Request-ID"]
                == requests[1].headers["X-Request-ID"]
            )

    asyncio.run(scenario())


class _API:
    def __init__(self) -> None:
        self.calls = []
        self.owner = True
        self.state_version = 1

    async def call(self, method, path, body=None, *, expected=None):
        self.calls.append((method, path, body, expected))
        if path.endswith("/me"):
            return {"identity_id": str(IDENTITY_ID), "deployment_operator": False}
        if "/authorities/" in path:
            return {"granted": True}
        if path.endswith("/tenants"):
            return {
                "items": [
                    {
                        "id": str(TENANT_ID),
                        "slug": "self-host",
                        "status": "active",
                        "role": "tenant_owner" if self.owner else "viewer",
                    }
                ]
            }
        if path.endswith("/provider-capabilities"):
            return {"id": str(CAPABILITY_ID)}
        if path.endswith("/state"):
            return {
                "state_version": self.state_version,
                "lifecycle": "disabled",
                "health": None,
            }
        if path.endswith("/provider-health-policies"):
            return {"id": str(HEALTH_ID)}
        if path.endswith("/provider-routing/chat_generation") and method == "GET":
            return {"head": None}
        if path.endswith("/provider-budgets") and method == "GET":
            return {"items": []}
        return {"created": True}


def test_existing_authority_then_bot_reconciliation_then_exact_governed_policy(
    setup_tool: ModuleType, tmp_path: Path
) -> None:
    async def scenario() -> None:
        settings, policy = _policy(setup_tool, tmp_path, _values(setup_tool))
        api = _API()

        async def reconcile(scoped, identity):
            assert scoped.telegram_tenant_id == TENANT_ID
            assert identity == _identity()
            assert any(path.endswith("/tenants") for _, path, _, _ in api.calls)
            return BootstrapResult(
                ASSISTANT_ID,
                CONNECTION_ID,
                identity.external_bot_id,
                identity.username,
                identity.display_name,
                True,
                False,
            )

        updates = await setup_tool.run_setup(
            settings, policy, api, _identity(), reconcile=reconcile
        )
        assert updates == {
            "JANUARY_TELEGRAM_TENANT_ID": str(TENANT_ID),
            "JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID": str(CONNECTION_ID),
            "JANUARY_CONTROL_PLANE_DEPLOYMENT_BOOTSTRAP_SUBJECTS": "[]",
        }
        writes = [
            (path, body, expected)
            for method, path, body, expected in api.calls
            if method in {"POST", "PATCH"}
        ]
        route = next(
            body
            for path, body, _ in writes
            if path.endswith("/provider-routing/chat_generation")
        )
        assert route["requirements"] == {
            "json_schema": True,
            "maximum_output_tokens": settings.llm_max_output_tokens,
            "allowed_data_classes": ["local", "approved_external"],
            "require_current_health": True,
        }
        assert route["capability_ids"] == [str(CAPABILITY_ID)]
        budget = next(
            body for path, body, _ in writes if path.endswith("/provider-budgets")
        )
        assert budget["mode"] == "hard" and budget["enabled"]
        assert budget["amount"] == 10
        assert all(
            expected == 0
            for path, _, expected in writes
            if "/provider-routing/" in path or path.endswith("/provider-budgets")
        )

    asyncio.run(scenario())


def test_wrong_owner_never_reconciles_bot_or_publishes_policy(
    setup_tool: ModuleType, tmp_path: Path
) -> None:
    async def scenario() -> None:
        settings, policy = _policy(setup_tool, tmp_path, _values(setup_tool))
        api = _API()
        api.owner = False

        async def forbidden(*_):
            pytest.fail("Wrong tenant role must never reconcile")

        with pytest.raises(setup_tool.SetupError, match="owner authority"):
            await setup_tool.run_setup(
                settings, policy, api, _identity(), reconcile=forbidden
            )
        assert not any("provider-" in path for _, path, _, _ in api.calls)

    asyncio.run(scenario())


def test_changed_provider_is_not_revived(
    setup_tool: ModuleType, tmp_path: Path
) -> None:
    async def scenario() -> None:
        settings, policy = _policy(setup_tool, tmp_path, _values(setup_tool))
        api = _API()
        api.state_version = 3
        with pytest.raises(setup_tool.SetupError, match="do not revive"):
            await setup_tool.publish_policy(api, settings, policy)
        assert not any(method == "PATCH" for method, _, _, _ in api.calls)
        assert not any(
            path.endswith("/provider-budgets") for _, path, _, _ in api.calls
        )

    asyncio.run(scenario())


def test_unconfirmed_cli_setup_makes_no_calls(
    setup_tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["setup_operator.py", "setup"])
    with pytest.raises(SystemExit) as result:
        asyncio.run(setup_tool.main())
    assert result.value.code == 2


def test_cli_offline_setup_check_before_ids_exist_has_no_network(
    setup_tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    path = tmp_path / ".env.self-host"
    values = _values(setup_tool)
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    path.chmod(0o600)
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(_policy_source()))

    def forbidden(*_, **__):
        pytest.fail("Offline check must not create network/database clients")

    monkeypatch.setattr(setup_tool, "TelegramAdapter", forbidden)
    monkeypatch.setattr(setup_tool, "Database", forbidden)
    monkeypatch.setattr(setup_tool.httpx, "AsyncClient", forbidden)
    arguments = [
        "setup_operator.py",
        "check",
        "--config",
        str(path),
        "--policy",
        str(policy),
    ]
    monkeypatch.setattr(sys, "argv", arguments + ["--phase", "setup"])
    assert asyncio.run(setup_tool.main()) == 0
    success = capsys.readouterr()
    assert "Typed setup/policy" in success.out
    # Without the explicit pre-provisioning phase, missing connection IDs are
    # still a runtime blocker, not a successful first-run check.
    monkeypatch.setattr(sys, "argv", arguments)
    assert asyncio.run(setup_tool.main()) == 1
    failure = capsys.readouterr()
    assert "SYNTHETIC-" not in success.out + success.err + failure.out + failure.err


def test_cli_init_leaks_no_secret_and_has_no_network_boundary(
    setup_tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    path = tmp_path / ".env.self-host"
    path.write_text((ROOT / ".env.self-host.example").read_text())

    def forbidden(*_, **__):
        pytest.fail("Initialization may not create network clients")

    monkeypatch.setattr(setup_tool, "TelegramAdapter", forbidden)
    monkeypatch.setattr(setup_tool.httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(
        sys, "argv", ["setup_operator.py", "init", "--config", str(path)]
    )
    assert asyncio.run(setup_tool.main()) == 0
    output = capsys.readouterr()
    values = setup_tool.read_config(path)
    assert values["JANUARY_DATABASE_PASSWORD"] not in output.out + output.err
    assert values["JANUARY_CONTROL_PLANE_JWT_SECRET"] not in output.out + output.err
