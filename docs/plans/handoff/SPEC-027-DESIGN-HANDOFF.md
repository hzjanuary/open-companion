# SPEC-027 Implementation Design Handoff

Date: 2026-09-04

## 1. Executive summary

Implement SPEC-027 by additively extending the existing `memory_items` system,
not by creating a second memory architecture. Add creator-private personal
context, positive record revisions, per-participant exact-conversation recall
policy, and a content-free mutation idempotency ledger. Extend the deterministic
Telegram `/memory` command namespace, split context database reads from
embedding/Qdrant I/O, enforce recall both before semantic I/O and during
PostgreSQL revalidation, and integrate all new state with SPEC-025 governance.

Personal context is private-conversation only and never enters Qdrant. There is
no cross-conversation identity, automatic extraction, inferred profile, model
call for administration, new control-plane content API, or new runtime worker.

## 2. Baseline SHA

- Repository: `hzjanuary/open-companion`
- `HEAD` and `origin/main`: `private-source-checkpoint-omitted`
- Commit: `feat(spec-026): implement provider routing, budgets and usage governance`
- Current committed Alembic head: `0017_provider_routing_cost_budgets`
- Next migration: `0018_user_controlled_memory`
- Starting worktree: clean; the Product Spec, indexes, and active plan are the
  first SPEC-027 changes.

## 3. Existing architecture reused

- `application/memory.py`: pure normalization and memory drafts.
- `infrastructure/database/memory.py`: canonical memory transactions and
  derived-index intents.
- `application/commands.py` and `runtime/telegram_command_worker.py`:
  deterministic grammar and existing response-plan/outbound delivery handoff.
- `Conversation.memory_privacy_revision`: stale-context fencing immediately
  before governed generation.
- semantic repository/retriever/index worker: opaque Qdrant IDs, PostgreSQL
  revalidation, durable UPSERT/DELETE jobs, safe deterministic fallback.
- governance builder/repository/privacy erasure/retention worker: subject/group
  export, erasure, data summary, inventory, package invalidation, backup limits.
- SPEC-026 governed response-generation and embedding boundaries.
- process-local metrics catalog and content-free audit conventions.

## 4. Scope

- Creator-owned personal-context subtype for private conversations.
- Inspect/list, add, optimistic update/delete, clear-mine, recall status/off/on.
- Backward-compatible remember/forget/group reset behavior.
- Exact scope/identity checks, content-free idempotency/audit, derived cleanup.
- Bounded context injection with explicit precedence.
- Migration, unit/integration proof, validator, ADR, runbook/docs, CI update.

## 5. Out of scope

- Automatic memory, inferred/sensitive traits, hidden profile, semantic personal
  context, cross-conversation identity, cross-platform/tenant federation.
- Tenant/deployment memory content administration or a new HTTP memory API.
- New workers, providers, processors, billing, proactive interaction, Zalo,
  SPEC-028.

## 6. Domain model

Extend `app.domain.persistence`:

- `MemoryKind`: add `personal_context`.
- `MemoryVisibility`: add `creator_only`.
- add `PersonalContextKey` with the five Product Spec keys.

Add pure application values:

- `PersonalContextDraft(content, key, scope, kind, visibility, confidence)`;
- `MemoryMutationOutcome`: `created`, `updated`, `deleted`, `cleared`,
  `enabled`, `disabled`, `unchanged`, `conflict`, `missing`, `denied`,
  `scope_denied`, `limit_reached`;
- immutable list/status/mutation result DTOs containing only authorized content
  and bounded metadata.

`normalize_personal_context` normalizes NFC/whitespace, validates the closed key,
1–300 characters, and creates only `personal_context` + `creator_only`.

## 7. Memory ownership model

`creator_participant_id` remains the owner. Migration 0018 adds an exact
participant/conversation composite constraint so a memory cannot name a creator
from another conversation. Application queries additionally require the full
Assistant/connection/conversation chain.

