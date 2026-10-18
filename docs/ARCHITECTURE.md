# January Architecture

January is a modular monolith. It will grow into independently scalable API,
worker, and sender runtime processes without splitting product behavior into
services prematurely.

## Self-host distribution boundary

From SPEC-043 onward, deployment defaults to local-first/self-hosted Docker
Compose with an optional single VPS, not a central commercial organization.
See the [deployment policy](product/self-hosted-deployment-profile.md) and
[quickstart](runbooks/self-hosted-quickstart.md). Historical SPEC-041/042 release
and promotion evidence remains unchanged; stricter downstream practices remain
supported. SPEC-043 is complete; SPEC-044 adds MIT licensing and public release
procedures without changing product architecture. See the
[release process](maintainers/release-process.md) for candidate and publication
boundaries; historical evidence is not rewritten.

`compose.self-host.yaml` wires existing stock modules: private PostgreSQL/Redis,
a sole exact-head migration, API, one polling ingress (or optional webhook),
dispatcher, conversation/planning/command/outbound, provider recovery,
governance and retention. Optional summary/semantic/knowledge/scheduler workers
are profile-gated; vector profiles supply private Qdrant. The normal app runs
non-root. Native API/dependency development remains in `compose.yaml` with
loopback host ports. No application route/domain/schema/capability change.

The bounded setup facade uses existing authenticated control routes and trusted
bot reconciliation to establish canonical active tenant/owner/Assistant/
connection and explicit enforced provider policies. It does not seed raw
tenant/policy SQL or enable a demo/legacy shortcut. Static doctor and optional
network-disabled typed image check are scoped preflight, not live acceptance.
PostgreSQL remains authoritative, Redis reconstructible coordination, and
Qdrant derived/revalidated. Raw media stays ephemeral; short-lived voice BYTEA
remains PostgreSQL-owned under existing erasure/retention. Public control-plane
exposure, vendor monitoring and registry publication are not prerequisites.

## Dependency Direction

SPEC-028 candidate extends the existing Telegram normalizer and planning worker
with source-scoped `message_media` state. Raw bytes stay ephemeral; voice/audio
transcripts become provenance-marked user content under existing privacy rules.
Current-turn images extend the generation request, and transcription shares the
SPEC-026 admission core. No media store, new vendor or worker service is added.
See [ADR-0025](decisions/0025-ephemeral-telegram-media-and-derived-transcripts.md)
and [media operations](runbooks/telegram-media.md).

```text
domain
  <- application
      <- infrastructure
          <- interface
              <- runtime surfaces
```

Dependencies point toward the left. The domain is framework-independent;
application code coordinates use cases; infrastructure implements external
ports; interfaces translate transport input and output; runtime surfaces wire
the application together.

SPEC-002 adds concrete domain records, application persistence ports, and
PostgreSQL infrastructure. It still avoids speculative modules.

## Boundary Rules

- Framework and provider clients stay outside the domain layer.
- Telegram, Zalo, LLM, database, and queue SDKs stay outside inner layers.
- Unknown external input is parsed at interfaces before it enters inner layers.
- Future model-generated actions are validated by application policy before
  execution by an adapter.
- Operational logs describe runtime behavior; product audit records are a
  separate future persistence concern.
- Current readiness reports only the running application. It does not claim
  health for future dependencies.

## Current Layout

```text
backend/app/
  core/          settings, logging, request context
  domain/        platform-independent persistence records and enums
  application/   persistence and platform-independent ingress contracts
  infrastructure/database/ async engine, models, repositories, migrations
  infrastructure/telegram/ typed Bot API HTTP adapter and Update DTOs
  infrastructure/queue/ Redis Streams ingress queue
  interface/http/ response models, routes, middleware
  runtime/       dedicated polling and outbox dispatch entry points
  main.py        application factory and API runtime entry point
```

The factory is the composition boundary. New modules are introduced only with
the first behavior that needs them.

SPEC-004 keeps Telegram raw payloads and SDK contracts in infrastructure. The
application ingress envelope is platform independent; PostgreSQL owns durable
deduplication and outbox intent; Redis Streams transports references only.

