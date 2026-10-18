# SPEC-028 — Rich Telegram Media and Voice Interactions

Date: 2026-09-08

Status: **APPROVED PRODUCT SPEC**. Implementation is authorized by the Product
Owner's SPEC-028 end-to-end goal; repository delivery and release proof are
in progress. This approval is not production activation or compliance approval.

## Purpose and problem statement

Lumi currently accepts Telegram text and stickers but cannot understand a
photo or a spoken message. Captions are treated as ordinary text while media
itself is ignored. Users should be able to address Lumi with a photo or short
voice note without creating a permanent file archive, inferred personal memory,
or an ungoverned provider-call path.

## Goals

- Understand an eligible Telegram photo on its current processing turn.
- Transcribe eligible short voice notes and supported audio, then use existing
  safe conversation planning to answer in text.
- Preserve authoritative PostgreSQL state, durable inbox/outbox, exact scope,
  privacy, explicit-only memory, and SPEC-026 provider admission/accounting.
- Make unavailable, oversized, unsupported, and ambiguous work deterministic.

## Explicit non-goals

No TTS, synthesized replies, video/video-note understanding, arbitrary document
parsing, document RAG, OCR subsystem, archive/executable processing, image
generation, permanent raw-media storage, new vendor, new platform, proactive
messaging, scheduled participation, album aggregation, new identity model,
multi-assistant tenancy, or billing system. SPEC-014 remains deferred on Zalo
prerequisites. SPEC-029 is not started.

## User stories

1. In a private conversation, I send a photo and optional caption and receive
   a relevant text reply when the configured provider supports it.
2. I reply to Lumi in a group with a voice note and receive a text response
   without activating ambient transcription of every group recording.
3. I can export or erase my derived transcript like my typed message content.
4. As an operator, I can disable media, govern transcription independently,
   observe bounded outcomes, and diagnose failures without seeing raw media.

## Terminology

| Term | Meaning |
| --- | --- |
| Telegram `file_id` | Bot-scoped fetch reference; not an identity or public URL |
| Telegram `file_unique_id` | Platform file metadata; not a fetch credential or identity key |
| Media metadata | Bounded kind, selected file references, size/dimension/duration and processing state scoped to one durable message |
| Raw ephemeral media | Downloaded bytes existing only during bounded in-memory processing |
| Caption | User-authored text accompanying media, not a generated description |
| Transcript | Provider-derived representation of spoken user content; may be inaccurate |
| Durable transcript | Successful bounded transcript saved as canonical derived user-message content with voice/audio provenance |
| Multimodal provider request | Existing generation request extended with current-turn image bytes in memory |
| Explicit memory | Content intentionally saved through existing deterministic memory controls; never automatically inferred from media |

## Supported media matrix

| Input | Accepted processing | Durable state | Raw retention | Capability | Failure |
| --- | --- | --- | --- | --- | --- |
| Photo | One bounded JPEG variant; current-turn understanding | Selected metadata, user caption, processing disposition; normal final reply | None after processing | `chat_generation` + explicit `image_input` | Fixed text fallback |
| Voice note | OGG/Opus transcription then ordinary response planning | Selected metadata; successful derived transcript/provenance | None after processing | Independent `transcription` + `speech_to_text` | Fixed text fallback |
| Audio | MP3 only, same bounded transcription pipeline | As voice; optional caption preserved separately | None after processing | Independent `transcription` + `speech_to_text` and MP3 support | Fixed text fallback |
| Video, video note, document, animation and other unsupported media | No fetch or model I/O for this media | Existing ingress/message metadata only, bounded and retained as before | Never downloaded | None | Fixed text fallback when addressed/eligible |
| Typed text and sticker | Existing behavior | Existing contract | Unchanged | Existing contract | Unchanged |

The v1 transcription adapter extends the existing Groq credential/HTTP family;
no processor is newly added. Image-capable existing adapters may be extended,
but only implemented adapter capabilities and an explicit operator-published
model capability can be selected. A provider name alone never proves vision.

## Ingress and caption semantics

Webhook and polling share existing authentication, deduplication and durable
normalization. A media attachment belongs to its source update/message and exact
conversation/Assistant/connection. File IDs never join users or conversations.
Choose one photo deterministically: greatest pixel area within declared byte
and dimension limits, then deterministic size/reference tie breaks. Unknown
file size is allowed only with enforced streaming limit; no suitable variant
receives the size/type fallback. Never download every thumbnail.

