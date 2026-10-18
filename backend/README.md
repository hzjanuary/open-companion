# Backend

The January backend is a Python 3.12 FastAPI application factory with
PostgreSQL persistence and a Redis Streams ingress foundation.

For a complete guarded bot rather than an API-only developer process, use the
[Docker self-host quickstart](../docs/runbooks/self-hosted-quickstart.md).
It starts the existing required worker graph with enforced safety/privacy/
provider controls and authenticated setup, polling-first, without host Python
or UV. Local Docker Compose and optional single-VPS are the future default;
webhook, Qdrant, TTS and centralized production procedures are conditional.
SPEC-043 is complete at the committed self-host baseline. The owner selected
[MIT](../LICENSE) in SPEC-044; historical handoff (private execution record omitted from this snapshot)
records retain their original license-pending chronology. Public release
validation and publication are separate; see [release policy](../docs/maintainers/release-process.md).
No new product entities/routes/schema or provider capabilities are introduced.

The commands below are the native Python 3.12/UV development path. Follow
[local development](../docs/runbooks/local-development.md) for its dependency/
configuration order. `.env.example` is the full inventory; `.env.self-host.example`
is the separate minimal raw Docker config and must not be sourced. Canonical
Quality needs no real Telegram/provider credentials. See [VPS](../docs/runbooks/self-hosted-vps.md),
[maintenance](../docs/runbooks/self-hosted-upgrades.md),
[troubleshooting](../docs/runbooks/self-hosted-troubleshooting.md), and
[security reporting](../SECURITY.md).

Run locally from the repository root:

```bash
uv run uvicorn app.main:app --app-dir backend --reload
```

Run `./scripts/validate.sh` from a normal shell after installing `uv`. It uses
`uv` from `PATH`, with `.tools/uv` as an optional repository-local fallback.

## Database

PostgreSQL 16 is the persistence runtime. Start it with `docker compose up -d
database`, then apply the reviewed schema with `uv run alembic upgrade head`.
Use `uv run alembic downgrade base` only for local validation; reapply with
`uv run alembic upgrade head`.

`/live` checks only the process. `/ready` performs bounded PostgreSQL and
Alembic-schema checks, plus Redis when Telegram delivery, rate limiting or
provider concurrency is enabled. The copied example enables rate limiting,
so start Redis as well. `/health`
reports application, database, and Redis component states.

## Telegram Adapter

Telegram is disabled by default. The typed adapter implements `getMe`,
`sendMessage`, `sendSticker`, `sendVoice`, `getChatMember`, `getUpdates`, `setWebhook`,
`deleteWebhook`, and `getWebhookInfo`. Webhook and polling share a durable
PostgreSQL inbox/outbox, then publish typed references to Redis Streams.

Run PostgreSQL/Redis ingress proof with:

```bash
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-ingress.sh
```

Run polling and dispatch only as dedicated processes: `uv run python -m
app.runtime.telegram_poller` and `uv run python -m
app.runtime.ingress_outbox_dispatcher`. Explicit webhook operations use
`./scripts/telegram-webhook.sh`; none run during API startup.

## Conversation Worker

The worker consumes durable ingress references into normalized conversations,
participants, messages, membership state, deterministic eligibility, and
bounded context. It does not call an LLM or send messages. Start it only as a
dedicated process after PostgreSQL and Redis are ready:

```bash
uv run python -m app.runtime.conversation_worker
```

Run its synthetic PostgreSQL/Redis proof with:

```bash
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-conversation.sh
```

The worker commits business state and its idempotency ledger before it
acknowledges Redis. It logs identifiers and outcomes, not message content.

## Response Planning

LLM integration is disabled by default. When explicitly enabled, the planning
worker uses configured OpenAI, Gemini, Groq, OpenRouter, or local Ollama models
through typed HTTP adapters. It stores validated platform-independent response
plans only; it does not send Telegram messages.

```bash
uv run python -m app.runtime.response_planning_worker
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-planning.sh
```

Provider keys are `SecretStr` settings and are never required for canonical
validation. Model capability declarations determine whether JSON Schema output
is requested; local schema and policy validation remains mandatory.

## Offline AI Evaluation

SPEC-032 composes the pure planning, context, ambient, scheduling, Telegram
media, voice-policy, and feedback seams into a deterministic 130-scenario runner. It does not
start a production runtime, read a database, call Telegram/providers, or use
credentials:

```bash
uv run python -m app.runtime.ai_evaluations
./scripts/validate-ai-evals.sh
```

