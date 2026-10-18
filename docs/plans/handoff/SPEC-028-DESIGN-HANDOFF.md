# SPEC-028 Implementation Design Handoff

Date: 2026-09-08

Status: **APPROVED DESIGN** under the Product Owner-authorized end-to-end goal.
Implementation is present in the uncommitted candidate; repository-safe audit
and validation passed. Docker-backed release evidence remains pending. Authority:
[SPEC-028 Product Spec](../../product/specs/SPEC-028-rich-telegram-media-and-voice-interactions.md).

## 1. Executive summary

Extend the existing normalized message and response-planning pipeline with one
bounded attachment per source message. PostgreSQL stores fetch/recovery metadata
and successful derived transcript, never raw bytes. The existing planning worker
performs secure Telegram download and governed transcription or multimodal
generation after existing eligibility/safety/rate gates. Existing response-plan
validation and outbound delivery remain the only reply path.

## 2. Baseline SHA and audit

Starting HEAD = origin/main = `private-source-checkpoint-omitted`;
clean baseline and diff check verified before modification. Actual head is
`0018_user_controlled_memory`. SPEC-027 and the central VARCHAR(64) migration
bootstrap hotfix are committed. No committed migration may be rewritten.

Audit details and Docker evidence are in the completed SPEC-028 execution plan
and final handoff. Completion of repository work does not imply live Docker proof.
Normalizer currently supports text/caption/sticker only; no getFile/downloader,
attachments, multimodal request or transcription workload exists. Existing
planning leases, provider admission, privacy redaction and outbox are reusable.

## 3. Existing architecture reused

- `telegram/updates.py`, webhook and poller → durable inbox/outbox → Redis refs.
- `database/conversation.py` → normalized message and processing ledger.
- `response_planning_worker.py` → context, protection, safety and rate gates.
- `governed_provider.py` + `database/provider_governance.py` → immutable routing,
  capabilities, health, reservations, I/O state and reconciliation.
- `planning_service.py` → bounded retries/correction and strict response plans.
- `database/planning.py` → final plan/outbound intent; existing delivery worker.
- Privacy/export/retention/context repositories and SPEC-027 explicit-memory rules.

## 4. Scope

One JPEG photo, OGG/Opus voice or MP3 audio per update; authenticated Telegram
fetch; independent transcription governance; current-turn image input; derived
transcript; existing text replies; durable bounded recovery and proof.

## 5. Out of scope

No TTS, new vendor, arbitrary URLs/documents/video, image generation, raw archive,
album state machine, new identity/tenancy, automatic memory or SPEC-029.

## 6. Telegram media domain model

Add framework-free immutable `MediaAttachment` and closed kind/outcome values in
`domain/media.py`. Fields: kind, selected file_id/unique_id, declared byte size,
MIME, width/height or duration. Bounded identifiers are opaque platform metadata.
Suppress repr of references/content-bearing fields. Invalid/unsupported media
is an explicit normalization disposition, never a downloadable arbitrary blob.

## 7. Normalized attachment representation

Add optional attachment and media-failure fields to `NormalizedMessage` with
defaults, preserving positional compatibility. `message_type` distinguishes
photo/voice/audio/unsupported; sticker stays unchanged. Normalize at most one
selected photo: eligible dimensions and declared byte size, greatest area,
then stable dimension/size/reference ordering. Limit photo candidate count.
Pass configured limits from conversation worker; pure default bounds support
unit normalization. Typed commands are parsed only from `text` + `entities`;
caption mentions use `caption_entities`. UTF-16 entity offsets must preserve
Telegram caption addressing. Never execute transcript or caption commands.

## 8. Persistence model

Add `message_media` with a unique message_id and exact conversation binding:

- UUID id; message_id + conversation_id composite FK to messages;
- kind; bounded file_id/file_unique_id; MIME; declared file_size;
- optional width/height/duration; bounded original caption;
- status (`pending`, `preparing`, `complete`, `failed`, `ambiguous`, `redacted`);
- closed outcome/reason; lease token, lease expiry, planning claim ordinal;
- source message edit timestamp and conversation privacy revision snapshot;
- created/updated/completed/redacted timestamps.

No byte/base64/path/URL/provider-response column. Successful transcription lives
in `messages.text`; `messages.metadata` records closed content provenance.
Caption remains separately distinguishable on the attachment. Caption and
references are cleared with content. Unique `(messages.id, conversation_id)`
allows the attachment composite FK. Resolve participant/Assistant/connection
from the canonical chain rather than duplicating portable identities.

