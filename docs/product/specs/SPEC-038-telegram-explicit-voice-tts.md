# SPEC-038 — Explicit Telegram Voice Playback / TTS

Date: 2026-09-20

Status: **APPROVED PRODUCT SPEC**. The Product Owner's bounded SPEC-038 goal
authorizes implementation and development validation. This approval is not
production activation, compliance approval, or a claim that global Quality CI
is green.

## Purpose

Lumi can understand inbound Telegram voice notes but cannot explicitly play an
existing assistant answer as a voice note. `/voice` adds a user-controlled
presentation of one retained, locally authoritative assistant response. It does
not create, revise, summarize, translate, or regenerate conversational content.

## Goals

- Reply to an assistant answer with `/voice` and receive that logical answer as
  one Telegram voice message.
- Resolve the source exclusively through current PostgreSQL authority, including
  split-response chunks and regenerated answers.
- Govern the one TTS request through the existing SPEC-026 routing, admission,
  budget, rate, concurrency, usage, timeout, and recovery boundaries.
- Persist one bounded, short-lived delivery artifact so Telegram retries never
  repeat TTS.
- Reuse durable outbound delivery and its conservative uncertain-delivery
  behavior without adding semantic history, memory, RAG, media, presence, or
  reaction side effects.

## Non-goals

No automatic voice replies, preference for always-voice, voice cloning, speaker
impersonation, custom voices, SSML, rewriting, summarizing, translation, user
message synthesis, arbitrary command text, URL or filesystem synthesis,
streaming/partial audio, scheduled/proactive/ambient/reaction-driven voice,
media retranscription, TTS dashboard, generic asset service, Zalo, or SPEC-039.

## Entry point and failure UX

The only v1 entry point is an argument-free `/voice` command that is a direct
reply to a locally authoritative outgoing assistant text message. `/voice`
without a reply, `/voice any text`, a reply to a user message, or any unresolved
target receives one deterministic command response. There is no “most recent
answer” fallback and Telegram's quoted body is never source authority.

The closed command-result categories are:

| Category | Meaning |
| --- | --- |
| `voice_target_unavailable` | Missing, foreign, non-assistant, undelivered, erased, redacted, expired, uncertain, or otherwise non-authoritative target |
| `voice_too_long` | Authoritative logical response exceeds 4,000 Unicode code points |
| `voice_tts_unsupported` | No eligible configured OpenAI speech capability or unsupported deployment configuration |
| `voice_tts_admission_denied` | Budget, rate, concurrency, or current governance admission denied before provider I/O |
| `voice_tts_generation_failed` | Definitive provider failure or invalid/empty/oversized output |
| `voice_tts_generation_uncertain` | Provider may have processed the request; no automatic repeat is allowed |
| `voice_delivery_uncertain` | Operational classification only; do not send an additional explanatory Telegram message because that could duplicate user-visible output |

Messages are short, code-owned, English/Vietnamese, and never expose provider
responses, credentials, source text, identifiers, or artifact data.

## Target and source authority

Resolution is exact:

```text
/voice command message
→ local reply_to_message_id
→ delivered outgoing assistant text message
→ originating or delivered edit outbound action
→ response plan
→ logical assistant response text
```

Every edge must retain the current tenant, Assistant, Telegram connection, and
conversation. The conversation, connection, Assistant, and tenant must remain
active; the command lease must still be owned; and the message/action/plan must
be delivered, non-uncertain, retained, non-erased, and non-redacted. Foreign
tenant, Assistant, connection, conversation, response plan, or outbound chunk
fails closed before provider I/O.

The source is `response_plans.text`. That field already represents the logical
response before SPEC-034 delivery splitting, so replying to any delivered text
chunk synthesizes the same whole answer. Sticker actions and reaction/delivery
metadata are excluded. For a SPEC-036 edit, the delivered message resolves
through the delivered `edit_text` action to that regeneration plan; it does not
jump to the root answer or combine versions.

No Telegram quoted body, remote message fetch, prompt snapshot, raw provider
log, Qdrant point, memory, knowledge chunk, or prior audio artifact may supply
or recover source text.

## Text semantics and limits

TTS receives the authoritative plan text exactly as retained. No LLM call,
normal text-generation request, safety rewrite, summary, translation, markdown
rewrite, or semantic normalization is permitted. JSON serialization by the
provider adapter is transport encoding, not content transformation.

The maximum source is exactly **4,000 Unicode code points**, checked before any
provider admission or I/O. Empty text is unavailable. There is no truncation:
4,001 code points is rejected. The limit is below OpenAI's current 4,096
character speech input limit and bounds duration, cost, memory, and output.

## TTS provider and format

V1 implements one common `TextToSpeechPort` and one production adapter:

- provider/adapter: OpenAI only;
- endpoint capability: speech synthesis, never chat completions;
- default model: `gpt-4o-mini-tts`;
- product-owned voice: one default companion voice, infrastructure identifier
  `alloy`;