Only the owner updates a record. Existing group-admin deletion/reset applies
only to shared `explicit_fact` records. Personal context is never group-admin
readable or mutable.

## 8. Personal-context model

Reuse `memory_items` with:

- `kind = personal_context`;
- `visibility = creator_only`;
- non-null closed `context_key`;
- positive `revision`, initially 1;
- private-conversation `scope = private_conversation`;
- existing content/hash/source/provenance/status timestamps.

A partial unique index enforces one active personal-context key per
`creator_participant_id + conversation_id`. Personal context never schedules an
embedding job.

## 9. Scope and identity model

Repository entry points take Assistant, PlatformConnection, conversation, and
actor participant IDs. A shared scope resolver proves:

```text
participant.conversation_id == conversation.id
conversation.platform_connection_id == connection.id
connection.assistant_id == assistant.id
```

Personal-context creation additionally proves private conversation type.
`platform_user_id` is not used to authorize cross-conversation recall.

## 10. Authorization matrix

| Actor | Shared explicit list | Own personal list | Create personal | Update | Delete | Clear | Recall | Group reset |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Exact participant | Yes | Private chat only | Private chat only | Own only | Own only | Own only | Own only | No |
| Fresh Telegram group admin | Yes | No | No | No | Shared explicit only via `/forget` | No | No | Yes, shared explicit only |
| Tenant roles | No new content access | No | No | No | No | No | No | No |
| Deployment operator | No new content access | No | No | No | No | No | No | No |

## 11. Command/API surface

Extend `parse_command` with exact grammar:

- `context add <key> <value>`;
- `update <public-id> <positive-revision> <content>`;
- `delete <public-id> <positive-revision>`;
- `clear_mine confirm`;
- `recall status|off|on`.

Keep `/memory`, `list`, `remember`, `reset_group confirm`, `/forget`, and
`/forget_me`. Reject extra/malformed input. Add compact Vietnamese/English
responses for conflict, scope denial, recall state, clear count, and revision.
No control-plane memory-content route is added.

## 12. Context-assembly integration

Add `ContextPersonalContext(public_id, key, content, revision, updated_at)` and
`ConversationContext.personal_context`.

Refactor `SqlAlchemyConversationContextReader.build_for_message`:

1. open a short session and load current/candidates/summary, current participant
   recall, eligible deterministic explicit-memory rows, exact identity, and
   personal context;
2. close the session;
3. if current recall permits, perform governed embedding + Qdrant query +
   PostgreSQL semantic revalidation through the retriever;
4. merge/limit application DTOs and build context.

No SQLAlchemy session remains open during embedding or Qdrant I/O.

## 13. Conflict/precedence model

Prompt system text and JSON structure declare:

```text
system/safety/privacy/action policy
  > current_message
  > personal_context
  > explicit_memories
  > recent_history
  > conversation_summary
```

Personal context uses its closed key and one-active-key uniqueness. Deterministic
explicit fallback orders by `updated_at DESC, revision DESC, id DESC`.
Semantic candidates preserve score order with stable ID tie behavior; they do
not claim semantic conflict resolution. Ordinary current-turn conflicts never
write storage.

## 14. Recall enable/disable semantics

Add `memory_recall_policies` keyed uniquely by exact participant/conversation,
with Assistant/connection scope, `enabled`, positive `revision`, last mutation
source, and timestamps. Absence means enabled for backward compatibility.

- current actor disabled: skip all deterministic and semantic memory context,
  including avoiding query embedding/Qdrant I/O;
- any owner disabled: exclude that owner's explicit facts from deterministic
  selection and semantic PostgreSQL revalidation for other users;
- enable restores only active/unexpired rows;
- every real state change increments policy and conversation privacy revisions;
- unchanged replay/state records a deterministic unchanged result without a
  spurious revision.

## 15. Semantic retrieval interaction

