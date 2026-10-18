"""Explicit operator recovery for a possibly duplicated outbound action."""

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from app.core.config import Settings
from app.domain.outbound import OutboundActionStatus
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import OutboundActionModel
from app.infrastructure.database.outbound import SqlAlchemyOutboundRepository


async def list_unknown(database: Database) -> int:
    async with database.session_factory() as session:
        actions = list(
            await session.scalars(
                select(OutboundActionModel)
                .where(
                    OutboundActionModel.status == OutboundActionStatus.DELIVERY_UNKNOWN
                )
                .order_by(OutboundActionModel.created_at, OutboundActionModel.id)
            )
        )
    for action in actions:
        print(
            f"{action.id} {action.conversation_id} {action.kind.value} "
            f"{action.created_at.isoformat()}"
        )
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action_id", nargs="?", type=UUID)
    parser.add_argument("--confirm-possible-duplicate", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    database = Database(settings)
    await database.start()
    try:
        if args.action_id is None:
            return await list_unknown(database)
        if not args.confirm_possible_duplicate:
            parser.error("--confirm-possible-duplicate is required to requeue")
        changed = await SqlAlchemyOutboundRepository(
            database.session_factory
        ).requeue_unknown(args.action_id, "local_operator")
        if not changed:
            print("action was not delivery_unknown", flush=True)
            return 1
        print(f"requeued {args.action_id}", flush=True)
        return 0
    finally:
        await database.stop()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
