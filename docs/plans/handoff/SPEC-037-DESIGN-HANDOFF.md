# SPEC-037 Design Handoff

Status: APPROVED DESIGN

## Deterministic eligibility and mapping

A pure application policy accepts immutable facts and returns either
`ReactionKind.THUMBS_UP`, `ReactionKind.HEART`, or explicit `NONE`. It has no
network, provider, database, random, or time dependency. It rejects every
platform except Telegram, every trigger except addressed, non-incoming or
non-user work, commands/regeneration/proactive work, media, unavailable or
redacted content, inactive authority, and input over 64 code points.

After NFKC/casefold/whitespace normalization and bounded terminal-punctuation
removal, exact full-message matches map `thanks`, `thank you`, `cảm ơn`,
`cám ơn`, and `❤️` to `HEART`; `ok`, `okay`, `got it`, `understood`,
`sounds good`, `được`, `hiểu rồi`, and `👍` to `THUMBS_UP`. No other string or
custom emoji can cross the typed boundary.

## Authority model

The response-planning worker reaches reaction consideration only after the
existing addressed participation and pre-generation safety path. A dedicated
SQLAlchemy reader then revalidates current state in one short session:

- the terminal planning job is an ordinary, non-regeneration addressed job;
- the source message is the job's exact incoming unredacted text message;
- its participant is current, unredacted, and not a bot;
- the conversation, connection, Assistant, and tenant form the canonical
  active authority chain and permit external I/O;
- the connection is Telegram and the exact chat/message identifiers are valid;
- no Telegram command job owns the source message.

It returns a minimal typed target only after the pure policy selects an
allowlisted kind. Foreign, disabled, retired, paused where applicable,
contradictory, erased, redacted, edited/control, or unknown state fails closed.
The session exits before any adapter call.

## Timing, safety, and response independence

Reaction consideration is admitted only after pre-generation safety allows
ordinary participation. After the planning job is durably terminal,
post-generation safety is recorded and current authority is re-read; that read
assembles the pure decision facts. A model safety refusal suppresses reaction;
ordinary non-safety provider failure does not influence the acknowledgement
decision. On successful planning, response plan/outbound work is already
durable and independently claimable before cosmetic I/O starts.

Reaction success or any typed Telegram failure cannot change provider attempts,
response plans, outbound actions, presence, recovery, memory, knowledge,
summaries, or media work. Cancellation and programming defects remain visible;
the integration catches only `PlatformAdapterError`.

## Adapter extension and failure handling

Add `SET_MESSAGE_REACTION`, `ReactionKind`, `SetReactionRequest`, and a narrow
`ReactionAdapter` protocol. `TelegramAdapter.set_reaction` validates a nonempty
chat ID, a positive decimal message ID, and the enum allowlist, then calls the
existing `_request` stack with:

```text
chat_id
message_id
reaction = [{"type": "emoji", "emoji": "👍" | "❤️"}]
is_big = false
```

It requires the Bot API result to be exactly `true`. Existing adapter mapping
classifies 400, 403, 429, 5xx, timeout, network/reset, malformed, and unsupported
responses. Reaction integration records one failure and never retries,
regardless of the category's general retryable flag.

## Rate control, idempotency, and durability

The bound is exactly zero or one attempt for a terminal logical inbound update,
with zero retries. There is no independent rate-limit loop, timer, heartbeat,
or fallback. Existing inbox identity and the single planning-job lineage reject
duplicate update execution; reaction runs only after terminal completion, so a
reclaimed/replayed planning job cannot repeat it.

No reaction decision, attempt, result, or recovery work is durable. No
`outbound_action` represents a reaction and no migration is added. Crash before
the call omits it; ambiguous crash during the call is not recovered.

## Privacy and telemetry

Add only low-cardinality counters for decision (`selected`/`none`), kind
(`thumbs_up`/`heart`/`none`), and delivery (`success`/`failure`) with bounded
platform error class. Do not log or label identifiers, body/caption, prompt,
response, memory, knowledge, or secrets. Exact-match input remains in the
already-authoritative current message and is never copied into reaction state.

## Loop prevention and feature interactions

`message_reaction` and `message_reaction_count` remain absent from
`allowed_updates` and `SUPPORTED_UPDATE_TYPES`. Parser and durable-ingress tests
must prove either update is rejected as unsupported with no downstream outbox,
message, command, planning, or reaction work.

Ambient, proactive/scheduled, deterministic command, and `/regenerate` paths
cannot reach reaction integration. Presence remains bound to admitted provider
I/O. Reaction never targets reply/thread IDs, outbound chunks, edit targets, or
regeneration lineage. Media always selects none, proving zero extra downloads,
transcription, and vision/provider calls.

## Testing and SPEC-032 expansion

Unit tests cover normalization/mapping, every NONE boundary, enum-only
allowlisting, exact adapter payload, result validation, every specified failure
class, one call/no retry, update filtering, and telemetry label safety.

Live PostgreSQL integration tests cover the actual response worker and
authority reader; active success; disabled Assistant and connection; foreign
tenant/Assistant/conversation; redacted/erased target; duplicate replay; zero
checked-out sessions at raw I/O; response persistence despite every reaction
failure; zero durable reaction actions; and zero memory, semantic-index,
knowledge, summary, and extra media operations.

Add 12 deterministic evaluation scenarios for eligible acknowledgement,
substantive question, ambient, proactive, command, regeneration, disabled
authority, foreign scope, API failure/response continuation, duplicate update,
reaction update loop prevention, and zero provider calls caused by reaction.
New hard gates expose reaction allowed/kind/attempts/retries, provider calls from
reaction, response continuation, forbidden-flow reaction, and loop creation.
Expected fixture answers are literal and a mutation test must fail at least the
reaction decision/kind gates.

## Validation and deferred debt

The dedicated executable validator uses canonical `resolve-uv.sh`, isolated
ports for live PostgreSQL, no `.env` or credentials, and works from a VCS-free
tracked-plus-untracked candidate. It is wired normally into Quality CI. Run the
complete SPEC-037 matrix plus `git diff --check`, mode, Alembic, privacy, and
integrity checks.

The reliability validator remains diagnostic. Only the exact six historical
`ForeignKeyViolationError` failures for `fk_assistants_tenant` and missing
tenant `00000000-0000-4000-8000-000000000030` are accepted as Product Owner-
deferred debt. They may not be skipped, masked, weakened, or repaired here.
