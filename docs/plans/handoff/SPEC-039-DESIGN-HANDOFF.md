# SPEC-039 Design Handoff

Status: **APPROVED DESIGN**

Date: 2026-09-26

## Command semantics

Add `CommandOperation.FEEDBACK`. Parse only the exact single-token arguments
`helpful` and `unhelpful` into a closed `FeedbackValue`; every other argument is
usage. Dispatch before generic read/configuration paths. The feedback repository
atomically persists state and the deterministic command acknowledgement.

## Target authority

Implement one feedback resolver mirroring the stronger regeneration/voice
resolver rules. It starts at the locked leased command and its local reply edge;
requires the canonical non-deleted participant and active SPEC-030 tenant /
Assistant / Telegram connection / conversation authority; and accepts only a
retained outgoing delivered text or voice presentation. It ignores quoted text.

For text, select the latest delivered `EDIT_TEXT` action when present, otherwise
the message's originating delivered `TEXT` action. Reject any delivery-unknown
sibling. Resolve only a retained `should_respond` response plan with semantic
planning-job lineage in the same conversation.

## Split, regenerated, and voice targeting

All split chunks keep the same action `response_plan_id`; store that plan once.
A delivered edit owns its exact regeneration plan. A delivered voice message
resolves through its originating `VOICE` action and same-scope generated
artifact to `source_response_plan_id`. Do not target the voice command plan or
audio bytes.

## Participant authority

Use `command.participant_id`, require the participant's composite conversation
membership and non-deleted state, and include the participant in the uniqueness
key. Separate participants therefore receive separate current rows and event
streams for the same response.

## Data model

`conversation_feedback` stores exact scope IDs, response plan, participant,
one authoritative target message/action anchor, value, revision 1..10, and
timestamps. `conversation_feedback_events` repeats the constrained scope/target
identity, points to its current row and unique source command, and stores value,
revision, and timestamps. Neither table stores content.

Composite FKs enforce owner/scope hierarchy and participant membership. A
PL/pgSQL trigger verifies the command's reply edge, target delivery mapping,
text/edit or voice source mapping, response plan retention, and planning-job
conversation. Contradictory direct SQL fails.

## Current state and immutable events

Take a transaction advisory lock derived from the full uniqueness key before
reading current state. Insert revision 1 or update under row lock. Every changed
value appends exactly one event before current state advances. An event UPDATE
always fails. Event DELETE fails unless its participant is already privacy-
deleted or target response plan is already redacted; this is the narrow governed
erasure/retention exception, not mutable history.

## Revision limit and concurrency

The exact maximum is 10. Same-value repeats return `NO_CHANGE` without an event
at any revision. Different-value revision 11 returns `LIMIT_REACHED`. Advisory
lock acquisition is the documented serialization order for distinct commands;
both opposite values may be events and the later serialized event wins. The
same lock makes a 50-way final-slot race consume at most one slot.

## Idempotency and atomic acknowledgement

The existing update/processing-record/command-job uniqueness rejects exact
replay. Events additionally make `command_job_id` unique. One transaction locks
the command, resolves authority, takes the feedback lock, mutates feedback,
creates the code-owned response plan/outbound action, and completes the command.
Target/limit/no-change outcomes are finalized by the same path.

## Privacy, retention, export, and backup

Subject erasure deletes events then current rows after participant tombstoning.
Retention deletes events/current after plan redaction. Subject export adds only
own structured feedback values, revisions, and timestamps without internal IDs
or response text. Group/deployment export remains unchanged. Backup/restore
proof checks current/event scope and revision integrity.

## Control plane and telemetry

Add no inspection endpoint or route. Role tests prove deployment operators have
no tenant feedback-content access. Emit one low-cardinality counter with fixed
outcomes only; never identity or content labels. PostgreSQL remains authority.

## No-provider and separation boundaries

The branch imports no provider, vector, platform-presence, reaction, TTS, or
generation service. Tests assert exact zero deltas/calls for generation, TTS,
embedding/transcription/vision, Qdrant, regeneration, voice artifacts, reactions,
presence, memory, semantic memory, knowledge, summaries, and configuration.
Command messages and feedback state remain absent from future prompt and summary
inputs.

## SPEC-032 and validation

Add exactly 15 synthetic `feedback.*` scenarios and independent hard gates for
target authority, value/state/event/revision/no-change, zero external calls,
and prompt exclusion. Add migration `0026_conversation_feedback`, dedicated
executable `scripts/validate-conversation-feedback.sh`, CI wiring, migration
lifecycle/populated-downgrade proof, real PostgreSQL contradiction/concurrency/
privacy/export/backup tests, clean-export execution, and the required regression
matrix. The six known reliability failures remain unchanged and visible.