Preserve bounded captions as authored content, with caption entity semantics
for addressing. A caption or transcript must not execute a management command:
only typed command entities use the existing command path. Each album update
is independent. Edits do not re-transcribe or produce another response; stale
in-flight results cannot overwrite an edited or erased source.

Private messages follow existing eligibility. Group media requires explicit
addressing (caption mention/name under the existing response mode, or reply to
the assistant); no ambient media download/transcription is authorized. Paused,
inactive, bot-loop, privacy-deleted, and foreign-scope work remains suppressed.
Unsupported-media fallbacks obey those same eligibility/safety/delivery gates.

## File fetch semantics and media limits

Only authenticated Telegram `getFile` may resolve a stored source `file_id`.
Fetch only a validated relative `file_path` from that response, at the configured
Telegram API/file boundary. No message URL, redirect, absolute/local filesystem
path, URL credential, traversal, percent-encoded separator, query or fragment
is accepted. Never persist the resolved path or token-bearing URL.

Conservative defaults (operator-configurable within hard caps):

| Limit | Default and hard cap |
| --- | --- |
| Photo bytes | 5 MiB, cap 10 MiB |
| Audio/voice bytes | 5 MiB, cap 10 MiB |
| Photo maximum side | 1280 pixels, cap 4096 |
| Audio declared duration | 120 seconds, cap 300 seconds |
| Caption | 1024 Unicode characters |
| Transcript | 4000 Unicode characters, cap 8000; reject excess, do not silently truncate canonical content |
| getFile plus download wall time | 15 seconds, cap 60 seconds |
| Transcription wall time | 20 seconds, cap 60 seconds |
| Provider transcription response body | 64 KiB |
| Media per source message | One selected attachment |

Reject oversized declared sizes before downloading; enforce actual streamed
bytes even with absent/false Content-Length, reject truncated/empty downloads,
and validate container signatures and MIME consistency. Do not decode or
transcode media locally. Audio duration is Telegram-declared metadata, not a
claim of independent signal-duration verification. Bounds on bytes and I/O time
remain independent of that declaration. Image dimensions are checked against
JPEG header dimensions before provider use. Reject invalid/mismatched media.

## Voice transcription contract

Transcription is a distinct SPEC-026 workload. It needs a published route,
current eligible health, matching format capability, enabled deployment budget,
and any exact-scope resource budgets before provider I/O. It shares the existing
rate/concurrency architecture and cannot invoke an ungoverned fallback.

A successful nonempty bounded transcript is derived user content. Persist it
once with provenance (`voice_transcript` or `audio_transcript`), keeping the
caption distinguishable. It is not original typed text and is never a command,
explicit memory, personal context, or automatic semantic-index source.
After transcription, rebuild the authorized current context and pass ordinary
safety, response validation, generation budgets/rates/concurrency and outbox.

One durable transcription work identity per message. Replays after success
reuse the canonical transcript. Once provider I/O may have started, crash,
timeout or unknown result never causes automatic retranscription or fallback.
Mark unavailable/ambiguous and ask for typed text or a new user submission.
Pre-I/O failure may safely retry only within bounded durable recovery. V1 does
not require transcription fallback: one selected eligible route and one
possible external transcription per durable work is sufficient.

## Photo understanding contract

Image bytes accompany the current-turn generation request only. Extend the
existing provider abstraction and local structured-plan/safety validation; do
not add an independent vision planner. Every retry/correction/fallback retains
the image capability requirement and repeats admission. No eligible provider
means a fixed fallback, not caption-only success disguised as understanding.

Future history may retain the user caption, a bounded media/provenance marker,
and the normal delivered assistant reply under existing retention. No hidden
generated image description, summary seed, biography or image memory is stored.
The normal user-visible reply may discuss the image and is ordinary retained
conversation content, not a second image-description store.

## Persistence, recovery, and idempotency contract

PostgreSQL owns bounded attachment/recovery metadata and successful transcript.
Raw media lives only in bounded memory; no temporary file is required in v1.
No bytes/base64, remote download path, prompt or raw provider response enters
database payloads, Redis, Qdrant, audits or telemetry. References are released
on success, error, cancellation and retry; process exit releases memory, with
no secure RAM zeroization claim.