Insert attachment with incoming message transaction. Existing message duplicate
must not enqueue another media planning job merely because update_id differs.
Edits invalidate the old media work and clear obsolete attachment fetch state;
do not reprocess edits. This prevents source content replacement during I/O.

## 9. Raw-byte lifecycle

Use bounded bytes in memory, no temporary files or object storage. Download,
validate, attach to current request/call, then release all references in finally
and after each work iteration. Dataclasses holding bytes use repr=False.
Provider JSON/base64 and multipart copies remain ephemeral and size-bounded.
No promise of cryptographic memory erasure; process memory/swap/crash-dump policy
is an operating-owner concern. The application must not create dumps/archives.

## 10. File download architecture

Extend Telegram adapter with typed `get_file`/bounded download support, using a
narrow application media-download port for fake injection. getFile JSON has a
small response-size limit and validates returned ID, integer size and path.
Stream with fixed-size chunks, reject advertised excess before reading, count
every byte, close the response on every exit and enforce an overall asyncio
deadline (not only a per-read timeout). Disable redirects and compression.
Reject empty, mismatched Content-Length, truncated and invalid responses.

## 11. Trusted URL/boundary model

Use only configured Telegram base origin plus fixed Bot API/file prefixes.
Accept only relative ASCII path segments; reject empty/dot/dot-dot components,
leading slash, backslash, percent escape, colon, query, fragment and controls.
Local Bot API absolute-path responses are deliberately unsupported; never read
local files. Require HTTPS except explicit loopback development HTTP matching
existing configuration conventions. Production configuration does not accept
user-controlled endpoints. Match the configured connection to its adapter token
source before fetch; never use one bot token for another connection's media.

The token-bearing URL is constructed only inside adapter memory. Add sanitizing
filters for HTTP client request logs and suppress unsafe chained exceptions on
this path. Tests enable HTTP library logging and inspect formatted tracebacks,
not only application messages. Never return the URL as an error detail.

## 12. Size/time limits

Implement Product Spec defaults/caps in Settings and validate their relations.
Photo/audio 5 MiB defaults (10 MiB caps), side 1280 (4096 cap), declared audio
duration 120s (300 cap), caption 1024 chars, transcript 4000 (8000 cap), download
15s (60 cap), transcription 20s (60 cap), response JSON 64 KiB. Reserve enough
planning lease time for bounded preparation and sequential calls or renew the
exact owner/ordinal lease before each phase. Provider reservation/concurrency
leases exceed each actual provider timeout. Expired ownership cannot complete.

## 13. MIME/media validation

Accept JPEG with valid marker/size structure and bounded header dimensions;
OGG containing Opus identification; MP3 framing/ID3 within bounded parsing.
Cross-check kind, declared MIME (if supplied), file extension where useful and
container signature. Generic octet-stream download MIME can be accepted only
when signature matches; explicit contradictory MIME is rejected. Do not trust
user filename, decode pixels, run ffmpeg, or execute codecs. Telegram duration
is bounded metadata, not independently verified signal duration.

## 14. Voice transcription architecture

Add typed `TranscriptionRequest`/`TranscriptionResult` and capability port beside
`GenerationRequest` in `application/model_provider.py`. Extend existing Groq
HTTP configuration with multipart `/audio/transcriptions`; no SDK/vendor added.
Upload fixed safe filename/content type from validated format, never Telegram
path/ID. Request JSON text output, no translation, no external file URL.
Bound result bytes and transcript length; absent token usage remains None.

Refactor reusable reservation→rate→concurrency→I/O-start→completion logic inside
the existing governed-provider module, or adapt the typed transcription call
through that same core. A second admission system or raw ungoverned adapter
invocation from runtime is prohibited. Canonical tests inject deterministic fakes.

## 15. Photo multimodal architecture

Add an optional typed current-image value to GenerationRequest (ephemeral
bytes/MIME/dimensions, no Telegram reference). Existing supported HTTP families
serialize base64 in their native current-turn message field. Capability defaults
remain false; reject image requests in adapters without implemented support.
OpenAI-compatible implemented image adapters may share their serializer; do not
claim Gemini/Ollama support unless their payload and tests are implemented.
The registered model must separately advertise image_input and a reservation
bound. Preserve image on correction/retry by dataclass replacement instead of
reconstructing only old request fields. No image enters history or summaries.

## 16. Provider capability extensions