See [`docs/runbooks/ai-evaluations.md`](../docs/runbooks/ai-evaluations.md) for
fixture, selection, result-status and optional-judge boundaries.

When enabled, `JANUARY_PROVIDER_CONCURRENCY_*` is a Redis TTL semaphore scoped
by deployment/provider. It caps in-flight provider I/O, while the existing
rate limiter caps throughput; both are checked before provider I/O and neither
blocks privacy or other database-only mutations.

## Ambient Participation

`JANUARY_AMBIENT_SELECTIVE_ENABLED=false` is the default. When enabled, a group
administrator may select `ambient_selective` mode and `/frequency low|normal|high`.
Addressed messages bypass ambient sampling and cooldown. Ambient candidates are
sampled deterministically from internal IDs, and only confirmed ambient
delivery starts PostgreSQL-backed cooldown. Run `./scripts/validate-ambient.sh`
for local, credential-free proof.

## Safety And Rate Limits

`response-plan-v2` carries closed interaction metadata and is checked against
current context, opt-outs, privacy deletion, and personality boundaries before
provider and Telegram I/O. `safety-policy-v1` has hard boundaries and no roast
mode; it is structural enforcement, not comprehensive semantic moderation.
When `JANUARY_RATE_LIMIT_ENABLED=true`, Redis atomically coordinates generation
and delivery budgets. Redis loss fails closed for external I/O, while durable
work retries and database-only privacy/admin commands continue. Run the
synthetic policy and datastore proof with:

```bash
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-safety.sh
```

Every response includes `X-Request-ID`. A syntactically valid incoming value is
preserved; otherwise one is generated. Unhandled failures return a safe JSON
error with the same request ID.

## Personality Configuration

SPEC-009 keeps personality as typed, immutable profile versions and applies
conversation-specific immutable revisions. New conversations reconcile to the
Assistant's `January Default` profile with `mention_only` mode and stickers
disabled by default. Planning jobs snapshot the selected profile version and
configuration revision in their creation transaction; the planning worker uses
that snapshot deterministically, while checking the current revision before
provider I/O. A newly paused configuration therefore blocks new and claimed
planning work. The outbound worker rechecks current sticker enablement before
Telegram I/O and skips stale sticker actions when disabled.

Use the local-only CLI documented in
[`docs/runbooks/group-configuration.md`](../docs/runbooks/group-configuration.md).
It has no public HTTP or Telegram administration path. Full prompts and
operator-provided free-form instructions are intentionally unsupported.

## Outbound Delivery

Response planning does not send directly. The optional outbound worker leases
durable actions and is disabled unless `JANUARY_OUTBOUND_DELIVERY_ENABLED=true`.
Run it separately with `uv run python -m app.runtime.outbound_delivery_worker`.
Known Telegram rejections are bounded retries; timeout, network, and malformed
post-send outcomes are terminal `delivery_unknown` to avoid automatic duplicate
sends. Direct Telegram responses put canonical reply metadata only on the first
visible action. Plain text is split deterministically at grapheme-safe
paragraph/newline/space boundaries into at most four 3,400 UTF-16-unit chunks;
all actions are persisted atomically and each later ordinal requires every
predecessor to be `delivered`. An exact Telegram 400 missing-reply rejection may
make one replyless attempt; ambiguous errors never do. Run the isolated proof:

```bash
JANUARY_DB_HOST_PORT=5448 ./scripts/validate-telegram-conversation-ux.sh
```

See [`docs/runbooks/telegram-conversation-ux.md`](../docs/runbooks/telegram-conversation-ux.md).
`./scripts/validate-delivery.sh` remains the broader synthetic delivery proof.

## Telegram Presence

The response-planning runtime reuses one Telegram adapter to emit native
`typing` only for directly addressed provider-backed work. Governed mode starts
after durable provider admission; legacy mode starts after its final provider
rate gate. One owned heartbeat refreshes every four seconds, makes at most five
calls over twenty seconds, and is cancelled and awaited before response-plan
completion. Ambient/proactive/command, denied, disabled, terminal, and recovered
work emits none. Presence failure never changes provider or response behavior.

```bash
JANUARY_DB_HOST_PORT=5450 JANUARY_REDIS_HOST_PORT=6397 \
  ./scripts/validate-telegram-presence.sh
```

See [`docs/runbooks/telegram-presence.md`](../docs/runbooks/telegram-presence.md).

## Telegram Reactions

