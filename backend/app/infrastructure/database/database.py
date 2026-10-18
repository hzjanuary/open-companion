"""Controlled async engine and request-session lifecycle."""

import asyncio
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


class Database:
    """Own one async engine lifecycle for an application process."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("database engine has not been started")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("database session factory has not been started")
        return self._session_factory

    async def start(self) -> None:
        if self._engine is not None:
            return
        self._engine = create_async_engine(
            self._settings.resolved_database_url,
            pool_size=self._settings.database_pool_size,
            max_overflow=self._settings.database_max_overflow,
            pool_timeout=self._settings.database_connect_timeout_seconds,
            pool_pre_ping=True,
            echo=self._settings.database_echo,
            hide_parameters=True,
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def stop(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
        self._engine = None
        self._session_factory = None

    async def is_ready(self) -> bool:
        """Check connectivity and the current Alembic schema within a timeout."""

        try:
            async with asyncio.timeout(self._settings.database_connect_timeout_seconds):
                async with self.engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                    revision = await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    return (
                        isinstance(revision, str)
                        and revision == "0026_conversation_feedback"
                    )
        except Exception:
            return False


async def get_session(database: Database) -> AsyncIterator[AsyncSession]:
    """Yield one request session; callers own commits via explicit transactions."""

    session = database.session_factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