Add `transcription` workload and `media_transcription` operation. Extend closed
registry metadata validation with `speech_to_text`, supported audio formats and
maximum byte/duration bounds for Groq transcription. Only that existing family
may register the new transcription capability initially. Generation metadata
adds `image_input` and positive `maximum_image_input_tokens`; deny unsupported
adapter/image claims and missing bounds. Embedding validation stays unchanged.

## 17. SPEC-026 routing/budget integration

Media requires enforce mode, rate limiter and concurrency limiter. Missing
configuration returns deterministic unavailable without download/provider I/O.
Use existing deployment/Assistant/connection policy hierarchy. One planning
source can snapshot distinct chat-generation and transcription policies.

Existing routes require exact published requirements. Preserve that equality
for base requirements; permit only explicitly defined stricter per-work image
and audio-format constraints, filtering capabilities against both. Do not allow
arbitrary requirement removal/weakening. Capability revisions are immutable;
admission rechecks lifecycle/current policy/health and required media flags.
Transcription uses the stable source operation identity (not a fresh arbitrary
retry identity) and one possible external call per source message.

## 18. Usage accounting

Extend existing price basis with `transcription_request`: operator-supplied
fixed upper per-request microusd estimate for bounded audio. No time/token-based
billing engine. Enforce price/workload matching. Add transcription to workload
enums/checks and aggregate/telemetry validation; supported budget measures are
requests and estimated cost. Do not reinterpret embedding_request as audio.

Image admission adds registered maximum_image_input_tokens to conservative
text input reservation. Refuse missing/incompatible bound. Token reports retain
complete/partial/missing/invalid classification; no fake zero. Transcription
may have known request estimate and missing token usage simultaneously.
Possible I/O retains debit; no-I/O releases reservations. Existing ledger owns
every attempt, including image retry/correction/fallback.

## 19. Rate limit/concurrency interaction

Existing conversation/deployment/connection/participant generation admission
precedes media preparation. Transcription and final generation each consume
provider-level rate admission and the existing shared provider semaphore.
No new semaphore or label keyed by file/user. Denied admission means zero
provider calls and released no-I/O reservation. Replayed successful transcripts
do not reacquire transcription capacity. Bound pre-I/O deferral/retry; possible
transcription I/O does not automatically fall back or retry.

## 20. Safety flow

Run existing pause/protection/reduce-interaction logic before media download or
transcription. A safe media failure notice may be generated only when those
gates allow a response. After transcript commit, rebuild context and use the
same untrusted input/system policy and response validation. Each provider-call
preflight rechecks privacy/scope/lease and active configuration. No transcript
becomes a command. Existing structural safety limitations remain documented.

## 21. Context/prompt integration

ContextMessage gains optional closed provenance and caption fields. Reader
returns authorized retained canonical transcript as derived user text and
bounded caption separately. Prompt JSON exposes provenance and untrusted
semantics; no file IDs/bytes in text context. Photo provider input is a separate
ephemeral current image, not prompt JSON persisted anywhere. Future context has
caption/media marker only, plus normal retained replies. Recall logic unchanged.

## 22. Message provenance

Closed values: typed_text/default, media_caption, voice_transcript,
audio_transcript. Store only after fenced success; reject empty/oversized result.
Never pretend transcript is user-typed or losslessly accurate. Retention of
transcript uses original message deadline, not a refreshed processing date.

## 23. Memory boundary

No calls to memory create/context mutation or semantic UPSERT from media paths.
Existing explicit command can intentionally save a fact later. Context recall
off and creator filtering remain unchanged; transcripts may enter ordinary
bounded conversation history, never explicit-memory indexing.

## 24. Data-governance integration

Update inventory version/category and volume mapping for message_media; explain
ephemeral bytes versus durable metadata/transcript. Subject summary includes the
bounded fact that voice/audio transcripts are derived retained message content.
No new content-control endpoint, external compliance declaration or raw archive.

## 25. Erasure behavior

In the existing subject erasure transaction, clear matching attachment caption,
file identifiers and dimensions/size/duration where retained, set redacted,
revoke lease; existing message.text/metadata cleanup clears transcript/provenance.
Invalidate exports and source plans as today. Media completion locks current
canonical scope and checks privacy revision, redaction, source edit and owner
ordinal. Thus stale provider result cannot resurrect erased content.

## 26. Export behavior

