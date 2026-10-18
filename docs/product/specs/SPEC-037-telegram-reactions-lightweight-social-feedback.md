# SPEC-037 — Telegram reactions and lightweight social feedback

Status: APPROVED PRODUCT SPEC

## Outcome

January may place one optional Telegram reaction on a narrow class of current,
authoritative, user-authored acknowledgement messages. The reaction is a
deterministic cosmetic signal. It is not conversation content, a response
authorization, model context, memory, knowledge, or a durable outbound action.

## Eligibility

A reaction is eligible only when every condition below is true:

- the platform is Telegram and Telegram is enabled;
- the source is the current canonical incoming message for an active tenant,
  Assistant, platform connection, and conversation;
- the author is a current non-bot participant and neither participant nor
  message has been erased or redacted;
- the message has a valid Telegram chat ID and positive integer message ID;
- the participation trigger is `addressed`;
- the message is ordinary text, not photo, voice, audio, sticker, or another
  media/control type;
- the message did not enter deterministic command or proactive scheduling work;
- the planning job is not regeneration work and has no command source;
- current pre-generation safety allowed ordinary participation;
- the bounded text rule selects one allowlisted reaction; and
- authority is revalidated immediately before external I/O.

Ambient remain-silent and unsolicited ambient work, every deterministic
command including `/regenerate`, proactive/scheduled work, edited or redacted
targets, assistant-authored messages, and foreign/unknown targets always select
`NONE`. Media and captions select `NONE`; reaction logic performs no download,
transcription, vision, or provider work.

## Allowlist and mapping

The complete v1 allowlist is:

- `thumbs_up`, serialized only as standard emoji `👍`;
- `heart`, serialized only as standard emoji `❤️`.

The policy first rejects missing text and text longer than 64 Unicode code
points. It then applies Unicode NFKC normalization, case folding, trims outer
whitespace, collapses internal whitespace, and removes only trailing ASCII
`.`, `!`, or `?` characters plus surrounding whitespace. It performs one exact
full-message match:

- `heart`: `thanks`, `thank you`, `cảm ơn`, `cám ơn`, `❤️`;
- `thumbs_up`: `ok`, `okay`, `got it`, `understood`, `sounds good`, `được`,
  `hiểu rồi`, `👍`.

All other input maps to explicit `NONE`. The rule does not score sentiment,
infer emotion or sensitive traits, inspect model output, use randomness, read
the clock, or accept dynamic Unicode/custom emoji.

## Timing and response independence

Reaction consideration becomes eligible only after canonical addressed
participation and pre-generation safety allow are known. The exact decision is
evaluated from current authority after planning reaches a terminal state.
Provider routing and generation continue under their existing policy and do not
consume reaction state.

The one raw reaction call may occur only after the planning job has reached a
terminal durable state. Therefore any normal response plan and outbound action
already exist and can be claimed independently; reaction latency or failure
cannot delay, suppress, delete, or alter them. A non-safety provider failure
does not revoke an otherwise eligible acknowledgement. A model safety refusal
does revoke it, avoiding a misleading positive signal. Reaction outcome never
changes provider attempts, response plans, outbound actions, presence, or
recovery decisions.

## Authority and privacy

Immediately before I/O, a short PostgreSQL session revalidates the planning
job, message, participant, conversation, connection, Assistant, and tenant.
The chain must retain matching tenant/Assistant/connection/conversation
identity and active external-I/O authority. The target must still be an
unredacted incoming user message with its original platform message ID. The
session closes before `setMessageReaction`; no transaction, lock, or checked-out
connection crosses external I/O.

No additional message content is persisted. Metrics and logs may contain only
bounded decision, reaction-kind, delivery-outcome, and platform-error-class
values. They must not contain body/caption, prompt/response, token, chat/user/
message IDs, or tenant/Assistant/conversation/connection IDs.

## Telegram delivery and bounds

`setMessageReaction` uses the existing Telegram adapter, HTTP client, base URL,
token handling, timeout, and error parser. The payload contains exactly
`chat_id`, `message_id`, one `ReactionTypeEmoji`, and `is_big: false`. It does
not transfer reply targets, thread IDs, regeneration targets, or outbound
message IDs.

There is at most one raw attempt per logical inbound update and no retry,
heartbeat, refresh, or fallback text for reaction delivery. HTTP 400, 403, 429,
5xx, timeout, connection reset/network failure, false/malformed responses, and
unsupported responses produce one bounded operational failure and no cosmetic
retry. Only the typed Telegram adapter failure family is contained at the
reaction boundary; programming/cancellation failures are not broadly swallowed.

## Idempotency, durability, and recovery

The durable inbox and conversation processor create at most one planning job
for one logical Telegram update. A reaction attempt happens only after that job
is terminal, and terminal planning jobs are not reclaimed. Replaying the same
update therefore creates no additional raw reaction call.

Reaction decisions, attempts, and results are not persisted and never become
`outbound_actions`. A crash before the call may omit the reaction. A crash or
disconnect during the call may make its visible result unknowable, but restart
does not retry it. This intentional at-most-once execution bias is preferable
to stale or duplicate cosmetic reactions.

## Loop prevention and interactions

Polling/webhook `allowed_updates` remains limited to ordinary message and
membership types; `message_reaction` and `message_reaction_count` are not
requested. If either nevertheless reaches ingress, it is an unsupported update
that creates no message, planning job, command job, outbound action, or
reaction. Telegram also documents that reactions set by bots do not generate
`message_reaction` updates.

Typing presence remains solely provider-I/O feedback; reactions neither start
nor extend a typing loop. Regeneration commands and regenerated edit/fallback
actions produce no reaction. Reaction targets are always the incoming user
message, never a reply, split-chunk, edit, or regeneration presentation target.

## Persistence and migration

Migration: NONE. There is no reaction table, history, attempt, preference, or
recovery record. Alembic remains `0024_telegram_response_regeneration`.

## Acceptance

Acceptance requires all 32 mandatory SPEC-037 proofs, 12 independent
deterministic SPEC-032 scenarios with mutation proof, the dedicated clean-
candidate validator, the full required validator matrix, no Critical or High
findings, and no new failures outside the exact six deferred historical
reliability failures.

Reference: [Telegram Bot API](https://core.telegram.org/bots/api), especially
`setMessageReaction`, `ReactionTypeEmoji`, `Update`, and `setWebhook`.
