# Telegram-first Release Readiness

This is the target-neutral operational contract for SPEC-041. It proves
repository readiness; it does not claim that production is deployed, that a
fresh live Telegram/provider check occurred, or that external alerts are
active.

## Evidence vocabulary

- **Verified locally:** executable proof against repository-owned synthetic or
  isolated services.
- **Verified by automated CI:** GitHub Quality result tied to an exact SHA.
- **Historical guarded acceptance:** SPEC-022 proved the guarded operator
  mechanism with fake adapters and explicitly recorded that no real live run
  occurred.
- **Requires external prerequisite:** an operator must supply infrastructure,
  secrets, approvals, or live evidence.
- **Operator action required:** a deliberate production mutation such as
  backup, migration, webhook registration, traffic enablement, rollback, or
  restore.

## Baseline and release boundary

- Previous green baseline:
  `private-source-checkpoint-omitted`.
- GitHub Quality run: `36405527959`, push on `main`, success.
- Schema: one head, `0026_conversation_feedback`.
- SPEC-041 migration: none.
- SPEC-041 product behavior: none.
- Zalo stays frozen.
- Repository approval may be
  **APPROVED RELEASE READINESS CANDIDATE — INDEPENDENT AUDIT PENDING**.
  That status is not production deployment or live external acceptance.

## Configuration authority and classification

`backend/app/core/config.py` is runtime authority. `.env.example` enumerates
all 244 typed `JANUARY_*` settings and must load with local-safe values. The
offline readiness validator compares the two inventories, rejects missing,
extra, or duplicate entries, and validates the example through `Settings`.

Classification terms:

- **required:** explicitly supplied for the full Telegram-first production
  profile;
- **conditional:** required only when its capability/worker is enabled;
- **optional:** bounded tuning or an intentionally disabled capability;
- **development-only/test-only/staging-only:** prohibited or irrelevant to
  production runtime;
- **production-sensitive:** operator-reviewed because it changes authority,
  external I/O, capacity, privacy, safety, retention, cost, or exposure;
- **secret:** value must come from a secret manager and must never be logged;
- **non-secret:** safe to name in configuration evidence, though values may
  still be operationally sensitive.

### Complete typed inventory

Every setting named below inherits the classification in its row. The secret
override table that follows takes precedence over a row's `non-secret` label.

