# Local Development

This is the native Python API/contributor path, not a complete bot installation.
For guarded polling chat and Docker-only onboarding, use the
[self-hosted quickstart](self-hosted-quickstart.md). Do not use test validators
on meaningful personal/deployment data; several deliberately reset schemas.

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker and Docker Compose for PostgreSQL/Redis container workflows

Install `uv` so it is available on your normal shell `PATH`; no system-wide
Python package installation is required. The validation script prefers that
command and falls back to an executable at `.tools/uv` when one is present.
When neither is available, it stops with an installation message before running
any checks.

Telegram remains disabled unless `JANUARY_TELEGRAM_ENABLED=true` and a token is
provided. The normal validation suite uses mock transport only. An operator may
run `./scripts/verify-telegram.sh` to explicitly perform a `getMe` identity
check; it is not part of CI or canonical validation.

Update delivery is also disabled by default. Configure exactly one mode only:
`webhook` needs a platform connection UUID, HTTPS public base URL, and secret;
`polling` needs a platform connection UUID. Neither starts inside the API
process.

## Setup And Run

```bash
uv sync --all-groups --locked
cp .env.example .env
docker compose up -d --wait database redis
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir backend --reload
```

The service listens on `http://127.0.0.1:8000`. Available endpoints are `/`,
`/health`, `/live`, `/ready`, and `/docs`. `.env` is local-only; it must not
contain or commit production secrets.

## Database And Migrations

Start PostgreSQL and required Redis, then apply the schema before expecting
readiness to succeed. The copied `.env.example` enables rate limiting even
though Telegram delivery is disabled:

```bash
docker compose up -d --wait database redis
uv run alembic upgrade head
```

The broad PostgreSQL integration selection also includes real synthetic Qdrant
tests and the fresh stock Docker acceptance test. CI supplies PostgreSQL,
Redis/Qdrant and explicitly builds the test image. Before local broad validation,
build that same local image and start only disposable, operator-owned fixtures.
Before executing the example, choose a proven-empty validation project name and
unused loopback ports; replace the illustrated values consistently:

```bash
docker build --tag january-self-host:spec043-development .
COMPOSE_PROJECT_NAME=january-local-quality JANUARY_DB_HOST_PORT=5433 \
  JANUARY_REDIS_HOST_PORT=6380 JANUARY_QDRANT_HOST_PORT=6334 \
  docker compose --profile qdrant up -d --wait database redis qdrant
COMPOSE_PROJECT_NAME=january-local-quality JANUARY_DB_HOST_PORT=5433 \
  JANUARY_REDIS_URL=redis://127.0.0.1:6380/0 \
  JANUARY_QDRANT_URL=http://127.0.0.1:6334 ./scripts/validate-db.sh
```

The validator deliberately resets the owned schema,
upgrades/downgrades/re-upgrades, runs the selected integration
tests and stops its database without deleting its volume. The separate fresh
Docker test cleans only its own unique resources. Stop/remove only your
identified disposable fixture project after proof; never an unrelated stack.
Qdrant is a selected vector-test fixture, not a core text-chat dependency.

`/live` never checks PostgreSQL. `/ready` returns a safe `503` when the database,
required schema or required Redis is unavailable; `/health` reports component
states. Redis is required whenever delivery, rate limiting or provider
concurrency is enabled, and is reported `disabled` only when all three are off.

## Telegram Ingress

For the SPEC-028 candidate, use the existing planning worker and
[Telegram media operations](telegram-media.md). Canonical media tests use fake
adapters. `./scripts/validate-telegram-media.sh --repository-only` deliberately
returns 2 when Docker/migration proof has not run; the full validator uses an
isolated PostgreSQL/Redis project and alternate ports.

Run PostgreSQL and Redis ingress proof with isolated host ports:

```bash
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-ingress.sh
```

It starts only `database` and `redis`, migrates, runs webhook, polling, outbox,
and Stream integration tests, then stops those services. No real Telegram API
call occurs.

Configured operators use explicit commands only:

```bash
./scripts/telegram-webhook.sh inspect
./scripts/telegram-webhook.sh register
./scripts/telegram-webhook.sh remove
uv run python -m app.runtime.telegram_poller
uv run python -m app.runtime.ingress_outbox_dispatcher
```

