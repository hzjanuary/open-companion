# SPEC-034 Design Handoff

Date: 2026-09-13

Status: **APPROVED DESIGN**. Product authority is
`docs/product/specs/SPEC-034-telegram-reply-context-ordered-delivery.md`.

## Current Telegram message model

Normalization already extracts `reply_to_message.message_id` without nested
body persistence. `messages` stores a platform ID, local reply edge and optional
outbound-action link. Outgoing delivered messages link action→response plan.
Response plans compile atomically to actions with a plan ID, ordinal and stable
idempotency key. Sender scopes already close before Telegram I/O.

## Reply authority model and persistence

Persist the inbound platform target as a bounded hint even when the target is
not yet locally resolvable. Keep the local message edge as a convenience backed
by `(reply_to_message_id, conversation_id) -> messages(id, conversation_id)`.
Resolution joins current message→conversation→connection→Assistant→tenant and
requires the target through that exact conversation; infrastructure returns
candidate data but the typed resolver owns visibility/budget policy.

Migration `0023_telegram_reply_ordered_delivery` adds the hint, action
`sequence_count`, attempt fallback fields, composite reply constraints, sequence
checks and an immutable-sequence trigger. Existing action groups are backfilled
with `max(sequence_number)` per response plan. Populated new state causes one
pre-DDL guarded downgrade refusal; safe state round-trips.

## Reply resolution and context representation

`ReplyContextResolver` receives the canonical current context message. It
returns `ContextReply | None`, containing target ID, source role, bounded text,
logical response-plan provenance when applicable, related message IDs for
de-duplication, and a truncation flag. It resolves only one direct edge.

For an incoming/user/media target, canonical retained `messages.text` is used.
For a delivered assistant chunk, the resolver follows its action to the one
non-redacted response plan and uses that logical response once. All delivered
message IDs from that plan are excluded from recent history. Unknown, foreign,
inactive, redacted, privacy-deleted or older-than-retention rows return `None`.
No Telegram/media/provider I/O occurs.

The existing `ConversationContext` gains `reply_reference`; recursive
`reply_chain` construction is retired. Prompt JSON serializes the reference in
its own typed section after current user data and explicitly denies it
system/safety/application/memory/knowledge authority. De-duplication removes
target/related rows from recent history. Current and mandatory system inputs
are budgeted first; reference max is 1,200 code points.

## Outbound reply target and splitter

Addressed planning and direct commands derive the reply target from the
triggering canonical inbound message. Ambient planning and proactive schedules
force `None`. Model-suggested IDs do not choose authority.

`split_telegram_text()` is pure. It counts UTF-16 code units and constructs
grapheme-safe units (combining/variation/modifier/ZWJ/regional-pair handling).
It chooses the last paragraph boundary, else newline, else whitespace, else
hard unit boundary at or below 3,400 units. Concatenation equals input. Logical
limit is 13,600 units/four chunks; excess raises a typed closed error. No parse
mode or formatting subsystem is added.

The compiler emits text chunks followed by any sticker, sets exact total count
on every action, and places reply/mention metadata only on the first visible
action. Existing response-plan transaction and unique keys make creation atomic
and idempotent.

## Durable delivery claim, ordering and concurrency

Claim SQL rejects a candidate when any lower ordinal in the same response plan
is not `delivered`. This covers pending, leased, retryable, failed, skipped and
unknown states. Adjacent workers may race; row locking and the predecessor
predicate allow at most the first eligible action. Plans remain independent and
no conversation/global lock spans I/O.

Claim/load commits, a separate short transaction marks the attempt externally
started, Telegram is called with no checked-out session, and a new transaction
finalizes after lease revalidation. Retryable later chunks keep earlier
delivered chunks terminal; ambiguous predecessors block their tail.

## Telegram adapter and invalid-reply fallback

Adapter text validation uses UTF-16 and retains plain text. `PlatformAdapterError`
adds a closed `reply_target_rejected` signal set only for send operations,
HTTP 400, and an exact allowlist of Telegram missing-reply descriptions. The
worker catches only that signal when a reply was actually supplied, records
fallback on the same durable attempt, and performs one request with reply
metadata suppressed. Timeout/reset/429/5xx/malformed/other 400 never reaches
that branch. Both HTTP calls occur outside DB scopes; any crash after external
start follows existing unknown/quarantine semantics.

## Retry, recovery and immutable sequence

Sequence count, ordinal, plan/conversation identity, idempotency key and kind
cannot change after insert. Before external start an expired lease may requeue;
after start it becomes `delivery_unknown`. A retry resumes the failed action,
not plan generation, so successful prefix actions are never recreated.

## Observability and privacy

Existing closed delivery counters continue to record action outcomes and safe
failure classes. Sequence position/status and exact reply-fallback use are
durable, content-free operational evidence. No new identifier-bearing metric
labels or content logs are introduced, and reply resolution writes no memory,
knowledge, summary or media row.

## SPEC-032 evaluation expansion

Add twelve hard, production-seam synthetic cases required by the Product Spec.
They use no optional judge, provider, network, Telegram token or persistence
credential and therefore add twelve PASS results and no NOT_EVALUATED result to
the canonical baseline when correct.

## Testing strategy

Unit tests cover normalization, typed reply selection, authority/retention,
prompt privilege, de-duplication/budget, splitter edge matrix and repeatability,
compiler metadata/count, exact adapter classification and recovery mapping.

Live PostgreSQL tests create legal and deliberately contradictory tenant,
Assistant, connection and conversation chains; prove erased/unknown handling,
atomic/idempotent sequences, DB constraints, adjacent claim races without
sleep, blocked unknown/failed tails, and lease recovery. Fake Telegram tests
prove exact fallback request ordering, ambiguous no-fallback and zero checked-out
pool connections during both external requests. Migration proof covers
base/head, 0022/0023 and guarded/safe downgrade.

## Known global CI debt

The pre-change `validate-reliability.sh` run has six
`test_memory_schema.py` failures with `fk_assistants_tenant` for missing tenant
`00000000-0000-4000-8000-000000000030`, then the historical persistence
readiness assertion. It is **KNOWN PRE-EXISTING CI DEBT — DEFERRED BY PRODUCT
OWNER**. The strict validator/CI step will not be suppressed; final diagnosis
must show no new failure signature.
