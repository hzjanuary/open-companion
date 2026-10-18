"""Local-only content-safe operational recovery CLI."""

import argparse
import asyncio
import json
from uuid import UUID

from app.core.config import Settings
from app.domain.recovery import RecoveryKind
from app.infrastructure.database.database import Database
from app.infrastructure.database.recovery import SqlAlchemyRecoveryRepository


async def _run(args: argparse.Namespace) -> int:
    database = Database(Settings())
    await database.start()
    try:
        repository = SqlAlchemyRecoveryRepository(database.session_factory)
        if args.command == "inspect":
            kind = RecoveryKind(args.kind) if args.kind else None
            print(json.dumps(await repository.summarize(kind), sort_keys=True))
            return 0
        work_id = UUID(args.id)
        if args.command == "show":
            item = await repository.show(work_id)
            print(
                json.dumps(
                    item.__dict__ if item else {"found": False},
                    default=str,
                    sort_keys=True,
                )
            )
            return 0 if item else 1
        if not args.confirm:
            print("refusing replay without --confirm")
            return 2
        accepted = await repository.replay(RecoveryKind(args.kind), work_id)
        print(json.dumps({"replayed": accepted, "id": str(work_id)}))
        return 0 if accepted else 1
    finally:
        await database.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="January local recovery operations")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--kind", choices=[item.value for item in RecoveryKind])
    show = sub.add_parser("show")
    show.add_argument("id")
    replay = sub.add_parser("replay")
    replay.add_argument(
        "--kind", choices=[item.value for item in RecoveryKind], required=True
    )
    replay.add_argument("--id", required=True)
    replay.add_argument("--confirm", action="store_true")
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