The planning worker may add one deterministic `👍` or `❤️` to an eligible
addressed user acknowledgement. It revalidates tenant, Assistant, connection,
conversation, participant, and message authority in a short session after the
planning job is terminal, closes that session, and makes one
`setMessageReaction` call with no retry. The decision makes no provider call and
creates no outbound action or recovery state; failure never changes the normal
response.

```bash
JANUARY_DB_HOST_PORT=5454 ./scripts/validate-telegram-reactions.sh
```

See [`docs/runbooks/telegram-reactions.md`](../docs/runbooks/telegram-reactions.md).

## Telegram Voice Playback

SPEC-038 adds argument-free, reply-only `/voice`. The command resolves a
delivered outgoing text message to its authoritative response plan, runs one
governed OpenAI `gpt-4o-mini-tts` request with voice `alloy`, persists at most
5 MiB of native OGG/Opus as a short-lived PostgreSQL artifact, and creates one
durable `voice` outbound action. The 4,000-code-point source is passed exactly;
no chat generation, rewrite, media download, transcription, memory, knowledge,
summary, typing, or reaction work is performed.

The command and outbound workers close all database scopes before TTS and
Telegram I/O. Definitive Telegram retry reuses the same artifact; ambiguous TTS
or Telegram completion is not automatically repeated. The feature is disabled
by default and requires enforced provider governance, an eligible OpenAI TTS
route/budget, Redis rate and concurrency coordination, and the normal Telegram
command/outbound prerequisites.

```bash
./scripts/validate-telegram-voice-tts.sh
```

See [`docs/runbooks/telegram-voice-tts.md`](../docs/runbooks/telegram-voice-tts.md).

## Conversation Feedback

SPEC-039 adds exact reply-only `/feedback helpful|unhelpful`. PostgreSQL resolves
the local delivered target to the exact split, regenerated, or voice-source
response plan and stores one participant-owned current row plus immutable
state-changing events. Same-value replay is `NO_CHANGE`; different values are
serialized and capped at 10 revisions.

The command creates only its deterministic acknowledgement plan/action. It
does not invoke generation, TTS, embeddings, transcription, vision, Qdrant,
Telegram reactions/presence, regeneration, memory, knowledge, summaries, or
configuration. Commands, acknowledgements, and values are excluded from future
context and summaries.

```bash
./scripts/validate-conversation-feedback.sh
```

See [`docs/runbooks/conversation-feedback.md`](../docs/runbooks/conversation-feedback.md).

## Dedicated Demo

The optional end-to-end demo is a polling-only workflow for one dedicated test
bot and explicit numeric chat allowlist. It is disabled by default. Create the
ignored local configuration and check it before any live operation:

```bash
./scripts/january-demo.sh init
# Edit .env.demo with a dedicated test bot, provider/model, and test chat IDs.
./scripts/january-demo.sh doctor
./scripts/january-demo.sh bootstrap --confirm-live-telegram
./scripts/january-demo.sh up --confirm-live-demo
```

`bootstrap` makes the only identity-verification Telegram request and requires
explicit confirmation. The allowlist is enforced before conversation processing
and again before outbound delivery. `./scripts/validate-demo.sh` is synthetic:
it uses fake adapters and local PostgreSQL/Redis only.

## Explicit Memory, Privacy, and Retention

Memory is explicit-only and scoped to the exact conversation. The command
worker never invokes a model provider for memory/privacy commands. `/forget_me`
warns without mutation; only `/forget_me confirm` erases/anonymizes January's
primary-database state. Deleted memory and redacted raw content are physically
cleared while technical tombstones remain.

```bash
JANUARY_RETENTION_WORKER_ENABLED=true uv run python -m app.runtime.retention_worker --once
JANUARY_CONVERSATION_SUMMARIES_ENABLED=true JANUARY_SUMMARY_WORKER_ENABLED=true \
  JANUARY_LLM_ENABLED=true uv run python -m app.runtime.conversation_summary_worker --once
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-memory.sh
```

The dedicated worker uses PostgreSQL only, applies a maximum 30-day raw-content
limit in bounded batches, and never calls Telegram or an LLM.
Conversation summaries are optional, short-lived derived context. Their dedicated
worker reads only retained incoming text, never runs on the response path, and
expires each summary at the earliest source-message retention deadline.

## Semantic Explicit Memory

Semantic retrieval is disabled by default and operates only on active explicit
memories. PostgreSQL remains authoritative; Qdrant is a rebuildable derived
index containing vectors and content-free opaque scope metadata, never memory
text. Each query result is revalidated in PostgreSQL before canonical content
enters context, so stale Qdrant points cannot restore forgotten memories.

