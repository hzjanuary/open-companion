"""Alembic configuration using the application's validated settings boundary."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import String, Table, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from alembic.ddl.impl import DefaultImpl
from app.core.config import Settings
from app.infrastructure.database import models  # noqa: F401
from app.infrastructure.database.base import Base
from sqlalchemy.sql.schema import Column, MetaData, PrimaryKeyConstraint

# Historical alembic_version was VARCHAR(32) which cannot store
# 0017_provider_routing_cost_budgets (34). Widen to 64 centrally so
# fresh DBs create wide, existing DBs self-heal, and offline SQL is coherent.
_ORIGINAL_VERSION_TABLE_IMPL = DefaultImpl.version_table_impl


def _patched_version_table_impl(  # type: ignore[no-untyped-def]
    self,
    version_table: str,
    version_table_schema=None,
    version_table_pk=True,
    **kw,
):
    vt = Table(
        version_table,
        MetaData(),
        Column("version_num", String(64), nullable=False),
        schema=version_table_schema,
    )
    if version_table_pk:
        vt.append_constraint(
            PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc")
        )
    return vt


DefaultImpl.version_table_impl = _patched_version_table_impl  # type: ignore[method-assign]

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    settings = Settings()
    context.configure(
        url=settings.resolved_database_url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _heal_version_width(connection: Connection) -> None:
    try:
        if connection.in_transaction():
            connection.commit()
        current = connection.execute(
            text(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_name='alembic_version' AND column_name='version_num'"
            )
        ).scalar()
        if current is not None and int(current) < 64:
            connection.execute(
                text(
                    "ALTER TABLE alembic_version "
                    "ALTER COLUMN version_num TYPE VARCHAR(64)"
                )
            )
            connection.commit()
    except Exception:
        try:
            if connection.in_transaction():
                connection.rollback()
        except Exception:
            pass


def do_run_migrations(connection: Connection) -> None:
    # Heal legacy VARCHAR(32) BEFORE stamping 0017 (which is 34 chars).
    _heal_version_width(connection)
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
    # Post-migration heal covers fresh creates on older code paths.
    _heal_version_width(connection)


async def run_migrations_online() -> None:
    settings = Settings()
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.resolved_database_url.render_as_string(
        hide_password=False
    )
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
