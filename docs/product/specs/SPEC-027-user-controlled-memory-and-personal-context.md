# SPEC-027 User-Controlled Memory and Personal Context

## Status

Product Owner approved on 2026-09-04 as the authoritative product contract for
SPEC-027. Design and implementation are authorized within this specification.
Production rollout remains an operating-owner decision. No legal/privacy
certification is claimed.

SPEC-026 is the completed predecessor. SPEC-014 remains deferred on its
external Zalo prerequisite. SPEC-027 does not begin or define SPEC-028.

## Purpose

Evolve Lumi's existing explicit, same-conversation memory into a transparent
user-controlled capability in which a user can see, create, correct, pause,
resume, and delete what Lumi remembers without automatic biography building,
hidden inferred traits, or new cross-conversation identity linkage.

The governing principle is:

> The user can see, control, correct, disable, and delete what Lumi remembers.

## Product Problem

SPEC-011 permits only explicit `/memory remember` records and provides listing
and deletion, while SPEC-019 adds optional semantic selection over that exact
corpus. The current product still lacks:

- an explicit creator-owned personal-context type distinct from shared
  conversation facts;
- an optimistic correction contract;
- a subject-controlled recall pause;
- one deterministic command-idempotency contract for every memory mutation;
- precise conflict and current-turn precedence rules; and
- an integrated SPEC-025 export, erasure, transparency, and inventory contract
  for the new state.

The repository's `Participant` identity is scoped to one conversation. Although
SPEC-025 erasure can match a platform user across conversations on one
PlatformConnection, that cleanup mechanism is not a durable identity assertion
for contextual reuse. SPEC-027 therefore cannot safely introduce
cross-conversation personal context.

## Goals

- Keep all durable memory explicitly user-created and inspectable.
- Add bounded personal context without creating a hidden profile.
- Let the record owner correct content with deterministic conflict detection.
- Let a participant pause and resume memory recall in the exact conversation.
- Make PostgreSQL authority and derived-index invalidation immediate.
- Preserve bounded context, current-turn precedence, safety, provider budgets,
  rate limits, concurrency, privacy, and content-safe observability.
- Integrate every new durable record with SPEC-025 export, erasure, retention,
  transparency, and backup limitations.

## Explicit Non-Goals

- Automatic memory extraction from messages, summaries, assistant responses,
  provider output, or observed behavior.
- Model-generated profiles, inferred traits, sensitive-trait classification,
  relationship scoring, biography construction, or hidden memory.
- Cross-conversation, cross-Assistant, cross-PlatformConnection, cross-platform,
  cross-tenant, or global-human identity linkage.
- Group-private personal context: Telegram group command replies are visible to
  the group, so creator-private personal context is supported only in a private
  conversation.
- Semantic indexing of personal-context records.
- A new memory service, second memory store, vector authority, or automatic
  conflict-resolution model.
- Tenant/group administrators inspecting or editing private personal context.
- A new control-plane memory browser or administrator API.
- Retraction of already-delivered Telegram messages, completed/in-flight
  provider calls, provider/platform copies, or backups outside the documented
  operating-owner policy.
- New providers, processors, billing, proactive messaging, scheduled social
  participation, rich media/voice, multi-assistant tenancy, Zalo runtime, or
  SPEC-028 behavior.

## User Stories

1. As a user, I can list the durable memory visible to me and see whether recall
   is enabled in this conversation.
2. As a user, I can explicitly save a shared conversation fact using the
   existing command and create bounded personal context in a private chat.
3. As a record owner, I can correct a record against the revision I inspected,
   and a concurrent change produces a conflict rather than silently losing an
   edit.
4. As a user, I can delete one owned record or clear all records I own in the
   exact conversation.
5. As a user, I can pause recall without deleting data and later restore only
   records that remain active.
6. As a group member, another participant or group administrator cannot inspect
   creator-private personal context.
7. As a data subject, my export, erasure, and data summary accurately include
   the new memory and recall state.

## Terminology

- **Conversation history:** retained raw messages in one conversation/thread;
  it is not durable memory and remains subject to raw-content retention.
- **Conversation summary:** short-lived derived history under SPEC-018; it is
  not memory and never becomes semantic-memory input.