| Group | Variables | Requirement | Sensitivity |
| --- | --- | --- | --- |
| Process identity | `JANUARY_APP_NAME`, `JANUARY_ENVIRONMENT`, `JANUARY_LOG_LEVEL` | `ENVIRONMENT` required; others bounded | production-sensitive, non-secret |
| Metrics | `JANUARY_METRICS_ENABLED`, `JANUARY_METRICS_EXPORT_ENABLED`, `JANUARY_METRICS_BIND_HOST`, `JANUARY_METRICS_PORT`, `JANUARY_PLANNING_METRICS_PORT`, `JANUARY_SUMMARY_METRICS_PORT`, `JANUARY_SEMANTIC_MEMORY_METRICS_PORT`, `JANUARY_PROVIDER_GOVERNANCE_METRICS_PORT`, `JANUARY_METRICS_PROVIDER_PRICING` | metrics required for release profile; export/pricing conditional | production-sensitive, non-secret |
| Provider governance | `JANUARY_PROVIDER_GOVERNANCE_MODE`, `JANUARY_PROVIDER_GOVERNANCE_WORKER_ENABLED`, `JANUARY_PROVIDER_GOVERNANCE_OWNER_NAME`, `JANUARY_PROVIDER_GOVERNANCE_BATCH_SIZE`, `JANUARY_PROVIDER_GOVERNANCE_POLL_INTERVAL_SECONDS`, `JANUARY_PROVIDER_RESERVATION_LEASE_SECONDS` | mode/worker required; remaining values bounded | production-sensitive, non-secret |
| PostgreSQL | `JANUARY_DATABASE_HOST`, `JANUARY_DATABASE_PORT`, `JANUARY_DATABASE_NAME`, `JANUARY_DATABASE_USER`, `JANUARY_DATABASE_PASSWORD`, `JANUARY_DATABASE_URL`, `JANUARY_DATABASE_POOL_SIZE`, `JANUARY_DATABASE_MAX_OVERFLOW`, `JANUARY_DATABASE_CONNECT_TIMEOUT_SECONDS`, `JANUARY_DATABASE_ECHO` | URL or components required; echo development/test-only | production-sensitive; password/URL secret |
| Telegram media | `JANUARY_TELEGRAM_MEDIA_ENABLED`, `JANUARY_TELEGRAM_MEDIA_PHOTO_MAX_BYTES`, `JANUARY_TELEGRAM_MEDIA_AUDIO_MAX_BYTES`, `JANUARY_TELEGRAM_MEDIA_PHOTO_MAX_SIDE`, `JANUARY_TELEGRAM_MEDIA_AUDIO_MAX_DURATION_SECONDS`, `JANUARY_TELEGRAM_MEDIA_TRANSCRIPT_MAX_CHARACTERS`, `JANUARY_TELEGRAM_MEDIA_DOWNLOAD_TIMEOUT_SECONDS`, `JANUARY_TELEGRAM_MEDIA_TRANSCRIPTION_TIMEOUT_SECONDS` | optional; bounds conditional when enabled | production-sensitive, non-secret |
| Telegram TTS | `JANUARY_TELEGRAM_VOICE_TTS_ENABLED`, `JANUARY_TELEGRAM_VOICE_TTS_MODEL`, `JANUARY_TELEGRAM_VOICE_TTS_VOICE`, `JANUARY_TELEGRAM_VOICE_TTS_SOURCE_MAX_CHARACTERS`, `JANUARY_TELEGRAM_VOICE_TTS_OUTPUT_MAX_BYTES`, `JANUARY_TELEGRAM_VOICE_TTS_TIMEOUT_SECONDS`, `JANUARY_TELEGRAM_VOICE_ARTIFACT_GRACE_HOURS`, `JANUARY_TELEGRAM_VOICE_ARTIFACT_HARD_RETENTION_DAYS` | optional; fixed/bounded contract when enabled | production-sensitive, non-secret |
| Telegram transport | `JANUARY_TELEGRAM_ENABLED`, `JANUARY_TELEGRAM_BOT_TOKEN`, `JANUARY_TELEGRAM_API_BASE_URL`, `JANUARY_TELEGRAM_TIMEOUT_SECONDS`, `JANUARY_TELEGRAM_CONNECT_TIMEOUT_SECONDS`, `JANUARY_TELEGRAM_CONNECTION_LIMIT`, `JANUARY_TELEGRAM_USER_AGENT`, `JANUARY_TELEGRAM_DELIVERY_MODE`, `JANUARY_TELEGRAM_TENANT_ID`, `JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID`, `JANUARY_TELEGRAM_ALLOWED_UPDATES`, `JANUARY_TELEGRAM_WEBHOOK_SECRET_TOKEN`, `JANUARY_TELEGRAM_WEBHOOK_PUBLIC_BASE_URL`, `JANUARY_TELEGRAM_WEBHOOK_BODY_LIMIT_BYTES`, `JANUARY_TELEGRAM_WEBHOOK_MAX_CONNECTIONS`, `JANUARY_TELEGRAM_POLL_TIMEOUT_SECONDS`, `JANUARY_TELEGRAM_POLL_BATCH_LIMIT`, `JANUARY_TELEGRAM_POLL_RETRY_BACKOFF_SECONDS`, `JANUARY_TELEGRAM_POLL_MAX_BACKOFF_SECONDS` | core enabled/token/mode/connection required; webhook fields conditional; tenant optional canonical bootstrap hint | production-sensitive; token/webhook secret secret |
| Redis stream | `JANUARY_REDIS_URL`, `JANUARY_REDIS_STREAM_NAME`, `JANUARY_REDIS_CONSUMER_GROUP`, `JANUARY_REDIS_BLOCK_TIMEOUT_MS`, `JANUARY_REDIS_BATCH_SIZE`, `JANUARY_REDIS_RECLAIM_IDLE_MS` | URL required; remaining values bounded | production-sensitive; URL secret-capable |
| Rate limits | `JANUARY_RATE_LIMIT_ENABLED`, `JANUARY_RATE_LIMIT_GENERATION_DEPLOYMENT_PER_MINUTE`, `JANUARY_RATE_LIMIT_GENERATION_CONNECTION_PER_MINUTE`, `JANUARY_RATE_LIMIT_GENERATION_CONVERSATION_PER_MINUTE`, `JANUARY_RATE_LIMIT_GENERATION_PARTICIPANT_PER_MINUTE`, `JANUARY_RATE_LIMIT_GENERATION_PROVIDER_PER_MINUTE`, `JANUARY_RATE_LIMIT_DELIVERY_DEPLOYMENT_PER_SECOND`, `JANUARY_RATE_LIMIT_DELIVERY_CONNECTION_PER_SECOND`, `JANUARY_RATE_LIMIT_DELIVERY_CONVERSATION_PER_SECOND`, `JANUARY_RATE_LIMIT_REDIS_FAILURE_RETRY_SECONDS`, `JANUARY_RATE_LIMIT_COOLDOWN_NOTICE_SECONDS` | enabled required; thresholds operator-reviewed | production-sensitive, non-secret |
| Provider concurrency | `JANUARY_PROVIDER_CONCURRENCY_ENABLED`, `JANUARY_PROVIDER_CONCURRENCY_LIMITS`, `JANUARY_PROVIDER_CONCURRENCY_LEASE_SECONDS` | enabled required; limits optional with safe limit-one fallback | production-sensitive, non-secret |
| Ingress/conversation | `JANUARY_INGRESS_OUTBOX_BATCH_SIZE`, `JANUARY_INGRESS_OUTBOX_POLL_INTERVAL_SECONDS`, `JANUARY_INGRESS_EVENT_SCHEMA_VERSION`, `JANUARY_CONVERSATION_CONSUMER_NAME`, `JANUARY_CONVERSATION_WORKER_POLL_INTERVAL_SECONDS` | bounded runtime tuning | production-sensitive, non-secret |
| Context | `JANUARY_CONTEXT_RECENT_MESSAGE_LIMIT`, `JANUARY_CONTEXT_REPLY_CHAIN_DEPTH`, `JANUARY_CONTEXT_TOKEN_BUDGET`, `JANUARY_CONTEXT_MESSAGE_CHARACTER_LIMIT`, `JANUARY_CONTEXT_MAX_HISTORY_AGE_DAYS` | bounded runtime tuning | production-sensitive, non-secret |
| Explicit/personal memory | `JANUARY_MEMORY_CONTEXT_LIMIT`, `JANUARY_MEMORY_CONTEXT_CHARACTER_BUDGET`, `JANUARY_PERSONAL_CONTEXT_LIMIT`, `JANUARY_PERSONAL_CONTEXT_CHARACTER_BUDGET`, `JANUARY_MEMORY_CONTROL_BATCH_SIZE` | bounded runtime tuning | production-sensitive, non-secret |
| Semantic memory and embeddings | `JANUARY_SEMANTIC_MEMORY_ENABLED`, `JANUARY_SEMANTIC_MEMORY_WORKER_ENABLED`, `JANUARY_EMBEDDING_PROVIDER`, `JANUARY_EMBEDDING_MODEL`, `JANUARY_EMBEDDING_DIMENSION`, `JANUARY_EMBEDDING_RATE_PER_MINUTE`, `JANUARY_QDRANT_URL`, `JANUARY_QDRANT_COLLECTION_PREFIX`, `JANUARY_SEMANTIC_MEMORY_TOP_K`, `JANUARY_SEMANTIC_MEMORY_CONTEXT_LIMIT`, `JANUARY_SEMANTIC_MEMORY_CHARACTER_BUDGET`, `JANUARY_SEMANTIC_MEMORY_QUERY_TIMEOUT_SECONDS`, `JANUARY_SEMANTIC_MEMORY_MIN_SCORE`, `JANUARY_SEMANTIC_MEMORY_JOB_LEASE_SECONDS`, `JANUARY_SEMANTIC_MEMORY_JOB_BATCH_SIZE`, `JANUARY_SEMANTIC_MEMORY_MAX_ATTEMPTS`, `JANUARY_SEMANTIC_MEMORY_RETRY_MIN_DELAY_SECONDS`, `JANUARY_SEMANTIC_MEMORY_RETRY_MAX_DELAY_SECONDS` | optional; provider/model and worker pairing conditional | production-sensitive, non-secret |
| Knowledge/RAG | `JANUARY_KNOWLEDGE_RAG_ENABLED`, `JANUARY_KNOWLEDGE_INDEX_WORKER_ENABLED`, `JANUARY_KNOWLEDGE_QDRANT_COLLECTION_PREFIX`, `JANUARY_KNOWLEDGE_TOP_K`, `JANUARY_KNOWLEDGE_CONTEXT_LIMIT`, `JANUARY_KNOWLEDGE_CONTEXT_CHARACTER_BUDGET`, `JANUARY_KNOWLEDGE_QUERY_TIMEOUT_SECONDS`, `JANUARY_KNOWLEDGE_MIN_SCORE`, `JANUARY_KNOWLEDGE_JOB_LEASE_SECONDS`, `JANUARY_KNOWLEDGE_JOB_BATCH_SIZE`, `JANUARY_KNOWLEDGE_MAX_ATTEMPTS`, `JANUARY_KNOWLEDGE_RETRY_MIN_DELAY_SECONDS`, `JANUARY_KNOWLEDGE_RETRY_MAX_DELAY_SECONDS` | optional; embedding/provider/worker pairing conditional | production-sensitive, non-secret |
| Summaries | `JANUARY_CONVERSATION_SUMMARIES_ENABLED`, `JANUARY_SUMMARY_WORKER_ENABLED`, `JANUARY_SUMMARY_MIN_SOURCE_MESSAGES`, `JANUARY_SUMMARY_MAX_SOURCE_MESSAGES`, `JANUARY_SUMMARY_MAX_OUTPUT_TOKENS`, `JANUARY_SUMMARY_LEASE_SECONDS`, `JANUARY_SUMMARY_BATCH_SIZE`, `JANUARY_SUMMARY_MAX_ATTEMPTS` | optional; worker pairing conditional | production-sensitive, non-secret |
| Retention | `JANUARY_RAW_CONTENT_RETENTION_DAYS`, `JANUARY_RETENTION_BATCH_SIZE`, `JANUARY_RETENTION_WORKER_ENABLED`, `JANUARY_RETENTION_WORKER_POLL_INTERVAL_SECONDS` | worker required; policy/cadence operator-reviewed | production-sensitive, non-secret |
| Model providers | `JANUARY_LLM_ENABLED`, `JANUARY_LLM_PRIMARY_PROVIDER`, `JANUARY_LLM_FALLBACK_PROVIDER`, `JANUARY_LLM_OPENAI_MODEL`, `JANUARY_LLM_GEMINI_MODEL`, `JANUARY_LLM_GROQ_MODEL`, `JANUARY_LLM_OPENROUTER_MODEL`, `JANUARY_LLM_OLLAMA_MODEL`, `JANUARY_LLM_OPENAI_BASE_URL`, `JANUARY_LLM_GEMINI_BASE_URL`, `JANUARY_LLM_GROQ_BASE_URL`, `JANUARY_LLM_OPENROUTER_BASE_URL`, `JANUARY_LLM_OLLAMA_BASE_URL`, `JANUARY_LLM_OPENAI_API_KEY`, `JANUARY_LLM_GEMINI_API_KEY`, `JANUARY_LLM_GROQ_API_KEY`, `JANUARY_LLM_OPENROUTER_API_KEY`, `JANUARY_LLM_TIMEOUT_SECONDS`, `JANUARY_LLM_CONNECT_TIMEOUT_SECONDS`, `JANUARY_LLM_MAX_OUTPUT_TOKENS`, `JANUARY_LLM_TEMPERATURE`, `JANUARY_LLM_MAX_TRANSPORT_ATTEMPTS`, `JANUARY_LLM_MAX_CORRECTION_ATTEMPTS`, `JANUARY_LLM_RETRY_MIN_DELAY_SECONDS`, `JANUARY_LLM_RETRY_MAX_DELAY_SECONDS` | enabled/provider/model required; remote credential conditional | production-sensitive; API keys secret |
| Planning | `JANUARY_PLANNING_JOB_BATCH_SIZE`, `JANUARY_PLANNING_OWNER_NAME`, `JANUARY_PLANNING_JOB_POLL_INTERVAL_SECONDS`, `JANUARY_PLANNING_JOB_LEASE_SECONDS` | bounded runtime tuning | production-sensitive, non-secret |
| Commands | `JANUARY_COMMAND_WORKER_ENABLED`, `JANUARY_COMMAND_OWNER_NAME`, `JANUARY_COMMAND_BATCH_SIZE`, `JANUARY_COMMAND_POLL_INTERVAL_SECONDS`, `JANUARY_COMMAND_LEASE_SECONDS`, `JANUARY_COMMAND_MAX_AUTHORIZATION_ATTEMPTS`, `JANUARY_COMMAND_RETRY_MIN_DELAY_SECONDS`, `JANUARY_COMMAND_RETRY_MAX_DELAY_SECONDS`, `JANUARY_COMMAND_MAX_ARGUMENT_LENGTH`, `JANUARY_COMMAND_MAX_PROFILES_SHOWN` | worker required; remaining values bounded | production-sensitive, non-secret |
| Proactive scheduling | `JANUARY_PROACTIVE_SCHEDULING_ENABLED`, `JANUARY_SCHEDULER_WORKER_ENABLED`, `JANUARY_SCHEDULER_OWNER_NAME`, `JANUARY_SCHEDULER_BATCH_SIZE`, `JANUARY_SCHEDULER_POLL_INTERVAL_SECONDS`, `JANUARY_SCHEDULER_LEASE_SECONDS`, `JANUARY_SCHEDULER_ACTIVE_REMINDER_LIMIT`, `JANUARY_SCHEDULER_MINIMUM_LEAD_SECONDS`, `JANUARY_SCHEDULER_HORIZON_DAYS`, `JANUARY_SCHEDULER_REMINDER_TEXT_LIMIT`, `JANUARY_SCHEDULER_HISTORY_RETENTION_DAYS` | optional; worker/delivery pairing conditional | production-sensitive, non-secret |
| Product-policy toggles | `JANUARY_AMBIENT_SELECTIVE_ENABLED`, `JANUARY_COMMAND_MENU_LIVE_MANAGEMENT_ENABLED`, `JANUARY_PROMPT_VERSION`, `JANUARY_RESPONSE_PLAN_SCHEMA_VERSION`, `JANUARY_RESPONSE_PLAN_TEXT_LIMIT` | optional/immutable bounded policy | production-sensitive, non-secret |
| Outbound delivery | `JANUARY_OUTBOUND_DELIVERY_ENABLED`, `JANUARY_OUTBOUND_OWNER_NAME`, `JANUARY_OUTBOUND_BATCH_SIZE`, `JANUARY_OUTBOUND_POLL_INTERVAL_SECONDS`, `JANUARY_OUTBOUND_LEASE_SECONDS`, `JANUARY_OUTBOUND_MAX_CONFIRMED_REJECTION_ATTEMPTS`, `JANUARY_OUTBOUND_RETRY_MIN_DELAY_SECONDS`, `JANUARY_OUTBOUND_RETRY_MAX_DELAY_SECONDS`, `JANUARY_TELEGRAM_TEXT_LIMIT`, `JANUARY_TELEGRAM_DISABLE_NOTIFICATION`, `JANUARY_TELEGRAM_PROTECT_CONTENT`, `JANUARY_TELEGRAM_STICKER_MAPPING` | outbound worker required; remaining settings bounded | production-sensitive, non-secret |
| Guarded live/demo | `JANUARY_TELEGRAM_DELIVERY_TEST_CHAT_ID`, `JANUARY_TELEGRAM_LIVE_DELIVERY_VERIFICATION_ENABLED`, `JANUARY_LLM_LIVE_VERIFICATION_ENABLED`, `JANUARY_DEMO_LIVE_ENABLED`, `JANUARY_DEMO_LIVE_TELEGRAM_VERIFICATION_ENABLED`, `JANUARY_DEMO_ALLOWED_CHAT_IDS`, `JANUARY_DEMO_RUNTIME_DIRECTORY` | test-only/external acceptance; demo forbidden in production | test-only, production-sensitive, non-secret |
| Control plane | `JANUARY_CONTROL_PLANE_ENABLED`, `JANUARY_CONTROL_PLANE_JWT_SECRET`, `JANUARY_CONTROL_PLANE_JWT_ISSUER`, `JANUARY_CONTROL_PLANE_JWT_AUDIENCE`, `JANUARY_CONTROL_PLANE_SESSION_TTL_SECONDS`, `JANUARY_CONTROL_PLANE_DEPLOYMENT_BOOTSTRAP_SUBJECTS` | all core auth values required; bootstrap subjects nonempty | production-sensitive; JWT secret secret |
| Safety | `JANUARY_SAFETY_MODERATION_ENABLED`, `JANUARY_SAFETY_SIGNAL_WINDOW_SECONDS`, `JANUARY_SAFETY_REVIEW_RETENTION_DAYS`, `JANUARY_SAFETY_DEFAULT_TEASING_CAP`, `JANUARY_SAFETY_THRESHOLD_PARTICIPANT_REFUSALS`, `JANUARY_SAFETY_THRESHOLD_MENTION_FREQUENCY`, `JANUARY_SAFETY_THRESHOLD_TEASING_FREQUENCY`, `JANUARY_SAFETY_THRESHOLD_RATE_LIMIT_VIOLATIONS`, `JANUARY_SAFETY_THRESHOLD_MEMORY_EXTRACTION`, `JANUARY_SAFETY_THRESHOLD_DANGEROUS_INSTRUCTION`, `JANUARY_SAFETY_THRESHOLD_PROMPT_INJECTION`, `JANUARY_SAFETY_THRESHOLD_MANIPULATION`, `JANUARY_SAFETY_PAUSE_AFTER_ACTIONS`, `JANUARY_SAFETY_FAIL_CLOSED_ALERT_BURST_WINDOW_SECONDS` | enabled required; values code-bounded/operator-reviewed | production-sensitive, non-secret |
| Data governance | `JANUARY_DATA_GOVERNANCE_ENABLED`, `JANUARY_GOVERNANCE_WORKER_ENABLED`, `JANUARY_GOVERNANCE_EXPORT_TTL_DAYS`, `JANUARY_GOVERNANCE_AUDIT_RETENTION_DAYS`, `JANUARY_GOVERNANCE_EXPORT_LEASE_SECONDS`, `JANUARY_GOVERNANCE_EXPORT_BATCH_SIZE`, `JANUARY_GOVERNANCE_EXPORT_MAX_ATTEMPTS`, `JANUARY_GOVERNANCE_OWNER_NAME`, `JANUARY_GOVERNANCE_WORKER_POLL_INTERVAL_SECONDS` | feature/worker required; policy/cadence operator-reviewed | production-sensitive, non-secret |

