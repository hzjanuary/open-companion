# Telegram reactions

SPEC-037 adds one optional, transient social signal to the existing Telegram
planning runtime. It is enabled whenever the existing Telegram planning adapter
is configured; there is no separate feature flag, service, credential, table,
or migration.

## Eligibility and mapping

All conditions must hold: Telegram; directly addressed ordinary work; current
incoming text message; eligible, non-bot, non-erased member; active tenant,
Assistant, connection, and conversation; exact same authority scope; current
message content still available; and ordinary pre-generation safety allow.

The policy normalizes at most 64 code points with NFKC, case-folding, collapsed
whitespace, and trailing ASCII `.`, `!`, or `?` removal. Exact full-message
matches are:

- `thanks`, `thank you`, `cảm ơn`, `cám ơn`, `❤️` → `❤️`;
- `ok`, `okay`, `got it`, `understood`, `sounds good`, `được`, `hiểu rồi`,
  `👍` → `👍`.

Everything else selects none. There is no sentiment/emotion/sensitive-trait
inference, model selection, arbitrary Unicode, custom emoji, or multiple
reaction support.

## Exclusions and interactions

Ambient messages, scheduled/proactive work, deterministic commands,
`/regenerate`, regenerated edit/fallback actions, outgoing messages, edited or
redacted content, media/captions, and foreign or inactive authority produce zero
reaction calls. Media is never downloaded or transcribed for this policy.
Typing presence remains bound only to admitted provider I/O.

`message_reaction` and `message_reaction_count` are not requested in Telegram
`allowed_updates` and remain unsupported at durable ingress. They produce no
outbox event or planning work. Bot-set reactions also do not generate a
`message_reaction` update under the Telegram Bot API contract.

## Timing, failure, and recovery

The decision is local. After the planning job becomes terminal, any response
plan/outbound action is already durable and independently claimable. A short
PostgreSQL session revalidates authority and returns only the exact chat ID,
incoming message ID, and typed reaction. The session closes before
`setMessageReaction`.

There is exactly zero or one raw attempt and zero retries. A typed 400, 403,
429, 5xx, timeout, connection reset/network error, false/malformed result, or
unsupported result records a bounded failure and returns. It cannot suppress,
alter, or delay durable response delivery. There is no reaction recovery:
crash-before-call omission and ambiguous crash-during-call are accepted to
avoid stale or duplicate cosmetic effects.

Duplicate ingress creates one planning lineage, and reaction runs only after
that job is terminal. Terminal jobs are not reclaimed, so replay produces no
second attempt.

## Privacy and observability

No extra content or reaction history is persisted. Metrics expose only:

- decision: `selected` or `none`;
- kind: `thumbs_up`, `heart`, or `none`;
- delivery outcome: `success` or `failure`;
- bounded Telegram adapter error class.

Never add body/caption, prompt/response, tokens, or chat/user/message/tenant/
Assistant/connection/conversation identifiers to labels or reaction logs.

## Validation

Run from the repository root without Telegram or provider credentials:

```bash
JANUARY_DB_HOST_PORT=5454 ./scripts/validate-telegram-reactions.sh
```

The validator checks the exact policy and adapter payload, no-retry error
classes, telemetry privacy, unsupported-update loop prevention, 12 offline
SPEC-032 scenarios and mutation proof, current PostgreSQL authority, response
failure isolation, terminal replay, zero checked-out sessions at raw I/O,
clean-candidate operation, and current Alembic head
`0026_conversation_feedback` (which includes `0025_telegram_voice_tts`).
SPEC-037 still adds no migration of its own.

If reaction delivery fails, do not manually retry or send explanation text.
Confirm normal response delivery independently, inspect only bounded metrics,
and fix Telegram authority/configuration outside the message path.

Reference: [Telegram Bot API](https://core.telegram.org/bots/api), especially
`setMessageReaction`, `ReactionTypeEmoji`, `Update`, and `setWebhook`.
