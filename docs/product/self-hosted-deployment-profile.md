# Self-Hosted Deployment Policy

Effective: SPEC-043, 2026-10-01.

January's future direction is OPEN SOURCE / LOCAL-FIRST / SELF-HOSTED:
local development, local Docker Compose, and an optional single Linux VPS.
The person running the software is its operator. Managed commercial SaaS,
central deployment authority, corporate on-call, private registry and a paid
provider are not prerequisites. The runtime remains headless.

License: [MIT](../../LICENSE), explicitly selected by the owner during SPEC-044.
Downstream commercial use is allowed under its terms; operating a managed SaaS
is outside this project's scope, not a license restriction. Licensing does not
itself prove technical acceptance or publish a release.

## Chronological continuity

SPEC-041 completed release/operational-readiness work. SPEC-042 completed the
repository production-promotion package; it did not deploy production or prove
fresh live acceptance. SPEC-043 changes future default deployment assumptions.
Historical specs, plans, handoffs and audits retain their original scope and
evidence. Their centralized operational model is an advanced downstream option,
not the ordinary self-host installation path.

SPEC-044's verified self-host baseline is `private-source-checkpoint-omitted`.
Existing schema/feature contracts
remain unchanged; single head `0026_conversation_feedback`, new migration NONE.

## Profiles

| Profile | Runtime and required configuration | Network | State/backup | Security |
| --- | --- | --- | --- | --- |
| `LOCAL_DEVELOPMENT` | Python 3.12 + UV; PostgreSQL; Redis whenever delivery/rate/concurrency uses it; explicit worker flags/credentials only for chosen live capabilities | loopback dependency ports; ordinary outbound for deliberate live use | disposable synthetic data: backup optional | no credential required by Quality; never copy real data into fixtures |
| `LOCAL_SELF_HOST` | locally built non-root Compose runtime; PostgreSQL/Redis, migration, API, complete core workers; configured bot, selected model, local operator auth and enforced persisted policies | loopback API; internal data services; outbound Telegram/provider | PostgreSQL persistent; personal meaningful-data backup recommended | ignored restricted secrets; mandatory engineering controls below |
| `VPS_SELF_HOST_POLLING` | same core; exactly one polling owner | outbound connectivity plus chosen operator access; no inbound Telegram HTTP, public hostname, TLS or proxy needed | persistent authoritative volume; meaningful-data backup strongly recommended | no public data stores/control API; firewall chosen operator access |
| `VPS_SELF_HOST_WEBHOOK` | same core without poller; configured public HTTPS URL and webhook secret; chosen reverse proxy/ingress | operator access and intentional public HTTPS with valid TLS | same as polling | authenticate webhook; keep control/data private; one ingress owner |

These names are deployment profiles, not new environment enum values.
`local`/`test`/`staging`/`production` retain their existing typed validation.
Single-host operation does not establish clustering, sharding, multi-region
availability or a measured throughput/resource guarantee.

## Future relevance of centralized prerequisites

| Classification | Requirements |
| --- | --- |
| `NOT_APPLICABLE` by default | central production operator, corporate promotion approval, formal production ticket, corporate on-call, mandatory central monitoring, registry publication, enterprise backup approval, formal restore authority, formal privacy officer, billing approval workflow |
| `CONDITIONAL` | public TLS/DNS/webhook; selected hosted provider credentials and account terms/costs; TTS credentials; Qdrant/embedding; persistent VPS backup procedures; monitoring integrations |
| `REQUIRED ENGINEERING CONTRACT` | migrations, secret hygiene, privacy, safety, tenant/Assistant/connection authority, reliability, health/readiness, backup capability and upgrade safety |

No corporate billing approval is required, but the operator must knowingly
choose finite budgets, model/data eligibility and applicable prices before
paid I/O. No formal restore officer is required, but the operator must stop
traffic, verify the backup and reconcile erasures before restoring. Removing
organizational ceremony does not remove engineering safeguards.

## Capability optionality