SPEC-005 consumes those references in a dedicated runtime. Telegram payloads
are normalized before application policy runs; PostgreSQL commits normalized
conversation state and the idempotency ledger before Redis acknowledgement.
Context readers return application values rather than ORM models, raw payloads,
or credentials. No LLM or outgoing-delivery dependency crosses this boundary.

SPEC-006 adds a separate response-planning runtime. Provider HTTP JSON remains
in infrastructure; application values carry only typed generation requests,
results, and safe errors. PostgreSQL leases and immutable response plans make
planning durable without claiming exactly-once generation or executing any
platform action.

SPEC-007 compiles response plans to ordered platform-independent actions in the
planning transaction. Its sender is a separate runtime: PostgreSQL owns action
leases, attempts, and outgoing-message linkage; Telegram rendering and asset
references stay in infrastructure. A send timeout or malformed post-send
response is terminal `delivery_unknown`, deliberately avoiding automatic
duplicate visible messages rather than claiming exactly-once delivery.

SPEC-008 adds only explicit runtime composition for local operators. Demo
allowlisting happens before conversation persistence, bootstrap reconciles safe
identity metadata transactionally, and all five workers remain separate from
the API process.

SPEC-009 adds typed personality values in `application` and immutable profile
and conversation-configuration persistence in `infrastructure/database`.
Operator mutation remains a local runtime CLI; no personality HTTP or Telegram
command surface exists. Planning receives immutable job snapshots and performs
provider I/O only after checking the current conversation safety projection.
Outbound delivery similarly checks current sticker enablement immediately before
Telegram I/O. ORM models and provider/platform clients do not enter the
personality application module.

SPEC-010 parses Telegram command entities only at the infrastructure boundary,
then writes a durable command job before ordinary model eligibility. A dedicated
command runtime performs fresh group authorization through the platform port and
creates the same response-plan/outbound-action handoff used by model work.
Command jobs, response plans, and delivery remain independently scalable
runtime processes; command parsing and grammar do not import provider clients.

SPEC-011 keeps explicit-memory contracts in `application`, while PostgreSQL
owns scoped memory rows, content-free events, physical redaction, and retention
batching. Context includes only active records belonging to the exact
Assistant, platform connection, and conversation; memory enters provider input
only as JSON-delimited untrusted data. Privacy and memory mutations advance a
durable conversation revision that planning rechecks immediately before
provider I/O. The retention runtime owns no Telegram, Redis, or provider client
and is separate from API startup.

SPEC-012 keeps hard safety policy and rate-limit contracts in the inner layers.
Redis is an infrastructure implementation of atomic multi-scope coordination;
enabled coordination is required for provider and Telegram I/O, while command
and privacy database mutations remain independent. Content-free PostgreSQL
decision records and the inspector expose policy state without unsafe content.

SPEC-013 verifies only that Zalo OA, OA messaging, GMF, and webhook are distinct
official product surfaces. Zalo runtime work remains deferred pending dedicated
test OA/app verification of auth, webhook, and GMF semantics. The core remains
platform-neutral; Telegram-specific assumptions, candidate schema risks, and
reusable boundaries are documented in `docs/platforms/zalo/` without adding a
platform enum, adapter, migration, or runtime dependency.

SPEC-014's repository preparation is complete, but its live verification is
`DEFERRED / BLOCKED_ON_EXTERNAL_PREREQUISITE` until an operator-owned dedicated
nonproduction OA/application exists. This Zalo-only dependency is outside the
Telegram MVP critical path; the next implementation specification is SPEC-015
for accepted Telegram/product work only.

SPEC-015 adds a platform-neutral application telemetry port. Each API or worker
runtime owns a process-local infrastructure registry; an external collector may
aggregate replicas. Prometheus-text export is an optional local runtime surface
and never enters domain/application policy or readiness dependencies.

SPEC-016 preserves the same direction: recovery vocabulary and concurrency
ports are inner contracts, while PostgreSQL recovery history, transaction
advisory ordering locks, and Redis TTL provider leases remain infrastructure.
PostgreSQL serializes durable processing of one conversation/topic only within
its business transaction; no lock spans provider or Telegram I/O. Recovery
history contains opaque internal work IDs and closed classes only. A generic
dead letter can re-enter normal scheduling once; a quarantine, including an
ambiguous Telegram delivery, is intentionally not generically replayable.