- **Explicit memory:** a user-commanded fact stored in `memory_items`, scoped to
  one Assistant, PlatformConnection, and conversation. Group explicit memory
  is shared within that exact group as established by SPEC-011.
- **Personal context:** a creator-private, explicitly supplied, typed preference
  stored through the same memory architecture. It is supported only in a
  private conversation and is never semantically indexed.
- **Semantic derived index:** optional Qdrant vectors for active explicit
  memory only. It contains opaque IDs/scope metadata and is never authoritative.
- **Current-turn instruction:** the current incoming user's explicit text for
  this interaction. It is not persisted as memory merely because it conflicts
  with or adds to remembered context.
- **Record owner:** the exact conversation participant who explicitly created
  the memory/personal-context record.
- **Recall policy:** a participant-owned, exact-conversation enable/disable
  setting controlling whether memory may be injected.
- **Revision:** a positive monotonic record or recall-policy version used for
  optimistic concurrency.

## Scope Model

### Supported identity boundary

Every new memory operation binds all of:

- `assistant_id`;
- `platform_connection_id`;
- `conversation_id`; and
- `participant_id`.

The participant must belong to that conversation; the conversation must belong
to that PlatformConnection; and the connection must belong to that Assistant.
Failure to prove the complete chain fails closed.

### Explicit-memory scope

Existing explicit facts retain their SPEC-011 scope:

- private conversation: same private conversation only;
- group conversation: shared same-group conversation only.

No record crosses a conversation or connection.

### Personal-context scope

Personal context is supported only for the record owner in an exact private
conversation. It must not be created, listed, injected, or edited as personal
context in a group. It never follows the same platform user into another
conversation.

### Recall-policy scope

Recall policy is owned by one participant in one exact conversation. When that
participant disables recall:

- none of that participant's owned memory may enter any response context in
  that conversation;
- when the current message is from that participant, no memory or personal
  context may enter that response context at all; and
- semantic retrieval must not bypass either rule.

Other participants cannot change this setting. Group administrators do not
inherit that authority.

## Memory Ownership

- The creator owns an explicit-memory record for inspection, correction,
  deletion, export, and recall-disable purposes.
- An active group explicit fact remains visible as shared group context and can
  still be deleted by a freshly verified Telegram group owner/administrator or
  cleared through the existing group reset contract.
- Only the creator may edit a record. Group administration never authorizes an
  edit because changing another person's words would falsify provenance.
- Personal context is creator-private. No group or tenant role grants read,
  edit, or delete access.
- PostgreSQL owns canonical content, ownership, status, revision, and recall
  state.

## Personal Context Model

Personal context is a bounded subtype of the existing memory item. Each active
record has exactly one closed key:

- `preferred_name`;
- `preferred_language`;
- `response_preference`;
- `accessibility_preference`; or
- `personal_note`.

Values are normalized explicit user input, contain 1–300 characters, and are
never inferred or expanded by a model. At most one active record per key may
exist for an owner in the exact private conversation. The database and
repository reject duplicates deterministically.

`personal_note` is a user-authored contextual note, not permission to infer or
classify traits. The system does not assert that user-supplied content is true.

## User Controls

SPEC-027 extends the existing `/memory` namespace:

```text
/memory
/memory list
/memory remember <fact>
/memory context add <key> <value>
/memory update <public-id> <expected-revision> <content>
/memory delete <public-id> <expected-revision>
/memory clear_mine confirm
/memory recall status
/memory recall off
/memory recall on
/memory reset_group confirm
/forget <public-id>
/forget_me
/forget_me confirm
```

Rules:

- `/memory` and `/memory recall status` show bounded counts, supported scope,
  and current recall state.
- `/memory list` shows shared explicit memory visible in the exact conversation
  and the caller's personal context only in a private conversation. It never
  shows another owner's personal context.
- `/memory context add` is private-conversation only and rejects an already
  active key with a deterministic conflict response.
- `/memory update` requires ownership and the inspected positive revision.
- `/memory delete` requires ownership and the inspected revision.
- Existing `/forget` remains backward-compatible: creators may delete their
  record; a freshly authorized group administrator may delete a shared group
  explicit fact. It can never target personal context.
- `/memory clear_mine confirm` deletes all active records owned by the caller in
  the exact conversation. It does not change the caller's recall policy.
