"""Explicit local operator setup using existing authenticated controls/services.

No provider generation, Telegram send, webhook mutation, schema migration,
anonymous API or direct tenant/provider SQL write exists in this tool.
"""

import argparse
import asyncio
import hashlib
import json
import secrets
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, get_args, get_origin
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import jwt
from asyncpg import PostgresError
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from self_host_config import (
    SetupError,
    read_config,
    require_local_target,
    update_config,
)
from sqlalchemy.exc import SQLAlchemyError

from app.application.bootstrap import BootstrapResult
from app.application.ports.platform import BotIdentity, PlatformAdapterError
from app.core.config import Settings
from app.domain.persistence import Platform
from app.domain.provider_governance import (
    BudgetMeasurement,
    BudgetMode,
    BudgetWindowKind,
    ProviderDataClass,
    WorkloadClass,
)
from app.infrastructure.database.bootstrap import (
    BootstrapConflictError,
    SqlAlchemyOperatorBootstrap,
)
from app.infrastructure.database.database import Database
from app.infrastructure.telegram.adapter import TelegramAdapter
from app.interface.http.provider_governance_control import (
    BudgetInput,
    CapabilityInput,
    HealthPolicyInput,
    PriceInput,
    RoutingInput,
)
from app.runtime.telegram_media import generation_requirements

SUBJECT = "self-host-operator"
TENANT_SLUG = "self-host"
CORE_OVERRIDES: dict[str, Any] = {
    "environment": "local",
    "log_level": "INFO",
    "database_host": "database",
    "database_port": 5432,
    "database_url": None,
    "database_echo": False,
    "redis_url": "redis://redis:6379/0",
    "qdrant_url": "http://qdrant:6333",
    "rate_limit_enabled": True,
    "provider_concurrency_enabled": True,
    "safety_moderation_enabled": True,
    "provider_governance_mode": "enforce",
    "provider_governance_worker_enabled": True,
    "control_plane_enabled": True,
    "data_governance_enabled": True,
    "governance_worker_enabled": True,
    "retention_worker_enabled": True,
    "demo_live_enabled": False,
    "demo_live_telegram_verification_enabled": False,
    "llm_live_verification_enabled": False,
    "telegram_live_delivery_verification_enabled": False,
}