SPEC-017 keeps ambient participation policy in inner typed contracts. PostgreSQL
retains immutable frequency revisions, trigger/origin, and confirmed delivery
timestamps; Redis remains rate/concurrency coordination only. Sampling uses
opaque internal IDs and no content.

SPEC-018 keeps conversation summaries outside the domain as short-lived derived
context. PostgreSQL stores summary jobs and content under the same conversation/
thread boundary, while provider I/O stays in an optional runtime worker. Summary
source windows use only retained raw messages; summaries never become input to
later summaries and expire at the earliest represented raw-content deadline.

SPEC-019 keeps explicit-memory semantic retrieval outside the inner domain.
PostgreSQL is authoritative for canonical text, active/deleted state, and exact
Assistant/connection/conversation scope. Qdrant is a rebuildable derived index
containing vectors and content-free opaque metadata only. Query results are
opaque IDs and must be revalidated against PostgreSQL before memory text enters
context. Embedding and Qdrant clients stay in infrastructure; the durable index
worker is a separate runtime and semantic failure falls back to existing memory
selection. A PostgreSQL routing row selects the active physical collection for
each compatible embedding version only after an operator rebuild verifies its
opaque point IDs against canonical active-memory IDs; prior collections remain
derived, non-authoritative recovery artifacts.

SPEC-020 keeps deployment concerns outside product policy. The API remains
stateless and migrations are a separately owned deployment step before API or
worker roles start. Ingress, conversation, planning, command, outbound,
retention, summary, and semantic-index processes have independent lifecycle,
restart, and drain boundaries. `/live` is process-only; `/ready` checks bounded
required dependencies and schema compatibility, while optional Qdrant/Ollama
and derived workers expose separate operational state. External secrets are
injected at the process boundary and controlled-restart rotation is the default.

SPEC-026 adds one provider-neutral admission boundary around response-planning,
summary, and embedding adapters. PostgreSQL owns immutable capability, routing,
health-policy, price, and budget revisions plus content-free attempt and
reservation state. Each call commits budget admission, then retains the
existing Redis rate and provider-concurrency gates, durably marks possible I/O,
and invokes the adapter without a database session or lock. Generation and
embedding policies and budgets never share headroom. Missing usage remains
unknown and operator-supplied fixed-point cost is always an estimate, not
billing truth. A separate bounded recovery worker releases proven no-I/O
reservations and conservatively consumes ambiguous `io_started` reservations.
Deployment configuration uses the existing `deployment_operator`; tenant
resource configuration uses exact SPEC-021 Assistant/PlatformConnection
bindings and does not broaden multi-tenancy.

SPEC-027 extends the existing memory aggregate rather than introducing a
profile service. PostgreSQL owns creator-private, exact-private-conversation
personal context; positive record revisions; exact participant/conversation
recall authority; and content-free command idempotency/progress. Deterministic
context selection applies recall before selection, keeps personal context out
of Qdrant, revalidates explicit semantic matches against creator recall state,
and closes the database session before embedding or derived-index I/O. Every
provider-bound response still crosses the SPEC-026 safety, budget, rate, and
concurrency boundary.

SPEC-029 adds a PostgreSQL-authoritative private scheduler without creating a
general workflow engine. Exact Telegram command jobs mutate preferences and
schedules idempotently; bounded due evaluation creates stable occurrence rows;
and a separate no-network scheduler worker leases occurrences before atomically
compiling the existing response-plan/outbound handoff. The outbound worker is
still the only Telegram sender and revalidates privacy, schedule version,
membership, runtime state, and check-in consent immediately before external I/O.
Catch-up collapses missed recurrence to one latest occurrence, and ambiguous
delivery retains the existing quarantine semantics. V1 check-ins are versioned
code-owned text: no provider, embedding, transcription, memory, or Qdrant path is
added. Terminal schedule timing/content is reduced to content-free tombstones.

