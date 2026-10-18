# Telegram response regeneration

## User operation

Reply to one January assistant message with exactly `/regenerate`. Arguments,
standalone commands, quoted-text guesses, user messages, foreign messages, and
erased or uncertain targets are rejected. Replying to any chunk of a split
answer targets that entire logical answer. There is no automatic regeneration
or “latest answer” fallback.

One root answer accepts at most three regeneration attempts, including attempts
requested by replying to a regenerated descendant. A fourth request fails
before provider I/O. Reprocessing the same Telegram update is idempotent.

## Context and authority

The new plan answers the original triggering user message. The command itself
is excluded from model context. January rebuilds current eligible history,
personality, safety, memory, knowledge, media-derived data, and provider policy;
it does not replay an old prompt or old retrieved text. Disabled/deleted memory
or knowledge cannot reappear from an old plan, summary, provider attempt, or
stale vector result. Regeneration does not itself write memory or knowledge.

Every accepted attempt is a fresh governed provider operation with a durable
command link, root response plan, immediate parent plan, and ordinal 1–3. The
old plan and generation attempts remain immutable.

## Edit versus new response

January edits only a single, certain, locally owned, delivered text message
whose platform ID and content remain available, with no ambiguous earlier edit,
when the replacement is also one Telegram-safe text chunk. Split or sticker
responses, missing IDs, erased content, foreign authority, ambiguous delivery,
or multi-chunk replacement use a new SPEC-034 ordered response. Old visible
answers are not deleted.

An edit is a durable `EDIT_TEXT` outbound action. Its text fallback is persisted
but blocked:

- confirmed edit, or exact `message is not modified`: edit is canonical and the
  fallback is skipped;
- exact `message to edit not found`, `message can't be edited`, or `there is no
  text in the message to edit`: edit is skipped and the fallback becomes pending
  transactionally;
- timeout, reset, malformed post-I/O response, generic 400, or 5xx: edit is
  uncertain and fallback stays blocked.

The worker, not the adapter, later sends an activated fallback. Never manually
send or unblock a fallback after ambiguous delivery: Telegram may already have
applied the edit.

## Recovery and operations

Use the existing outbound recovery inspection for `delivery_unknown` edit work.
Preserve the immutable plan/action audit trail. A populated `0024` downgrade is
intentionally refused with `SPEC-036 regeneration or edit state blocks
downgrade`; prefer a compatible application rollback with schema `0024`.

Typing presence reuses SPEC-035 and stops before durable presentation starts.
Presence failure is cosmetic and does not change regeneration correctness.

## Privacy and observability

Metrics/logs may record only closed outcomes such as requested, accepted,
denied, limit reached, edit/new mode, edit result, and fallback result. Never
label telemetry with tenant, Assistant, connection, conversation, Telegram
message, response-plan IDs, prompts, responses, memory, knowledge, or secrets.

## Validation

Run the isolated no-credential validator:

```bash
JANUARY_DB_HOST_PORT=5452 ./scripts/validate-telegram-regeneration.sh
```

It proves unit/eval behavior, real PostgreSQL authority and races, fresh
provider/edit/fallback I/O with zero checked-out database connections, exact
fallback/ambiguity/not-modified behavior, migration lifecycle and populated
downgrade refusal, executable mode, and a tracked-plus-untracked VCS-free clean
candidate. No Telegram token or provider credential is used.

## Known limitations

V1 has no fuzzy target, response tree/browser, multi-message in-place editing,
automatic retry/self-critique, streaming edits, deletion of old answers,
cross-conversation regeneration, reactions, or Zalo support. Regeneration never
invokes TTS itself; the separate SPEC-038 `/voice` command may target a
delivered regenerated response and synthesizes only that exact plan. See
[`telegram-voice-tts.md`](telegram-voice-tts.md).
The separate SPEC-039 `/feedback helpful|unhelpful` command targets the latest
delivered edit's exact regeneration plan without starting another regeneration;
see [`conversation-feedback.md`](conversation-feedback.md).