Pass current participant authority into retrieval/revalidation. All semantic
canonical queries require `kind = explicit_fact`, exact scope/status/content,
and owner recall enabled or no policy row. If the current actor is disabled,
the context reader never invokes the retriever.

Deterministic fallback applies identical owner/current recall filtering.

## 16. Qdrant implications

No Qdrant schema or payload expansion is needed. Personal context never becomes
an UPSERT candidate. Existing payload remains memory ID plus opaque internal
Assistant/connection/conversation/scope/version metadata and no text.

Explicit updates reschedule/reopen UPSERT jobs for all required active target
versions; deletes/clear/erasure schedule DELETE for all known versions. Qdrant
failure remains safe because PostgreSQL is revalidated.

## 17. PostgreSQL authoritative state

PostgreSQL owns record kind/key/content/hash/owner/scope/status/revision, recall
policy, command outcome, events, and semantic work intent. Qdrant owns no recall
authority. Redis coordinates only existing queues/rate/concurrency.

## 18. Derived-state invalidation

Every memory/personal-context/recall mutation increments the affected
conversation `memory_privacy_revision`. Planning rechecks that value before
provider I/O and releases stale work.

- explicit update: durable semantic UPSERT;
- explicit delete/clear/reset/erasure: durable DELETE for all known versions;
- personal-context mutation: no Qdrant job;
- recall disable: PostgreSQL filter is immediately authoritative; Qdrant points
  may remain but cannot pass revalidation;
- recall enable: only active explicit rows become eligible; existing/rebuilt
  index state remains derived.

## 19. Data-governance integration

Bump `DATA_INVENTORY_VERSION` to v3 and add recall policy/idempotency categories.
Update public data-governance and retention tables. Deployment snapshots expose
counts only. Invalidate outstanding subject export packages whenever exported
memory/context/recall state changes.

## 20. Erasure integration

Extend `SqlAlchemyPrivacyRepository.erase_subject` within its existing
Assistant/PlatformConnection platform-user boundary:

- existing memory update already captures both kinds;
- set every matched recall policy to disabled and clear mutation source where
  appropriate while preserving content-free tombstone/revision;
- count recall policies in the result;
- increment each affected conversation revision once;
- schedule semantic deletes only for explicit facts (personal context has none);
- preserve governed erasure request completion/partial semantics.

## 21. Export integration

Subject package memory entries add `visibility`, `context_key`, `revision`, and
`updated_at`; query remains owner + exact conversation. Add `memory_recall` with
enabled/revision, defaulting to enabled if no row exists.

Group export explicitly filters `kind = explicit_fact` and shared visibility;
it never returns personal context or recall policy. Deployment export adds only
new table/category counts.

## 22. Retention implications

Active memory/personal context persists until explicit lifecycle mutation.
Content-free recall policy, operation ledger, and memory-event rows remain
operator-retained history. Existing command response content remains subject to
raw-content redaction. The existing retention worker also expires canonical
memory in bounded ordered batches, clearing content/hash, invalidating exports
and stale context, and scheduling explicit-only derived deletion. This closes
the Product Spec's expiry lifecycle without adding a worker.

## 23. Provider-budget interaction

Memory management executes database/application logic only. It never constructs
a `GenerationRequest` or calls embedding/Qdrant synchronously. Async explicit
memory UPSERTs continue through the SPEC-026 governed embedding gateway.
Responses using memory continue through the governed generation gateway. Recall
disable happens before semantic provider I/O and cannot be bypassed by fallback.

## 24. Safety interaction

Stored values are explicitly supplied but remain untrusted. Existing structural
safety and response-plan policy still apply to generated output. Memory cannot
alter system/safety/action instructions, authorize targeting, or re-enable
teasing/mentions. Administration itself is deterministic and content is not
copied into audit/telemetry.

## 25. Transaction boundaries

- Create/update/delete: lock exact rows, mutate canonical state, record event
  and operation, invalidate exports, increment privacy revision, schedule
  derived intent, commit.