SPEC-030 reuses `control_tenants`, memberships, and deployment authorities as
the only administrative authority graph. Every Assistant has one immutable
tenant; every PlatformConnection has one immutable tenant and Assistant, with
composite foreign keys proving they agree. Conversations intentionally do not
copy those authority columns: they derive one Assistant and tenant through
their persisted connection. Participants, private context, memory, schedules,
media, and outbound work remain descendants of that conversation boundary.

```text
ControlTenant 1 ── N Assistant 1 ── N PlatformConnection
                                      1
                                      └── N Conversation 1 ── N Participant
                                                          ├── memory/context
                                                          └── schedules/work

OperatorIdentity ── tenant-scoped Membership ── ControlTenant
OperatorIdentity ── deployment-wide DeploymentAuthority (separate)
```

Compatibility control bindings remain constrained indexes, not authority.
Provider attribution retained for operations is composite-constrained to the
same core rows. Tenant/Assistant/connection status is freshly revalidated after
work claims and before provider or Telegram I/O. Authority fields cannot be
reassigned, retired state is terminal, and new Assistants/connections are
disabled until explicitly activated. See [ADR-0027](decisions/0027-canonical-tenant-assistant-authority.md).

SPEC-032 adds an offline evaluation package outside the production runtime
graph. Versioned repository-synthetic JSON enters a strict loader, one closed
driver invokes existing pure planning/context/ambient/scheduling/media policy,
and objective observations flow through independent hard gates before optional
rubric scoring. The package imports no database repository, Settings, Redis,
Qdrant, real provider factory or Telegram client. Canonical execution therefore
has no production state or external-I/O edge. Missing subjective judgment stays
`NOT_EVALUATED`; a hard privacy/safety/authority failure always fails the suite.
See [ADR-0028](decisions/0028-offline-hard-gate-ai-evaluation.md).

```text
synthetic JSON -> strict fixture loader -> closed policy driver -> observation
                                                              |-> hard gates
                                                              `-> soft rubric
                                                                  (disabled v1)
```

SPEC-033 adds a knowledge aggregate beside, never inside, explicit memory.
PostgreSQL owns Assistant enablement, knowledge-base/document lifecycle,
immutable content revisions, deterministic chunks, current-revision pointers,
and replayable index jobs. The separate Qdrant collection contains vectors and
only opaque tenant/Assistant/base/document/revision/chunk IDs plus embedding and
index-schema versions. Search results are candidates until a fresh PostgreSQL
join validates the full ownership and lifecycle chain and returns bounded text.
The ordinary context reader closes its database scope before embedding/Qdrant
I/O, and the worker never retains a session or lock across either dependency.

```text
operator -> PostgreSQL KB/revision/chunks -> durable index job
                                              | (session closed)
                                              v
                                      governed embedding -> Qdrant IDs

message -> eligible active KB IDs -> query embedding -> Qdrant candidate IDs
                                                    -> PostgreSQL revalidation
                                                    -> reference-only context
```

Knowledge references are a distinct prompt field and cannot mutate or inherit
memory/personal-context policy. Owner/admin roles manage content; auditors see
content-free lifecycle/index metadata; operators, viewers, deployment-only
identities, and foreign tenant chains are denied. PostgreSQL-first deletion
redacts canonical content before derived cleanup. See
[ADR-0029](decisions/0029-postgresql-authoritative-knowledge-rag.md) and the
[knowledge runbook](runbooks/knowledge-base-rag.md).

SPEC-034 adds one typed `reply_reference` to the existing context path. The
platform reply ID remains a hint until PostgreSQL verifies the current message,
target message, conversation, connection, Assistant and tenant as one active
authority chain. Redacted, erased, expired, unknown or foreign targets return
no reference; assistant chunks resolve through their non-redacted response plan
so the logical response appears once and its delivered chunk rows are removed
from recent history. Reply text remains untrusted conversational context and
cannot become system policy, memory or knowledge.

The existing response-plan transaction compiles plain text into a bounded
action sequence. Every action carries the exact count and immutable ordinal;
claim SQL admits an ordinal only after every predecessor is `delivered`.
Telegram I/O occurs after database scopes close. Only a code-owned exact 400
missing-reply classification permits one second request without reply metadata;
ambiguous outcomes remain `delivery_unknown` and block the sequence tail.

```text
reply platform ID -> PostgreSQL authority/retention -> typed reply_reference