Media transitions use existing planning leases plus owner/attempt fencing and
one source-message identity. Non-expired owners cannot be stolen; terminal work
cannot be reopened by normal replay. Download can be repeated safely within
bounded recovery; possible provider I/O is conservative. No exactly-once external
I/O claim. Failed finalization cannot restore content after erasure, expiry,
edit or scope change. Durable privacy revision is rechecked at each media
external boundary and on completion. I/O already in flight cannot be retracted.

## User-facing failure behavior

Use short deterministic English/Vietnamese text through existing response plans
and outbound actions: unsupported type; too large/invalid format; media disabled
or unavailable; unavailable provider/budget; or uncertain transcription. Ask for
typed text (or a smaller supported photo/voice file for size rejection). Never
echo provider error bodies, captions, file references, transcripts, URLs or
credentials in a failure notice. Safety silence and privacy suppression take
precedence over the notice. A media-disabled deployment can process eligible
media notices without provider I/O; disabled global planning may leave the
existing worker stopped, an operational state rather than a bypass.

## Provider governance, usage and cost

Media provider I/O is enabled only in SPEC-026 `enforce` mode with configured
rate limiting and provider concurrency. `legacy`/`observe` media processing
degrades safely; existing text behavior in those modes is unchanged.

Generation/embedding/transcription budgets are separate workload partitions.
Vision uses chat-generation budgets with a declared conservative per-image
token reservation bound for the registered model, added to existing text bounds.
Never infer an image token bound from compressed byte count. Missing bound
denies media I/O. Transcription budgets support request count and operator-supplied
fixed maximum per-request estimated cost for the configured bounded input, not
invented audio-token units. Cost-only enforcement requires a valid price.
Missing token usage stays missing; partial/invalid reports stay classified.
Operator price estimates are not billing truth or a guarantee of provider fees.
Ambiguous I/O conservatively retains its reservation; no-I/O releases it.

## Safety, memory, privacy and authorization

Reuse SPEC-024 protection/abuse gates before expensive media I/O and ordinary
post-generation safety. Transcript/caption/image content is untrusted and
cannot alter system/action policy. Existing structural safety is not certified
semantic media moderation; no new classifier or moderation guarantee is claimed.

No automatic memory or personal context write and no semantic transcript/image
indexing. SPEC-027 recall remains unchanged. Exact source participant,
conversation, Assistant, connection and tenant attribution are revalidated;
no caller can request arbitrary stored file IDs. Existing deployment_operator
controls registry/routes/pricing; tenant roles get only existing bound budget
authority and no media-content inspection API.

## Export, erasure and retention

Subject exports include authorized retained transcript, caption, provenance and
bounded media metadata for that exact subject/conversation. File references
are platform identifiers, never public access links. Group/deployment exports
do not gain member media or transcript content. Update inventory and summary.
Erasure clears transcript/caption/file metadata, invalidates pending media and
derived responses/exports, and prevents stale writes. Existing group reset
remains memory/summary reset, not a new group-message erasure command.
Retention clears metadata and transcript within existing raw-content retention
(default/max 30 days); expired content is ineligible before physical batch
cleanup. No raw-media archive exists to export/delete. Telegram, provider and
backup copies remain external boundaries under the existing documented policy.

## Telemetry and concurrency

Only closed media kind/stage/outcome/reason and existing provider/workload
enums enter metrics. No caption/transcript/raw bytes, file ID/unique ID, URL/path,
user/Telegram/conversation ID, model string, token or secret as a label. Log
only fixed classes; suppress secret-bearing HTTP library URLs and exception
chains. Per-process memory is bounded by one active media item per sequential
planning loop and bounded request encoding; horizontal concurrency still uses
the shared provider semaphore. No DB session/lock spans external I/O.

## Functional requirements

