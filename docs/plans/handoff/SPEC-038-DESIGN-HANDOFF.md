# SPEC-038 Design Handoff

Status: **APPROVED DESIGN**

Date: 2026-09-20

## Command semantics

Add `CommandOperation.VOICE` and parse only empty-argument `/voice`. The normal
Telegram ingress/update/command-job uniqueness remains the first idempotency
boundary. The command worker dispatches voice before generic read/configuration
handling. Invalid syntax uses existing usage output; missing/invalid authority
uses closed voice result codes. Successful generation completes the command
without creating a text acknowledgement because SEND_VOICE is its response.

The voice action's reply target is the `/voice` command message. It never replies
to the source assistant chunk or an edit target.

## Target authority graph

Create one reusable SQLAlchemy voice target resolver by extracting or sharing
the strong SPEC-036 linkage—not a weaker parallel query:

```text
leased command job
  → command Message.reply_to_message_id in the same conversation
  → outgoing TEXT message with delivered OutboundAction
  → latest delivered EDIT_TEXT action for that message, if present;
    otherwise the message's originating action
  → non-uncertain ResponsePlan
  → plan.text and planning lineage
```

Require current composite chain:

```text
ControlTenant(active)
  → Assistant(active, tenant)
  → PlatformConnection(active, telegram, tenant, Assistant)
  → Conversation(connection, not erased/expired)
  → command/source Message(conversation)
  → action/plan(conversation lineage)
```

The source message must be outgoing text, delivered, and non-redacted. The
action plan must have no `delivery_unknown` sibling and must be retained,
`should_respond`, text-bearing, and non-redacted. Revalidate the source plan's
planning job conversation. No platform quote/body participates.

## Split and regenerated response resolution

Every SPEC-034 text chunk points to an action whose `response_plan_id` owns the
whole `ResponsePlan.text`, so any chunk resolves the same plan text. Do not join
chunk text. For regenerated messages, the delivered edit action identifies the
regeneration plan; choose it exactly as the existing regeneration resolver does.
Do not follow `root_response_plan_id` for TTS.

## Domain and provider port

Add provider-independent `app.application.ports.text_to_speech` values:

- `VoiceFormat.OGG_OPUS`;
- immutable `TextToSpeechRequest(text, model, voice, format, max_bytes)`;
- immutable `TextToSpeechResult(audio_bytes, format, mime_type,
  provider_request_id)`;
- typed closed failure category and retry/certainty fields;
- `TextToSpeechPort.synthesize(request)`.

The application/domain layer has no httpx, SQLAlchemy, Telegram, filesystem, or
provider JSON dependency. Pure validation enforces 1..4,000 code points and
1..5,242,880 output bytes plus Ogg envelope/MIME consistency.

## OpenAI TTS adapter

Implement through the repository's existing configured `httpx.AsyncClient`
patterns and OpenAI credential family. POST JSON to `/v1/audio/speech` with the
route model, exact text, configured `alloy` voice, and `response_format=opus`.
Use 30-second bounded timeout, no redirects, and streamed response iteration
with a 5 MiB actual-byte ceiling. Accept success only for allowed audio content
type, nonempty Ogg (`OggS`) bytes, and the requested format. Ignore external
filenames. Map 400/401/403/429/5xx, timeout, reset/network, malformed/invalid,
and oversize into secret-safe typed outcomes. Once dispatch may have occurred,
timeout/reset is ambiguous and is never automatically repeated.

## SPEC-026 integration

Extend the closed schemas with:

- `WorkloadClass.TEXT_TO_SPEECH`;
- `ProviderOperation.VOICE_SYNTHESIS`;
- `RateLimitOperation.TEXT_TO_SPEECH`;
- provider price unit `tts_request`;
- capability keys `text_to_speech`, `voice_format`,
  `maximum_input_characters`, and `maximum_output_bytes`.

Capability matching permits only `ProviderId.OPENAI`, native `ogg_opus`, and
sufficient published bounds. Add `voice_generation_job_id` to both provider
work snapshots and usage attempts and update exactly-one-source constraints.
`voice_source(job_id)` verifies exact tenant/Assistant/connection ownership.