- Clear: one operation row progresses through ordered bounded batches; each
  batch commits before the next; replay resumes and completion is durable.
- Recall change: lock/upsert policy + operation and increment conversation
  revision in one transaction.
- Context read closes before embedding/Qdrant/provider I/O.
- Telegram response delivery stays in the existing outbound worker after the
  command mutation transaction.

## 26. Command idempotency

Add `memory_control_operations` with unique `command_job_id`, closed operation,
status/outcome, optional memory reference, resulting revision, affected count,
recall result, and timestamps—never content. Repository methods first resolve
an existing operation and return its durable result. Insert races use PostgreSQL
uniqueness/CAS and deterministic reread.

Existing remember remains fenced by unique `source_command_job_id`; add its
bounded result to the operation ledger for uniform proof. Existing governance
erasure request uniqueness continues to fence group reset and forget-me.

## 27. Concurrency/revision semantics

`memory_items.revision` starts at 1. Owner update/revision-delete uses
`SELECT ... FOR UPDATE`, exact expected revision, and increments only update.
Stale revisions return conflict with no mutation. Compatibility `/forget`
serializes and delete-wins.

Personal-context active-key uniqueness closes concurrent create. Clear selects
`ORDER BY created_at, id LIMIT memory_control_batch_size FOR UPDATE`, updates a
batch, and repeats until drained with the operation row tracking count. The
participant scope lock serializes owner mutations; omitting `SKIP LOCKED`
prevents a transient row lock from being mistaken for a drained owner scope.
Recall policy uses row lock/upsert uniqueness.

## 28. Worker impact

No new worker. Modify:

- Telegram command worker for new deterministic actions;
- response-planning context reader behavior only;
- semantic index worker/repository to exclude personal context and reopen
  explicit UPSERT after update;
- existing retention/governance workers only if tests reveal required count or
  lifecycle integration.

## 29. Migration design

Create `0018_user_controlled_memory` after 0017:

1. add `context_key VARCHAR(32)` nullable and `revision INTEGER NOT NULL DEFAULT 1`;
2. replace the old memory explicit-scope check with kind/key/visibility/status
   shape constraints;
3. add `UNIQUE (id, conversation_id)` to participants and composite creator
   scope FK for memory;
4. add partial unique active personal key index and owner/context indexes;
5. create `memory_recall_policies` with exact scope FKs, unique
   participant/conversation, positive revision, enabled boolean;
6. create `memory_control_operations` with unique command job, closed
   operation/status/outcome, nonnegative counts, result-shape checks;
7. preserve all legacy rows at explicit-fact/same-conversation/revision 1.

No content backfill or identity linkage occurs.

## 30. Downgrade behavior

Downgrade to 0017 must reject while any personal-context row, recall-policy row,
or memory-control operation exists because silently dropping user control or
revision history is unsafe. With no governed 0018 state, remove new tables,
indexes/FKs/columns, restore the exact 0017 memory check, and retain explicit
memory data.

## 31. Telemetry

Add `january_memory_control_operations_total` counter with labels:

- `operation`: status/list/create/update/delete/clear/recall_disable/recall_enable;
- `outcome`: success/unchanged/conflict/missing/denied/scope_denied/invalid/failed;
- `record_kind`: explicit_fact/personal_context/recall_policy/none;
- `conversation_type`: private/group.

All values are catalog-enforced closed enums. No IDs or content. Existing
semantic query/fallback, index job, governance erasure, and provider metrics
remain unchanged.

## 32. Audit events

Continue `memory_events` for created/updated/deleted/cleared and recall changes.
Add command ID and bounded revision/count/reason fields only. Operation ledger
is content-free. Do not log command arguments or record content from repository
methods. User-facing Telegram response text is product content, not audit.

## 33. Failure/recovery

- validation/scope/revision errors produce closed deterministic responses;
- database failure fails the command safely and command lease retry follows
  existing rules;