| ID | Independently testable requirement |
| --- | --- |
| FR-01 | Normalize photo/voice/MP3 audio metadata and preserve unchanged text/sticker behavior |
| FR-02 | Select one deterministic within-bounds photo; reject no valid variant; albums independent |
| FR-03 | Preserve caption/provenance and caption addressing; never parse derived content as commands |
| FR-04 | Authenticate/deduplicate ingress and bind attachment to exact durable source/scope |
| FR-05 | Resolve getFile through configured Telegram boundary only; reject unsafe paths/redirects |
| FR-06 | Enforce declared/streamed byte, time, format, dimension and transcript/body limits |
| FR-07 | Keep bytes ephemeral, no temp archive, and release references on every exit |
| FR-08 | Transcribe OGG/Opus and MP3 through implemented existing-provider capability |
| FR-09 | Persist successful transcript exactly once with explicit derived provenance |
| FR-10 | Replays reuse transcript; expired pre-I/O work recovers; ambiguous I/O never retranscribes |
| FR-11 | Photo is current-turn multimodal generation with capability-safe retries/fallback |
| FR-12 | Every media provider call crosses enforced authorization/health/budget/rate/concurrency gates |
| FR-13 | Separate transcription budgets and usage; image reservation includes explicit model bound |
| FR-14 | Preserve missing/partial/invalid usage and estimated-not-billing cost semantics |
| FR-15 | Deliver deterministic bounded notices through existing safe durable text outbox |
| FR-16 | Apply existing safety/protection; group media is addressed-only, never ambient |
| FR-17 | No automatic memory/personal-context/vector writes; recall behavior unchanged |
| FR-18 | Export own transcript/metadata only; group/deployment expose no new member content |
| FR-19 | Erasure immediately invalidates media and clears content/references; stale writes fail |
| FR-20 | Bounded retention clears media-derived state and denies expired reads/I/O |
| FR-21 | Closed content-safe logs/metrics/audits; bot token absent including error paths |
| FR-22 | Reuse operator versus tenant authorization; no new content-access API |
| FR-23 | Disabled/unavailable/unsupported media fails safely without provider I/O |
| FR-24 | Deploy through existing workers with configuration/lease validation and recovery proof |

## Non-functional requirements

| ID | Independently testable requirement |
| --- | --- |
| NFR-01 | PostgreSQL authoritative; Redis/Qdrant receive no new media payload |
| NFR-02 | No DB session/lock across getFile, download, provider, Qdrant or outbound I/O |
| NFR-03 | Bound memory, wall time, retries and cleanup, including negative input tests |
| NFR-04 | Owner/attempt/source fencing prevents replay duplicates and stale completion |
| NFR-05 | Fail closed across privacy/tenant/provider boundaries without new identity |
| NFR-06 | Deterministic fake adapters prove behavior without production credentials |
| NFR-07 | One additive next migration, guarded downgrade and full lifecycle validation |
| NFR-08 | Preserve SPEC-001–027 regressions; fail-fast dedicated and affected validators |

## Acceptance criteria

All FR/NFR rows require direct tests mapped in the design, including negative
security cases. Demonstrate ingress→durable media→governed fake provider→safe
plan→existing outbound; replay after success/claim/I/O; active and stale leases;
cross-scope denial; privacy during I/O; multi-batch expiry; no secret in logs or
raw media in persistence. General, dedicated and affected validation must pass.
Docker-only proof may be explicitly pending when the agent socket is unavailable,
but no repository-owned Critical or High issue may remain for candidate approval.

## Migration expectation, risks and external prerequisites

Actual predecessor: `0018_user_controlled_memory`. Add the next revision without
editing committed history. Preserve central Alembic VARCHAR(64) bootstrap.
Guard destructive downgrade once media-derived/governed state exists.

Risks: transcription errors, provider ambiguity, malicious formats, secret URL
logging, privacy races, inaccurate operator price bounds. Mitigate through
bounded formats, no local decoding, conservative durable attempts, strict scope,
safe failures and independently tested cleanup. Existing provider-race proof and
stale release-document wording are audit debt, not waived media acceptance.

External: Telegram bot configuration; approved existing provider/model credentials,
media capability/data-class publication, conservative price/budget/health values;
encrypted infrastructure/backups, logging policy, production rollout and operating
owner acceptance. No legal/compliance or production acceptance is self-approved.

## Future work

TTS, video, document RAG, OCR subsystem, image generation, proactive/scheduled
participation, album aggregation, other codecs/vendors/platforms and expanded
tenancy need future Product Owner authority. SPEC-029 — not started.

## Audit references

Repository baseline `private-source-checkpoint-omitted`; SPEC-025/026/027
handoffs, ADR-0003/0004/0006/0015/0023/0024, current normalizer, provider gateway,
planning/context/privacy/retention repositories are primary implementation inputs.
Official protocol references checked 2026-09-08:
[Telegram getFile](https://core.telegram.org/bots/api#getfile),
[Groq transcription](https://console.groq.com/docs/speech-to-text), and
[OpenAI image inputs](https://developers.openai.com/api/docs/guides/images-vision).
These establish protocol support, not production model enablement or pricing.