response plan -> deterministic chunks -> atomic ordered actions
                                      -> short claim transaction
                                      -> Telegram I/O (no DB session)
                                      -> short result transaction
```

See the [Telegram conversation UX runbook](runbooks/telegram-conversation-ux.md).

SPEC-035 adds a transient presence branch at the provider-I/O boundary. The
planning worker constructs it only for Telegram `addressed` work. Governed
providers invoke the initial action after durable reservation, rate,
concurrency, authority, and `io_started` admission; legacy providers invoke it
after their final pre-provider rate check. The initial call and every refresh
run only after a closed exact planning-lease/lifecycle query, so no database
session spans Telegram I/O.

```text
planning/safety gates -> provider admission -> exact lease fence
                                         -> sendChatAction(typing)
                                         -> provider I/O
                         owned 4s refresh -> exact lease fence -> typing
provider terminal/cancel -> cancel + await refresh -> durable plan completion
```

The controller is execution-scoped, capped at five calls/twenty seconds, and
never persisted or recovered. Its first typed adapter failure disables further
presence for that execution while provider generation and governed outbound
delivery continue unchanged. See the
[Telegram presence runbook](runbooks/telegram-presence.md).

SPEC-036 adds explicit response regeneration without introducing a second
planning or Telegram stack. Reply authority resolves locally from a delivered
Telegram message through its outbound action and response plan. A new planning
job retains immutable root/parent/ordinal lineage while the existing context,
safety, knowledge, memory, governance, and presence paths run against current
state.

```text
/regenerate reply -> local authority + root lock -> fresh governed planning
                  -> current context, original user turn (command excluded)
                  -> safe text: durable EDIT_TEXT -> confirmed: canonical
                                                \-> exact rejection: SEND_TEXT
                                                \-> ambiguous: no fallback
                  -> split/unsafe: normal ordered SEND_TEXT sequence
```

Telegram presentation never replaces PostgreSQL history. No session spans
provider, `editMessageText`, or fallback `sendMessage` I/O, and edit/fallback
state constraints prevent two canonical presentations. See the
[Telegram regeneration runbook](runbooks/telegram-regeneration.md).

SPEC-037 adds a transient reaction branch without adding a response channel or
durable work type. The pure policy recognizes only exact bounded
acknowledgements and returns a typed two-value allowlist. After response
planning becomes terminal, a short PostgreSQL read revalidates the original
incoming user message and same tenant/Assistant/connection/conversation chain.
The session closes before one best-effort `setMessageReaction` call.

```text
addressed + pre-safety allow -> normal governed planning -> terminal job
                                                   |-> durable response ready
                                                   \-> short authority read
                                                       -> close DB session
                                                       -> setMessageReaction once
```

Reaction failure does not mutate plans, outbound actions, presence, memory,
knowledge, summaries, or media. Terminal-job and inbox idempotency prevent
replay; crash omission is accepted and never recovered. Reaction-related
Telegram updates stay outside the supported ingress set. See the
[Telegram reactions runbook](runbooks/telegram-reactions.md).

SPEC-038 adds explicit voice presentation without creating another semantic
response or delivery stack. A reply-only command resolves the local outgoing
message through its delivered text/edit action to one retained response plan.
The plan's whole text—not the Telegram quote or individual split chunk—is the
only synthesis source. The command's unique voice job carries its scope,
source hash/length, privacy revision, lease, and one SPEC-026 provider attempt.

```text
/voice reply -> PostgreSQL message/action/plan authority -> governed TTS reserve
             -> durable provider io_started -> close DB -> OpenAI speech I/O
             -> revalidate lease/source/privacy -> atomic artifact + voice action
             -> close DB -> Telegram sendVoice -> durable delivery result