- crash after mutation but before command completion replays the operation row
  and creates the one normal command response;
- clear resumes unfinished bounded batches;
- semantic cleanup failure leaves PostgreSQL deletion/recall authoritative and
  retries existing jobs;
- context authority failure omits memory; semantic outage uses already-filtered
  deterministic fallback;
- no provider or Telegram exactly-once claim.

## 34. Test strategy

Unit tests:

- exact grammar and normalization/key/value limits;
- context item/character bounds and prompt precedence/fields;
- deterministic ordering/merge and telemetry closed labels;
- command worker actions make no provider calls.

PostgreSQL integration tests:

- create/list/update/delete/clear/recall happy paths;
- replay and uniqueness race;
- concurrent active-key create and optimistic update/delete conflicts;
- exact Assistant/connection/conversation/participant isolation;
- group-admin cannot view/edit personal context;
- subject export/group exclusion/data summary;
- erasure disables recall and clears content;
- privacy revision and semantic job intents;
- context session is closed during embedding/Qdrant I/O.

Semantic tests:

- only explicit facts index;
- disabled owner/current caller filtering;
- personal context absent from Qdrant;
- opaque payload; stale point revalidation; safe outage fallback.

Regression searches/tests prove messages, summaries, and generated output do
not schedule memory creation.

## 35. Validator strategy

Create executable `scripts/validate-personal-context.sh` with `set -euo pipefail`:

1. clean-environment focused unit suite;
2. isolated PostgreSQL/Redis/Qdrant dependencies;
3. `0017 -> 0018 -> 0017 -> 0018`;
4. personal-context/memory/governance/semantic integration markers;
5. safe downgrade guard with governed state;
6. fresh-volume base/head/base/head;
7. exactly one head and static content/metric checks;
8. cleanup via trap without hiding phase failures.

Add it to CI and preserve general/affected validators.

## 36. Docker/runtime proof

With Docker available, prove PostgreSQL/Redis/Qdrant integration, migration
lifecycle, semantic worker UPSERT/update/DELETE, context read with fake governed
embedding/index clients, and existing command/planning worker start/stop paths.
No live Telegram/provider credentials are used.

If sandbox socket access fails, perform one capability check and report the
Docker phases separately without modifying the socket or weakening validation.

## 37. Rollback

Before any SPEC-027 data exists, disable deployment of new commands and
downgrade 0018 to 0017 after validator proof. After personal-context, recall, or
operation rows exist, do not downgrade destructively; disable new command paths,
retain 0018 data, and fix/roll forward. Recall defaults must never be reset in a
way that re-enables explicitly disabled data.

## 38. Risks

| Risk | Mitigation |
| --- | --- |
| Cross-conversation identity leak | Exact conversation participant only; never join for recall by platform user |
| Group disclosure of personal context | Private-conversation creation/list/injection only |
| Recall bypass through Qdrant | Pre-query current-policy check plus PostgreSQL owner-policy revalidation |
| Stale prompt after mutation | Conversation privacy revision recheck before governed provider I/O |
| Lost concurrent correction | Positive revision CAS and deterministic conflict |
| Mutation applied twice after crash | Unique operation ledger and replayed result |
| Qdrant contains personal text/context | Personal-context kind excluded from every indexing query and payload tests |
| Unbounded clear/context | Bounded clear batches and fixed item/character limits |
| Existing session across external I/O | Explicit context read/external/read transaction split |
| Stale export after mutation | Atomic subject/group package invalidation where content/state changes |

## 39. Expected files changed

New:

- `alembic/versions/0018_user_controlled_memory.py`
- `backend/tests/integration/test_personal_context_schema.py`
- `docs/decisions/0024-user-controlled-personal-context-and-recall.md`
- `docs/runbooks/personal-context.md`
- `scripts/validate-personal-context.sh`
- final SPEC-027 handoff.