### Compose and validator-only inventory

| Variables | Classification | Purpose |
| --- | --- | --- |
| `JANUARY_BACKEND_IMAGE` | required staging/production representation, non-secret | immutable image reference |
| `JANUARY_STAGING_HTTP_PORT`, `JANUARY_STAGING_DB_PORT`, `JANUARY_STAGING_REDIS_PORT`, `JANUARY_STAGING_QDRANT_PORT` | staging-only, non-secret | loopback host bindings for the repository staging representation |
| `JANUARY_HOST_PORT`, `JANUARY_DB_HOST_PORT`, `JANUARY_REDIS_HOST_PORT`, `JANUARY_QDRANT_HOST_PORT` | development/test-only, non-secret | isolated local validator host ports |
| `COMPOSE_PROJECT_NAME` | development/test/staging orchestration, non-secret | isolates Compose resources; production orchestrator owns its equivalent |

### Secret override

| Setting | Purpose | Safe default? | Required in production? | Validation and failure behavior |
| --- | --- | --- | --- | --- |
| `JANUARY_DATABASE_PASSWORD` | component-form PostgreSQL credential | local only; unsafe outside local/test | yes when URL absent | local default, empty resolved credential, or loopback target fails staging/production startup |
| `JANUARY_DATABASE_URL` | complete async PostgreSQL URL, possibly credential-bearing | empty means use components | alternative to components | only `postgresql+asyncpg`; resolved nonlocal host and credential required |
| `JANUARY_REDIS_URL` | Redis endpoint and optional credential | loopback local only | yes | absolute `redis://` or `rediss://`; loopback fails staging/production |
| `JANUARY_TELEGRAM_BOT_TOKEN` | Telegram Bot API authentication | empty/disabled | yes for Telegram-first profile | normalized empty becomes missing; enabled delivery fails before startup |
| `JANUARY_TELEGRAM_WEBHOOK_SECRET_TOKEN` | authenticates Telegram webhook delivery | empty/disabled | webhook mode only | safe ASCII 1–256; missing fails before startup; request comparison is constant-time |
| `JANUARY_LLM_OPENAI_API_KEY`, `JANUARY_LLM_GEMINI_API_KEY`, `JANUARY_LLM_GROQ_API_KEY`, `JANUARY_LLM_OPENROUTER_API_KEY` | remote provider authentication | empty/disabled | selected remote route only | empty normalizes to missing; enabled selected provider fails before startup |
| `JANUARY_CONTROL_PLANE_JWT_SECRET` | JWT verification secret | empty/disabled | yes for release profile | minimum 32 characters; missing/short fails before startup |

