"""HTTP dependencies that keep FastAPI outside database infrastructure."""

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.database import Database, get_session


async def database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session with explicit caller transaction ownership."""

    database = cast(Database, request.app.state.database)
    async for session in get_session(database):
        yield session