The worker requires governance `enforce`, resolves one eligible route, reserves
one request-based maximum cost, applies TTS-specific deployment/connection/
conversation/participant/provider Redis keys with the existing generation quota
values and the existing provider
concurrency port, marks the attempt `io_started`, then releases all DB resources
before calling the adapter. Admission denials finalize no-I/O and emit the
deterministic command result with zero raw calls. Token usage remains missing;
request count and price revision account for TTS.

## Durable generation job and possible-I/O fence

Migration `0025_telegram_voice_tts` adds
`telegram_voice_generation_jobs`. One row is unique by `command_job_id` and
contains exact scope/source IDs, source SHA-256 and code-point length, privacy
revision, status, lease owner/expiry, attempt count, provider attempt reference,
and terminal reason/timestamps. It contains no source text.

Statuses distinguish `pending`, `leased`, `io_possible`, `completed`,
`failed`, and `stale`. The command lease and voice-job lease are acquired and
revalidated together. A crash before durable provider `io_started` can recover;
after it, recovery marks possible-I/O and forbids another synthesis. Immediate
typed timeout/reset after dispatch follows the same terminal uncertain rule.
No exactly-once provider claim is made.

The raw TTS await receives only immutable scalar/source snapshots and a bounded
string after the transaction exits. Tests instrument `database.engine.pool`
and require `checkedout() == 0` at the exact fake-provider call.

## Artifact model and atomic activation

Migration `0025` adds `generated_voice_artifacts` with:

- exact composite scope and source-plan/job links;
- unique generation job;
- `format='ogg_opus'`, `mime_type='audio/ogg'`;
- nullable `BYTEA audio_bytes`, `byte_size`, 64-hex SHA-256;
- lifecycle `ready|purged` and created, action-terminal, expiry, purge times.

Checks enforce 1..5,242,880 bytes, `octet_length(audio_bytes)=byte_size` while
READY, bytes absent while PURGED, closed format/MIME, and lifecycle timestamp
shape. Composite FKs prove tenant/Assistant/connection/conversation/source
scope. Identity, size, checksum, and source links are immutable after insert.

On successful provider return, one short transaction locks the voice job and
command, verifies current lease/privacy/source/authority/provider attempt, then
inserts READY artifact and one pending VOICE outbound action and completes the
job/command atomically. Stale state discards returned bytes and creates neither
READY artifact nor active action.

## Outbound SEND_VOICE model

Extend `OutboundActionKind` with `VOICE`. Add nullable
`generated_voice_artifact_id`, unique for voice action, and schema checks:

- VOICE has artifact ID, no text/sticker/edit/fallback payload;
- non-VOICE has no artifact ID;
- scope matches through composite foreign keys;
- sequence is 1/1 and response plan is a code-owned nonsemantic command plan or
  the action model is extended with a command source without creating semantic
  text. Prefer retaining the existing required `response_plan_id` by creating a
  non-text `should_respond=true` command response plan only if its semantic
  exclusion is explicit and tested.

The response plan/action is operational presentation state; conversation
context ignores voice messages and does not duplicate source plan text.

## Telegram multipart adapter

Add `PlatformCapability.SEND_VOICE`, `SendVoiceRequest`, and
`PlatformAdapter.send_voice`. The request accepts bytes plus closed
format/MIME—not path, URL, or caller filename. Validate 1..5 MiB and `OggS` at
the boundary. Use existing `_request` error mapping with multipart:

```text
chat_id=<authoritative chat>
message_thread_id=<authoritative thread, if any>
reply_parameters={"message_id": <voice command platform id>, ...}
voice=("voice.ogg", bytes, "audio/ogg")
```

No caption. The adapter requires a normal Telegram Message response.

## Outbound loading and session boundary

Extend the existing outbound repository/worker only. During resolve, lock/recheck
action authority and load at most 5 MiB from a READY, unexpired, same-scope
artifact into an immutable bounded snapshot. Close the session. The existing
delivery-attempt fence then marks `external_started_at` in its own committed
transaction. Revalidate artifact readiness in that fence transaction so purge
cannot race activation. Close the session and call `send_voice`; exact-call
instrumentation requires zero checked-out DB connections. Reopen to finalize.

Definitive retryable rejection requeues the same action and reloads the same
artifact; TTS is never reached. Unknown delivery uses existing
`DELIVERY_UNKNOWN` plus quarantine and never resends. A definitive invalid reply
target may use the worker's single no-reply fallback with the same bytes.