| Capability | Required for core chat? | Actual config | External service | Self-host condition |
| --- | --- | --- | --- | --- |
| PostgreSQL | yes | `JANUARY_DATABASE_*` | project PostgreSQL | authoritative, persistent |
| Redis | yes for supported guarded chat | `JANUARY_REDIS_URL`, rate/concurrency controls | project Redis | private coordination, not truth |
| Telegram | yes | enabled/token/delivery mode/platform connection | Telegram Bot API | choose exactly one ingress mode |
| Model provider | yes for generated chat | `JANUARY_LLM_ENABLED`, primary provider and selected model/key | chosen provider or local Ollama | persisted enforce-mode route/capability/budget |
| Ollama | no; keyless alternative | `JANUARY_LLM_OLLAMA_MODEL`, base URL | accessible local model server | container loopback is not the host; no parity promise |
| Qdrant | no | `JANUARY_QDRANT_URL` | optional derived index | only for enabled semantic/knowledge indexing |
| Semantic memory | no | semantic feature/worker, embedding provider/model/dimension | Ollama embedding and Qdrant | complete worker/profile pair; opaque derived points |
| Knowledge/RAG | no | knowledge feature/index-worker and embedding settings | Ollama embedding and Qdrant | independent knowledge index and scope |
| Summaries | no | summary feature/worker and LLM settings | selected governed provider | complete worker/profile pair |
| Scheduling | no | proactive/scheduler flags and outbound | no separate provider required | existing materialization worker |
| TTS | no | voice-TTS settings, OpenAI credential and governed TTS route | OpenAI | explicit `/voice`; existing bounds/retention |
| Webhook | no | delivery mode, public base URL, secret | chosen public HTTPS ingress | no poller; explicit registration |
| Control plane | authenticated functionality yes for enforced profile; public exposure no | enabled/JWT issuer/audience/secret/bootstrap subjects | no mandatory corporate IdP | loopback/internal, separate deployment and tenant grants |
| Monitoring | external backend no | metrics/export/bind settings | optional operator backend | local safe health/worker/log inspection still required |

Safety, rate limits, concurrency, provider enforcement/recovery, data governance,
retention, commands and outbound are not optional shortcuts in the supported
guarded self-host chat path. Disabled optional absence must not block core
readiness. Enabled optional features require complete actual dependencies even
when global API readiness is green.

## Authority, ingress and readiness

The self-host operator establishes authenticated deployment authority through
the existing empty-set bootstrap contract, then creates a tenant and receives
its owner membership. Provider deployment policies use deployment authority;
tenant/Assistant/connection work uses tenant authority. No magic default tenant
or anonymous operator API is permitted. Retired/disabled resources must not be
silently revived by an installer.

Polling needs token, canonical connection and outbound connectivity; it checks
for an installed webhook and refuses conflict. Cursor/batch acceptance and
idempotency remain durable. Switching modes means stopping/draining the old
owner, explicitly changing/verifying webhook state when chosen, then starting
the new owner. Never drop pending updates or register/delete a webhook at startup.

`/live` is process life. `/ready` requires PostgreSQL connectivity at the exact
head and Redis when delivery/rate/concurrency uses it. Optional disabled
Qdrant/provider/TTS services do not block it. An API 200 is not proof of bot
identity, configured provider policies, active workers or a delivered response.

## Persistence, backup and privacy

PostgreSQL is the only authoritative data store, including scope/lifecycle,
inbox/outbox/cursors, policy/accounting, privacy and short-lived voice artifacts.
Redis streams/limits/leases are transient coordination. Qdrant contains derived
vectors/opaque IDs and is rebuilt/revalidated from PostgreSQL. Telegram raw
media processing is bounded/ephemeral; no permanent media-volume guarantee.

Backup capability is mandatory engineering. Taking backups is optional for
casual disposable local testing, recommended for persistent personal local
use, strongly recommended for meaningful VPS data. A Redis/Qdrant snapshot is
not an authoritative backup. The operator controls destination, access,
encryption and retention without an enterprise approval process.

Restore must quiesce ingress and writing/external-I/O workers, restore into a
verified selected database, verify revision and authority, reconcile erasures
since the backup, recreate Redis and rebuild derived state before traffic.
Never restore erased voice/content to satisfy stale pending work. Application
rollback and guarded database downgrade are different; use a forward fix when
compatibility or downgrade safety is unknown.

## Secrets, packaging and upgrades

Local env/config is protected operator material, not an enterprise secret
manager. Ignore it in Git, restrict access, exclude it from Docker build context
and rotate compromised credentials. Do not dump full env/Compose settings,
tokens, private messages or provider bodies into logs, issues or support reports.
VPS operators may choose stronger secret injection and monitoring.

Build from locked dependencies on Python 3.12, run the application non-root,
pin an exact SHA or a future release tag, review release/config/schema changes
and back up before upgrading. No tag/release was observed in the audit, and
this task creates none. Resource needs depend on workers, model and optional
Qdrant; no unmeasured CPU/RAM minimum is promised.

## Quality boundary

Canonical tests use fake Telegram/provider/TTS boundaries, no real credentials,
paid calls or public deployment. Fresh isolated Compose, synthetic polling and
webhook, Git-mode materialization, shallow/PATH-UV/VCS-free and full Quality
proof are required before candidate approval. Existing stricter downstream
production validators remain intact and green.

Implementation status/evidence belongs to the active/completed SPEC-043 plan
and final handoff, not this stable policy. See the
[Product Spec](specs/SPEC-043-open-source-self-hosted-distribution-first-run.md).