- `/memory recall off|on` updates only the caller's exact-conversation policy.
- `/memory reset_group confirm` retains its fresh Telegram administrator
  authorization and clears shared group explicit facts, not personal context or
  another participant's recall policy.
- All commands are deterministically parsed and executed without an LLM.

## Conflict Semantics

The precedence order for model context is:

1. system, safety, privacy, authorization, and action policy;
2. the current-turn explicit user instruction;
3. active personal context for that current user;
4. active explicit memories, with deterministic ordering for the selected
   retrieval mode;
5. recent conversation history; and
6. historical conversation summary.

Stored content is untrusted context and cannot alter higher-level policy.
Current-turn instructions always outrank stale memory and do not silently
mutate it.

One active personal-context record per key removes same-key ambiguity. An
update increments the record revision. An update/delete whose expected revision
is stale returns `conflict` and changes nothing. Concurrent delete versus update
is serialized: if delete wins, update reports missing/deleted; if update wins,
a delete using the older revision reports conflict. Existing `/forget` is a
delete-wins compatibility operation under a row lock.

Explicit facts are not semantically classified into attributes. If separate
facts appear contradictory, both remain inspectable. Deterministic fallback
orders newest updates first; optional semantic retrieval orders by score with a
stable tie-break. In either mode the current turn wins. The system does not use
an LLM to merge or silently rewrite them.

## Recall Semantics

- Recall defaults to enabled for existing participants to preserve behavior.
- Recall is checked from PostgreSQL before deterministic selection and again in
  PostgreSQL semantic revalidation.
- A disabled current participant receives no injected memory/context.
- A disabled record owner's explicit facts are excluded from context for other
  participants too.
- Personal context enters only responses to its owner in the exact private
  conversation.
- Re-enabling recall restores only still-active, unexpired, non-erased records.
- Recall pause never reverses deletion or erasure.
- PostgreSQL/recall lookup failure fails closed by omitting memory. Semantic,
  embedding, or Qdrant failure uses the existing safe deterministic fallback,
  still filtered by current recall authority.
- At most 5 personal-context items and 10 explicit-memory items are candidates.
  Personal context consumes at most 600 characters, and the combined injected
  personal-context plus explicit-memory content consumes at most 1,200
  characters. Existing overall prompt/context limits remain authoritative.

## Personal Context Injection

Personal context appears in a dedicated, JSON-delimited `personal_context`
field marked as explicit untrusted user data. It is not hidden prompt rewriting.
The deterministic system instruction declares the precedence above. Prompt
construction does not echo or transform personal context into system policy.

## User Transparency

The user-visible status identifies:

- whether recall is enabled;
- count of the caller's active explicit records;
- count of shared explicit records visible in the conversation;
- count of the caller's active personal-context records; and
- the exact commands for inspection, correction, deletion, clear, pause, and
  resume.

Listings include a public ID, kind/key, revision, timestamp, creator label only
for shared explicit memory, and bounded content preview/full command-safe value.
No hidden profile or derived trait surface exists.

## Privacy

- No message, summary, generated response, provider output, or behavior creates
  durable memory automatically.
- Personal context is creator-private and private-conversation only.
- Cross-scope joins fail closed through exact ownership checks.
- PostgreSQL deletion/disable state is authoritative immediately.
- Delete/update/clear/erasure increments the conversation memory/privacy
  revision so planning assembled under stale authority is released before I/O.
- Explicit-memory changes schedule derived UPSERT/DELETE work; Qdrant cannot
  resurrect content because every ID is revalidated in PostgreSQL.
- Personal context never enters Qdrant.
- Qdrant payloads remain vectors plus opaque internal IDs and scope metadata;
  no memory text, preview, personal-context value, raw Telegram ID, or user ID.
- Logs, audits, and metrics remain content-safe. User-visible command responses
  may contain the requesting user's authorized data and remain subject to the
  established raw-content retention policy.

## Sensitive Information

SPEC-027 does not infer, label, rank, or persist sensitive traits. Explicit
user-supplied text follows existing memory validation, safety, privacy, export,
and erasure policies. The closed context key describes intended use, not a
sensitive-trait taxonomy. No administrator gains a sensitive-profile view.

## Data Governance Integration