Enable a separately configured local Ollama embedding capability and run the
optional worker outside the API process. Qdrant or embedding failure falls back
to the existing bounded explicit-memory selection. See
[`docs/runbooks/semantic-memory.md`](../docs/runbooks/semantic-memory.md).
The existing OpenAI, Gemini, Groq, OpenRouter, and Ollama chat adapters are
generation capabilities; only the separate local Ollama embedding adapter is
currently supported for semantic memory. `/ready` deliberately does not depend
on Qdrant, Ollama, or the optional worker.

## Assistant Knowledge Base / RAG

SPEC-033 adds a second, strictly separate Qdrant pathway for operator-provided
Assistant knowledge. PostgreSQL owns the tenant/Assistant/KB/document/revision/
chunk chain; Qdrant payloads contain opaque IDs and index versions only. The
planning reader drops every vector candidate not reconfirmed as current and
eligible in PostgreSQL, and derived-service failure yields empty knowledge
context without failing the Telegram response path.

Enable it explicitly, configure the existing governed Ollama embedding route,
and run the separate worker:

```bash
JANUARY_KNOWLEDGE_RAG_ENABLED=true \
  JANUARY_KNOWLEDGE_INDEX_WORKER_ENABLED=true \
  uv run python -m app.runtime.knowledge_index_worker
```

Use [`docs/runbooks/knowledge-base-rag.md`](../docs/runbooks/knowledge-base-rag.md)
for lifecycle, reindex/rebuild, deletion and Qdrant-reset recovery. Knowledge
does not share tables, jobs, collections, context fields or deletion behavior
with explicit memory.
# Backend

## Observability

Operational telemetry is disabled by default. Set `JANUARY_METRICS_ENABLED=true`
and `JANUARY_METRICS_EXPORT_ENABLED=true` to start the local loopback-only
Prometheus-text exporter on `JANUARY_METRICS_BIND_HOST` and
`JANUARY_METRICS_PORT` (defaults: `127.0.0.1:9464`). See
`docs/runbooks/observability.md`; no metrics endpoint is exposed by the API.
# Operational recovery

SPEC-016 adds local-only, content-safe inspection with `uv run python -m
app.runtime.operations inspect`. A single replayable dead letter requires
`replay --kind <planning|outbound> --id <opaque-id> --confirm`; ambiguous
Telegram delivery is quarantined and cannot be replayed by this interface.

Provider in-flight concurrency is enabled with
`JANUARY_PROVIDER_CONCURRENCY_ENABLED=true`, a JSON provider limit map, and a
TTL lease. It is separate from throughput rate limiting.

## Telegram regeneration

An argument-free `/regenerate` command is accepted only as a reply to a local,
certain, provider-backed assistant response. Admission creates a fresh governed
planning job with immutable root/parent/ordinal lineage (maximum three per root)
and rebuilds current context around the original user turn. A single eligible
text presentation compiles a durable `edit_text` action plus a blocked text
fallback; split, sticker, erased, ambiguous, or otherwise unsafe targets use a
new ordered send. See
[`docs/runbooks/telegram-regeneration.md`](../docs/runbooks/telegram-regeneration.md).

## Production stabilization

SPEC-040 changes no backend runtime, model, API, worker, or migration. It repairs
integration-test authority setup that had depended on migration residue or
earlier test order. Tests that create an Assistant must explicitly establish
its Tenant first; bootstrap tests must select unambiguous tenant authority.
`fk_assistants_tenant` remains validated and non-nullable. Run
`./scripts/validate-reliability.sh` as a hard gate and use the complete clean
matrix in
[`docs/runbooks/production-stabilization.md`](../docs/runbooks/production-stabilization.md).

## Production release readiness

SPEC-041 adds no API, command, worker, model, schema, or product behavior. It
hardens typed configuration loading, keeps the complete 244-setting inventory
in `.env.example`, and provides an offline default preflight plus explicit
redacted production-config and database-preflight modes:

```bash
./scripts/validate-production-readiness.sh
./scripts/validate-production-readiness.sh --production-config
./scripts/validate-production-readiness.sh --database-preflight
```

The first command performs no external I/O. Production-config mode reads only
the supplied environment and prints no values. Database preflight is read-only:
it verifies connectivity, current revision, and the approved linear upgrade
path to `0026_conversation_feedback`; it never migrates or downgrades. See the
[release-readiness runbook](../docs/runbooks/telegram-first-release-readiness.md)
and [operator checklist](../docs/runbooks/telegram-first-release-checklist.md).