Modified:

- memory/persistence domain and application contracts;
- database models, memory/context/semantic/privacy repositories;
- command grammar/worker and prompt/context values;
- governance export/inventory/data summary and documentation;
- configuration/telemetry;
- affected unit/integration schema-head tests;
- product/architecture/decision/command/runbook indexes;
- CI and validators where head/runtime proof requires it.

No Compose change is expected because no worker is added.

## 40. FR/NFR traceability matrix

| Requirement | Implementation surfaces | Primary proof |
| --- | --- | --- |
| FR-01 | command grammar + memory normalizers/repository only | creation-source regression/search |
| FR-02 | scope resolver + composite constraints | cross-scope integration matrix |
| FR-03 | memory kind/key/visibility + private gate | key/group/duplicate tests |
| FR-04 | actor-filtered status/list | privacy/authorization response tests |
| FR-05 | revision update transaction + UPSERT | optimistic/update/index tests |
| FR-06 | revision delete + compatibility forget | redaction/DELETE/admin tests |
| FR-07 | resumable bounded clear | multi-batch/replay/isolation tests |
| FR-08 | recall policy + context/revalidation filters | off/on/current/owner tests |
| FR-09 | prompt contract + ordering | exact JSON/system/unchanged-storage tests |
| FR-10 | context application limits | item/character boundary tests |
| FR-11 | semantic repo/index worker | kind/payload/revalidation/fallback tests |
| FR-12 | operation ledger + row locks/CAS | replay/race/concurrency tests |
| FR-13 | export/privacy/summary/inventory | governance integration tests |
| FR-14 | Telegram/control authority exclusions | role/admin/cross-scope tests |
| FR-15 | command worker + governed provider paths | zero-provider and SPEC-026 regressions |
| FR-16 | metric catalog + memory events | label/content inspection tests |
| NFR-01 | PostgreSQL models/repositories | stale-Qdrant and DB authority proof |
| NFR-02 | creator-only/private constraints | group/cross-user denial proof |
| NFR-03 | pure parsing/normalization/fakes | unit suite without external services |
| NFR-04 | config limits/batches/order | >batch and boundary proof |
| NFR-05 | atomic mutation transaction | fault/replay integration proof |
| NFR-06 | context phase split | blocking fake asserts session availability |
| NFR-07 | fail-closed queries + jobs | DB/Qdrant failure and retry proof |
| NFR-08 | compatibility filters/commands | complete affected regression matrix |

## 41. Implementation phases

1. Migration/domain/model/application contracts.
2. Memory repository operations/idempotency/recall and command grammar.
3. Context/prompt integration and no-session-across-I/O refactor.
4. Semantic kind/recall filtering and derived invalidation.
5. Governance export/erasure/summary/inventory integration.
6. Telemetry, ADR, runbook, docs, CI, validator.
7. Focused/full/Docker/migration proof and independent audit remediation.

## 42. Final acceptance checklist

- [ ] Product Spec FR-01–FR-16 and NFR-01–NFR-08 implemented.
- [ ] Personal context remains explicit, private-conversation only, creator-only,
  bounded, inspectable, editable, deletable, and absent from Qdrant.
- [ ] Recall disable is authoritative before deterministic and semantic recall.
- [ ] Current-turn precedence is explicit and tested.
- [ ] Command replay/races and optimistic conflicts are proven.
- [ ] No DB session/lock spans embedding, Qdrant, provider, or Telegram I/O.
- [ ] SPEC-025 export/erasure/summary/inventory and SPEC-026 governance pass.
- [ ] Migration 0018 lifecycle, downgrade guard, and exactly one head pass.
- [ ] Dedicated/general/affected validators pass or Docker-only proof is
  precisely separated.
- [ ] Independent audit has no repository-owned Critical or High issue.
- [ ] Final handoff and completed plan reflect observed evidence.

Design status: **APPROVED DESIGN**.
