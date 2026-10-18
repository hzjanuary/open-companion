# Telegram Conversation UX — SPEC-034

This runbook covers authoritative direct reply context and durable ordered
delivery of long plain-text Telegram responses. It introduces no live
acceptance operation, formatting mode, or new credential.

## Reply resolution

An inbound `reply_to_message.message_id` is stored as a bounded discovery hint;
the nested Telegram message body is not copied. January resolves at most one
direct target from PostgreSQL and requires the current and target messages to
share the active tenant, Assistant, platform connection and conversation.
Unknown, foreign, inactive, erased, redacted, expired or unavailable targets
produce no reply context and ordinary processing continues without a network
lookup.

The prompt receives a typed `reply_reference` after higher-authority/current
turn budgeting. It is capped at 1,200 Unicode code points and is explicitly
untrusted conversational reference—not system/operator policy, safety,
personality, memory or knowledge. The current user message remains the request.
If the target is already in recent history, that copy is removed. Replying to a
known assistant chunk resolves the bounded non-redacted logical response plan
once and removes its delivered chunk messages from history.

Reply resolution never fetches Telegram history or media, creates memory or
knowledge rows, reconstructs old knowledge provenance, or downloads media.
Retention/redaction remains authoritative even when relationship IDs survive.

## Direct replies and long responses

Private direct interactions, explicit group replies and direct commands use the
canonical triggering inbound Telegram message as the reply target when its
platform ID exists. Ambient participation and proactive scheduling remain
replyless. Only the first visible action carries reply and mention metadata; a
sticker-only direct response may carry it.

The adapter remains plain text. Accepted logical text is at most 13,600 UTF-16
code units. The pure splitter emits at most four chunks of 3,400 units, choosing
the last paragraph, newline, whitespace, then grapheme-safe hard boundary.
Concatenation exactly restores the input. Oversize text fails planning closed;
it is not truncated, summarized, partially persisted or regenerated.

The response-plan ID is the sequence identity. All text chunks and an optional
final sticker (five total actions maximum) are inserted in one transaction with
immutable one-based ordinals and exact counts. Reprocessing uses existing
idempotency and cannot create a second sequence.

## Ordering, fallback and recovery

An action is claimable only when every lower ordinal in its response plan is
`delivered`. Pending, leased, retryable, failed, skipped and
`delivery_unknown` predecessors block the tail. Plans remain independent; no
conversation-wide lock spans Telegram I/O. Claim/load, external-start and
finalization use short database scopes, and Telegram requests run with no
checked-out database session.

The first direct send sets `allow_sending_without_reply=false`. One immediate
replyless request is allowed only for HTTP 400 with a code-owned exact Telegram
missing-reply description. The attempt ledger records that fallback without
content or identifiers. Never fallback on timeouts, resets, 429, 5xx, malformed
responses, other 4xx or any uncertain result.

If an early chunk is delivered and a later one is retryable, recover the later
action only; do not regenerate or resend the successful prefix. An ambiguous
action becomes `delivery_unknown`, blocks its tail and follows the existing
possible-duplicate recovery policy. Exactly-once external delivery is not
claimed.

## Validation

Run the strict isolated validator from the repository root:

```bash
JANUARY_DB_HOST_PORT=5448 ./scripts/validate-telegram-conversation-ux.sh
```

It uses no real Telegram/provider credential. It proves a tracked+untracked
clean export, offline SPEC-032 scenarios, lint/type checks, 0022↔0023 and
base→head migration lifecycles, live PostgreSQL authority/constraints and
adjacent claims, fake-Telegram fallback/ambiguity behavior, session fencing,
and populated downgrade refusal. The validator owns and removes only its
`january-spec034-validation` Compose project.

Migration downgrade to 0022 is safe only with no reply platform hints,
multi-action sequence state or reply-fallback audit state. Populated state is
refused with `SPEC-034 reply or ordered delivery state blocks downgrade`.
Prefer a compatible image/configuration rollback and preserve schema 0023.

## Known limitations

SPEC-034 itself does not recursively expand reply ancestry, fetch arbitrary
Telegram history, serialize reply trees, preserve Markdown/HTML fragments,
stream edits, emit reactions, or support cross-chat replies. Native bounded
typing presence is the separate SPEC-035 behavior documented in
[`telegram-presence.md`](telegram-presence.md); it does not alter ordered
delivery. Explicit response retry/edit presentation is the separate SPEC-036
behavior documented in [`telegram-regeneration.md`](telegram-regeneration.md).
Lightweight reactions are the separate non-durable SPEC-037 behavior documented
in [`telegram-reactions.md`](telegram-reactions.md); they target only the
incoming user message and never enter the ordered outbound sequence.
Explicit `/voice` is the separate SPEC-038 behavior documented in
[`telegram-voice-tts.md`](telegram-voice-tts.md); any delivered text chunk
resolves to this response plan's whole authoritative text, while voice delivery
itself remains one independent 1/1 outbound action.
Explicit `/feedback helpful|unhelpful` is the separate SPEC-039 behavior in
[`conversation-feedback.md`](conversation-feedback.md); it uses the same local
reply/plan authority but never adds conversational context or provider work.
Zalo remains out of scope.
