"""Cross-session proof of the durable conversation ordering coordination."""

import asyncio

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.infrastructure.database.database import Database


@pytest.mark.integration
def test_conversation_advisory_lock_serializes_one_identity_not_others() -> None:
    async def lock(session, identity: str) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": identity},
        )

    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            first = database.session_factory()
            await first.begin()
            await lock(first, "connection:conversation-a")
            same_started = asyncio.Event()
            same_acquired = asyncio.Event()
            other_acquired = asyncio.Event()

            async def contend_same() -> None:
                async with database.session_factory() as session:
                    async with session.begin():
                        same_started.set()
                        await lock(session, "connection:conversation-a")
                        same_acquired.set()

            async def contend_other() -> None:
                async with database.session_factory() as session:
                    async with session.begin():
                        await lock(session, "connection:conversation-b")
                        other_acquired.set()

            same_task = asyncio.create_task(contend_same())
            other_task = asyncio.create_task(contend_other())
            await same_started.wait()
            await asyncio.wait_for(other_acquired.wait(), timeout=1)
            assert not same_acquired.is_set()
            await first.commit()
            await first.close()
            await asyncio.wait_for(same_task, timeout=1)
            await other_task
        finally:
            await database.stop()

    asyncio.run(scenario())
