# SPEC-043 Design Handoff

Date: 2026-10-01

Status: VERIFIED SELF-HOST DISTRIBUTION DESIGN — INDEPENDENT AUDIT PENDING

## Authority and policy transition

The [approved Product Spec](../../product/specs/SPEC-043-open-source-self-hosted-distribution-first-run.md)
and [canonical policy](../../product/self-hosted-deployment-profile.md) implement
the Product Owner's local-first/self-hosted/optional-VPS direction. Historical
SPEC-041/042 artifacts remain unchanged. No central organization, approval
ticket, corporate on-call, mandatory registry, monitoring vendor or paid
provider is introduced. Engineering safeguards remain required.

Exact baseline `private-source-checkpoint-omitted`, prior Quality
`36755636502` success, single head `0026_conversation_feedback`; migration,
new entities/features/routes/commands/provider capabilities/evals: NONE.

## Audit findings that determine the design

- Root Compose is a native-development dependency/API representation, not a
  complete bot. Its current API/DB/Redis host bindings need loopback hardening.
  Qdrant should be explicit/optional, with existing explicit-service validation
  preserved. Do not repurpose staging's hardcoded webhook/production controls
  as a polling installer.
- Current demo supervision is demo-specific, requires an existing tenant,
  and does not establish persisted provider enforcement. Do not rename it and
  call first run solved.
- Authenticated `/control/v1/me`, deployment-authority bootstrap and tenant
  provisioning already exist. Tenant creation grants its creator owner
  membership. Transactional `SqlAlchemyOperatorBootstrap.reconcile` already
  binds a verified Telegram bot to an active selected tenant and default
  personality, refusing wrong identity/tenant/inactive authority.
- Provider enforcement requires control-plane functionality and recovery.
  Existing authenticated provider endpoints publish capability, health policy,
  current state, price, route and deployment hard budgets. Missing policies
  must fail before I/O, not trigger a legacy fallback.
- API health is dependency/schema evidence, not complete worker/provider/bot
  readiness. Optional feature pairing needs operational checks beyond `/ready`.
- No license, remote tag, CHANGELOG or verified private reporting channel was
  found. Do not invent any; reuse existing contribution guidance.

## First-run state sequence

```text
checkout/pin -> choose config/provider and explicit operator policy
 -> offline configuration checks
 -> local build + private PostgreSQL/Redis
 -> single bounded migration to 0026
 -> internal authenticated setup API
 -> explicit operator setup (identity/authority/tenant/provider policies)
 -> persist canonical connection configuration; close setup phase
 -> normal API and required workers; one ingress owner
 -> live/ready + worker evidence
 -> optional deliberate user message through governed durable workers
```

Documentation must separate these states. A template without credentials may
be ready to configure, never ready to talk. Dependency/migration/setup phases
perform no paid generation or outbound Telegram delivery. Telegram identity
verification is an explicit live operator action and not part of canonical
proof; setup never changes webhook/DNS, buys credits or creates accounts.

A bounded script outside `backend/app` may orchestrate the existing control
API and bootstrap service. It must authenticate, verify selected tenant owner
authority before reconciliation, use existing optimistic revisions/idempotency,
reject conflicts/inactive resources, and emit no credential or response body.
No direct policy/tenant SQL seeding in the installation path. A setup failure
leaves durable evidence and a reported recovery step, not a blind retry or
automatic resource revival. Existing demo guards remain untouched.

The operator supplies local secret material plus selected Telegram/model
credentials and explicit finite budget/price/health policy inputs. Do not
auto-select a remote model, price or spend allowance. Generated local random
database/JWT secrets, if provided as convenience, must be written privately
without displaying them, and must not overwrite existing configuration.

### Implemented operator facade

`scripts/self_host/setup_operator.py` is packaged at
`/app/self-host/setup_operator.py`. Its operations are:

- `init`: explicit offline generation of only missing PostgreSQL/JWT local
  secrets; atomic owner-only file replacement; existing values retained.
- `check --phase setup`: offline existing-Settings/policy validation before
  tenant/connection IDs exist. `check` defaults to runtime validation and must
  reject missing runtime IDs. Neither operation connects to PostgreSQL,
  Telegram or a model provider.
- `setup --confirm-operator-setup --confirm-live-telegram`: deliberately verifies
  Telegram identity, uses the authenticated existing control API for authority,
  tenant and policies, calls the existing trusted local bot reconciler, then
  records canonical IDs and clears bootstrap subjects in the private file.
  No Telegram sends, provider generation, migrations or webhook mutation.