`remove --drop-pending-updates` is required to request pending-update removal.
The poller refuses to run when Telegram reports an existing webhook.

SPEC-022 connection readiness, webhook lifecycle, and mode-exclusivity
operations provide verified, fail-closed alternatives (see
[`live-acceptance.md`](live-acceptance.md)):

```bash
uv run python -m app.runtime.telegram_connection_operations verify \
  --confirm-live-telegram --json
uv run python -m app.runtime.telegram_connection_operations webhook-register \
  --confirm-live-telegram --json
uv run python -m app.runtime.telegram_connection_operations webhook-delete \
  --confirm-live-telegram --confirm-delete-webhook --json
uv run python -m app.runtime.telegram_connection_operations mode-verify \
  --confirm-live-telegram --json
```

Each command contacts Telegram only after the explicit confirmation flag, never
prints the bot token or webhook secret, and verifies the resulting Telegram
state. The deterministic SPEC-022 proof uses fake adapters only:

```bash
./scripts/validate-live-acceptance.sh
```

## Conversation Processing

The conversation consumer is separate from the API, poller, and outbox
dispatcher. It reads Redis references and requires PostgreSQL and Redis:

```bash
uv run python -m app.runtime.conversation_worker
```

Run its isolated integration proof with:

```bash
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-conversation.sh
```

It uses synthetic durable Telegram updates only. No Telegram credential,
network request, LLM, or outgoing message is involved.

## Response Planning

LLM planning is disabled by default and is a separate runtime. Set a provider,
model, and required remote credential only in local operator configuration;
Ollama is the keyless local option. Do not add provider credentials to source
control.

```bash
uv run python -m app.runtime.response_planning_worker
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-planning.sh
```

The validation command uses a fake provider and synthetic context. It checks
the `0004_response_planning` schema, leases, durable attempt/plan handoff, and
duplicate worker execution without a public provider or Telegram request.

For an explicitly configured operator, `./scripts/verify-model-provider.sh`
checks configuration without network access. `--live` requires both LLM flags
and sends one small synthetic structured request; it prints only provider,
model, and local validation success.

## Outbound Delivery

Outbound delivery is disabled by default and runs only in its own process:

```bash
uv run python -m app.runtime.outbound_delivery_worker
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-delivery.sh
```

The delivery validator migrates to `0005_outbound_delivery` and uses synthetic
no-network tests. Timeout, transport, and malformed post-send outcomes become
terminal `delivery_unknown`; they are never retried automatically.

Run the SPEC-034 clean-candidate and live PostgreSQL/fake-Telegram proof with:

```bash
JANUARY_DB_HOST_PORT=5448 ./scripts/validate-telegram-conversation-ux.sh
```

It validates one authoritative direct reply reference, privacy/tenant/
Assistant exclusion, lossless deterministic splitting, adjacent-worker claim
ordering, exact deleted-target fallback, zero database sessions during external
I/O, migration round-trips and the populated downgrade guard. It needs no
Telegram or provider credential. See
[`telegram-conversation-ux.md`](telegram-conversation-ux.md).

Run the SPEC-035 no-credential clean-candidate, controlled-heartbeat, and live
PostgreSQL/Redis proof with:

```bash
JANUARY_DB_HOST_PORT=5450 JANUARY_REDIS_HOST_PORT=6397 \
  ./scripts/validate-telegram-presence.sh
```

It proves exact `sendChatAction` payload/error handling, post-admission start,
bounded owned refresh, lease/lifecycle and database-session fencing, failure
independence, offline hard evals, no migration, and no task leak. See
[`telegram-presence.md`](telegram-presence.md).

List uncertain actions without message content, or intentionally requeue one
only after accepting a possible duplicate:

```bash
uv run python -m app.runtime.outbound_recovery
uv run python -m app.runtime.outbound_recovery ACTION_UUID --confirm-possible-duplicate
```

## Telegram Commands

Deterministic Telegram administration commands run in a separate worker and
are disabled unless `JANUARY_COMMAND_WORKER_ENABLED=true`:

```bash
uv run python -m app.runtime.telegram_command_worker
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-commands.sh
```

