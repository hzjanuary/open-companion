# SPEC-036 Design Handoff

Status: APPROVED DESIGN

## Authority and entry point

`parse_command` classifies argument-free `/regenerate` as a dedicated operation.
The command worker delegates admission to one PostgreSQL repository transaction.
That transaction locks the command and replied message, resolves the delivered
outbound action and logical plan, follows the latest certain edit presentation,
and verifies the target is provider-backed, unredacted, and in the command's
conversation. The conversation's connection determines tenant and Assistant;
database constraints/triggers reject contradictory lineage.

Any split chunk resolves through its outbound action to the same response plan.
The root planning job supplies the original triggering user message. Command
and schedule plans, user messages, unresolved raw Telegram reply IDs, and
delivery-unknown presentations are rejected.

## Persistence

Migration `0024_telegram_response_regeneration` extends
`response_planning_jobs` with nullable, all-or-none regeneration lineage:

- `source_command_job_id` (unique);
- `root_response_plan_id`;
- `parent_response_plan_id`;
- `regeneration_ordinal` constrained to 1..3.

A trigger validates same-conversation command/root/parent/source authority,
root consistency, parent ancestry, and immutable lineage. A unique root/ordinal
constraint plus a `FOR UPDATE` lock on the root response plan serializes the
limit. Non-regeneration jobs keep all four fields null.

`outbound_actions` gains typed `edit_text`, an exact composite
`edit_target_message_id`/conversation reference, immutable
`edit_target_platform_message_id`, and a nullable unique
`fallback_for_action_id`. A fallback-shape check permits only blocked text
fallback actions paired with edit actions in the same plan/conversation. The
existing SPEC-034 immutable trigger is extended to cover these identities.

`fallback_blocked` is a non-claimable outbound status. Compilation creates an
edit at sequence 1 and blocked fallback at sequence 2. Exact edit rejection
atomically makes the edit skipped and fallback pending. Confirmed/unchanged edit
atomically marks the edit delivered and fallback skipped. Ordering admits the
fallback only for its skipped edit predecessor. Ambiguous edit leaves the
fallback blocked.

## Planning and context

Admission snapshots the current configuration/personality into a new normal
addressed planning job, with `message_id` set to the root's original source
message. The existing context reader and prompt builder are reused. It receives
the command message ID as an exclusion so control text cannot enter recent
history. Current memory, knowledge retrieval/revalidation, safety, media,
provider governance, and presence behavior stay on their existing paths.

Planning completion reads the lineage and authoritative parent presentation in
its transaction, calls one pure `choose_regeneration_presentation` policy, then
compiles either the edit/fallback pair or ordinary ordered outbound sends. No
old provider attempt or RAG payload is copied.

## Telegram delivery

The existing adapter gains `edit_text(EditTextRequest)` and capability
`EDIT_TEXT`. `_request` retains the real Telegram error code and maps only exact
normalized descriptions to `edit_rejected_without_application` or
`edit_not_modified`. Transport ambiguity for `editMessageText` has UNKNOWN
certainty, matching send operations.

The delivery worker resolves the edit target in a short session, closes it,
marks the attempt externally started in another short transaction, then calls
Telegram. Confirmed edits update the target message presentation text/time and
terminally skip the fallback. The not-modified class uses the same terminal
transition without a second raw call. Exact non-application rejection activates
the fallback transactionally; its later `sendMessage` uses the normal worker.
All other failures use existing retry, dead-letter, or uncertainty handling.

## Concurrency and recovery

- Existing command leases plus unique source-command lineage prevent replay.
- Root row locking plus unique root/ordinal prevents over-limit races.
- Outbound leases and owner checks serialize edit finalization and fallback
  activation.
- A fallback cannot be claimed while blocked, and cannot be activated after an
  edit has become canonical.
- External-started lease expiry is ambiguous and quarantined; no automatic
  fallback is enabled.
- Migration downgrade refuses while any regeneration lineage, edit, or fallback
  state exists; fresh safe downgrade remains supported.

## Evaluation and observability

Add 14 offline scenarios covering valid/invalid authority, stale/current
memory/RAG, governance denial, exact limit, edit/new selection, fallback,
ambiguity, not-modified, and presence ordering. Hard gates expose independent
expected facts, not production-policy-derived oracles. Unit/integration tests
cover exact error strings, real PostgreSQL constraints/concurrency, worker
delivery, and checked-out connection counts at provider/edit/fallback I/O.

Telemetry is content-free and low-cardinality. Existing SPEC-035 metrics and
controller are reused. The exact six pre-existing reliability failures remain
deferred and may not be masked.
