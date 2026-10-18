# Telegram Capabilities

## Implemented In SPEC-003 And SPEC-004

- `getMe` identity verification.
- `sendMessage`, including reply parameters and safe optional send controls.
- `sendSticker` using an existing Telegram asset reference.
- `getChatMember`; information for other users can depend on bot administrator
  access granted by Telegram.
- Typed `getUpdates`, `setWebhook`, `deleteWebhook`, and `getWebhookInfo`.
- Secure webhook ingress and controlled polling into one durable inbox.
- PostgreSQL deduplication and Redis Streams outbox publication.
- Durable ordered text and sticker outbound actions with PostgreSQL leases.
- UTF-16 username mention entities, same-conversation reply/topic preservation,
  and configuration-only sticker intent mapping.
- Confirmed rejection retry policy and terminal `delivery_unknown` handling for
  ambiguous sends; no exactly-once Telegram delivery claim.

## SPEC-028 Candidate: Inbound Media

- JPEG photo understanding on the current turn, through an eligible governed
  image-capable generation model. Albums are not aggregated.
- OGG/Opus voice and MP3 audio transcription through the existing Groq family.
- Authenticated getFile and bounded, validated ephemeral downloads; no arbitrary
  URL input or raw-media archive.
- Existing durable text/sticker replies; no voice synthesis, video, document
  parsing or image generation. Media never automatically becomes memory.
- Disabled or unavailable media processing produces a deterministic text notice.
  See [media operations](../runbooks/telegram-media.md) for prerequisites/limits.

## SPEC-039 Candidate: Explicit Response Feedback

- Reply directly to a retained January response with exactly `/feedback helpful`
  or `/feedback unhelpful`; quotes and replyless commands are not authority.
- Split chunks share the same target, delivered regeneration edits use their
  exact plan, and delivered voice presentations use the source text plan.
- Feedback is private participant-owned metadata with one current value,
  immutable state-changing history, `NO_CHANGE` repeats, and a 10-revision cap.
- The operation is local and never invokes providers, vectors, regeneration,
  reactions, typing presence, memory, knowledge, summaries, or adaptation.
- See [feedback operations](../runbooks/conversation-feedback.md).

## Deferred

- Later specifications: authorization policy and operator bootstrap workflows.

## Operator Configuration

Set `JANUARY_TELEGRAM_ENABLED=true` and provide the token outside source
control. `./scripts/verify-telegram.sh` performs only an explicit `getMe`
check. Normal startup, CI, and tests do not require a Telegram credential.

For configured operators, `scripts/telegram-webhook.sh register|inspect|remove`
manages webhook state explicitly. `remove --drop-pending-updates` is the only
form that requests Telegram to discard pending updates.

`./scripts/verify-telegram-delivery.sh` is configuration-only by default.
`--live --confirm-live-send` sends exactly one labelled synthetic text only
when its explicit delivery test settings are configured; it is never CI work.
