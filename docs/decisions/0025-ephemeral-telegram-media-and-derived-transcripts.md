# 0025 Ephemeral Telegram Media and Derived Transcripts

Date: 2026-09-10

## Status

Accepted design under the SPEC-028 Product Owner authority; implementation
candidate remains under validation.

## Context

Photo and voice understanding must preserve durable delivery, privacy erasure,
explicit-memory boundaries and provider-budget admission without introducing a
raw-media archive or a second provider system.

## Decision

- Bind one bounded attachment to its originating PostgreSQL message and
  conversation. Telegram file identifiers permit recovery, not identity joins.
- Fetch only authenticated getFile paths at the configured Telegram boundary.
  Validate relative paths, byte count, type and time; hold bytes in bounded
  memory, never an application archive, logs or audit payloads.
- Extend the existing generation request with a current-turn image. Require
  registered image capability and an operator-supplied image reservation bound.
- Use the existing Groq adapter family for bounded OGG/MP3 transcription and
  the shared SPEC-026 admission core. Separate transcription request/cost budgets
  from generation and embedding. Unknown usage remains unknown; fixed request
  pricing is an operational estimate, never billing truth.
- Persist successful transcripts as derived user-message text with provenance,
  preserving captions separately. Apply subject export, live erasure and the
  original message's retention deadline. Never create implicit memory, personal
  context, semantic points or hidden image descriptions.
- Fence preparation and finalization by source, claim ordinal, expiry and privacy
  revision. A possible transcription I/O attempt is not automatically repeated.
  Existing planning/outbound workers remain the delivery topology.

## Alternatives Considered

1. Permanent object-store archive: outside authority and increases privacy scope.
2. Independent vision/transcription worker/provider pipeline: duplicates admission
   and weakens the existing recovery boundary.
3. Automatic transcription retries after ambiguous I/O: risks uncontrolled cost
   and cannot establish exactly-once external execution.

## Consequences

Positive:

- Existing authorization, privacy, budgeting and durable outbox remain authoritative.
- No new vendor, codec process, raw-media store, worker service or identity model.

Tradeoffs:

- Album photos are processed independently; unsupported media receives a text
  notice. No TTS, video, document parsing or image-generation product is added.
- Telegram/provider copies are external. Application cleanup does not claim
  deletion of their copies or historical backups.
- Media requires enforce mode, configured eligible models, rate coordination
  and provider concurrency. Missing prerequisites degrade safely.

## Follow-Up

- Complete the SPEC-028 validation matrix and operating-owner rollout review.
- SPEC-029 — not started.