Never place these values in committed files, command output, metrics, logs, or
container layers. `SecretStr` redaction is defense in depth, not a substitute
for a secret manager.

### Production-sensitive fail-closed summary

| Setting/family | Purpose | Safe default? | Required? | Failure behavior |
| --- | --- | --- | --- | --- |
| `JANUARY_ENVIRONMENT` | activates environment policy | `local`, not production-safe | yes | production preflight requires exact `production` |
| database target/pool/echo | authoritative persistence and bounded connections | local target unsafe; pool defaults bounded | target yes | invalid driver/host/credential, debug echo, or bad bounds reject startup/preflight |
| Telegram enabled/mode/connection/webhook | ingress and delivery ownership | disabled | core yes; webhook conditional | missing dependencies reject startup; webhook secret/path/body/update parsing fail closed |
| Redis/rate/concurrency | durable handoff coordination and external-I/O admission | Redis local; gates disabled | yes for release profile | unavailable coordination makes readiness fail or I/O admission fail closed |
| provider models/routes/governance | external generation/TTS/embedding eligibility and cost | disabled/legacy | generation and enforce mode required; optional capabilities conditional | missing model/credential/worker/lease rejects startup or admission before I/O |
| control plane | authenticated operator operations | disabled | yes | missing secret/issuer/audience rejects startup; authorization remains deny-by-default |
| safety | moderation/protection thresholds | disabled locally | yes | production preflight rejects disabled safety; runtime denials remain fail closed |
| governance/retention | export, erasure, redaction, artifact purge | disabled locally | yes | production preflight rejects absent workers; durable work remains recoverable |
| Qdrant/embedding/knowledge | optional derived retrieval | disabled | only when enabled | incomplete provider/worker pairing rejects startup; outage degrades to no derived context |
| TTS | explicit `/voice` playback | disabled | only when enabled | requires enforce mode, rate/concurrency, OpenAI credential, command/outbound workers, and safe leases |
| debug/live/demo flags | diagnostics and guarded external acceptance | off | no | debug/database echo rejected outside local/test; demo rejected in production; live tools remain explicit |