- speed: provider default `1.0`;
- response format: native `opus`;
- durable MIME/format: `audio/ogg` / `ogg_opus`;
- Telegram filename: fixed `voice.ogg`;
- provider wall timeout: 30 seconds;
- maximum accepted provider body and artifact bytes: exactly **5 MiB
  (5,242,880 bytes)**.

The adapter accepts only non-empty native Ogg/Opus output with an Ogg envelope,
an allowed audio content type, and at most 5 MiB. It streams and enforces the
actual byte count even when `Content-Length` is absent or false. It never trusts
`Content-Disposition`, executes bytes, follows a provider-supplied URL, or
derives a filesystem path. No FFmpeg or conversion dependency is introduced.

The current Telegram Bot API accepts OGG/Opus multipart voice uploads up to
50 MB, so the 5 MiB product limit is intentionally stricter. Duration is not
stored or enforced because this provider response does not supply a trustworthy
duration; source and byte limits remain authoritative.

Other configured provider families are not advertised as TTS-capable. Missing
or non-OpenAI capability, wrong format/voice/limits, or missing credential fails
closed before external I/O.

## Provider governance

Text-to-speech is a distinct `text_to_speech` workload and `voice_synthesis`
operation in the existing SPEC-026 system. Enforced operation requires:

- an eligible current route/capability with `text_to_speech=true`, OpenAI
  adapter, `ogg_opus`, source/byte bounds, and approved external data class;
- an active deployment budget and any exact-scope Assistant/connection budgets;
- request-based price/reservation accounting (`tts_request`), with operational
  microusd estimates explicitly not billing truth;
- TTS-specific limiter keys at deployment, connection, conversation,
  participant, and provider scopes, using the repository's already-authorized
  generation quota values rather than inventing a second quota policy;
- the existing provider concurrency gate;
- one durable usage attempt with one request at most.

`legacy` and `observe` modes do not authorize TTS. Budget, rate, concurrency,
unavailable-route, or configuration denial produces zero raw TTS calls.
Successful output records missing token usage rather than fabricating tokens;
request count and the selected price estimate provide accounting.

## Durable TTS work and possible-I/O behavior

One `telegram_voice_generation_job` is uniquely owned by one durable Telegram
command job and binds the exact source plan, tenant, Assistant, connection,
conversation, source text hash/length, and privacy revision without copying the
text. The command worker may execute it; no separate service is required.

The flow is:

1. lock and validate command/target, then create or reuse the one TTS job;
2. resolve and reserve the governed provider attempt;
3. apply TTS rate and provider-concurrency admission;
4. durably mark provider `io_started` and the TTS job possible-I/O;
5. close every database session/transaction;
6. perform one bounded TTS request;
7. reopen a short transaction, lock the job/command, and revalidate lease,
   privacy revision, source plan, conversation, connection, Assistant, tenant,
   and provider attempt;
8. atomically persist READY artifact, SEND_VOICE action, and terminal generation
   state.

A definitive pre-I/O denial can finish with deterministic text. Once provider
I/O is marked started, timeout, reset, cancellation after dispatch, worker crash,
or unknown completion is conservative possible-I/O: retain the reservation,
record uncertainty, create no artifact/action, and never automatically call TTS
again. No exactly-once external provider claim is made.

If authority or ownership becomes stale after provider output, no READY artifact
or active outbound voice action is created. Returned bytes are discarded and
the job is terminal stale/quarantined metadata only.

## Generated voice artifact

The repository has no suitable blob service, so v1 uses a narrowly scoped
PostgreSQL `generated_voice_artifacts` row with bounded `BYTEA`. It contains:

- opaque ID and the unique voice-generation job;
- exact tenant, Assistant, connection, conversation, and source response plan;
- closed `ogg_opus` format and `audio/ogg` MIME;
- bytes, exact byte size, SHA-256 checksum;
- `ready` or `purged` state, creation, delivery-terminal, expiry, and purge
  timestamps.

It never duplicates source text and is a sensitive delivery artifact, not a
message, response plan, memory, summary, knowledge document, semantic point, or
prompt input. Database constraints and composite foreign keys enforce exact
scope, format, size 1..5,242,880, immutable source identity, and one artifact
per generation job.

READY artifact creation and the one pending `SEND_VOICE` outbound action occur
in the same transaction. The action holds a same-scope artifact reference and
replies to the `/voice` command message, not the source assistant message,
regeneration target, arbitrary chunk, or foreign message.

## Retention, erasure, export, and backup

Bytes remain available while the voice action is nonterminal. After confirmed
delivery, permanent rejection, skip, or delivery-unknown classification, the
artifact receives a terminal timestamp and expires exactly **24 hours** later.
Independently, every artifact has a hard expiry exactly **7 days after
creation**. The earlier deadline wins. At expiry the retention worker sets
`bytes=NULL`, state `purged`, and a purge timestamp; size/checksum may remain as
content-free integrity metadata. A nonterminal action whose hard-expired bytes
are purged becomes quarantined/permanently unavailable and can never send.

Privacy erasure, source response redaction, or conversation erasure wins
immediately over delivery: purge bytes and make pending/leased voice delivery
ineligible. A stale worker cannot restore or send them. No old Telegram quote,
log, vector, or artifact can resurrect source content.