Add a content-safe allowlisted media/provenance projection to subject message
exports; exact participant/conversation joins only. Caption/transcript are the
authorized subject-content exception. Do not export secret URL/path or raw bytes.
Group exports and deployment counts never include members' transcripts/files.
Existing export manifest/token/expiry contracts remain.

## 27. Retention behavior

Use the existing ordered raw-message retention batch to clear associated media
references/caption/state in the same transaction, not an unbounded scan.
Also deny expired media at read/preflight/finalize, before batch cleanup.
Multi-batch tests show fresh/unrelated rows survive and repeated cleanup is empty.
No extra worker or independent raw-byte purge schedule is needed.

## 28. Authorization

Resolve from planning job→message→participant/conversation→connection→Assistant
and current tenant binding. Validate bot connection matches configured runtime
adapter scope. Client input cannot supply a different media row/file ID to runtime.
Exact participant privacy is required; addressed-only group eligibility applies.
Registry/routing/pricing use deployment_operator; existing bound resource-budget
roles remain. No tenant owner becomes deployment operator or media inspector.

## 29. Transaction boundaries

Short transaction: validate claim/scope and snapshot metadata, commit/close.
External: Telegram resolution/download. Short transaction: revalidate current
privacy/edit/lease; external provider admission uses its existing short atomic
reservation and durable I/O-start transactions, never an open session during I/O.
Short transaction: owner/ordinal/source/privacy-fenced transcript commit or
media failure, then rebuild context after close. Final plan uses the same fence.
Pass pre-I/O validation to all media generation attempts, not just first route.

## 30. Idempotency

Unique attachment message identity and no duplicate media planning job on
duplicate platform message. Transcript commit is one terminal state transition.
Consult durable transcription attempts before any retranscription: any possible
I/O (including completed usage with missing transcript after crash) prevents
another call. No-I/O attempts may recover within bounded limit; completed
transcript is reused. Unique ledger constraints retain accounting race fences.

## 31. Crash/recovery semantics

Reclaim expired preparing state only with a new unique lease token and current
planning claim ordinal. Active unexpired token cannot be stolen. If no provider
I/O is possible, re-fetch is safe; otherwise transcription becomes ambiguous.
Crash after provider success but before transcript commit loses that transcript
and yields safe notice, not another paid call. Old worker completion fails after
expiry/reclaim, same-host restart, edit, privacy revision or redaction.
Photo retries remain the existing bounded governed planning behavior; no
exactly-once claim. Cancellation drops bytes and leaves recoverable durable state.

## 32. Worker topology

No new worker. Conversation worker persists metadata; planning worker prepares
media; existing provider-governance recovery worker handles usage reservations;
retention handles metadata cleanup; existing outbound worker sends replies.
Media disabled means no external media calls. Preserve lifecycle signal/drain
and restart configuration; validate bounded per-phase leases/expiry.

## 33. Outbound implications

Only existing text/sticker actions. Fixed localized media notices are ordinary
validated response candidates with original reply/thread target. Final transcript
is not automatically echoed as a transcription receipt. Delivery ambiguity
continues to use existing quarantine, never automatic resend.

## 34. Database/migration design

Create exactly `0019_telegram_media` after `0018_user_controlled_memory`:

1. Unique messages(id, conversation_id), message_media table with FK/unique,
   bounded values, positive dimensions, closed state/outcome, lease-shape checks,
   and index for bounded stale/retention lookup.
2. Extend message_type CHECK to photo/voice/audio without changing old values.
3. Extend workload CHECKs/column widths on provider capabilities, routing
   revisions/heads, work snapshots, budgets, usage attempts for transcription.
4. Extend provider operation CHECK for media_transcription.
5. Extend provider price basis/shape CHECK for transcription_request, and any
   capability locality/registry shape checks needed for safe new workload.

Discover exact existing constraint names and widths from current models and
0017 schema. No historical edits. Capability metadata is existing JSONB with
strict API/application validation; adding keys requires no extra column.
Provenance uses existing message metadata, requiring no backfill of false text.
Update current schema pins and affected validators. Retain VARCHAR(64) bootstrap.

## 35. Downgrade behavior

Reject downgrade if any media row or transcription registry/route/budget/usage
state exists; do not silently discard provenance or budget authority. On clean
state restore predecessor checks/widths and drop new table/unique constraint in
dependency order. Before activation empty-state downgrade is supported; after
activation disable media and retain schema or use an approved forward repair.

## 36. Configuration/secrets

