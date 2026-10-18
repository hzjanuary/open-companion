# SPEC-036 — Telegram response editing and regeneration

Status: APPROVED PRODUCT SPEC

## Outcome

January supports one explicit Telegram interaction: a user replies to an
authoritative delivered assistant response with `/regenerate`. January answers
the original triggering user turn again using current policy and current
eligible context. A regenerated answer is a new immutable response in
PostgreSQL even when Telegram presents it by editing an existing message.

## User contract

- `/regenerate` accepts no arguments and is valid only as a reply.
- There is no “most recent response,” quoted-text, or fuzzy target fallback.
- A successful command starts generation without explanatory command chatter.
- Unknown, erased, foreign, incomplete, or unsupported targets fail closed with
  a deterministic command reply.
- At most three regenerations are accepted for one root response chain. Every
  descendant shares that root count; a fourth request is rejected before model
  I/O.

## Authoritative target

The reply hint is resolved through local PostgreSQL state. The command message,
reply target, delivered outbound action, response plan, planning job, original
source message, conversation, platform connection, Assistant, and tenant must
form one active authority chain. Telegram quoted text is never authority.

Replying to any delivered chunk of a split response targets the entire logical
response plan. Only provider-backed planning responses are eligible; command
and scheduled responses are not. A target with ambiguous presentation state or
redacted source/response content is rejected. Foreign tenant, Assistant,
connection, or conversation identity is rejected before provider or outbound
I/O.

When a Telegram message has been edited successfully by an earlier
regeneration, the newest certain edit action is its current logical response.
An uncertain edit makes that Telegram message ineligible until existing
recovery handling resolves it.

## Context and policy

The new planning job keeps the root planning job's original triggering user
message as its current user turn. `/regenerate` is control input and is excluded
from prompt history. The normal planning/prompt pipeline rebuilds relevant
history and applies the current:

- tenant, Assistant, connection, conversation, and safety authority;
- conversation configuration and personality;
- memory recall policy and eligible non-erased memory;
- enabled knowledge bases/documents and fresh retrieval validation;
- provider routing, admission, budget, rate, concurrency, and usage policy.

No serialized old prompt, retrieved passage, provider admission, or assistant
answer is replayed as authority. Deleted/disabled memory and knowledge cannot be
restored from old plans, summaries, attempts, quoted Telegram payloads, or stale
vector results. Newly eligible memory/knowledge may participate under current
policy. Regeneration itself writes neither memory nor knowledge. Existing media
metadata/derived content may be reused under its current retention and privacy
rules; raw erased media is never recovered or downloaded merely to regenerate.

Historical summaries are not rewritten retroactively. Existing future summary
jobs continue to use the repository's authoritative conversation rules.

## Immutable lineage and cost

Every accepted operation creates one fresh response-planning job linked to:

- the command job;
- the root response plan;
- the immediate parent response plan;
- a root-chain ordinal from 1 through 3.

The original response plan and all generation attempts remain immutable. The
new work goes through the existing governed provider pipeline and produces new
attempt/usage records. Duplicate processing of one command creates at most one
planning job. A database lock on the root plan serializes distinct concurrent
commands at the chain limit.

## Presentation policy

A single application policy chooses `EDIT_EXISTING` only when all of these are
authoritatively true:

- the parent has exactly one certain delivered visible text message and no
  delivered sticker or split presentation;
- the message belongs to the current Telegram connection/conversation and has
  an exact platform message ID;
- the target and payload are not redacted;
- no prior edit attempt for that message has an ambiguous outcome;
- the regenerated result is one non-sticker text chunk within the repository's
  Telegram-safe limit;
- no deterministically known platform constraint makes it uneditable.

Otherwise the result is delivered as a new SPEC-034 ordered response sequence,
replying to the original triggering user message where normal reply policy
allows. Old responses are not deleted. Split old responses are never edited in
place; split regenerated results are always fresh ordered sends.

The Bot API's 48-hour restriction applies to specified business messages not
sent by the bot, not ordinary bot-authored messages. This product supports only
locally recorded bot-authored outbound targets, so it adds no artificial age
cutoff. Telegram remains free to reject an edit; the result classification
below is authoritative for fallback.

## Durable edit and fallback

An eligible regeneration compiles two durable actions: one `EDIT_TEXT` action
and one initially blocked `SEND_TEXT` fallback. They are one mutually exclusive
presentation path.

- Confirmed edit: edit is delivered and fallback is terminally skipped.
- Exact `message is not modified`: terminal edit success; no fallback send.
- Exact rejected/non-applied edit (`message to edit not found`, `message can't
  be edited`, or `there is no text in the message to edit`): the edit becomes
  skipped and the blocked fallback becomes pending in one database transaction.
- Timeout, connection reset/network ambiguity, malformed response after I/O, or
  HTTP/server 5xx: edit becomes delivery-unknown and fallback stays blocked.
- Generic HTTP 400 is not a fallback class.

The normal delivery worker performs both edit and fallback work. It holds no
database transaction/session across `editMessageText`, fallback `sendMessage`,
or provider generation. Lease expiry after external I/O is delivery-unknown.
Recovery uses the existing quarantine/operator process; automatic duplicate
presentation is forbidden.

On confirmed edit, the local Telegram message presentation is updated while
the old response plan remains unchanged. Future replies to that platform
message resolve through the newest certain edit action. The exact target
platform message ID is persisted on the edit action.

## Presence, privacy, and observability

Regeneration is addressed provider-backed work, so SPEC-035 typing presence is
reused. It starts only at admitted provider I/O and stops before durable edit or
send delivery. Presence failure never changes correctness.

Metrics use only low-cardinality outcomes such as requested, accepted/denied,
limit, presentation mode, edit result, and fallback result. IDs, prompt/response
content, memory, and knowledge text are forbidden in metric labels and logs.

## Acceptance

Acceptance requires the 31 proofs in the SPEC-036 handoff, 14 deterministic
SPEC-032 scenarios with zero network/credentials, executable dedicated
validation, migration lifecycle coverage, no Critical/High findings, and no new
regression outside the exact deferred six-failure global reliability debt.

References: [Telegram Bot API](https://core.telegram.org/bots/api), especially
“Making requests” and `editMessageText`.