```

OpenAI is the only v1 speech adapter. It produces native bounded OGG/Opus; no
conversion, URL, or filesystem path exists. The generated bytes live in a
narrow PostgreSQL `BYTEA` artifact with exact tenant/Assistant/connection/
conversation/source linkage. It is delivery data—not message text, memory,
knowledge, summary, or semantic-index content—and is purged at the earlier of
terminal delivery plus 24 hours or creation plus seven days. Privacy erasure
wins immediately.

Provider timeouts/resets after possible I/O become terminal uncertain and do
not repeat synthesis. Telegram definitive no-send retries reuse the artifact;
ambiguous delivery remains `delivery_unknown` and is not resent. Neither raw
external call holds a database session. See the
[Telegram voice runbook](runbooks/telegram-voice-tts.md).

## Explicit Conversation Feedback Boundary

SPEC-039 records user-authored quality metadata without entering the generation
or delivery pipeline. The command worker resolves only a retained local reply
edge and commits current state, one immutable state-changing event, command
completion, and a deterministic acknowledgement atomically:

```text
/feedback reply -> active scoped message/action/plan authority
                -> full-key PostgreSQL advisory lock + current-row lock
                -> current feedback + immutable event (or NO_CHANGE/limit)
                -> local acknowledgement plan/action
```

The response plan remains the semantic target across split chunks. Delivered
edits use their exact regeneration plan; voice messages dereference the voice
artifact's source response plan. Participant identity is part of the current
state key, so group members never overwrite one another.

Feedback has no provider, vector, media, reaction, presence, regeneration,
memory, knowledge, summary, configuration, safety, routing, or budget edge.
Context and summary readers exclude both feedback commands and their local
acknowledgements. Subject governance alone exposes structured own-user state;
privacy/retention deletion is permitted only after participant tombstoning or
response-plan redaction. See the
[conversation feedback runbook](runbooks/conversation-feedback.md).

## Test Authority and Clean-Runner Boundary

SPEC-040 preserves the production ownership graph and makes its test boundary
explicit. An integration test that creates an Assistant owns creation or
selection of the corresponding Tenant inside its scoped setup. Migration
`0021_multi_assistant_tenancy` may create a legacy tenant while canonicalizing
legacy rows, but that conditional migration result is not an immortal test
fixture and production runtime does not recreate it for tests.

The production `fk_assistants_tenant` remains validated, non-nullable, and
restrictive. Reliability proof deliberately runs knowledge-RAG tenant setup
before the historical memory tests, exercises alternate orders, and attacks
the FK with invalid and valid inserts. Clean-runner proof includes candidate
files and executable modes without `.git`, `.env`, credentials, prior volumes,
or developer PATH assumptions. See the
[production stabilization runbook](runbooks/production-stabilization.md).

## Release-readiness boundary

SPEC-041 changes no product topology or persistence model. PostgreSQL remains
authoritative; Redis remains transient coordination/queue state; Qdrant remains
optional rebuildable derived state. The supported promotion order is
dependencies, backup and read-only preflight, a single migration owner, API
readiness, workers, and only then external ingress.

`/live` proves only the process is running. `/ready` proves PostgreSQL is
reachable at exact head `0026_conversation_feedback` and checks Redis whenever
delivery, rate limiting, or provider concurrency requires it. Optional disabled
Qdrant/provider capabilities do not become global readiness dependencies.

Configuration is parsed once before runtime construction. Enabled Telegram,
provider, TTS, semantic-memory, knowledge, control-plane, governance, and worker
relationships fail closed when incomplete. Staging/production reject local
database/Redis targets, local database credentials, debug logging, database
echo, and insecure remote Telegram/provider URLs. Release preflight adds
placeholder detection and the full Telegram-first profile without contacting
external systems.

Application rollback and database downgrade are separate decisions. Current
guarded migrations may forbid downgrade when governed state exists; the safe
response is traffic/capability disable plus a forward fix, not forced DDL.
Restore reestablishes PostgreSQL authority, reapplies post-backup erasures,
recreates Redis, and rebuilds/revalidates Qdrant before workers or ingress.
See the [release-readiness runbook](runbooks/telegram-first-release-readiness.md)
and [release checklist](runbooks/telegram-first-release-checklist.md).