The `tools` Compose profile supplies a one-shot `setup-tool` with no service
dependencies, ports or restart loop. Its default command is offline `check`;
invoke through `run --rm --no-deps` and the host operator UID/GID when writing.
It reads the checkout-mounted private file rather than inheriting shell
credentials. An explicit image check can use Docker `--network none` and needs
no host Python/UV. The default static doctor must not create such a container.

`docs/examples/self-host-provider-policy.json` is deliberately incomplete:
prices, health thresholds and budget limits are null, and structured-output
support is unconfirmed. The operator must supply actual integer prices/limits,
an explicit current/past UTC effective time, a finite hard chat budget and
model/data-boundary affirmation. The template must not become a usable spend
default. Initial READY state is the operator's affirmation, not a provider
probe; retry never refreshes its health timestamp. Changed/disabled state or
different routing/budgets must fail rather than be silently overwritten.

Hermetic facade tests, real authenticated PostgreSQL setup/retry/interruption
and the fresh complete Compose polling/webhook synthetic delivery proof are
recorded in the execution record (private execution record omitted from this snapshot).
Full local Quality, Git-materialized packaging and closed complete runtime
proof pass. They do not prove live provider availability or real user Telegram
acceptance; see the candidate handoff (private execution record omitted from this snapshot) for audit boundaries.

## Compose representation and ports

Introduce a separate self-host representation only where needed to supply the
complete current worker graph. Local and VPS polling share it; webhook is a
chosen ingress variant. Build the locked non-root Python 3.12 runtime locally.
No mandatory registry, host Python virtualenv, GUI, or unrelated host service.

Implemented `scripts/self-host-compose.sh` invokes this exact representation
with a private raw configuration file. Its shared source-only Bash parser
does not evaluate/source values. Only actual Compose interpolation fields are
exported literally; other January shell settings are removed in the child.
Compose reads `/dev/null` for interpolation and the selected file as raw
application env. This avoids a hidden dollar-expansion mismatch between
PostgreSQL and the application. The wrapper refuses accidental secret-bearing
configuration dumps; quiet validation and safe metadata selectors remain.

| Role | Existing entrypoint | Required dependency |
| --- | --- | --- |
| migration | Alembic upgrade to `0026_conversation_feedback` | healthy PostgreSQL, sole owner |
| API/setup control | `app.main:app` | completed schema; Redis for enabled gates |
| poller | `app.runtime.telegram_poller` | active canonical connection; polling only |
| dispatcher | `app.runtime.ingress_outbox_dispatcher` | PostgreSQL/Redis |
| conversation | `app.runtime.conversation_worker` | PostgreSQL/Redis |
| planning | `app.runtime.response_planning_worker` | enforced provider policy, safety/rate/concurrency |
| commands | `app.runtime.telegram_command_worker` | PostgreSQL; Redis/external dependencies when required |
| outbound | `app.runtime.outbound_delivery_worker` | active canonical scope and Redis/Telegram |
| provider recovery | `app.runtime.provider_governance_worker` | PostgreSQL |
| privacy/governance | `app.runtime.governance_worker` | PostgreSQL |
| retention | `app.runtime.retention_worker` | PostgreSQL |
| optional scheduler | `app.runtime.proactive_scheduler_worker` | matching feature/worker flags |
| optional summaries | `app.runtime.conversation_summary_worker` | matching feature/worker and governed provider |
| optional semantic memory | `app.runtime.semantic_memory_index_worker` | matching feature/worker, embedding and Qdrant |
| optional knowledge | `app.runtime.knowledge_index_worker` | independent knowledge flags/collection, embedding and Qdrant |

Startup dependencies use health and completed migration, not fixed sleeps.
Long-running processes need graceful SIGTERM and appropriate restart policy;
one-shot migration/setup must fail visibly rather than restart forever. Keep
poller separate from the API and never start it in webhook mode. No fictional
recovery daemon: recovery is the existing claims/leases/provider worker.

Private self-host data services need no host ports. API may bind loopback
container port 8000 for local operator checks; intentional public HTTPS terminates
at the operator's edge. Root native ports retain `JANUARY_HOST_PORT`,
`JANUARY_DB_HOST_PORT`, `JANUARY_REDIS_HOST_PORT`, `JANUARY_QDRANT_HOST_PORT`
overrides while binding `127.0.0.1`. No data-service public bind, Docker socket
mount, privileged/root application or host-specific security workaround.

## Polling and webhook