class FileSettings(Settings):
    """Existing Settings contract with explicit file/init values only."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def _json_field(annotation: object) -> bool:
    return get_origin(annotation) in {dict, list, tuple, set} or any(
        _json_field(value) for value in get_args(annotation)
    )


def configured_settings(values: dict[str, str], *, setup: bool) -> Settings:
    names = {f"JANUARY_{name.upper()}": name for name in Settings.model_fields}
    unknown = (
        set(values)
        - names.keys()
        - {
            "JANUARY_HOST_PORT",
            "JANUARY_BACKEND_IMAGE",
            "JANUARY_SELF_HOST_ENV_FILE",
        }
    )
    if unknown:
        raise SetupError(
            "Unknown configuration name; use the actual Settings inventory."
        )
    fields: dict[str, Any] = {
        names[key]: value for key, value in values.items() if key in names
    }
    # Pydantic's environment source normally JSON-decodes collection fields;
    # explicit constructor values require that same conversion here.
    for name, value in fields.items():
        if value and _json_field(Settings.model_fields[name].annotation):
            fields[name] = json.loads(value)
    fields.update(CORE_OVERRIDES)
    if setup:
        fields.update(
            telegram_enabled=True,
            telegram_delivery_mode="disabled",
            outbound_delivery_enabled=False,
            llm_enabled=False,
            telegram_media_enabled=False,
            telegram_voice_tts_enabled=False,
            conversation_summaries_enabled=False,
            summary_worker_enabled=False,
            semantic_memory_enabled=False,
            semantic_memory_worker_enabled=False,
            knowledge_rag_enabled=False,
            knowledge_index_worker_enabled=False,
            proactive_scheduling_enabled=False,
            scheduler_worker_enabled=False,
        )
    return FileSettings(_env_file=None, **fields)


@dataclass(frozen=True)
class SetupPolicy:
    """Parsed operational inputs; these are existing API DTOs, not new policy."""

    capability: CapabilityInput
    health: HealthPolicyInput
    price: PriceInput
    budgets: tuple[BudgetInput, ...]
    effective_at: datetime


def read_policy(path: Path, settings: Settings) -> SetupPolicy:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65_536:
        raise SetupError("Policy must be a bounded regular JSON file, not a link.")
    source = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "effective_at",
        "data_class",
        "json_schema_supported",
        "input_microusd_per_million",
        "output_microusd_per_million",
        "health",
        "budgets",
    }
    if not isinstance(source, dict) or set(source) != required:
        raise SetupError("Policy fields do not match the self-host policy template.")
    if not isinstance(source["effective_at"], str):
        raise SetupError("Policy effective_at must be an explicit UTC time string.")
    effective = datetime.fromisoformat(source["effective_at"].replace("Z", "+00:00"))
    if effective.utcoffset() != timedelta(0) or effective > datetime.now(UTC):
        raise SetupError(
            "Policy effective_at must be an explicit past/current UTC time."
        )
    provider = settings.llm_primary_provider
    model = getattr(settings, f"llm_{provider}_model")
    key: SecretStr | None = getattr(settings, f"llm_{provider}_api_key", None)
    if not model or (provider != "ollama" and key is None):
        raise SetupError("Configure the selected provider model and required key.")
    data_class = ProviderDataClass(source["data_class"])
    expected = (
        ProviderDataClass.LOCAL
        if provider == "ollama"
        else ProviderDataClass.APPROVED_EXTERNAL
    )
    if data_class != expected or source["json_schema_supported"] is not True:
        raise SetupError("Confirm the selected model's data boundary and JSON schema.")
    capability = CapabilityInput(
        provider_id=provider,
        adapter_key=provider,
        workload_class=WorkloadClass.CHAT_GENERATION,
        model=model,
        capability_metadata={
            "json_schema": True,
            "maximum_output_tokens": settings.llm_max_output_tokens,
        },
        data_class=data_class,
        credential_slot=provider,
        credential_configured=True,
        reservation_strategy="utf8_byte_upper_bound",
    )
    # Validation-only ID, replaced by the real API capability ID before writes.
    validation_id = uuid4()
    health_values = source["health"]
    health_fields = set(HealthPolicyInput.model_fields) - {
        "capability_id",
        "effective_at",
    }
    if not isinstance(health_values, dict) or set(health_values) != health_fields:
        raise SetupError("Supply all actual health-policy thresholds, no defaults.")
    if any(type(value) is not int for value in health_values.values()) or any(
        type(source[field]) is not int
        for field in ("input_microusd_per_million", "output_microusd_per_million")
    ):
        raise SetupError("Policy thresholds/prices must be explicit JSON integers.")
    health = HealthPolicyInput(
        capability_id=validation_id, effective_at=effective, **health_values
    )
    price = PriceInput(
        capability_id=validation_id,
        unit_basis="generation_tokens",
        input_rate=source["input_microusd_per_million"],
        output_rate=source["output_microusd_per_million"],
        effective_from=effective,
    )
    raw_budgets = source["budgets"]
    maximum_scopes = len(BudgetMeasurement) * len(BudgetWindowKind)
    if not isinstance(raw_budgets, list) or not 1 <= len(raw_budgets) <= maximum_scopes:
        raise SetupError("Supply at least one finite hard chat budget.")
    budgets = []
    seen = set()
    for value in raw_budgets:
        if not isinstance(value, dict) or set(value) != {
            "measurement",
            "window_kind",
            "amount",
            "alert_threshold_bps",
        }:
            raise SetupError("Budget fields must match the template.")
        if any(
            type(value[field]) is not int for field in ("amount", "alert_threshold_bps")
        ):
            raise SetupError("Budget amount/alert threshold must be JSON integers.")
        budget = BudgetInput(
            workload_class=WorkloadClass.CHAT_GENERATION,
            enabled=True,
            mode=BudgetMode.HARD,
            effective_at=effective,
            **value,
        )
        scope = (budget.measurement, budget.window_kind)
        if scope in seen:
            raise SetupError("Duplicate budget measurement/window.")
        seen.add(scope)
        budgets.append(budget)
    return SetupPolicy(capability, health, price, tuple(budgets), effective)


class ControlAPI:
    """Bounded authenticated calls; errors never include URLs, JWTs or bodies."""

    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self.client = client
        self.token = token

    async def call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        expected: int | None = None,
    ) -> dict[str, Any]:
        material = json.dumps(body, sort_keys=True, separators=(",", ":"))
        identifier = hashlib.sha256(f"{method}|{path}|{material}".encode()).hexdigest()
        headers = {
            "Authorization": f"Bearer {self.token}",
            "X-Request-ID": f"self-host-{identifier}",
        }
        if expected is not None:
            headers["If-Match"] = str(expected)
        try:
            response = await self.client.request(
                method, path, json=body, headers=headers
            )
            if not response.is_success:
                raise SetupError(
                    f"Authenticated setup rejected (HTTP {response.status_code}); "
                    "inspect redacted state before retrying."
                )
            result = response.json()
        except httpx.HTTPError as exc:
            raise SetupError("Control API unavailable (details redacted).") from exc
        if not isinstance(result, dict):
            raise SetupError("Control API returned an invalid response shape.")
        return result


def operator_token(settings: Settings) -> str:
    if settings.control_plane_jwt_secret is None:
        raise SetupError("Local operator authentication is incomplete.")
    return jwt.encode(
        {
            "iss": settings.control_plane_jwt_issuer,
            "aud": settings.control_plane_jwt_audience,
            "sub": SUBJECT,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        settings.control_plane_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


async def ensure_tenant(api: ControlAPI, settings: Settings) -> UUID:
    me = await api.call("GET", "/control/v1/me")
    if not me["deployment_operator"]:
        await api.call(
            "PUT", f"/control/v1/deployment/authorities/{UUID(me['identity_id'])}"
        )
    tenants = (await api.call("GET", "/control/v1/tenants"))["items"]
    if settings.telegram_tenant_id is not None:
        matches = [t for t in tenants if t["id"] == str(settings.telegram_tenant_id)]
    else:
        matches = [t for t in tenants if t["slug"] == TENANT_SLUG]
    if len(matches) > 1:
        raise SetupError("Ambiguous tenant authority; stop and review.")
    if matches:
        tenant = matches[0]
        if tenant["role"] != "tenant_owner" or tenant["status"] != "active":
            raise SetupError("Selected tenant requires current active owner authority.")
    elif settings.telegram_tenant_id is not None:
        raise SetupError("Configured tenant is not owned by this operator.")
    else:
        tenant = await api.call(
            "POST",
            "/control/v1/tenants",
            {"slug": TENANT_SLUG, "name": "Personal self-host"},
        )
    return UUID(tenant["id"])


async def publish_policy(
    api: ControlAPI, settings: Settings, policy: SetupPolicy
) -> None:
    base = "/control/v1/deployment"
    capability = await api.call(
        "POST",
        f"{base}/provider-capabilities",
        policy.capability.model_dump(mode="json"),
    )
    capability_id = UUID(capability["id"])
    state = await api.call("GET", f"{base}/provider-capabilities/{capability_id}/state")
    if state["state_version"] not in {1, 2} or (
        state["state_version"] == 2
        and (state["lifecycle"] != "enabled" or state["health"] != "ready")
    ):
        raise SetupError(
            "Provider was changed/disabled; do not revive it via first run."
        )
    health_body = policy.health.model_copy(update={"capability_id": capability_id})
    health = await api.call(
        "POST", f"{base}/provider-health-policies", health_body.model_dump(mode="json")
    )
    # Same stable request ID replays the initial mutation; never refresh health
    # or revive changed state. The public API exposes state_version, not its FK.
    await api.call(
        "PATCH",
        f"{base}/provider-capabilities/{capability_id}/state",
        {
            "lifecycle": "enabled",
            "health": "ready",
            "health_policy_revision_id": health["id"],
            "reason": "operating_owner",
        },
        expected=1,
    )
    price = policy.price.model_copy(update={"capability_id": capability_id})
    await api.call("POST", f"{base}/provider-prices", price.model_dump(mode="json"))
    route = RoutingInput(
        requirements=generation_requirements(settings),
        capability_ids=[capability_id],
        effective_at=policy.effective_at,
    )
    current = await api.call("GET", f"{base}/provider-routing/chat_generation")
    if current.get("head") is not None and "head_version" not in current:
        raise SetupError("Unexpected provider routing state.")
    if "head_version" in current and (
        current["capability_ids"] != [str(capability_id)]
        or current["requirements"] != route.requirements
        or current["fallback_reasons"]
        or datetime.fromisoformat(current["effective_at"]) != policy.effective_at
    ):
        raise SetupError(
            "An existing route differs; do not overwrite it via first run."
        )
    await api.call(
        "POST",
        f"{base}/provider-routing/chat_generation",
        route.model_dump(mode="json"),
        expected=0,
    )
    current_budgets = (await api.call("GET", f"{base}/provider-budgets"))["items"]
    for budget in policy.budgets:
        matches = [
            b
            for b in current_budgets
            if b["workload"] == "chat_generation"
            and b["measurement"] == budget.measurement.value
            and b["window"] == budget.window_kind.value
        ]
        if matches and any(
            b["amount"] != budget.amount
            or b["mode"] != "hard"
            or not b["enabled"]
            or b["alert_threshold_bps"] != budget.alert_threshold_bps
            for b in matches
        ):
            raise SetupError(
                "An existing budget differs; do not overwrite it via first run."
            )
        await api.call(
            "POST",
            f"{base}/provider-budgets",
            budget.model_dump(mode="json"),
            expected=0,
        )


async def reconcile_bot(settings: Settings, identity: BotIdentity) -> BootstrapResult:
    database = Database(settings)
    await database.start()
    try:
        return await SqlAlchemyOperatorBootstrap(database.session_factory).reconcile(
            settings, identity
        )
    finally:
        await database.stop()


async def run_setup(
    settings: Settings,
    policy: SetupPolicy,
    api: ControlAPI,
    identity: BotIdentity,
    *,
    reconcile: Callable[
        [Settings, BotIdentity], Awaitable[BootstrapResult]
    ] = reconcile_bot,
) -> dict[str, str]:
    if not identity.is_bot or identity.platform != Platform.TELEGRAM:
        raise SetupError("Verified Telegram identity is not a bot.")
    tenant_id = await ensure_tenant(api, settings)
    scoped = settings.model_copy(update={"telegram_tenant_id": tenant_id})
    # Trusted local operator command, not a new HTTP provisioning endpoint.
    result = await reconcile(scoped, identity)
    await publish_policy(api, scoped, policy)
    return {
        "JANUARY_TELEGRAM_TENANT_ID": str(tenant_id),
        "JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID": str(result.platform_connection_id),
        "JANUARY_CONTROL_PLANE_DEPLOYMENT_BOOTSTRAP_SUBJECTS": "[]",
    }


def initialize(path: Path) -> None:
    require_local_target(path)
    values = read_config(path, private=False)
    updates = {
        key: secrets.token_hex(32)
        for key in ("JANUARY_DATABASE_PASSWORD", "JANUARY_CONTROL_PLANE_JWT_SECRET")
        if not values.get(key)
    }
    update_config(path, updates)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("init", "check", "setup"))
    parser.add_argument(
        "--config", type=Path, default=Path("/workspace/.env.self-host")
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("/workspace/.local/self-host/provider-policy.json"),
    )
    parser.add_argument("--api-base-url", default="http://operator-api:8000")
    parser.add_argument(
        "--phase",
        choices=("setup", "runtime"),
        help="Offline check phase only; runtime by default, setup before IDs exist.",
    )
    parser.add_argument("--confirm-operator-setup", action="store_true")
    parser.add_argument("--confirm-live-telegram", action="store_true")
    args = parser.parse_args()
    if args.phase is not None and args.operation != "check":
        parser.error("--phase applies only to the offline check operation.")
    if args.operation == "setup" and not (
        args.confirm_operator_setup and args.confirm_live_telegram
    ):
        parser.error("Both setup/live confirmation flags are required; no calls made.")
    try:
        if args.operation == "init":
            initialize(args.config)
            print(
                "Local secrets initialized/preserved; file restricted; "
                "no network calls."
            )
            return 0
        if args.operation == "setup":
            # Refuse an unignored/example output target BEFORE any live/API
            # mutation, not after policies were persisted but IDs cannot save.
            require_local_target(args.config)
        values = read_config(args.config)
        settings = configured_settings(
            values, setup=args.operation == "setup" or args.phase == "setup"
        )
        policy = read_policy(args.policy, settings)
        if args.operation == "check":
            print(
                f"Typed {args.phase or 'runtime'}/policy configuration valid; "
                "no live or database checks."
            )
            return 0
        url = urlsplit(args.api_base_url)
        if (
            url.scheme != "http"
            or url.hostname not in {"operator-api", "127.0.0.1", "localhost"}
            or url.username
            or url.password
            or url.path
            or url.query
            or url.fragment
        ):
            raise SetupError(
                "Setup API must be internal operator-api or explicit loopback HTTP."
            )
        adapter = TelegramAdapter(settings)
        try:
            async with httpx.AsyncClient(
                base_url=args.api_base_url, timeout=10, trust_env=False
            ) as client:
                api = ControlAPI(client, operator_token(settings))
                await api.call("GET", "/control/v1/me")
                identity = await adapter.verify_identity()
                updates = await run_setup(settings, policy, api, identity)
                update_config(args.config, updates)
        finally:
            await adapter.aclose()
        print(
            "Operator setup recorded; bootstrap subjects cleared; "
            "no provider calls or Telegram sends."
        )
        return 0
    except SetupError as exc:
        print(f"Operator setup/check failed: {exc}", file=sys.stderr)
        return 1
    except (
        ValidationError,
        OSError,
        SQLAlchemyError,
        PostgresError,
        PlatformAdapterError,
        BootstrapConflictError,
        jwt.PyJWTError,
        ValueError,
        TypeError,
        KeyError,
    ):
        print(
            "Operator setup/check failed; values redacted. "
            "Check configuration, policy, authority and service state.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