- **Subject export:** includes the requesting participant's active explicit
  memories, private personal-context records, record revisions/keys, and exact
  recall-policy state within the requested conversation. It excludes other
  participants' personal context.
- **Group export:** may include shared active group explicit facts as before;
  it excludes personal context and participant recall policies.
- **Deployment export:** adds content-free category/volume and retention facts
  only.
- **Erasure:** `/forget_me confirm` clears all owned memory/personal-context
  content across the existing Assistant/PlatformConnection erasure boundary,
  disables surviving recall-policy tombstones, invalidates summaries/export
  packages, increments affected conversation revisions, and schedules semantic
  deletion for explicit memory.
- **Data summary:** states exact-scope counts and recall state without exposing
  other subjects' content.
- **Retention:** active explicit memory/personal context persists until updated,
  deleted, cleared, expired, reset where authorized, or erased. Content-free
  recall/idempotency/audit tombstones persist under the documented
  operating-owner history policy.
- **Audit:** memory events and control-operation results contain only opaque
  references, closed operation/outcome codes, revisions, counts, and timestamps.
- **Backups:** deletion is authoritative in live state; copies predating it
  remain subject to SPEC-025 operating-owner purge/reapply limitations.

## Provider Governance Interaction

Listing, status, create, update, delete, clear, recall enable/disable, and exact
command parsing make no LLM or embedding call. Explicit-memory indexing may
perform an embedding asynchronously through the existing SPEC-026 governed
embedding path. Any generation request containing recalled context still passes
SPEC-026 authorization, budget, rate-limit, concurrency, health, and safety
checks before provider I/O. Fallback cannot bypass recall authority.

## Authorization

- A participant controls only records they own and their own recall policy in
  the exact conversation.
- Any participant may inspect existing shared explicit group facts because that
  is the established SPEC-011 group-memory contract.
- A freshly verified Telegram group owner/administrator may delete/reset shared
  group explicit facts, but cannot inspect private personal context, edit
  another person's record, change recall policy, or clear another person's
  private data.
- Tenant owner/admin/operator/auditor/viewer roles receive no personal-memory
  content access under SPEC-027.
- `deployment_operator` receives no personal-memory content access.
- SPEC-025 subject export/erasure identity and group export/reset authorization
  remain unchanged.

## Idempotency

Every mutating SPEC-027 command uses the durable Telegram command job as its
source identity. Replaying the same command creates at most one record,
revision change, recall-policy revision, event, and derived-index intent and
returns the same bounded result. Database uniqueness must enforce this across
workers and races; application logic must deterministically resolve a
uniqueness race.

## Concurrency

- Create of the same personal-context key is protected by active-key uniqueness.
- Updates and revision-aware deletes lock the exact record and require the
  expected revision.
- Clear operations lock/transition an ordered bounded set and record one
  idempotent outcome.
- Recall updates lock the exact policy row and increment its revision only when
  state changes.
- No database lock/session spans Telegram, provider, embedding, Redis, or
  Qdrant I/O.

## Observability

Emit bounded metrics for `status`, `list`, `create`, `update`, `delete`,
`clear`, `recall_disable`, and `recall_enable` with closed outcome, record kind,
and conversation-type dimensions only where cataloged. Do not emit memory text,
context values, user/participant/conversation/Telegram IDs, memory public IDs,
Qdrant point IDs, prompts, credentials, or other high-cardinality identifiers
as metric labels. Operational logs use only closed codes and opaque internal
work references already allowed by repository policy.

## Functional Requirements

### FR-01 — Explicit-only durable creation

Only deterministic memory commands may create or update durable memory or
personal context. No automatic inference/extraction path exists.

### FR-02 — Exact scope and ownership

Every record and recall policy is authorized against the exact Assistant,
PlatformConnection, conversation, and participant chain. Cross-conversation
and cross-tenant reuse is prohibited.

### FR-03 — Bounded personal context

Private-conversation users can create one active explicit value per approved
personal-context key through the existing memory architecture. Personal
context is creator-private and excluded from semantic indexing.

### FR-04 — Inspect and list

Users receive bounded status/counts and may list only shared explicit memory
visible under SPEC-011 plus their own personal context.

### FR-05 — Correct/update

The owner may update an active record using its public ID and expected revision.
Successful update preserves provenance, increments revision, emits a
content-free event, invalidates stale context, and refreshes derived semantic
state only for explicit memory.