Generated audio is excluded from subject/group semantic exports. While live it
is included naturally in authoritative PostgreSQL backups so artifact/action
referential integrity can be restored; restore validation must prove a live
pair remains internally consistent. Backup retention/deletion limitations stay
those already documented by SPEC-025. Purged bytes remain absent from new
backups.

## Durable SEND_VOICE delivery

Add typed outbound kind `voice`/`SEND_VOICE` to the existing outbox. The normal
worker claims and revalidates it, loads no more than the configured 5 MiB trusted
artifact into a bounded snapshot, commits/closes the session, durably marks the
delivery attempt externally started, then calls Telegram `sendVoice` with:

- the action's authoritative chat and thread;
- multipart field `voice` containing the trusted bytes;
- fixed filename `voice.ogg` and MIME `audio/ogg`;
- `reply_parameters` for the `/voice` command message when currently valid.

No user URL, provider URL, local path, filename, caption, or source text enters
the request. The raw Telegram call occurs with zero checked-out database
connections. Finalization reopens a session and revalidates the action lease.

Definitive no-send/rejection retries reuse the same artifact and never call TTS.
If Telegram may have received the upload but the response times out/resets, the
existing attempt becomes `delivery_unknown`, the action is quarantined, and no
immediate resend or explanatory message occurs. No exactly-once delivery claim
is made. Existing invalid-reply fallback may retry once without reply metadata
using the same artifact only when Telegram definitively rejected the request.

Voice delivery creates an outgoing operational message/link for delivery audit
if required by the existing worker, but it contains no text and is excluded
from conversational semantic context. The original source response remains the
only assistant answer.

## Idempotency and abuse bounds

Existing update/inbox and command-job uniqueness plus a unique voice job,
artifact, and action guarantee one accepted work identity per Telegram update.
Replay and concurrent duplicate processing yield one governed attempt, at most
one raw TTS call, one artifact, and one SEND_VOICE action.

One command produces one synthesis; there is no batch mode, TTS retry storm, or
fallback provider. Exact input/output bounds, enforced budget/rate/concurrency,
30-second timeout, and seven-day artifact ceiling bound cost and storage.

## Feature separation

For `/voice`, all of the following deltas are exactly zero:

- normal text-generation provider calls and regeneration jobs;
- typing, recording, uploading, or other presence calls;
- reaction calls;
- memory items/events and semantic-memory jobs/Qdrant access;
- knowledge documents/revisions/chunks/jobs and RAG retrieval;
- summaries;
- inbound media downloads, vision calls, and transcription calls.

An answer originally produced from media still uses only its retained assistant
plan text. The source has already passed generation safety; current privacy and
authority are revalidated without another LLM safety rewrite.

## Privacy and observability

Audio and source text are sensitive conversation-derived data. Never log audio,
base64/hex/snippets, source text, request bodies, provider bodies, tokens,
Telegram bot token, or provider credential. Exceptions and diagnostics use
closed categories only.

Metrics may use only low-cardinality enums: TTS admission/result/provider
family, voice delivery result, artifact lifecycle state, and size bucket. They
must not label tenant, Assistant, connection, conversation, user/chat/message,
plan, job, artifact, source text, or bytes.

## Evaluation and validation contract

SPEC-032 gains 15 offline deterministic scenarios covering valid reply, missing
reply, user/foreign targets, split and regenerated answers, erasure, input
limit, admission denial, successful artifact/action, delivery failure without
TTS repeat, ambiguous delivery, duplicate command, and zero memory/knowledge
writes. Hard gates measure exact target authorization, provider calls,
admission, artifact/action counts, rewriting, forbidden writes, Telegram
attempts, and ambiguous duplicates; a production mutation must fail them.

Unit and live PostgreSQL integration proof covers exact input/output boundaries,
provider validation, multipart bytes, scope constraints, admission modes,
possible-I/O fencing, atomic activation, stale-authority and duplicate races
with barriers, both zero-session I/O boundaries, privacy deletion, retention,
retry reuse, delivery uncertainty, and all prohibited side effects. Canonical
eval uses synthetic bytes and no external credentials or network.

Migration `0025_telegram_voice_tts` is required because current schema cannot
represent the TTS work identity, bounded durable bytes, or artifact linkage.
Downgrade is refused while any voice job, artifact, SEND_VOICE action, TTS
provider usage/snapshot/budget/routing state, or related live state exists.

## External contract basis

The implementation is based on the official Telegram Bot API `sendVoice`
contract and official OpenAI `POST /v1/audio/speech` contract audited on
2026-09-20. Operational owners must re-verify changing provider/platform limits
before production activation; product caps remain authoritative even when an
external limit is larger.

## Acceptance requirements

SPEC-038 is an approved development candidate only when all 44 mandatory proofs
in the task brief pass, Critical and High findings are zero, the dedicated
validator and VCS-free candidate pass, and every new SPEC-038 regression is
resolved. The known six `fk_assistants_tenant` reliability failures remain
unmasked Product Owner-deferred global CI debt and prevent a globally
release-ready claim.
