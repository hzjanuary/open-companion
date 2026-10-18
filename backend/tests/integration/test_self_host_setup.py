"""Real authenticated first-run controls on a uniquely owned, fresh database.

The configured PostgreSQL test service must permit database creation, as the
canonical postgres:16 CI service does. No shared fixture rows are truncated.
Telegram identity is synthetic; network transports other than PostgreSQL and
the in-process control API are prohibited.
"""

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from sqlalchemy import text

from app.application.ports.platform import BotIdentity
from app.core.config import Settings
from app.domain.persistence import Platform
from app.infrastructure.database.database import Database
from app.main import create_app

ROOT = Path(__file__).resolve().parents[3]


async def _migrate(settings: Settings) -> None:
    # Use the already running Python environment, not a hidden uv/host install.
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("JANUARY_")
    }
    environment.update(
        JANUARY_ENVIRONMENT="test",
        JANUARY_DATABASE_URL=settings.resolved_database_url.render_as_string(
            hide_password=False
        ),
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "upgrade",
        "0026_conversation_feedback",
        cwd=ROOT,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await process.communicate()
    assert process.returncode == 0, "Fresh self-host test migration failed (redacted)."


def _setup_settings(tool: ModuleType, base: Settings, name: str) -> Settings:
    values = tool.read_config(ROOT / ".env.self-host.example", private=False)
    values.update(
        JANUARY_DATABASE_PASSWORD="SYNTHETIC-UNUSED-CONTAINER-PASSWORD",
        JANUARY_CONTROL_PLANE_JWT_SECRET="SYNTHETIC-SELF-HOST-AUTH-SECRET-32-PLUS",
        JANUARY_TELEGRAM_BOT_TOKEN="SYNTHETIC-NEVER-SENT-TOKEN",
        JANUARY_LLM_OPENAI_MODEL="synthetic-schema-model",
        JANUARY_LLM_OPENAI_API_KEY="SYNTHETIC-NEVER-SENT-KEY",
    )
    configured = tool.configured_settings(values, setup=True)
    # Only the synthetic test moves the private Docker DB address to the
    # canonical project's configured PostgreSQL test service.
    return configured.model_copy(
        update={
            "environment": "test",
            "database_url": None,
            "database_host": base.database_host,
            "database_port": base.database_port,
            "database_name": name,
            "database_user": base.database_user,
            "database_password": base.database_password,
            "redis_url": base.redis_url,
        }
    )


async def _snapshot(database: Database) -> tuple[object, ...]:
    async with database.session_factory() as session:
        return tuple(
            (
                await session.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM provider_capabilities), "
                        "(SELECT count(*) FROM provider_health_policy_revisions), "
                        "(SELECT count(*) FROM provider_price_revisions), "
                        "(SELECT count(*) FROM provider_routing_policy_revisions), "
                        "(SELECT count(*) FROM provider_budget_revisions), "
                        "(SELECT last_evaluated_at FROM provider_capability_states)"
                    )
                )
            ).one()
        )


