# SPEC-034 — Telegram Reply Context and Ordered Delivery

Status: **APPROVED PRODUCT SPEC**. The Product Owner's SPEC-034 request is the
authority for this bounded Telegram-first work. Global Quality CI remediation
is explicitly deferred and is not part of this specification.

## Purpose

Make Telegram replies conversationally meaningful when their target is locally
authoritative, and deliver a long generated response as a deterministic,
durable, ordered sequence without regenerating or silently discarding content.

## Existing-system audit

The Telegram normalizer already exposes the nested target message ID without
copying nested text. Messages already have a local reply edge and outgoing
messages link to outbound actions and response plans. Response plans already
compile to atomically persisted actions with a stable plan identity and ordinal.
Delivery already separates database scopes from Telegram I/O and quarantines
ambiguous post-request outcomes. Missing behavior is durable unresolved target
metadata, strict same-authority resolution, one typed direct-reference context,
long-text compilation, exact total count, strict predecessor success, and exact
missing-reply fallback classification.

## Goals and non-goals

Goals are authoritative direct reply context, correct direct-response reply
metadata, deterministic long-message splitting, atomic/idempotent sequences,
strict per-sequence ordering, safe retry/recovery, and content-safe evidence.

Not included: reply-tree UI, recursive ancestry, cross-chat lookup, Telegram
history fetch, rich Markdown/HTML splitting, edit streaming, placeholders,
typing heartbeat, reactions, TTS, voice output, Mini Apps, new keyboard UX,
generic adapter redesign, automatic regeneration, WhatsApp, Zalo, or SPEC-035.

## Reply relationship and authority

For an inbound Telegram message, persist the bounded target platform message ID
(`VARCHAR(255)`) as a discovery hint. If the target is already known, also store
the local message edge. Never persist Telegram's nested replied-message body
merely because it appears in the update and never fetch old Telegram messages to
resolve it.

Resolution begins with the current canonical message and its canonical
conversation. A candidate must be reached through the same platform connection,
conversation, Assistant and tenant; every lifecycle authority must remain
active. The platform ID alone grants no content authority. Unknown, mismatched,
deleted, erased, redacted, expired or unavailable targets resolve to no context
and ordinary processing continues.

Persistent local reply edges use a same-conversation composite foreign key.
Application queries additionally join conversation, platform connection,
Assistant and tenant authority. This is defense in depth and prohibits foreign
tenant, Assistant, connection and conversation injection.

## Reply context semantics and limits

V1 resolves at most one direct target. It never follows the target's own reply
edge. A typed `reply_reference` section carries source role/direction,
provenance, local target ID and bounded text. It is conversational reference,
not system/operator instruction, memory, knowledge, safety policy or personality.
The current message remains the active user request.

Reference text is limited to 1,200 Unicode code points with deterministic
end-truncation. System, safety and personality instructions and the current user
turn are allocated first; reply reference then consumes the ordinary context
budget. If it cannot fit, it is omitted or shortened and can never starve those
higher-authority inputs.

If the target already appears in recent history, its recent-history copy is
removed and the typed reference is retained. For a target that is a delivered
assistant chunk, the action's authoritative, non-redacted response-plan text is
used once and every delivered message from that plan is excluded from recent
history. Replying to any known chunk therefore yields one bounded logical
assistant response, not repeated chunk duplicates. Historical knowledge
provenance is not reconstructed.

## Retention, media, memory and knowledge

The resolver applies existing raw-content age and redaction rules. A surviving
identifier may remain for audit/relationship integrity, but cleared or expired
text never re-enters model context. A media caption or retained transcript may
serve as the existing message text; resolution never downloads media, duplicates
raw media, or creates a media job.

Reply resolution creates no memory, semantic-memory, knowledge, summary or
provider state. Replied content cannot become memory/knowledge automatically,
and old response knowledge does not gain current knowledge authority.

## Outbound reply behavior

- Private direct interaction, explicit group reply and direct command: the
  response targets the triggering canonical inbound message when its Telegram
  platform ID is available.
- Ambient/unprompted participation: no forced reply target.
- Proactive scheduling: no reply target.
- In a multi-action response, only the first visible action carries the reply
  target and mention metadata. Later chunks and stickers do not produce a reply
  notification storm. A sticker-only direct response may carry the target.

Model-selected platform IDs are never authority. Application policy derives the
direct target from the canonical current message.

## Plain-text splitting and limits

The existing adapter remains plain text. The splitter is pure, deterministic,
provider-independent and performs no LLM call. Limits are measured in UTF-16
code units because Telegram's message-entity limit is UTF-16 based:

- maximum rendered text action: 3,400 UTF-16 units before bounded mention
  rendering, safely below Telegram's 4,096-unit text limit;
- maximum logical response: 13,600 UTF-16 units;
- maximum text chunks: four;
- maximum total actions: five, allowing the existing optional sticker.

