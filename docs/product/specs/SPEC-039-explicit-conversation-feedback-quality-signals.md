# SPEC-039 — Explicit Conversation Feedback and Quality Signals

Date: 2026-09-26

Status: **APPROVED PRODUCT SPEC**. This approval authorizes the bounded
development implementation and validation described here. It is not production
activation and does not close the separately deferred global Quality CI debt.

## Purpose

Lumi users can explicitly record whether one retained assistant response was
helpful or unhelpful. Feedback is durable, privacy-scoped product metadata. It
does not change that response, later prompts, provider behavior, memory,
knowledge, safety, personality, budgets, or offline evaluation truth.

## Entry point and grammar

The only supported forms are `/feedback helpful` and `/feedback unhelpful`.
The command must directly reply to an eligible outgoing assistant message.
There are no aliases, numeric ratings, neutral value, inferred value, or free-
text comment. Missing, unknown, or extra arguments use the ordinary bounded
command-usage response.

An accepted state change receives the code-owned acknowledgement `Feedback
saved.` A same-value repeat receives `Feedback already saved.` Rejected targets
and the revision limit receive short deterministic responses. Acknowledgements
use no model, TTS, typing presence, or reaction.

## Target authority

Resolution uses only local PostgreSQL authority:

```text
leased feedback command
  -> command message.reply_to_message_id
  -> delivered outgoing assistant message
  -> originating or latest delivered edit outbound action
  -> exact response plan
  -> logical assistant response
```

Every edge must remain in the current active tenant, Assistant, Telegram
connection, and conversation. The canonical command participant must belong to
that conversation and must not be privacy-deleted. The target message, action,
and plan must be delivered, retained, non-erased, non-redacted, and free of a
delivery-unknown sibling. Telegram quoted text and remote fetches are never
authority. Command acknowledgement plans and user-authored messages are not
eligible targets.

For a SPEC-034 split response, every delivered chunk resolves to the same
logical response plan, so feedback is plan-level rather than chunk-level. A
SPEC-036 edited/regenerated message resolves to the exact delivered regeneration
plan, not its root or parent.

A delivered SPEC-038 voice presentation may resolve to its exact
`generated_voice_artifacts.source_response_plan_id`. The voice artifact/action
is presentation only and never becomes a separate semantic target; audio
quality is outside v1.

## Values and participant authority

The closed values are `HELPFUL` and `UNHELPFUL`. Each current canonical
Telegram participant owns only their own feedback. Multiple group members may
independently rate the same response. The current-state uniqueness key is:

```text
tenant + Assistant + connection + conversation + response plan + participant
```

No participant may read or mutate another participant's row through this
feature.

## State, history, revisions, and races

PostgreSQL stores one authoritative current row plus immutable state-changing
events. The first value is revision 1. A different value appends one event and
updates current state to the next revision. A same-value explicit repeat is
`NO_CHANGE`: it creates no event and consumes no revision.

At most **10 state-changing revisions** may exist for one participant/response.
After revision 10, a different value is rejected deterministically; same-value
repeats remain free and return `NO_CHANGE`.

The existing inbox and command-job uniqueness make exact update replay create
one command acknowledgement and at most one event. For genuinely distinct
commands, PostgreSQL takes one transaction-scoped advisory lock for the full
current-state key, then locks the current row. Lock acquisition defines the
serialization order: each accepted command observes the committed predecessor,
receives the next revision, and the last serialized event is current. This is
the repository-defined winner rule; no update is lost and a final-slot race
cannot exceed revision 10.

The feedback mutation, event/current state, command completion, response plan,
and acknowledgement outbox action commit atomically. No database lock spans
external I/O because this operation performs none.

## Persistence and database authority

Migration `0026_conversation_feedback` adds `conversation_feedback` and
`conversation_feedback_events`. Rows contain only opaque authority identifiers,
the closed value, positive bounded revision, command provenance for events, and
timestamps. They never contain response text, Telegram quoted text, prompt
snapshots, provider data, comments, or arbitrary metadata.

Composite foreign keys enforce tenant/Assistant/connection/conversation and
participant scope. A database trigger verifies the command reply, delivered
message/action, exact response-plan mapping (including voice source linkage),
and semantic planning lineage. Event identity, scope, target, participant,
value, revision, and source command are immutable. Governance deletion is the
only deletion path: it is allowed only after the participant is privacy-deleted
or the target response plan is redacted.

## Provider and feature separation

Feedback produces exactly zero text-generation, TTS, embedding, transcription,
vision, Qdrant, platform reaction, and typing-presence calls. It creates no
regeneration job, voice artifact, memory item/event, semantic-memory job,
knowledge document/revision/chunk/job, summary, provider route/budget change,
safety change, or personality/configuration change.

Feedback commands and values are control metadata and are excluded from future
model context and summaries. They are not uploaded, used for training or fine-
tuning, or converted into production evaluation labels. Any such use requires
a future product/privacy specification.

## Privacy, retention, export, and backup

Feedback is user-authored privacy-scoped quality metadata. Subject export
includes only that participant's structured current values and immutable
revision history with timestamps and target-response timestamps; it includes no
assistant response text, quoted body, internal UUID, or another participant's
feedback. Group and deployment exports contain no feedback content.

Subject privacy erasure hard-deletes that participant's feedback events and
current rows after marking the participant deleted. Response/conversation
retention hard-deletes linked events and current rows after the response plan is
redacted. New feedback on a redacted or erased target is rejected. Feedback has
no independent permanent analytics retention period and cannot preserve erased
content or linkage.

Live rows are ordinary authoritative PostgreSQL data and therefore participate
in backup and restore with their constraints intact. Data absent after governed
erasure/retention is absent from later backups subject to the existing SPEC-025
backup-retention limitations.

## Control plane and observability

V1 adds no feedback inspection endpoint. In particular,
`deployment_operator` gains no tenant feedback-content authority. Existing
tenant roles are not expanded merely for implementation convenience.

Low-cardinality metrics may count `helpful`, `unhelpful`, `no_change`, and fixed
rejection reasons. Metrics never carry tenant, Assistant, connection,
conversation, participant, response-plan, Telegram, message, or response-text
labels and are not authoritative state. Logs contain fixed result categories,
not feedback-plus-identity pairs.

## SPEC-032 boundary

Production feedback never changes canonical scores, judge behavior, hard gates,
or fixtures. No production feedback is harvested. SPEC-032 gains exactly 15
literal, offline, deterministic scenarios about this feature's contracts, with
no credentials, network, database, production helpers for expected values, or
new unexplained `NOT_EVALUATED` result.

## Non-goals

No free-text survey, numeric score, implicit timing/reaction/regeneration/voice
signal, automatic adaptation, analytics dashboard, training export, generic
rating API, control-plane browser, Zalo support, or SPEC-040 work is included.