@pytest.mark.integration
def test_fresh_setup_real_auth_persistence_retry_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "scripts/self_host"))
    tool = importlib.import_module("setup_operator")

    async def forbid_external_request(*args, **kwargs):
        raise AssertionError("No real Telegram/provider HTTP request is permitted.")

    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", forbid_external_request
    )

    async def scenario() -> None:
        base = Settings(_env_file=None, environment="test")
        assert base.resolved_database_url.host in {"127.0.0.1", "localhost"}, (
            "Self-host integration proof requires the local project test database."
        )
        name = "spec043_setup_" + uuid4().hex
        # Name is entirely generated here, not an env/CLI-provided delete target.
        assert name.removeprefix("spec043_setup_").isalnum()
        admin = await asyncpg.connect(
            base.resolved_database_url.set(drivername="postgresql").render_as_string(
                hide_password=False
            )
        )
        created = False
        try:
            await admin.execute(f'CREATE DATABASE "{name}"')
            created = True
            settings = _setup_settings(tool, base, name)
            await _migrate(settings)
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
            policy_path = tmp_path / "synthetic-policy.json"
            policy_path.write_text(json.dumps(source))
            policy = tool.read_policy(policy_path, settings)
            identity = BotIdentity(
                Platform.TELEGRAM,
                "71000001",
                "synthetic_bot",
                "Synthetic",
                True,
                True,
                False,
            )
            app = create_app(settings)
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as client:
                    assert (await client.get("/control/v1/me")).status_code == 401
                    api = tool.ControlAPI(client, tool.operator_token(settings))
                    unauthorized = tool.ControlAPI(client, "synthetic-invalid-jwt")
                    with pytest.raises(tool.SetupError, match="HTTP 401"):
                        await unauthorized.call("GET", "/control/v1/me")

                    class InterruptedAPI(tool.ControlAPI):
                        async def call(self, method, path, body=None, *, expected=None):
                            if path.endswith("/provider-prices"):
                                raise tool.SetupError("Synthetic interrupted setup.")
                            return await super().call(
                                method, path, body, expected=expected
                            )

                    interrupted = InterruptedAPI(client, tool.operator_token(settings))
                    with pytest.raises(tool.SetupError, match="interrupted setup"):
                        await tool.run_setup(settings, policy, interrupted, identity)
                    partial = await _snapshot(app.state.database)
                    assert partial[:5] == (1, 1, 0, 0, 0)
                    assert partial[5] is not None
                    first = await tool.run_setup(settings, policy, api, identity)
                    assert (
                        first["JANUARY_CONTROL_PLANE_DEPLOYMENT_BOOTSTRAP_SUBJECTS"]
                        == "[]"
                    )
                    tenant_id = UUID(first["JANUARY_TELEGRAM_TENANT_ID"])
                    connection_id = UUID(
                        first["JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID"]
                    )
                    me = await api.call("GET", "/control/v1/me")
                    assert me["deployment_operator"] is True
                    tenants = (await api.call("GET", "/control/v1/tenants"))["items"]
                    owned = next(
                        item for item in tenants if item["id"] == str(tenant_id)
                    )
                    assert (
                        owned["role"] == "tenant_owner" and owned["status"] == "active"
                    )
                    database = app.state.database
                    assert await database.is_ready()
                    async with database.session_factory() as session:
                        row = (
                            await session.execute(
                                text(
                                    "SELECT tenant_id, credential_reference, "
                                    "configuration "
                                    "FROM platform_connections WHERE id = :id"
                                ),
                                {"id": connection_id},
                            )
                        ).one()
                        assert row.tenant_id == tenant_id
                        assert (
                            row.credential_reference == "env:JANUARY_TELEGRAM_BOT_TOKEN"
                        )
                        assert "SYNTHETIC-NEVER-SENT" not in json.dumps(
                            row.configuration
                        )
                    before = await _snapshot(database)
                    assert before[:5] == (1, 1, 1, 1, 1)
                    assert before[5] == partial[5]
                    retry = settings.model_copy(
                        update={
                            "telegram_tenant_id": tenant_id,
                            "telegram_platform_connection_id": connection_id,
                            "control_plane_deployment_bootstrap_subjects": [],
                        }
                    )
                    assert await tool.run_setup(retry, policy, api, identity) == first
                    assert await _snapshot(database) == before
                    route = await api.call(
                        "GET", "/control/v1/deployment/provider-routing/chat_generation"
                    )
                    assert route["requirements"] == tool.generation_requirements(
                        settings
                    )
                    assert route["head_version"] == 1
                    budgets = (
                        await api.call("GET", "/control/v1/deployment/provider-budgets")
                    )["items"]
                    assert len(budgets) == 1
                    assert budgets[0]["mode"] == "hard" and budgets[0]["amount"] == 10
                    capability_id = route["capability_ids"][0]
                    state_path = (
                        "/control/v1/deployment/provider-capabilities/"
                        f"{capability_id}/state"
                    )
                    await api.call(
                        "PATCH",
                        state_path,
                        {"lifecycle": "disabled", "reason": "administrative"},
                        expected=2,
                    )
                    with pytest.raises(tool.SetupError, match="do not revive"):
                        await tool.run_setup(retry, policy, api, identity)
                    state = await api.call("GET", state_path)
                    assert (
                        state["lifecycle"] == "disabled" and state["state_version"] == 3
                    )
        finally:
            try:
                if created:
                    # Every app/bootstrap engine is closed above before dropping
                    # this exact UUID-owned database. No FORCE/shared-db cleanup.
                    await admin.execute(f'DROP DATABASE "{name}"')
            finally:
                await admin.close()

    asyncio.run(scenario())
