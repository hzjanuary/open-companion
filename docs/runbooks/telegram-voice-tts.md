# Telegram explicit voice playback

SPEC-038 adds one user-controlled presentation command. Reply directly to a
locally delivered January text answer with exactly `/voice`. January resolves
the local outgoing message to its PostgreSQL response plan and synthesizes the
whole logical answer. Replying to any chunk of a split answer uses the same
whole plan; replying to a regenerated answer uses that exact regeneration.

The command does not accept arguments or a fuzzy “latest answer” fallback. It
does not trust Telegram's quoted text, regenerate or rewrite the answer, call a
chat model, retrieve memory or knowledge, redownload media, transcribe audio,
emit typing presence, or add a reaction.

## Provider, format, and limits

V1 supports only the governed OpenAI speech capability:

- model `gpt-4o-mini-tts`;
- product-owned voice `alloy`;
- native `opus` response persisted as `ogg_opus` / `audio/ogg`;
- fixed Telegram multipart filename `voice.ogg`;
- exactly 4,000 Unicode code points maximum source text;
- exactly 5,242,880 bytes maximum provider output and artifact;
- 30-second provider timeout.

Input is never truncated. The adapter streams and counts the actual body, does
not trust `Content-Length`, rejects empty/non-Ogg/encoded/oversized output, does
not follow redirects, and never accepts a URL or filesystem path.

## Enablement

The feature is disabled by default. Before enabling it, apply Alembic head
`0025_telegram_voice_tts`, activate an OpenAI `text_to_speech` capability and
route with `tts_request` pricing and a hard budget, and verify all normal
Telegram command/outbound prerequisites. Required settings include:

```dotenv
JANUARY_TELEGRAM_VOICE_TTS_ENABLED=true
JANUARY_LLM_OPENAI_API_KEY=<secret>
JANUARY_PROVIDER_GOVERNANCE_MODE=enforce
JANUARY_PROVIDER_GOVERNANCE_WORKER_ENABLED=true
JANUARY_RATE_LIMIT_ENABLED=true
JANUARY_PROVIDER_CONCURRENCY_ENABLED=true
JANUARY_COMMAND_WORKER_ENABLED=true
JANUARY_OUTBOUND_DELIVERY_ENABLED=true
```

The control plane, Telegram adapter/token/connection, Redis, command worker,
outbound worker, provider-governance worker, and retention worker must already
be configured. Startup fails closed when the required credential, governance,
rate, concurrency, command, or outbound prerequisite is missing. Other provider
families are not advertised as speech-capable.

## Durable and recovery behavior

One command owns one durable voice-generation job, governed provider attempt,
bounded artifact, and `voice` outbound action. Provider `io_started` is
committed before the request and every database scope is closed during raw TTS
I/O. A crash before that marker can reclaim the same no-I/O reservation. A
timeout, reset, or crash after possible provider I/O is terminal uncertain:
do not run TTS again.

Successful bounded bytes and the pending outbound action are activated in one
transaction only after command lease, source hash/length, privacy revision,
tenant, Assistant, connection, conversation, plan, and provider result are
revalidated. Stale output is discarded.

The outbound worker loads the same bounded artifact, closes its database scope,
and calls Telegram `sendVoice`. A definitive retryable no-send response reuses
the same artifact and never invokes TTS. A timeout/reset that may have delivered
the upload becomes `delivery_unknown`; do not replay it or send an explanatory
message. Voice replies to the `/voice` command message, not the source answer.

## Retention, privacy, export, and backup

Audio is sensitive derived delivery data, not conversational text, memory,
knowledge, summary, or semantic-index content. It is omitted from semantic user
exports. Live rows remain in PostgreSQL backups so job/artifact/action foreign
keys restore consistently.

After delivery becomes terminal, bytes expire at terminal time plus 24 hours.
Every artifact also has a creation-plus-seven-day hard ceiling; the earlier
deadline wins. The retention worker clears `audio_bytes` and retains only the
content-free tombstone/checksum metadata. Privacy erasure purges immediately
and permanently fails pending delivery. Never recover text or audio from a
Telegram quote, logs, vectors, old provider data, or a prior artifact.

## Failure categories and troubleshooting

- `voice_target_unavailable`: verify the command directly replies to a current,
  delivered, non-redacted local assistant text message in the same authority
  scope.
- `voice_too_long`: the whole authoritative plan exceeds 4,000 code points; no
  partial synthesis is allowed.
- `voice_tts_unsupported`: verify the feature flag, OpenAI credential, enforced
  TTS capability/route, current provider health, and exact format/limit metadata.
- `voice_tts_admission_denied`: inspect content-free budget, rate, and
  concurrency state; raw TTS I/O did not occur.
- `voice_tts_generation_failed`: inspect the closed provider result category;
  no artifact or voice action exists.
- `voice_tts_generation_uncertain`: provider I/O may have occurred; do not
  retry the command automatically.
- `delivery_unknown`: Telegram may already have accepted the voice; do not
  resend.

Metrics are limited to closed admission/result/provider labels. Never put
source text, audio/base64/hex, tenant/Assistant/conversation/message IDs, bot
tokens, provider tokens, or response bodies into logs, metrics, or incidents.

## Validation

Canonical proof uses fake HTTP boundaries and an isolated PostgreSQL project;
it requires no Telegram or provider credential:

```bash
./scripts/validate-telegram-voice-tts.sh
```

The validator proves unit/eval/static checks, a VCS-free candidate, real
PostgreSQL authority/idempotency/fencing/privacy/session boundaries, migration
`0024 → 0025`, empty rollback/re-upgrade, base-to-head, and populated downgrade
refusal. Run `./scripts/validate-backup-restore.sh` separately to rehearse a
live voice artifact/action pair through PostgreSQL restore.

## Known limitations

V1 has one voice and one provider adapter, one synthesized voice message per
command, no duration metadata, no conversion, no SSML, no streaming, no
automatic voice replies, and no Zalo support. SPEC-040 closed the six historical
reliability failures; every current Quality failure is release-blocking. Never mask
them as part of voice operations.

A delivered voice presentation may be the reply target for SPEC-039 feedback;
the feedback applies to this artifact's source response plan, not audio quality
or the `/voice` command plan. See
[`conversation-feedback.md`](conversation-feedback.md).