## Production configuration preflight

Offline, credential-free repository proof:

```bash
./scripts/validate-production-readiness.sh
```

Explicit operator-supplied production configuration, still without network I/O:

```bash
env -i PATH="$PATH" \
  JANUARY_ENVIRONMENT=production \
  ...approved runtime variables... \
  ./scripts/validate-production-readiness.sh --production-config
```

The tool reads no `.env`, prints no values, rejects missing/obvious placeholder
values, validates the typed dependency graph, and requires the Telegram-first
core controls. Optional media, TTS, semantic memory, knowledge, summaries, and
scheduling remain optional, but enabled capabilities must be complete.

After the operator selects the production database, perform the read-only
connectivity/current-revision/upgrade-path check:

```bash
./scripts/validate-production-readiness.sh --database-preflight
```

This command does not upgrade or downgrade. It accepts only one known current
revision on the linear path to `0026_conversation_feedback`. The operator
records the current revision, verifies the backup, runs the separately approved
single-owner upgrade, and repeats preflight until current equals target.

## Build and container contract

- Python 3.12 slim runtime; dependencies are locked by `uv.lock` and installed
  with `uv sync --locked --no-dev`.
- Runtime runs as non-root user `january`.
- `.dockerignore` excludes `.git`, `.env`, `.venv`, docs, caches, Harness state,
  and developer artifacts.