Polling is preferred: outbound Telegram/provider reachability, no public IP,
DNS/TLS/proxy/webhook secret. Preserve atomic durable batch/cursor acceptance,
deduplication, exclusive ownership and bounded retry/recovery. Refuse an
installed webhook; never remove it implicitly.

Webhook is optional advanced use: configured public HTTPS URL, valid TLS,
secret, bounded authenticated ingress and exactly one owner. Use the existing
`app.runtime.telegram_connection_operations` explicit confirmation guards for
identity/mode/lifecycle. Mode transition drains/stops the old owner, explicitly
mutates/verifies webhook state as chosen, then opens the new mode. No pending
update drop or insecure TLS shortcut. Canonical webhook proof stays local/fake.

## Provider and optional feature contract

Actual adapters support OpenAI/Gemini/Groq/OpenRouter/Ollama chat. Each needs its
selected model and base URL; hosted families need the corresponding key;
Ollama is keyless/local. Adapter structured-output support is not a promise
that every upstream model supports the required response contract.

Ollama must be reachable from the container; its `127.0.0.1` is not the host.
Document an explicitly chosen Docker/host network arrangement, not an automatic
model download or mandatory local-model service. Only existing Ollama embedding,
Groq transcription and OpenAI TTS capabilities are authorized. No parity claims.

The quickstart now supplies an explicit optional CPU-container recipe: reviewed
image digest, deliberate model selection/download, a separate owned cache and
named attachment to the existing Compose project network, no published model
port. These are operator steps, not canonical live inference or a mandatory
Compose service. Keep project identity stable; container loopback is not reused
as a host address. Official Ollama/Docker references are linked in the guide.

The authenticated operator publishes real capability/data/health/price/route
and finite hard-budget policies through existing controls. Health staleness
and possible-I/O accounting remain effective. Local use does not waive budgets.
A public control-plane port/enterprise IdP is unnecessary; JWT authentication,
deployment authority and tenant membership remain mandatory.

Qdrant is optional derived state. Semantic and knowledge workers require their
matching feature flags, configured Ollama embedding model/dimension, independent
collections and governed routes. Disabled summaries/semantic/knowledge/TTS/media/
scheduling remain off and do not block core. Enabled feature/profile mismatches
are actionable blockers even if API readiness succeeds.

TTS is optional explicit `/voice`, enforced OpenAI `gpt-4o-mini-tts`/`alloy`
OGG/Opus, 4,000 code points and 5 MiB. External cost and governed reservation
apply; no OpenAI key for ordinary text under another provider. PostgreSQL voice
bytes are short-lived: 24-hour terminal grace, seven-day hard retention and
immediate erasure, through real retention/governance workers.

## State, backup, restore and upgrade

PostgreSQL owns all durable authority/content/work/policies/accounting/artifacts.
Redis is coordination/transient handoff; Qdrant is derived/rebuildable. Raw
media processing is ephemeral, not a permanent filesystem archive.

Backup tiers: disposable local tests optional; persistent personal local use
recommended; meaningful VPS data strongly recommended. Use supported PostgreSQL
logical backup/restore, protected destination/access/encryption/retention chosen
by the operator, no enterprise approval. Existing synthetic restore validator
proves a drill, not a real operator backup.

Restore: close ingress, quiesce writes/external-I/O workers, select/verify the
backup and isolated destination, restore, check head and constraints/authority,
reconcile post-backup erasures, recreate Redis, rebuild/revalidate derived
Qdrant state, then verify readiness/workers before traffic. Do not overwrite a
live database or resurrect erased voice/content. No downgrade promise.

Upgrade: record current immutable SHA, back up, fetch/review exact desired
release/SHA/config/migration changes, offline preflight, stop ingress/writers,
single bounded schema upgrade when needed, restart, exact head/readiness and
worker/smoke checks. A previous application may be used only after schema
compatibility is established; otherwise forward-fix. No automatic restore.

No tags/CHANGELOG observed: pin exact SHA now. A future lightweight maintainer
release convention records version/tag/SHA/head/Quality/config changes and
limitations. Do not create/push tags in this goal.

## Doctor, troubleshooting and security

Add a bounded offline doctor for the new distribution gaps rather than change
the production validator. It must work for Docker-only new users and not
source executable env files. Parse/check configuration without printing values,
render Compose quietly without daemon/resource mutation, distinguish template,
setup and runtime checks, and report missing required inputs nonzero. Validate
the real typed graph in the application image where host Python is absent.
Any optional build/runtime-backed mode must be explicit about its local effects.

