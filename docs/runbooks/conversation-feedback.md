# Explicit conversation feedback

SPEC-039 adds one local, reply-only quality signal. Reply directly to a
delivered January answer with exactly one of:

```text
/feedback helpful
/feedback unhelpful
```

There are no aliases, numeric scores, neutral value, free-text comment, or
"latest answer" fallback. Missing, unknown, and extra arguments receive the
ordinary command-usage response. Telegram quoted text is never authority.

## Target and acknowledgement behavior

January resolves the command's retained local reply edge to a delivered
outgoing message and its exact response plan. Any delivered chunk of a split
answer targets the same logical plan. A successfully delivered regenerated
edit targets that regeneration rather than the root response. A delivered
`/voice` presentation targets its source text response; audio quality is not a
separate feedback target.

An accepted state change replies `Feedback saved.` and an exact same-value
repeat replies `Feedback already saved.` Rejected targets and the revision cap
use deterministic local responses. These acknowledgements use no generation,
TTS, embedding, transcription, vision, vector store, reaction, or typing call.

## State and revision semantics

Each canonical participant owns one current feedback row per response plan,
independently of other group members. The first state-changing command is
revision 1. Changing the value appends one immutable event and advances the
current row. Repeating the current value is `NO_CHANGE`: it creates no event
and consumes no revision.

One participant may create at most 10 state-changing revisions for a response.
At revision 10, a different value is rejected; a same-value repeat remains a
free `NO_CHANGE`. PostgreSQL serializes distinct concurrent commands by the
full tenant, Assistant, connection, conversation, response-plan, and
participant key. Exact Telegram update replay remains idempotent.

Feedback is quality metadata only. It never regenerates a response, changes
future prompts, writes memory or knowledge, changes personality or safety,
adjusts provider routes or budgets, trains a model, or becomes a production
evaluation label. Feedback commands, acknowledgements, and values are excluded
from future model context and conversation summaries.

## Privacy, retention, and export

A subject export contains only that participant's structured current values,
revision history, and timestamps. It contains no response body, quoted text,
internal UUID, or another participant's feedback. Group and deployment exports
contain no feedback content, and deployment operators gain no inspection route.

Subject privacy erasure hard-deletes that participant's feedback events and
current rows after tombstoning the participant. Response retention does the
same after redacting the linked response plan. A redacted response or
privacy-deleted participant cannot create new feedback. Live rows participate
in ordinary PostgreSQL backup and restore; governed deletions are not retained
as an independent analytics copy.

## Troubleshooting

- `Target unavailable.`: verify the command directly replies to a locally
  retained, delivered January text or voice-presentation message in the same
  active Telegram authority scope. User messages, acknowledgements, redacted
  plans, erased participants, and delivery-unknown responses are ineligible.
- `Feedback limit reached.`: the participant has already made 10 state-changing
  revisions for that response. Same-value repeats are still allowed.
- A repeat says `Feedback already saved.`: this is expected and creates no new
  event.

Never recover authority from Telegram quotes or manually change feedback rows.
For an ambiguous or contradictory case, preserve the database state and inspect
the command result category without logging participant or response identity.

## Validation

Run the isolated no-credential validator:

```bash
JANUARY_DB_HOST_PORT=5458 ./scripts/validate-conversation-feedback.sh
```

It proves offline grammar/evaluation behavior, real PostgreSQL authority,
concurrency, privacy/export/retention, migration lifecycle and populated
downgrade refusal, direct-validator modes, and execution from a VCS-free
tracked-plus-untracked candidate. It uses no Telegram or provider credentials.

Run `./scripts/validate-backup-restore.sh` separately to rehearse current state
and immutable history through PostgreSQL dump and restore.

## Known limitations

V1 provides no free-text survey, analytics dashboard, generic rating API,
implicit reaction/timing signal, automatic adaptation, training export,
control-plane browser, Zalo support, or audio-quality rating.