- The runtime image contains the application, Alembic configuration/migrations,
  and locked production dependencies; it does not require Git or developer
  files.
- Default command is bounded Uvicorn on port 8000. Workers use explicit module
  entrypoints and graceful signal handling.

## Service topology and startup

| Service | Authority/state | Startup dependency | Failure/recovery |
| --- | --- | --- | --- |
| PostgreSQL | all durable product/authority state | first | readiness false; no external I/O; restore under incident authority |
| Redis | transient streams/rate/concurrency | before API/workers that require it | readiness/admission fail closed; rebuild from durable handoff |
| Qdrant | optional opaque derived vectors | before enabled index worker; not global readiness | no derived context; rebuild from PostgreSQL |
| migration | schema owner | healthy PostgreSQL and verified backup | any nonzero stops rollout |
| API/webhook | ingress/control/readiness | completed migration; Redis for enabled gates | `/ready` 503 on required dependency/head failure |
| dispatcher/conversation | durable ingress handoff and processing | migration, PostgreSQL, Redis | idempotent replay/consumer recovery |
| planning/commands/outbound | provider planning, commands/TTS, Telegram delivery | migration, PostgreSQL, Redis and enabled dependencies | bounded leases; current authority; possible-I/O/unknown quarantine |
| scheduler/governance/retention/provider-governance | proactive, privacy, purge, accounting recovery | migration, PostgreSQL; Redis where operation requires | bounded claims/retry; backlog/terminal evidence |
| optional summary/semantic/knowledge workers | derived context/index state | matching feature/provider; Qdrant for vector workers | retry/defer/rebuild; never supersede PostgreSQL |

