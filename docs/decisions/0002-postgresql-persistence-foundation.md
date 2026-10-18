# 0002 PostgreSQL Persistence Foundation

Date: 2026-07-29

## Status

Accepted

## Context

SPEC-002 requires a durable, platform-independent persistence foundation that
preserves the modular-monolith dependency direction and can prove PostgreSQL
behavior without substituting SQLite.

## Decision

Use PostgreSQL 16 with SQLAlchemy 2.x asynchronous APIs, asyncpg, and Alembic.
Keep engines, sessions, declarative models, migrations, and repositories in
the infrastructure boundary. Use UUID primary keys, timezone-aware UTC
timestamps, JSONB metadata, and validated application string enums persisted
as non-native constraints. Run persistence integration tests against PostgreSQL.

## Alternatives Considered

1. SQLite for local and test persistence.
2. Synchronous SQLAlchemy sessions.
3. Native PostgreSQL enum types.

## Consequences

Positive:

- Tests exercise PostgreSQL JSONB, constraints, and migration behavior.
- Inner application interfaces remain independent of SQLAlchemy and asyncpg.

Tradeoffs:

- Database integration validation requires Docker.

## Follow-Up

- Later specifications add only the persistence objects proven necessary by
  their accepted scope.