## Retention and erasure

Extend the existing retention/governance worker. Terminal action finalization
sets artifact `action_terminal_at` and `expires_at` to the earlier of terminal
+ 24 hours and created + 7 days. Hard expiry independently purges nonterminal
bytes and makes delivery permanently unavailable/quarantined. Purge is
idempotent and clears only `audio_bytes`; it never preserves a second encoded
copy.

Conversation/source privacy erasure immediately locks and purges linked
artifacts, then prevents pending/leased delivery from passing revalidation.
Existing response/action redaction remains authoritative. Exports omit audio
and artifact rows. PostgreSQL backup/restore includes live rows and must validate
referential consistency; new backups of purged rows contain no bytes.

## Multi-tenancy and stale-work fence

All new tables carry tenant, Assistant, connection, conversation, and source
links with repository-standard composite ownership FKs. Repository queries
repeat exact predicates rather than relying on opaque IDs. Cross-tenant,
same-tenant foreign Assistant, foreign connection/conversation/plan/action, and
mixed-scope inserts fail closed or violate constraints.

An asyncio barrier integration test pauses after provider return and before
activation, then disables Assistant/connection or erases source. Resume must
produce zero READY artifact, zero active VOICE action, and zero Telegram calls.
No sleeps are used.

## Idempotency

`telegram_command_jobs.conversation_processing_record_id`, voice job
`command_job_id`, artifact `generation_job_id`, action idempotency key, and the
provider attempt identity form layered uniqueness. Exact update replay and two
concurrent claimers converge to one job/attempt/artifact/action. Raw TTS count is
exactly one for an accepted command.

## Feature separation

The voice branch does not invoke response planning, normal generation,
regeneration, presence, reactions, media download/transcription/vision, memory,
semantic memory/Qdrant, knowledge/RAG, or summaries. Context loaders exclude
outgoing voice operational messages. Live tests measure zero deltas at durable
tables and instrument raw ports, rather than inferring separation from imports.

## Privacy and observability

Use only fixed error/result enums and low-cardinality provider/result/artifact
size/lifecycle labels. Do not log source text, audio, encoded audio, HTTP body,
provider filename, IDs, chat/message/user values, or credentials. Explicitly
exercise provider/Telegram 400/429/5xx, timeout/reset, oversize, and privacy
failures and inspect captured records/labels.

## SPEC-032 evaluation

Add 15 literal, offline scenarios and voice hard-gate fields for target
authorization, TTS calls/admission, artifact validity/count, voice actions,
duplicate actions, rewriting, memory/knowledge writes, Telegram attempts, and
ambiguous duplicate sends. Fixtures contain bounded synthetic Ogg-like bytes,
derive no expected values from production helpers, require no credential or
network, and include a mutation that changes a production voice decision and
causes gate failure.

## Migration and rollback

`0025_telegram_voice_tts` modifies closed provider/rate/outbound constraints,
adds source columns and the two voice tables, and installs immutable/scope
triggers only where declarative constraints cannot express cross-row state.
Downgrade first checks every TTS/voice table and all provider/outbound/rate state
introduced by 0025; any populated state raises an exact refusal in-transaction,
leaving revision 0025. Empty downgrade restores the exact 0024 constraints and
can be upgraded again. No manual ALTER is part of validation.

## Validation

Create executable `scripts/validate-telegram-voice-tts.sh` using
`scripts/lib/resolve-uv.sh`, isolated supported ports, no `.env`, credentials,
Git history, network, sleeps, hidden audio, skips, xfails, `|| true`, or
continue-on-error. Wire it normally into Quality CI. Candidate proof exports
tracked modifications, untracked files, and executable modes into a VCS-free
tree.

Run the full brief matrix, migration base/0024/0025 guarded lifecycle,
backup/restore, privacy/integrity searches, and exact 44-proof audit. Reliability
remains diagnostic: only the six named historical `fk_assistants_tenant`
failures for tenant `00000000-0000-4000-8000-000000000030` are accepted as
unmasked Product Owner-deferred debt.

## Deferred global CI debt

SPEC-038 must not weaken the tenant FK, seed compatibility rows, skip/xfail
tests, change unrelated validator modes, add best-effort shell logic, or claim
global release readiness. Any new failure is SPEC-038 work and must be fixed.