Supported order:

```text
dependencies -> backup/preflight -> migration -> API /ready -> workers
-> worker evidence -> external ingress -> bounded live smoke
```

No arbitrary sleep is an authority boundary. Use service health, migration
completion, readiness, and durable worker evidence.

Scale API replicas behind the operator's traffic router; all replicas share
the same PostgreSQL authority and required Redis coordination. Durable workers
may scale through their existing database claims, lease tokens, uniqueness
constraints, and Redis consumer group. Give replicas distinct consumer/owner
names for attribution, preserve per-conversation ordering, and account for
each replica's database pool and provider concurrency budget. Keep one
migration owner and one polling owner per connection. PostgreSQL/Redis/Qdrant
clustering and data sharding are outside this Compose contract; adding replicas
does not establish those capabilities. Metrics must aggregate replica counts
without adding identity labels.

## Readiness and failure injection

- `/live`: process-only; it does not check dependencies.
- `/ready`: PostgreSQL connectivity and exact Alembic head; Redis additionally
  when Telegram delivery, rate limiting, or provider concurrency requires it.
- `/health`: descriptive `ok`/`degraded` component view; it is not the traffic
  readiness gate.
- Optional disabled Qdrant/provider/TTS capabilities do not block global
  readiness. Their enabled paths fail closed or degrade exactly as their
  product contracts specify.

Synthetic failure proof covers database unavailable, Redis unavailable,
provider unavailable, Telegram 5xx/timeout, Qdrant unavailable, migration
mismatch, optional missing credential, and required production credential.
Never use production endpoints for injection.

## Migration, backup, restore, and rollback

Before migration:

1. verify exact SHA, remote Quality, source integrity, production config, one
   head, database current revision, and upgrade path;
2. create an operator-owned PostgreSQL backup;
3. verify backup completion, checksum/catalog metadata, retention, restore
   authority, RPO/RTO, and the post-backup erasure reapplication record;
4. stop external ingress and ensure only one migration owner;
5. run `alembic upgrade 0026_conversation_feedback`; any failure stops rollout;
6. rerun database preflight and `/ready` before workers/traffic.

Synthetic restore uses `./scripts/validate-backup-restore.sh`. PostgreSQL is
restored as authority. Redis is recreated, not restored as truth. Qdrant is
rebuilt. Re-run multi-tenancy, governance, memory/personal/semantic retrieval,
knowledge revalidation, and live voice artifact/action integrity. Reapply
governed erasures that occurred after the backup before traffic resumes.

Rollback decision:

- prefer traffic/capability disable and application image/config rollback when
  the previous application is compatible with current schema;
- never equate application rollback with database downgrade;
- use an existing downgrade only when its guards prove current state is safe
  and the incident/restore owner explicitly approves it;
- when guarded downgrade refuses, keep current schema and forward-fix;
- restore only for authoritative data loss/corruption under incident authority.

## Worker recovery and shutdown

Each process defaults to a PostgreSQL pool of 5 persistent connections and up
to 5 overflow connections; pool acquisition uses the configured 3-second
timeout, and readiness bounds its whole database probe to that timeout.
Operators must budget the aggregate across
API and worker replicas against PostgreSQL capacity. SQL echo stays disabled.
The read-only release preflight uses one connection, no overflow, and the same
bounded connection/query timeout; errors expose no connection credentials.

SIGINT/SIGTERM initiates drain. Workers stop claiming, finish bounded current
work, and close external clients/database pools. Abrupt termination relies on
lease expiry and current-owner tokens. Planning jobs, outbound actions,
schedules, privacy/retention work, provider reservations, and voice artifacts
all revalidate authority before external I/O. A possible provider call or
possible Telegram delivery is never described as exactly once.

## Release acceptance matrix