The validator uses project PostgreSQL/Redis plus fake boundaries only. See
[`telegram-administration-commands.md`](telegram-administration-commands.md)
for guarded live acceptance steps.

## Proactive Scheduling

SPEC-029 uses the command worker for private schedule mutations, a separate
no-network scheduler for materialization, and the existing outbound worker for
Telegram delivery:

```bash
JANUARY_PROACTIVE_SCHEDULING_ENABLED=true \
JANUARY_SCHEDULER_WORKER_ENABLED=true \
JANUARY_OUTBOUND_DELIVERY_ENABLED=true \
uv run python -m app.runtime.proactive_scheduler_worker
./scripts/validate-proactive-scheduling.sh --repository-only
```

Repository-only mode exits 2 after successful unit/static proof to make pending
Docker migration/integration evidence explicit. A Docker-capable operator runs
the full validator using its isolated project and alternate ports. No real
Telegram or provider credential is used. See
[`proactive-scheduling.md`](proactive-scheduling.md).

## Data Governance

SPEC-025 adds two no-network workers that are part of the production
topology and disabled unless their flags are set. The governance worker
materializes subject/group/deployment export packages and expires stale ones; the
retention worker enforces the written retention schedule, including the
bounded `governance_audit_events` and `control_audit_events` tables:

```bash
JANUARY_DATA_GOVERNANCE_ENABLED=true JANUARY_GOVERNANCE_WORKER_ENABLED=true \
  uv run python -m app.runtime.governance_worker
JANUARY_RETENTION_WORKER_ENABLED=true \
  uv run python -m app.runtime.retention_worker
```

The DB-backed governance proof covers the export/erasure lifecycle, migration
lifecycle, and audit retention:

```bash
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 \
  ./scripts/validate-governance.sh
```

### Deployment-operator authority

Deployment export is not inferred from any tenant role. Enable the existing
SPEC-021 control plane and supply its JWT issuer, audience, and secret. To
establish the first deployment authority, set
`JANUARY_CONTROL_PLANE_DEPLOYMENT_BOOTSTRAP_SUBJECTS` to a JSON array containing
the externally approved JWT subject. That subject authenticates, calls
`GET /control/v1/me` to obtain its `identity_id`, and explicitly calls
`PUT /control/v1/deployment/authorities/{identity_id}` while no active
deployment authority exists. PostgreSQL serializes this one-time empty-set
transition.

An active deployment operator can grant an existing authenticated identity with
the same PUT route and revoke it with
`DELETE /control/v1/deployment/authorities/{identity_id}`. Repeated grant/revoke
requests do not create duplicate durable effects. Every request re-reads current
authority, so revocation is effective immediately; deployment authority does
not permit tenant operations. Set the bootstrap-subject configuration to the
empty JSON array `[]` after the authority set is established, and always do so
before deliberately revoking the final authority unless recovery by that
configured subject is intended.

The authorized export call is
`POST /control/v1/governance/deployment/export`. Supply a stable bounded
`X-Request-ID` for command idempotency. The first call returns `202`; wait for
the governance worker, then repeat the same call and request ID. The completed
HTTPS response returns the retrieval credential once with
`Cache-Control: no-store`; only the credential hash is stored. Submit the
credential only in the `Authorization` header to
`POST /api/v1/governance/exports/retrieve`, never in a path or query string.
The worker rechecks the grant before materializing. Revocation while a request
is pending records a terminal content-free failure and creates no package; use
a new request ID only after authority is explicitly granted again.

### Tenant and Assistant authority

SPEC-030 tenant provisioning is deployment-wide but all later resource work is
tenant-scoped. `POST /control/v1/tenants` requires an active
`deployment_operator` and atomically grants the creator `tenant_owner`
membership. Assistants and connections are created disabled and activated only
after configuration under an owner/admin membership. In a database with more
than one active tenant, set `JANUARY_TELEGRAM_TENANT_ID` explicitly before
running bootstrap. See [multi-tenant administration](multi-tenant-administration.md).

## Validation

Run the repository's canonical local validation command:

```bash
./scripts/validate.sh
```

It runs pytest, Ruff lint, Ruff formatting verification, mypy, Harness status
and doctor checks, and `git diff --check` when Git is available. No external
service or credential is required.