### FR-06 — Delete one

Revision-aware owner deletion physically clears content/hash immediately and
invalidates derived state. Backward-compatible `/forget` remains restricted to
explicit memory and the established creator/group-admin rules.

### FR-07 — Clear owned scope

`/memory clear_mine confirm` idempotently clears the caller's active records in
the exact conversation without clearing another subject or changing recall.

### FR-08 — Recall status/disable/enable

The participant can inspect, disable, and enable exact-conversation recall.
Disable is authoritative before deterministic or semantic context injection;
enable restores only valid active records.

### FR-09 — Deterministic precedence

Current-turn instruction outranks personal context and explicit memory.
Personal context is ordered before shared explicit memory; record order and
revision conflicts are deterministic. Ordinary messages never mutate memory.

### FR-10 — Bounded context injection

Personal and explicit memory enter distinct JSON-delimited untrusted fields
within declared item/character limits. Failed authority lookup omits memory.

### FR-11 — Semantic-index preservation

Only explicit-memory content is embedded. Qdrant remains opaque and derived;
PostgreSQL revalidation checks scope, status, expiry, kind, and recall authority.
Delete/update/clear/erasure schedules correct derived work.

### FR-12 — Command idempotency and concurrency

All mutations are command-idempotent at the database boundary. Optimistic
revision checks prevent silent lost updates and produce deterministic conflicts.

### FR-13 — Data-governance integration

Subject export, erasure, data summary, inventory, retention documentation, and
backup limitations accurately cover personal context and recall state without
cross-subject disclosure.

### FR-14 — Authorization isolation

Group and control-plane administration confers no private personal-context read
or mutation authority. Cross-scope operations fail closed.

### FR-15 — Provider/safety preservation

Memory administration invokes no model. Recalled-context generation and
explicit-memory embedding retain all SPEC-024/026 gates and failure behavior.

### FR-16 — Content-safe observability

Metrics, logs, and audit events use closed bounded metadata and never carry
memory/personal-context content or high-cardinality subject/platform IDs.

## Non-Functional Requirements

### NFR-01 — PostgreSQL authority

Canonical content, ownership, revision, status, and recall policy live in
PostgreSQL. Redis and Qdrant never authorize recall.

### NFR-02 — Privacy by default

Private personal context is deny-by-default, exact-scope, creator-only, and
never semantically indexed.

### NFR-03 — Deterministic and testable

Management behavior requires no live Telegram API except the already-established
fresh group-admin check, no LLM, and no external provider in tests.

### NFR-04 — Bounded

Commands, values, listings, injected items, characters, queries, batches, and
audit metadata have explicit limits and deterministic ordering.

### NFR-05 — Atomic and idempotent

Each mutation, audit/idempotency result, revision increment, privacy revision,
and derived intent commits atomically or not at all.

### NFR-06 — No lock across external I/O

No database lock or session remains open across Telegram, provider, embedding,
Redis, or Qdrant I/O.

### NFR-07 — Fail closed and recoverable

Unknown identity, stale revision, unavailable authority, or recall-state
failure cannot expose memory. Derived cleanup is durable and retryable.

### NFR-08 — Backward compatible

SPEC-011/019 commands, same-conversation shared explicit memory, privacy
redaction, Qdrant opacity/revalidation, and SPEC-025/026 guarantees remain
valid. No exactly-once external-call claim is introduced.

## Acceptance Criteria

1. **AC-01 / FR-01:** searches and tests prove that raw messages, summaries,
   generated responses, and provider output cannot create memory.
2. **AC-02 / FR-02:** exact-scope tests deny foreign conversation, participant,
   Assistant, connection, and tenant combinations.
3. **AC-03 / FR-03:** approved keys create bounded personal context only in a
   private conversation; duplicate active keys and group creation fail.
4. **AC-04 / FR-04:** status/list are bounded and another participant/group or
   tenant administrator cannot view personal context.
5. **AC-05 / FR-05:** owner update increments revision; stale, foreign, deleted,
   and unauthorized updates change nothing; explicit updates schedule UPSERT.
6. **AC-06 / FR-06:** revision-aware deletion clears canonical content/hash and
   schedules explicit-memory DELETE; `/forget` compatibility remains proven.