| Capability | Synthetic acceptance | External prerequisite | Production configuration | Failure behavior | Repository release status |
| --- | --- | --- | --- | --- | --- |
| Telegram text | adapter, ingress, conversation, planning, delivery validators | bot/token and approved chat | Telegram core, Redis, workers | retry confirmed no-send; quarantine unknown | locally verifiable |
| Reply/ordered delivery | conversation-UX validator | same as text | response schema/current DB | tail blocked behind non-delivered predecessor | locally verifiable |
| Presence | presence validator | Telegram support | admitted provider path | cosmetic failure independent | locally verifiable |
| Regeneration/edit | regeneration validator | editable bot-authored message | command/planning/outbound | exact rejection may fall back; ambiguity blocks duplicate | locally verifiable |
| Reactions | reactions validator | Telegram reaction support | ordinary addressed text | at-most-once cosmetic failure | locally verifiable |
| Voice/TTS | voice validator | approved OpenAI TTS route/credit | optional TTS plus enforce/rate/concurrency | possible-I/O no repeat; delivery unknown quarantined | locally verifiable; live external prerequisite |
| Feedback | feedback validator | none | command worker/current schema | structured deterministic rejection; no provider effect | locally verifiable |
| Explicit memory | memory validator | none | retention/privacy workers | exact-scope fail closed | locally verifiable |
| Personal context | personal-context validator | none | same as memory | exact-private scope, delete wins | locally verifiable |
| Semantic memory | semantic-memory validator | approved embedding/Qdrant if enabled | optional embedding + worker | lexical/no semantic context; stale points rejected | locally verifiable |
| Knowledge/RAG | knowledge validator | approved embedding/Qdrant if enabled | optional KB + index worker | no knowledge context; PostgreSQL revalidation | locally verifiable |
| Scheduled/proactive | scheduling validator | operator enablement/timezone ops | optional scheduler + outbound | bounded catch-up, current-authority skip | locally verifiable |
| Privacy/export/delete | governance/backup validators | retention/RPO/RTO approval | governance and retention workers | privacy authority wins; retry cleanup | locally verifiable |
| Provider governance | provider validator | account, credential, route, price/budget approval | enforce + recovery worker | deny before I/O; ambiguous debit retained | locally verifiable; billing/live external prerequisite |
| Multi-tenancy | multi-tenancy validator | identity/member review | canonical tenant/Assistant/connection | foreign scope denied | locally verifiable |
| Operator control plane | auth/config tests | IdP and role owners | JWT values/bootstrap subjects | authentication/authorization fail closed | locally verifiable; IdP external prerequisite |
| Observability | observability validator | metrics/alert backend and destinations | metrics enabled; safe exporter choice | telemetry failure does not duplicate product I/O | contract locally verifiable; external alerts unproven |
| Backup/restore | synthetic logical drill | encrypted destination, retention, restore owner | DB access and operator procedure | traffic remains closed until authority proof | locally verifiable; production drill operator-owned |

## Telegram ingress security and polling

Webhook mode checks the exact configured path/connection, constant-time secret
header, bounded `Content-Length` and actual body, JSON/update shape, supported
payload type, durable connection authority, and update idempotency. Unsupported
reaction update types create no product work.

Polling is a production-supported alternative for controlled deployments, but
webhook is the staging default and preferred public-ingress mode. The poller
checks Telegram webhook state and refuses simultaneous ownership. Cursor and
batch acceptance advance atomically through durable PostgreSQL state.

## Provider, privacy, and observability acceptance

Provider admission preserves capability/data eligibility, cumulative budgets,
rate and concurrency gates, bounded timeout, attempt-level usage quality, and
conservative possible-I/O accounting. Disabled capabilities require no secret.
Enabled remote providers, embeddings, media, or TTS require their complete
contract and fail before I/O when missing.

Retention and recovery processes are real worker entrypoints, not assumed cron:

- `app.runtime.retention_worker`: raw content, schedule history, and voice
  artifact purge in bounded batches;
- `app.runtime.governance_worker`: export/erasure work and cleanup;
- `app.runtime.provider_governance_worker`: reservations and ambiguous usage;
- outbound/planning repositories: expired leases, retry, and unknown-state
  quarantine;
- scheduler: bounded occurrence materialization and recovery.

Metrics/logs must never contain prompt/response, memory/knowledge text, audio
bytes/base64, tokens, credentials, raw provider bodies, or prohibited identity
labels. Representative Telegram, provider, TTS, privacy, and unknown-delivery
failures are inspected under synthetic values only.

## SLO and incident readiness

The repository defines content-safe SLIs/SLOs and alert conditions for inbox
lag, planning/provider failures, outbound retry/unknown, worker lease recovery,
database pool saturation, Redis availability, optional Qdrant degradation, and
privacy worker failure. It does not provision an alert backend. Operators must
map these contracts to dashboards, thresholds, notification destinations,
on-call ownership, and escalation before traffic.

Incident order is: protect people/privacy, stop unsafe traffic or provider I/O,
preserve evidence, classify delivery/provider ambiguity, choose application
rollback versus forward-fix, authorize restore only when necessary, reconcile
erasures/derived state, verify readiness/workers, and reopen bounded traffic.

## External prerequisites

The repository cannot prove these without operator action:

1. dedicated production/staging Telegram bot token, connection, bounded test
   chat, public webhook URL, DNS/TLS, and webhook secret;
2. production PostgreSQL and Redis; optional Qdrant/embedding runtime only for
   enabled features;
3. provider accounts/credits, approved models/capabilities/data handling,
   credentials, prices, budgets, rate/concurrency values, and billing review;
4. a production secret manager plus rotation/revocation owner;
5. hosting/orchestrator, immutable image digest, network policy, TLS
   termination, and one migration owner;
6. IdP issuer/audience, deployment bootstrap subjects, membership review, and
   named deployment/incident/rollback/restore owners;
7. encrypted backup destination, retention, restore drill, RPO/RTO, and
   post-backup erasure-reapplication record;
8. metrics/alert backend, dashboards, thresholds, destinations, on-call and
   escalation; and
9. independent release-readiness audit and production-promotion approval.

Fresh live Telegram/provider/staging acceptance is therefore
`BLOCKED_ON_EXTERNAL_PREREQUISITE` as an external promotion step. Repository
readiness may still be approved using current synthetic proof and the
historical SPEC-022 guarded-acceptance chronology. No real secret should be
requested or printed in review evidence.