Run the SPEC-032 Telegram-first synthetic conversation-quality suite with:

```bash
uv run python -m app.runtime.ai_evaluations
./scripts/validate-ai-evals.sh
```

The dedicated validator proves the 64-case schema/runner, hard-gate precedence,
foreign tenant/Assistant exclusion, optional-judge `NOT_EVALUATED` behavior,
stable JSON, zero production mutation/external call, and a clean PATH-resolved
runner. It needs no Docker, `.env`, Telegram token or provider credential. See
[`ai-evaluations.md`](ai-evaluations.md) for selection, report and fixture
review rules.

For SPEC-009 PostgreSQL/Redis personality, snapshot, policy, and fake-adapter
proofs, run:

```bash
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 \
  ./scripts/validate-personality.sh
```

For SPEC-011 explicit-memory, privacy, and retention schema proof, run:

```bash
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 \
  ./scripts/validate-memory.sh
```

It uses only project PostgreSQL/Redis and synthetic values, upgrades through
`0008_memory_privacy_retention`, tests the schema, downgrades to
`0007_telegram_commands`, then re-upgrades. To run one bounded raw-content
retention pass outside validation, enable the dedicated no-network worker:

```bash
JANUARY_RETENTION_WORKER_ENABLED=true uv run python -m app.runtime.retention_worker --once
```

For the additive SPEC-027 personal-context, revision, recall, export/erasure,
and 0017↔0018 migration proof, run:

```bash
JANUARY_DB_HOST_PORT=5438 JANUARY_REDIS_HOST_PORT=6385 \
  ./scripts/validate-personal-context.sh
```

This validator uses synthetic data only and refuses to treat a destructive
downgrade with SPEC-027 state as success.

Conversation summaries are disabled by default. To run their separate worker,
enable both flags and the already-configured LLM provider:

```bash
JANUARY_CONVERSATION_SUMMARIES_ENABLED=true JANUARY_SUMMARY_WORKER_ENABLED=true \
  JANUARY_LLM_ENABLED=true uv run python -m app.runtime.conversation_summary_worker --once
```

Semantic explicit-memory retrieval is separately disabled by default. It has no
effect on readiness and does not embed summaries or raw messages. See
[`semantic-memory.md`](semantic-memory.md) for the guarded configuration and
local Qdrant worker commands.

Assistant knowledge RAG is independently disabled by default and uses a
separate worker and collection prefix from semantic explicit memory. Configure
the existing local embedding adapter, set both knowledge flags, and run:

```bash
JANUARY_KNOWLEDGE_RAG_ENABLED=true \
  JANUARY_KNOWLEDGE_INDEX_WORKER_ENABLED=true \
  uv run python -m app.runtime.knowledge_index_worker
```

Canonical proof needs no provider credential or Telegram token:

```bash
./scripts/validate-knowledge-rag.sh
```

See [`knowledge-base-rag.md`](knowledge-base-rag.md) for the authenticated
operator lifecycle and derived-index recovery commands.

## Safety And Rate Limits

SPEC-012 uses `response-plan-v2` and `safety-policy-v1`. Hard safety boundaries
cannot be disabled and this is not comprehensive semantic moderation. When
`JANUARY_RATE_LIMIT_ENABLED=true`, Redis is required for provider and Telegram
I/O; an outage makes `/ready` return safe `503` and leaves durable work
retryable. Commands and privacy deletion remain database mutations, while their
delivery acknowledgements may wait for Redis capacity.

Run the no-credential policy, PostgreSQL, and Redis proof with:

```bash
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-safety.sh
```

## Guarded Telegram Demo

The optional polling-only dedicated-bot workflow is documented in
[`telegram-end-to-end-demo.md`](telegram-end-to-end-demo.md). It is disabled by
default and uses the ignored `.env.demo` file created by
`./scripts/january-demo.sh init`. The script requires explicit confirmation for
live Telegram/provider checks and runs API, poller, dispatcher, conversation,
planning, command, outbound, governance, and retention workers as separate
local processes (governance/retention when their flags are enabled). Its
synthetic validator uses only project PostgreSQL/Redis and fake adapters:

```bash
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-demo.sh
```

To validate reply-based regeneration without Telegram or provider credentials:

```bash
JANUARY_DB_HOST_PORT=5452 ./scripts/validate-telegram-regeneration.sh
```

The validator uses a dedicated Compose project, preserves the explicit `0024`
migration-boundary lifecycle while verifying current head `0026`,
exports tracked and untracked candidate files into a VCS-free tree, and removes
only its own temporary database and files. Usage and recovery behavior are in
[`telegram-regeneration.md`](telegram-regeneration.md).

To validate deterministic Telegram reactions without Telegram or provider
credentials:

```bash
JANUARY_DB_HOST_PORT=5454 ./scripts/validate-telegram-reactions.sh
```

The validator exports tracked plus untracked candidate files without Git
history or `.env`, runs the 130-scenario offline eval, verifies Alembic head
`0026`, and starts only its isolated database project. See
[`telegram-reactions.md`](telegram-reactions.md).

To validate explicit reply-only voice playback without Telegram or provider
credentials:

```bash
JANUARY_DB_HOST_PORT=5456 ./scripts/validate-telegram-voice-tts.sh
```

The validator exports the full tracked-plus-untracked candidate into a VCS-free
tree, checks the 4,000-code-point and 5 MiB boundaries, runs the offline voice
eval, proves real PostgreSQL authority/idempotency/privacy and both external-I/O
session boundaries, and rehearses `0024 → 0025`, base-to-head, empty rollback,
and populated downgrade refusal. See
[`telegram-voice-tts.md`](telegram-voice-tts.md).

To validate explicit conversation feedback without Telegram or provider
credentials:

```bash
JANUARY_DB_HOST_PORT=5458 ./scripts/validate-conversation-feedback.sh
```

The validator exports the full tracked-plus-untracked candidate into a VCS-free
tree, runs the feedback slice of the 130-scenario offline suite, proves real
PostgreSQL target authority, duplicate/opposite/final-slot races, privacy,
retention and export isolation, and rehearses `0025 → 0026`, empty rollback,
base-to-head, and populated downgrade refusal. See
[`conversation-feedback.md`](conversation-feedback.md).

## Production stabilization checks

SPEC-040 adds no migration or product feature. It makes test Tenant authority
explicit and treats reliability as a hard gate. Run the complete procedure in
[`production-stabilization.md`](production-stabilization.md), including all
direct workflow validators rather than assuming `validate.sh` covers them.

For a fresh isolated reliability run, use unused alternate ports and a unique
Compose project:

```bash
COMPOSE_PROJECT_NAME=spec040-reliability \
JANUARY_DB_HOST_PORT=5580 \
JANUARY_REDIS_HOST_PORT=6430 \
./scripts/validate-reliability.sh
```

The run must exit zero with `Reliability checks: valid`. Remove only that
project with `docker compose down -v --remove-orphans`; never stop unrelated
host stacks. Do not use an ignored `.env`, credentials, prior volumes, or
arbitrary sleeps as validation prerequisites.

## Release-readiness checks

SPEC-041 adds no feature or migration. Run the credential-free release preflight
from the repository root:

```bash
./scripts/validate-production-readiness.sh
```

It validates the complete `.env.example` inventory, typed fail-closed settings,
staging Compose, container policy, direct Quality script modes, and the single
source head without contacting Telegram, providers, or production services.
Use `--production-config` only with an explicitly supplied, operator-owned
environment; it reads no `.env` and prints no values. Use
`--database-preflight` only against the selected staging/production PostgreSQL;
it is read-only and never runs an upgrade or downgrade. Follow
[`telegram-first-release-readiness.md`](telegram-first-release-readiness.md)
and the [operator checklist](telegram-first-release-checklist.md).

## Container Run

```bash
docker compose up --build backend
```

When port `8000` is already occupied, select another host port without changing
the container port:

```bash
JANUARY_HOST_PORT=8002 docker compose up --build backend
```

Stop it with:

```bash
docker compose down
```

The Compose scope contains the backend, PostgreSQL, and Redis 7. Telegram
remains disabled unless explicitly configured. When delivery is enabled,
readiness requires both PostgreSQL and Redis but never calls Telegram.