New media enable and limits under existing JANUARY settings. No new secret
store/credential slot or content management API. Existing Groq key and existing
image-adapter keys remain external. Media enforce/rate/concurrency dependencies
are validated; selected route determines model rather than a hidden default.
Document model format/capability/pricing publication. Unknown route degrades.

## 37. Telemetry

Add `january_telegram_media_operations_total` and duration histogram with only
closed kind (`photo`,`voice`,`audio`,`unsupported`), stage (`prepare`,`download`,
`transcription`,`generation`,`cleanup`), outcome/reason enums. Extend existing
provider metrics for transcription workload/op, never arbitrary model/IDs.
Validate all label values against catalog. Emit failures and ambiguity honestly;
do not report every worker iteration as success. Audits remain content-free;
message_media state is content-governed metadata, not an audit event payload.

## 38. Test strategy

Use deterministic httpx transports and fake providers/limiters; no credentials.
Unit: full normalization/selection/caption/text/sticker regression, format/path/
redirect/size/timeout/truncation checks, encoded payloads, response caps, safe
logs/tracebacks, registry/route/budget validation and unknown usage.
PG integration: ingress idempotency, exact attachment binding, transcript replay,
lease reclaim/active lease/late result, possible-I/O crash, pre-I/O denials,
export/erasure during I/O, multi-batch retention, final outbox and safety.
Redis: existing limit/semaphore tests plus governed fake transcription boundary.
No tests weakened or excluded to make a validator pass.

## 39. Validator strategy

`scripts/validate-telegram-media.sh`: set -euo pipefail; focused media/Telegram/
provider/regression units first with JANUARY_ENVIRONMENT unset; optional explicit
repository-only mode returns nonzero pending status, never false success.
Default uses isolated Compose project/alternate ports, readiness checks,
migration lifecycle, media/affected PG+Redis proof, fake runtime and guard proof.
Trap removes only its own resources. Integrate CI and schema pins. General and
affected validators remain required; inspect known provider-race/guard debt if
it fails affected proof, do not silently waive it.

## 40. Docker/runtime proof

This goal's one Docker check returned socket permission denied (65534:65534,
660; execution uid1000). No modifications/retry. Encode and collect live tests;
run all repository-safe proof. If access remains unavailable, explicitly mark
only Docker-only integration/migration/runtime proof pending. Deterministic fake
worker startup needs no real Telegram/provider credentials.

## 41. Rollback

Disable media first. Preserve existing text/sticker path and schema after media
activation. Stop provider-calling workers for incompatible binary rollback.
Never discard governed attempts, revive redacted content or downgrade away
privacy state. Backups obey current erasure reconciliation runbook.

## 42. Risks and threat model

| Threat | Control and negative proof |
| --- | --- |
| Bot-token leakage | Secret URL confined to adapter; HTTP log sanitization, no exception chain; log/traceback tests |
| Arbitrary URL/SSRF | getFile-only origin, no redirects/user URL, relative-path grammar; malicious path tests |
| file_path manipulation | Reject traversal, absolute/encoded/query/fragment/backslash paths; never local open |
| Oversized file/memory exhaustion | Declared+stream count+JPEG dimensions+overall timeout+body cap; lying-length tests |
| Temp leaks | No temp files; bounded byte lifetime with finally/cancellation tests |
| Duplicate Telegram update | Existing unique inbox plus source-message/attachment uniqueness; concurrent replay |
| Duplicate transcription | Stable durable attempt/state and one possible I/O; crash/replay tests |
| Crash after/ambiguous I/O | Conservative debit and ambiguous media terminal notice; no auto resend/retranscribe |
| Cross-conversation/tenant reuse | Canonical chained scope and configured bot binding, no arbitrary reference API; foreign tests |
| Transcript privacy leak | Exact export projection, immediate erasure, fresh preflight and stale-result fencing |
| Raw media logging | No bodies/base64/references in telemetry, repr suppression, exact negative tests |
| Unsupported fallback bypass | Capability+bound recheck on every attempt; legacy media denied; non-vision fallback excluded |
| Stale worker overwrite | Unique token+claim ordinal+expiry+source edit/privacy checks on every transition |
| Misleading costs | Missing usage retained, fixed conservative operator estimates explicitly non-billing |

## 43. Expected files changed

New domain/application media values/service, Telegram media support, database media
repository/model, typed transcription adapter/gateway support, migration0019,
unit/integration media tests, validator, ADR-0025 if final decision warrants.
Modify normalizer/conversation/context/prompt/planning/provider admission/API/
telemetry/privacy/retention/export/config; schema-head pins; CI; relevant product,
architecture, provider/Telegram/governance/operations/local-development docs.
No unrelated debt cleanup or committed migration rewrites.

