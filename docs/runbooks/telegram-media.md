# Telegram Media Operations — SPEC-028 Candidate

Status: implementation candidate under final validation. This guide does not
authorize production rollout or certify compliance.

## Enablement

Use the existing conversation and response-planning workers, provider-governance
recovery worker, retention worker and outbound worker. No media worker or store
is added. Apply migration `0019_telegram_media` after `0018_user_controlled_memory`.

Keep `JANUARY_TELEGRAM_MEDIA_ENABLED=false` until an operating owner supplies:

- The existing Telegram bot credential and its exact PlatformConnection ID.
- `JANUARY_PROVIDER_GOVERNANCE_MODE=enforce`, existing recovery/control-plane
  configuration, rate limiting and `JANUARY_PROVIDER_CONCURRENCY_ENABLED=true`.
- An authorized chat routing policy with eligible registered model capability
  `image_input=true` and positive `maximum_image_input_tokens`. Only implemented
  OpenAI-compatible image adapters qualify; registration does not prove the
  external model supports images, which remains operator verification.
- For voice/audio, an existing Groq credential and a transcription capability:
  `speech_to_text=true`, audio formats `audio/ogg` and/or `audio/mpeg`, bounded
  maximum audio bytes/duration. Routing uses workload `transcription`, required
  current health and approved external data class.
- Independent transcription request/cost budgets and an operator-supplied
  `transcription_request` price when estimated-cost enforcement is desired.
  Estimates are not invoices; missing token usage remains unknown.

Only deployment operators manage deployment-wide provider configuration. Tenant
roles retain only their existing resource authority. No media-content API or
cross-conversation file lookup is added.

## Bounds and behavior

Defaults: 5 MiB photo/audio, JPEG side 1280, declared audio duration 120 seconds,
caption 1024 characters, transcript 4000 characters, download 15 seconds and
transcription 20 seconds. Configurable hard caps are 10 MiB, side 4096, duration
300 seconds, transcript 8000 and each media timeout 60 seconds. Oversize responses
are rejected, not silently truncated. Transcription JSON is capped at 64 KiB.
Planning and provider leases must exceed the relevant call timeout.

The downloader accepts only a validated relative path returned by authenticated
getFile at the configured Telegram origin. It rejects redirects, arbitrary
URLs, local absolute paths, traversal and MIME/signature mismatch. Do not enable
HTTP request-body logging or debug tooling that captures credentials/content.

One bounded photo variant is selected; album updates remain independent. Voice
notes use OGG/Opus and supported audio uses MP3. Unsupported, disabled or
unavailable processing returns a bounded text notice. Text/sticker outbound
delivery and ambiguous-send quarantine remain unchanged. There is no TTS.

## Recovery and privacy

PostgreSQL media state records source metadata and preparation lease/ordinal,
not raw bytes. Expired pre-I/O preparation is reclaimable. A possible external
transcription call is never automatically repeated; the user can send a new
message after an ambiguous result. Do not manually reset ledger/media states to
force replay. No exactly-once external execution is claimed.

Successful transcripts are derived user content in messages, with provenance
and a separate caption. They are eligible for ordinary authorized context, not
automatic explicit memory or personal-context writes. Images are current-turn
only; no hidden image-description store is created. Existing user-controlled
recall remains unchanged.

Subject exports include retained source-scoped transcript/metadata. Erasure
clears content and file references; privacy/edit/lease fences deny stale writes.
Retention uses the original message deadline, not transcription time. Raw bytes
exist only in bounded processing memory. Telegram/provider copies and historical
backups remain under their existing external retention/erasure policies.

## Validation and rollback

Run `./scripts/validate-telegram-media.sh` against its dedicated disposable Compose
project (default database port 5440, Redis 6387). It uses fake external adapters,
not production credentials. It proves predecessor/head/base cycles before
creating test media, then requires a guarded downgrade refusal. It cleans only
its dedicated temporary project. Do not point this validator at production data.

`--repository-only` runs safe focused tests and exits **2** to clearly report
Docker proof pending; it is not equivalent to a fully passed validator.

Operational rollback is feature-disable first. Existing text flows remain.
Do not downgrade a database with retained media/transcription state: the guard
intentionally refuses it. Reconcile/export/erase under the existing approved
governance process before considering a schema rollback; do not bypass guards.

Operating-owner prerequisites remain: real model format/capability verification,
prices and production budgets, encryption/key ownership, retention/backup purge,
production rollout and acceptance. No legal/compliance approval is inferred.