Text is segmented into extended grapheme-safe units sufficient to keep combining
marks, variation selectors, emoji modifiers, regional-indicator pairs and ZWJ
sequences together. Within the limit, the last available boundary is chosen in
priority order: paragraph, newline, whitespace, then hard grapheme boundary.
Concatenating chunks exactly reconstructs the source; no character is discarded
or inserted. Empty text yields no text action. Oversize output is rejected with
a closed deterministic planning failure; it is never truncated, summarized or
partially persisted.

## Durable sequence and idempotency

The response-plan ID is the logical sequence identity. Each outbound action
stores a one-based ordinal and exact total action count. The existing unique
`(response_plan_id, sequence_number)` and action idempotency keys prevent a
second sequence on reprocessing. Compilation happens inside the existing
response-plan transaction: all expected actions are inserted or none are.

Sequence identity, conversation, ordinal, total count, idempotency key and kind
are immutable after creation. Counts are positive, ordinals are one-based and
never exceed total count. The optional sticker is the final action.

## Delivery order, concurrency and recovery

An action is claimable only if every lower ordinal in its response plan is in
the repository-defined successful terminal state `delivered`. Pending, leased,
retryable, permanently failed, skipped and `delivery_unknown` predecessors all
block the tail. Ordering is scoped to one response plan, not globally or across
unrelated conversations.

Claims and results use short database transactions. No database session,
transaction, advisory lock or connection is held during Telegram HTTP I/O. If
chunk 1 is delivered and chunk 2 fails retryably, recovery retries chunk 2 and
does not recreate/resend chunk 1. Lease expiry before external start may requeue;
expiry after external start remains ambiguous and quarantined. Exactly-once
external delivery is not claimed.

## Deleted reply-target fallback

The first request uses Telegram `reply_parameters` with
`allow_sending_without_reply=false`. One immediate replyless attempt is allowed
only when Telegram returns HTTP 400 and an exact, code-owned missing-reply-target
description proving the request was deterministically rejected before sending.
The attempt ledger records that fallback without content or identifiers.

There is no replyless fallback for rate limits, timeouts, connection resets,
malformed responses, unknown 4xx, 5xx or any ambiguous outcome. Those retain
existing retry/unknown classification to avoid an unsafe second visible send.

## Safety, governance and observability

Existing pre-generation and pre-delivery safety, current tenant/Assistant
lifecycle revalidation, rate limiting, provider governance, memory, knowledge,
retention and recovery remain authoritative. Reply reference text is explicitly
lower privilege than system/safety/application/current-user instructions.

Closed telemetry may record reply-reference present/resolved/unresolved,
split/single, chunk-count bucket, sequence blocked, and fallback
attempted/succeeded/failed. Labels and logs must not contain reply/response text,
platform IDs, conversation/tenant/Assistant IDs, user/chat IDs or credentials.

## Persistence and migration

Migration `0023_telegram_reply_ordered_delivery` adds:

- `messages.reply_to_platform_message_id VARCHAR(255) NULL`;
- same-conversation composite reply foreign keys where the schema carries both
  columns;
- `outbound_actions.sequence_count INTEGER NOT NULL`, backfilled per plan;
- bounded ordinal/count checks and immutable sequence trigger;
- delivery-attempt reply-fallback audit fields.

Downgrade performs one preflight before DDL. It refuses with an exact SPEC-034
message if reply platform hints, multi-action sequence state, or fallback audit
state exists. An empty/single-action state may round-trip 0022→0023→0022→0023.

## Evaluation and acceptance

SPEC-032 gains twelve deterministic hard scenarios: recent-user reply,
assistant reply, unknown target, foreign Assistant, foreign tenant,
erased target, history de-duplication, deterministic long split, order,
tail-blocking, first-chunk direct reply, and ambient/proactive no-reply. They run
offline without Telegram/provider credentials and introduce no soft
`NOT_EVALUATED` result.

Acceptance requires all twenty proofs named in the SPEC-034 execution request,
including real PostgreSQL authority/constraint and adjacent-worker race proof,
fake Telegram exact fallback versus ambiguous no-fallback, session fencing,
zero memory/knowledge/media side effects, migration lifecycle, executable clean
candidate validator, and visible classification of global CI debt.

## Deferred global CI debt

At baseline, `validate-reliability.sh` fails six historical
`test_memory_schema.py` cases with `fk_assistants_tenant` because tenant
`00000000-0000-4000-8000-000000000030` is absent, followed by
`test_persistence.py::test_models_constraints_jsonb_repositories_and_timestamps`
at `database.is_ready()`. This is **KNOWN PRE-EXISTING CI DEBT — DEFERRED BY
PRODUCT OWNER**. SPEC-034 must neither repair nor suppress it. Any different
failure is a SPEC-034 regression and blocks candidate approval.
