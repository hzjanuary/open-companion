"""Content-safe SPEC-022 live acceptance evidence bundles.

Evidence records metadata and redacted outcome classes only. It contains no
message content, credentials, tokens, prompts, memories, vectors, or provider
bodies. The content-safety guard runs on every bundle before it is emitted.
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select

from app.core.config import Settings
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import (
    IncomingPlatformUpdateModel,
    IngressOutboxEventModel,
    OutboundActionModel,
    OutboundDeliveryAttemptModel,
    OutboundRecoveryEventModel,
    ResponsePlanningJobModel,
)
from app.infrastructure.telegram.adapter import TelegramAdapter
from app.runtime.telegram_connection_operations import (
    ConnectionVerification,
    load_approved_bot_id,
    verify_connection,
)

EVIDENCE_SCHEMA_VERSION = 1

FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "authorization",
        "secret",
        "secret_token",
        "token",
        "api_key",
        "password",
        "raw_payload",
        "raw_body",
        "text",
        "message",
        "prompt",
        "provider_body",
        "memory",
        "vector",
        "content",
        "transcript",
    }
)

BOT_TOKEN_PATTERN = re.compile(r"\d{6,10}:[A-Za-z0-9_-]{35}")
CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*:"),
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"(?i)\bx-telegram-bot-api-secret-token\s*:"),
)
CREDENTIAL_PREFIXES = ("ghp_", "sk-", "xoxb-", "AKIA")


class ContentSafetyViolation(ValueError):
    pass


def assert_content_safe(value: object, key: str = "root") -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            if child_key in FORBIDDEN_EVIDENCE_KEYS:
                raise ContentSafetyViolation(
                    f"forbidden evidence key {child_key!r} under {key!r}"
                )
            assert_content_safe(child, child_key)
    elif isinstance(value, list | tuple):
        for item in value:
            assert_content_safe(item, key)
    elif isinstance(value, str):
        if BOT_TOKEN_PATTERN.search(value) or any(
            pattern.search(value) for pattern in CREDENTIAL_PATTERNS
        ):
            raise ContentSafetyViolation(f"credential-shaped string under {key!r}")
        for prefix in CREDENTIAL_PREFIXES:
            if value.startswith(prefix):
                raise ContentSafetyViolation(f"credential-shaped string under {key!r}")


def build_evidence(
    *,
    verification: ConnectionVerification,
    durable_state: dict[str, object] | None,
    health_readiness: dict[str, object] | None,
    run_id: str,
    started_at: datetime,
    operator: str | None,
    incident_contact: str | None,
    rollback_authority: str | None,
    test_group: str | None,
    cleanup_confirmed: bool,
) -> dict[str, object]:
    bundle: dict[str, object] = {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "run_id": run_id,
        "ok": verification.ok,
        "environment": verification.environment,
        "connection": {
            "platform_connection_id": verification.platform_connection_id,
            "delivery_mode": verification.delivery_mode,
        },
        "bot_identity": verification.identity,
        "webhook_state": verification.webhook,
        "mode_exclusivity": (
            verification.exclusivity.evidence()
            if verification.exclusivity is not None
            else None
        ),
        "observations": list(verification.observations),
        "result_classification": "accepted" if verification.ok else "rejected",
        "timestamps": {
            "started_at": started_at.isoformat(),
            "collected_at": datetime.now(UTC).isoformat(),
        },
        "health_readiness": health_readiness,
        "worker_lifecycle": (
            durable_state.get("worker_lifecycle") if durable_state is not None else None
        ),
        "duplicate_retry_outcomes": (
            durable_state.get("duplicate_retry_outcomes")
            if durable_state is not None
            else None
        ),
        "cleanup": {"confirmed": cleanup_confirmed},
        "owners": {
            "operator": operator,
            "incident_contact": incident_contact,
            "rollback_authority": rollback_authority,
        },
        "test_group": test_group,
    }
    assert_content_safe(bundle)
    return bundle


async def collect_durable_state(settings: Settings) -> dict[str, object]:
    database = Database(settings)
    await database.start()
    try:
        async with database.session_factory() as session:
            incoming_total = await session.scalar(
                select(func.count(IncomingPlatformUpdateModel.id))
            )
            incoming_status_rows = (
                await session.execute(
                    select(
                        IncomingPlatformUpdateModel.status,
                        func.count(IncomingPlatformUpdateModel.id),
                    )
                    .group_by(IncomingPlatformUpdateModel.status)
                    .order_by(IncomingPlatformUpdateModel.status)
                )
            ).all()
            distinct_updates = await session.scalar(
                select(
                    func.count(
                        func.distinct(IncomingPlatformUpdateModel.platform_update_id)
                    )
                )
            )
            outbox_status_rows = (
                await session.execute(
                    select(
                        IngressOutboxEventModel.status,
                        func.count(IngressOutboxEventModel.id),
                    )
                    .group_by(IngressOutboxEventModel.status)
                    .order_by(IngressOutboxEventModel.status)
                )
            ).all()
            retried_outbox = await session.scalar(
                select(func.count(IngressOutboxEventModel.id)).where(
                    IngressOutboxEventModel.attempt_count > 1
                )
            )
            planning_jobs = await session.scalar(
                select(func.count(ResponsePlanningJobModel.id))
            )
            action_status_rows = (
                await session.execute(
                    select(
                        OutboundActionModel.status,
                        func.count(OutboundActionModel.id),
                    )
                    .group_by(OutboundActionModel.status)
                    .order_by(OutboundActionModel.status)
                )
            ).all()
            delivery_certainty_rows = (
                await session.execute(
                    select(
                        OutboundDeliveryAttemptModel.certainty,
                        func.count(OutboundDeliveryAttemptModel.id),
                    )
                    .group_by(OutboundDeliveryAttemptModel.certainty)
                    .order_by(OutboundDeliveryAttemptModel.certainty)
                )
            ).all()
            recovery_events = await session.scalar(
                select(func.count(OutboundRecoveryEventModel.id))
            )
            latest_ingress_at = await session.scalar(
                select(func.max(IncomingPlatformUpdateModel.received_at))
            )
        return {
            "worker_lifecycle": {
                "latest_ingress_at": (
                    latest_ingress_at.isoformat() if latest_ingress_at else None
                ),
            },
            "duplicate_retry_outcomes": {
                "incoming_total": incoming_total,
                "incoming_statuses": {
                    status.value: count for status, count in incoming_status_rows
                },
                "distinct_platform_updates": distinct_updates,
                "duplicate_ingress": (incoming_total or 0) - (distinct_updates or 0),
                "ingress_outbox_statuses": {
                    status.value: count for status, count in outbox_status_rows
                },
                "retried_ingress_outbox_events": retried_outbox,
                "planning_jobs": planning_jobs,
                "outbound_action_statuses": {
                    status.value: count for status, count in action_status_rows
                },
                "outbound_delivery_certainties": {
                    certainty.value: count
                    for certainty, count in delivery_certainty_rows
                },
                "outbound_recovery_events": recovery_events,
            },
        }
    finally:
        await database.stop()


async def collect_health_readiness(
    settings: Settings, app_base_url: str
) -> dict[str, object]:
    import httpx

    result: dict[str, object] = {}
    async with httpx.AsyncClient(
        base_url=app_base_url, timeout=httpx.Timeout(5.0)
    ) as client:
        for path in ("/health", "/ready", "/live"):
            try:
                response = await client.get(path)
                body = response.json()
                if isinstance(body, dict):
                    result[path.strip("/")] = {
                        "status_code": response.status_code,
                        **body,
                    }
                else:
                    result[path.strip("/")] = {"status_code": response.status_code}
            except (httpx.HTTPError, ValueError):
                result[path.strip("/")] = {"status_code": None}
    return result


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["collect"])
    parser.add_argument("--confirm-live-telegram", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--operator")
    parser.add_argument("--incident-contact")
    parser.add_argument("--rollback-authority")
    parser.add_argument("--test-group")
    parser.add_argument("--confirm-cleanup", action="store_true")
    parser.add_argument("--no-durable-state", action="store_true")
    parser.add_argument("--app-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.command != "collect":
        parser.error("only the collect command is implemented")
    if not args.confirm_live_telegram:
        parser.error(
            "--confirm-live-telegram is required; no Telegram request was made"
        )
    settings = Settings()
    if not settings.telegram_enabled or settings.telegram_bot_token is None:
        parser.error(
            "Set JANUARY_TELEGRAM_ENABLED=true and JANUARY_TELEGRAM_BOT_TOKEN first."
        )
    approved_bot_id = await load_approved_bot_id(settings)
    started_at = datetime.now(UTC)
    adapter = TelegramAdapter(settings)
    try:
        verification = await verify_connection(
            settings, adapter, approved_bot_id=approved_bot_id
        )
    finally:
        await adapter.aclose()
    if not verification.ok:
        print("connection verification failed:", file=sys.stderr)
        for observation in verification.observations:
            print(f"- {observation}", file=sys.stderr)
        return 1
    durable_state: dict[str, object] | None = None
    if not args.no_durable_state:
        durable_state = await collect_durable_state(settings)
    health_readiness = await collect_health_readiness(settings, args.app_base_url)
    bundle = build_evidence(
        verification=verification,
        durable_state=durable_state,
        health_readiness=health_readiness,
        run_id=args.run_id or str(uuid4()),
        started_at=started_at,
        operator=args.operator,
        incident_contact=args.incident_contact,
        rollback_authority=args.rollback_authority,
        test_group=args.test_group,
        cleanup_confirmed=args.confirm_cleanup,
    )
    output = json.dumps(bundle, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(output + "\n")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
