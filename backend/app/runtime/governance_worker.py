"""Dedicated SPEC-025 export materialization runtime.

Claims pending subject/group/deployment export requests, builds the versioned
package, marks it complete, and expires stale packages past their TTL.
"""

import argparse
import asyncio
import logging
import socket
from datetime import UTC, datetime
from time import perf_counter
from typing import cast

from app.application.governance_export import GovernanceExportBuilder
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.core.config import Settings
from app.domain.governance import (
    GovernanceScope,
)
from app.infrastructure.database.database import Database
from app.infrastructure.database.deployment_authority import (
    SqlAlchemyDeploymentAuthorityRepository,
)
from app.infrastructure.database.governance import (
    GovernanceExportRecord,
    SqlAlchemyGovernanceRepository,
)
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.runtime.lifecycle import RuntimeLifecycle

logger = logging.getLogger(__name__)


def worker_name(settings: Settings) -> str:
    return f"{settings.governance_owner_name}-{socket.gethostname()}"


async def consume_once(
    settings: Settings,
    database: Database,
    owner: str | None = None,
    telemetry: MetricsRecorder | None = None,
) -> int:
    if not (settings.data_governance_enabled and settings.governance_worker_enabled):
        return 0
    recorder = telemetry or NoOpMetricsRecorder()
    started = perf_counter()
    try:
        lease_owner = owner or worker_name(settings)
        repository = SqlAlchemyGovernanceRepository(database.session_factory)
        deployment_authority = SqlAlchemyDeploymentAuthorityRepository(
            database.session_factory
        )
        builder = GovernanceExportBuilder(
            database.session_factory, retention_days=settings.raw_content_retention_days
        )
        request_ids = await repository.find_claimable_export_requests(
            limit=settings.governance_export_batch_size,
            max_attempts=settings.governance_export_max_attempts,
        )
        completed_scopes: list[str] = []
        failed_scopes: list[str] = []
        materialized = 0
        for request_id in request_ids:
            claimed = await repository.claim_export_request(
                request_id=request_id,
                lease_owner=lease_owner,
                lease_seconds=settings.governance_export_lease_seconds,
                max_attempts=settings.governance_export_max_attempts,
            )
            if not claimed:
                continue
            result = await _materialize(
                repository,
                deployment_authority,
                builder,
                request_id,
                settings,
                lease_owner,
            )
            if result is not None and result[1] == "complete":
                scope = result[0]
                completed_scopes.append(scope)
                materialized += 1
            elif result is not None:
                failed_scopes.append(result[0])
        expired = await repository.expire_stale_exports(
            limit=settings.retention_batch_size
        )
        if expired:
            recorder.increment(
                "january_governance_packages_cleared_total",
                expired,
                outcome="expired",
            )
        if completed_scopes:
            for scope in sorted(set(completed_scopes)):
                recorder.increment(
                    "january_governance_export_requests_total",
                    completed_scopes.count(scope),
                    scope=scope,
                    outcome="complete",
                )
        if failed_scopes:
            for scope in sorted(set(failed_scopes)):
                recorder.increment(
                    "january_governance_export_requests_total",
                    failed_scopes.count(scope),
                    scope=scope,
                    outcome="failed",
                )
        batch_outcome = "failed" if failed_scopes else "completed"
    except Exception:  # noqa: BLE001 - emit a bounded batch failure, then propagate
        recorder.increment(
            "january_worker_operations_total",
            runtime="governance",
            operation="export_batch",
            outcome="failed",
        )
        recorder.observe(
            "january_worker_operation_duration_seconds",
            perf_counter() - started,
            runtime="governance",
            operation="export_batch",
            outcome="failed",
        )
        raise
    recorder.increment(
        "january_worker_operations_total",
        runtime="governance",
        operation="export_batch",
        outcome=batch_outcome,
    )
    recorder.observe(
        "january_worker_operation_duration_seconds",
        perf_counter() - started,
        runtime="governance",
        operation="export_batch",
        outcome=batch_outcome,
    )
    return materialized + expired


async def _materialize(
    repository: SqlAlchemyGovernanceRepository,
    deployment_authority: SqlAlchemyDeploymentAuthorityRepository,
    builder: GovernanceExportBuilder,
    request_id: object,
    settings: Settings,
    lease_owner: str,
) -> tuple[str, str] | None:
    from uuid import UUID

    assert isinstance(request_id, UUID)
    request = await repository.get_export_request(request_id)
    if request is None:
        return None
    assert isinstance(request, GovernanceExportRecord)
    if request.scope == GovernanceScope.DEPLOYMENT and (
        request.source_control_identity_id is None
        or not await deployment_authority.has(request.source_control_identity_id)
    ):
        await repository.record_export_failed(
            request_id=request.id,
            reason="authorization_revoked",
            max_attempts=1,
            lease_owner=lease_owner,
        )
        return (request.scope, "failed")
    try:
        package = await _build_package(repository, builder, request, settings)
    except Exception as error:  # noqa: BLE001 - persist a durable failure
        logger.warning(
            "governance_export_failed request=%s error=%r", request.id, error
        )
        await repository.record_export_failed(
            request_id=request.id,
            reason=type(error).__name__,
            max_attempts=settings.governance_export_max_attempts,
            lease_owner=lease_owner,
        )
        return (request.scope, "failed")
    completed = await repository.complete_export(
        request_id=request.id,
        schema_version=str(package["schema_version"]),
        manifest=cast(dict[str, object], package["manifest"]),
        package=package,
        expires_at=request.expires_at or datetime.now(UTC),
        lease_owner=lease_owner,
    )
    if completed:
        return (request.scope, "complete")
    return None


async def _build_package(
    repository: SqlAlchemyGovernanceRepository,
    builder: GovernanceExportBuilder,
    request: GovernanceExportRecord,
    settings: Settings,
) -> dict[str, object]:
    if request.scope == GovernanceScope.SUBJECT and request.participant_id is not None:
        if request.conversation_id is None:
            raise ValueError("subject export requires a conversation")
        return await builder.build_subject_export(
            request_id=request.id,
            conversation_id=request.conversation_id,
            participant_id=request.participant_id,
        )
    if request.scope == GovernanceScope.GROUP:
        if request.conversation_id is None:
            raise ValueError("group export requires a conversation")
        return await builder.build_group_export(
            request_id=request.id, conversation_id=request.conversation_id
        )
    if request.scope == GovernanceScope.DEPLOYMENT:
        return await builder.build_deployment_snapshot(
            request_id=str(request.id),
            settings=settings,
            governance_counts=await repository.governance_state_counts(),
        )
    raise ValueError(f"unmaterializable export scope {request.scope}")


async def run(once: bool) -> None:
    settings = Settings()
    if not settings.governance_worker_enabled:
        return
    database = Database(settings)
    telemetry = (
        InMemoryMetricsRecorder() if settings.metrics_enabled else NoOpMetricsRecorder()
    )
    await database.start()
    lifecycle = RuntimeLifecycle("governance_worker")
    lifecycle.install()
    try:
        while not lifecycle.stopping:
            processed = await consume_once(settings, database, telemetry=telemetry)
            if once:
                return
            if processed == 0:
                await lifecycle.wait(settings.governance_worker_poll_interval_seconds)
    finally:
        lifecycle.close()
        await database.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    asyncio.run(run(parser.parse_args().once))