## 44. FR/NFR traceability matrix

| Requirement | Implementation surfaces | Direct proof |
| --- | --- | --- |
| FR-01 | domain/media, normalizer, message model | text/sticker/photo/voice/audio normalization |
| FR-02 | pure photo selector | reordered variants, oversize, unknown size, albums |
| FR-03 | caption entities, context/prompt, typed command guard | UTF-16 mentions, caption/transcript command denial |
| FR-04 | ingress/conversation/media unique/FK | duplicate update/message, wrong scope |
| FR-05 | Telegram getFile/downloader | injected URL/path/redirect/log negative cases |
| FR-06 | settings, streaming, signatures/body parser | size/time/length/MIME/dimension tests |
| FR-07 | byte values and finally lifetimes | cancellation/failure, no file or DB bytes |
| FR-08 | Groq transcription port/adapter | OGG/MP3 request and fake success/unavailable |
| FR-09 | media repository and messages provenance | exact derived text/caption commit once |
| FR-10 | media/usage ledger recovery | complete replay, no-I/O reclaim, crash after I/O |
| FR-11 | GenerationRequest/serializers/planning_service | image retained on retries; incompatible fallback denied |
| FR-12 | shared governed core + runtime preflight | each denial zero I/O, attribution revocation |
| FR-13 | workload/price/registry/reservation changes | independent balances, image bound, missing price |
| FR-14 | usage classification/reconciliation | missing/partial/invalid reports and ambiguous debit |
| FR-15 | fixed localized candidate/existing outbox | exact notices, reply/thread, duplicate actions |
| FR-16 | eligibility and existing moderation | paused/protected/group unaddressed no I/O |
| FR-17 | no media memory calls; existing recall | no UPSERT/personal mutation; recall regressions |
| FR-18 | governance subject projection | own export, group/deployment exclusion |
| FR-19 | privacy/media repository fencing | erase during download/provider and late completion |
| FR-20 | retention batch and media preflight | >batch rows, expired read denied, repeat empty |
| FR-21 | catalog, log safety, fixed errors | capture metrics/logs/audits/tracebacks |
| FR-22 | existing control-plane validators/roles | operator vs tenant and cross-scope denial |
| FR-23 | media enable and fixed failure path | disabled/legacy/observe/no-capability no I/O |
| FR-24 | existing worker composition/settings | startup/config validation and restart fake proof |
| NFR-01 | PostgreSQL media aggregate | inspect persistence/Redis/Qdrant payloads |
| NFR-02 | repository/I/O split, preflight callbacks | pool/session assertion while fake I/O blocks |
| NFR-03 | limits and retry state | adversarial bounds/cancellation/replay tests |
| NFR-04 | unique FK/source/owner/ordinal | race/reclaim/same-owner stale result |
| NFR-05 | scope/privacy/admission gates | each fail-closed negative case |
| NFR-06 | deterministic adapters | canonical suite requires no real tokens |
| NFR-07 | migration0019 + pins | 0018→0019→0018→0019; base/head cycles; guard |
| NFR-08 | general/dedicated/affected validators | recorded exit status and full matrix |

## 45. Implementation phases

1. Domain/normalization/security download + focused tests.
2. Schema/media repository/provenance/privacy/export/retention + PG tests.
3. Shared provider admission extensions/transcription/multimodal + gate tests.
4. Planning integration, recovery/fencing, context/outbound/safety regression.
5. Validator/CI/pins/docs/ADR, full regression and migration/runtime evidence.
6. Skeptical independent audit, fixes/retests, completed plan and final handoff.

## 46. Acceptance checklist

- [x] All FR/NFR rows mapped to implementation and tests; live proof explicitly pending.
- [x] Source/unit checks for no raw bytes/secret URL in persistence/logs/metrics/audit.
- [x] Shared admission and transaction boundaries reviewed; live race proof pending.
- [x] Transcript/privacy and current-only photo design implemented; no memory writes.
- [x] Negative tests for lease, expiry, scope, format, bounds and ambiguity added.
- [ ] Docker-only: live migration cycles and destructive-state guard execution.
- [x] Focused/general/affected repository-safe matrix and truthful pending evidence.
- [x] No open repository Critical/High defect; final handoff and exact git status.
- [x] No staging/commit/push, historical rewrites, or SPEC-029.