Implemented `scripts/self-host-doctor.sh` distinguishes template/setup/runtime
configuration and polling/webhook profiles, with explicit matching optional
profiles. Default `--offline` checks are read-only/static, including private raw
file shape, selected credentials/IDs, optional pairing and embedding reachability
configuration, unfilled policy markers and the static migration head. It renders
Compose quietly without a daemon/resource change or host Python/UV/Git.
`--typed` explicitly requires an existing local image and runs the real Settings/
policy check as the operator UID in one read-only, capability-dropped,
network-disabled container, with no pull/build/migration/live calls. Both modes
state that persisted authority/policies, dependency/worker readiness and live
delivery are unverified. Static policy checks are not a complete JSON/DTO parser.

Hermetic tests cover missing config, placeholders, polling without HTTPS,
incomplete webhook/Qdrant/provider, disabled optional absence, invalid feature
pairing, exit semantics, command/no-network boundaries and canary non-leakage.
Do not mislabel a static pass as live bot/provider verification.

Troubleshooting uses actual Docker/Compose, port, dependency/head, auth/credential,
mode-conflict, provider denial/timeout, optional Qdrant/TTS, permission and worker
failure behavior. Safe evidence: SHA, service state, redacted error class, head,
doctor status and health. Never full env, private conversations, tokens, model
prompts or raw provider responses. No giant support bundle or invented reporting
email. Private report availability must be verified before publishing a channel.

Local env is ignored restricted operator material; rotate compromised credentials.
Exclude all non-example env files and local policy/artifacts from image context
and Git. Rootless/normal Docker group/host procedures may be documented with
their privilege implications; no socket permission relaxation or root workaround.

## VPS and resource guidance

One Linux VPS, Docker Engine/Compose, local build, private persistent services.
Polling needs chosen operator access and outbound connectivity only; webhook
additionally needs chosen domain/HTTPS edge/secret. Expose only necessary
operator access and intentional HTTPS. Never publicly publish PostgreSQL/Redis/
Qdrant or make control auth anonymous. Resource use depends on enabled workers,
local model and Qdrant; no unmeasured CPU/RAM minimum or scaling promise.

## Proof and handoff

Add self-host validation only for new non-duplicative composition/config/docs/
doctor proof. Preserve every existing selector and gate. Build a fresh isolated
stack with new volumes and fake external boundaries; prove base-to-head, normal
API/core worker lifecycle, `/live`/`/ready`, disabled optionals, synthetic polling
cursor→inbox→conversation→governed planning→outbound and webhook secret/dedup/
delivery. All external Telegram/provider/TTS live calls: zero.

Implemented `validate-self-hosted.sh` uses ordinary PATH UV (existing resolver
fallback retained), locked/offline dependency resolution, real Compose CLI
rendering of 17 selected core/setup/tools/optional topologies, source/example/
worker contracts, bounded local documentation path/heading checks and focused
hermetic tests. It performs no daemon/resources, migration or live API/model
operation and does not stand in for runtime or Git-tree proof. New unit tests
are selected by unchanged general Quality. CI adds this validator and explicitly
builds the local stock image required by the fresh Docker test in the existing
integration selection; no existing check or selector is removed. The Docker
test's internal network contains all fake Telegram/provider I/O; its separate
host-port probe starts only API/database/Redis with all I/O workers quiesced.
Final acceptance also runs this supplemental validator.

Run all 24 direct Quality validators, supplemental gates, inline CI, reliability,
deployment/readiness/backup/governance/safety/tenancy/provider/memory/RAG/Telegram
regressions and static/Harness/shell/diff. Exact eval 130/125/5/0/0; zero failures,
zero new behavior scenarios. Do not weaken CI or mask failures.

Prove direct script worktree/index/tree `100755` through an alternate candidate
index/tree, materialize Git-intended modes, and exercise new scripts. Prove an
Actions-style shallow checkout and exact VCS-free candidate with ordinary PATH
UV, no developer env/venv/credentials/history. Validate changed doc links and
secret/network/integrity occurrences. Inventory Docker before/after; clean only
identified new synthetic projects and preserve pre-existing stacks.

Implementation proof and the full 77-phase/56-gate internal audit are recorded
in the execution record/candidate handoff after validation. Internal unresolved
technical Critical/High findings: zero; independent review remains next.
License remains OWNER DECISION REQUIRED — OPEN-SOURCE LICENSE; no
public license grant is implied. No commit/push/SPEC-044 or external deployment.
Next after technical proof: independent OpenCode self-host distribution audit.
