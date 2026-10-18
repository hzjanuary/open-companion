# SPEC-002: Database and Persistence Foundation

## Outcome

January has a production-oriented PostgreSQL persistence foundation that later
platform and conversation work can use without a schema redesign.

## Scope

- PostgreSQL 16, SQLAlchemy 2.x async sessions, asyncpg, and Alembic.
- Typed database settings, an engine lifecycle, session dependency, and
  controlled readiness checks.
- Platform-independent Assistant, PlatformConnection, Conversation,
  Participant, and Message persistence models.
- A reviewed initial migration and focused repositories for the required
  identity lookups.

## Non-Goals

No Telegram behavior, webhook processing, Redis, queues, LLMs, personality,
memory, authentication, frontend, Zalo integration, billing, or external
deployment is part of this specification.

## Data Model

All core records use UUID primary keys, UTC timestamps, explicit foreign keys,
and PostgreSQL `JSONB` for extensible platform-independent metadata.

- Assistant: name and lifecycle status.
- PlatformConnection: assistant connection identity, platform, safe credential
  reference, configuration, and status.
- Conversation: platform connection identity, type, response mode, settings,
  and status.
- Participant: conversation-scoped platform identity and privacy flags.
- Message: conversation-scoped platform identity, optional participant and
  reply reference, content metadata, direction, type, and processing status.

Persisted enums are application string enums with non-native database check
constraints. Credentials and bot tokens are never stored in these tables.

## Acceptance Criteria

- Empty PostgreSQL databases migrate to head, downgrade to base, and re-upgrade.
- Async sessions and model-specific repositories operate against PostgreSQL.
- Model foreign keys, unique identities, enum constraints, JSONB, UUIDs, and
  UTC timestamps are enforced and tested.
- `/live` remains process-only; `/ready` performs bounded database/schema
  readiness; `/health` reports application and database state.
- Docker Compose runs only the backend and PostgreSQL for this scope.

## Validation

`./scripts/validate.sh` runs non-database checks. `./scripts/validate-db.sh`
starts the project PostgreSQL service, migrates, runs PostgreSQL integration
tests, validates downgrade and re-upgrade, and stops its service. CI runs both
quality and migration/integration checks without external credentials.