7. **AC-07 / FR-07:** clear-mine affects only the caller/exact conversation,
   handles more than one record, and replay returns one durable effect.
8. **AC-08 / FR-08:** disable removes all memory from the caller's response and
   removes their owned memory from others' contexts; enable restores only valid
   rows; semantic retrieval cannot bypass it.
9. **AC-09 / FR-09:** prompt tests prove explicit precedence language and stable
   deterministic/semantic ordering; ordinary conflict text does not update
   storage.
10. **AC-10 / FR-10:** item/character bounds and separate untrusted prompt
    fields are exact and deterministic.
11. **AC-11 / FR-11:** only explicit facts are indexed, Qdrant payload remains
    opaque, PostgreSQL revalidation applies recall policy, stale points do not
    resurrect deleted/disabled data, and fallback remains safe.
12. **AC-12 / FR-12:** replay and concurrent create/update/delete tests prove
    database idempotency and optimistic conflicts without lost edits.
13. **AC-13 / FR-13:** subject export includes only authorized personal context
    and recall state; group export excludes both; erasure clears/disables them;
    data summary and inventory are accurate.
14. **AC-14 / FR-14:** group admin, tenant roles, and deployment operator gain no
    private memory inspection or edit capability.
15. **AC-15 / FR-15:** deterministic management uses zero provider calls, while
    generation/embedding integration continues through SPEC-026 governance.
16. **AC-16 / FR-16:** telemetry/audit schema and emitted labels contain no
    prohibited content or identifiers.
17. **AC-17 / NFR-05/06:** integration proof shows atomic mutation and no
    database session/lock across embedding, Qdrant, provider, or Telegram I/O.
18. **AC-18 / NFR-07/08:** migration/recovery/regression proof passes without
    weakening SPEC-001–026 behavior.

## Migration Expectations

Create exactly one additive migration after committed
`0017_provider_routing_cost_budgets`, expected as
`0018_user_controlled_memory`. It must:

- extend memory kind/visibility constraints for creator-private personal
  context;
- add context key and positive revision fields to `memory_items`;
- enforce one active personal-context key per exact owner/conversation;
- add exact participant/conversation recall-policy state with positive revision;
- add a content-free command-operation idempotency ledger;
- add indexes for bounded owner/scope/recall queries;
- preserve legacy explicit-memory rows with revision 1; and
- downgrade safely only when SPEC-027 personal-context/recall/operation state
  cannot be silently lost, following repository migration-guard conventions.

Prove `0017 -> 0018 -> 0017 -> 0018`, exactly one Alembic head, and the
repository-required `base -> head -> base -> head` lifecycle with synthetic data.

## External Decisions

The following remain operating-owner decisions and do not alter repository
mechanism completion:

- production rollout timing and acceptance;
- final content-free memory event/idempotency tombstone retention duration;
- backup retention, purge, and post-restore erasure reconciliation;
- semantic-memory/Qdrant production enablement and infrastructure ownership;
- provider routing/pricing/budget operating values under SPEC-026; and
- legal/privacy/compliance declarations.

## Future Work

Not authorized by SPEC-027:

- verified cross-conversation personal identity and portable personal context;
- cross-platform identity federation;
- additional structured context types or sensitive-data classification;
- end-user web UI, tenant memory administration, or data portability import;
- automatic but user-reviewable memory suggestions;
- semantic indexing of personal context;
- proactive/scheduled interaction, rich media/voice, Zalo runtime, billing, or
  SPEC-028 and later capabilities.

## Product Specification Completion Evidence

This specification derives scope from the committed repository audit:

- `participants` are unique only within a conversation;
- `memory_items` are authoritative, explicit, same-conversation records;
- existing deterministic commands and `memory_privacy_revision` are reusable;
- semantic retrieval filters exact Assistant/connection/conversation and
  revalidates IDs through PostgreSQL;
- delete/reset/erasure already schedule Qdrant cleanup;
- SPEC-025 subject export is participant/conversation scoped; and
- SPEC-026 governs generation and embedding calls independently.

The contract makes no cross-conversation identity claim, adds no automatic
memory path, and contains no unresolved product choice inside the authority
granted for SPEC-027. Status: **APPROVED PRODUCT SPEC**.
