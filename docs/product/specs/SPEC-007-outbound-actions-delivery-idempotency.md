# SPEC-007 Outbound Actions, Delivery, and Idempotency

SPEC-007 compiles each accepted response plan into deterministic PostgreSQL
outbound actions: text first, then an optional sticker. Silence creates no
action. A unique plan/sequence and SHA-256 idempotency key prevent duplicate
creation.

Workers lease actions without holding a database transaction across Telegram
HTTP. Confirmed Bot API responses persist an outgoing message and delivered
state atomically. Known rejected responses may retry within bounded settings.
Timeout, transport, or malformed post-send outcomes become terminal
`delivery_unknown`; they are never retried automatically because a duplicate
send is possible.

Telegram rendering remains infrastructure-only. Internal reply IDs resolve to
the same conversation's platform message ID. Username mentions are appended
deterministically with UTF-16 offsets; participants without usernames are
omitted. Sticker intent is resolved only through configured local mappings.

The worker is disabled by default. No canonical validation sends a Telegram
request. The official [Telegram Bot API](https://core.telegram.org/bots/api)
is the adapter contract for sending, entities, replies, and response parameters.

## Lifecycle

`pending` actions are leased in deterministic order without holding locks during
Telegram HTTP. They finalize as `delivered`, `skipped`, `permanently_failed`,
or terminal `delivery_unknown`. Sequence two cannot run while sequence one is
pending or leased. Confirmed success creates one outgoing Message and completes
the action in the same transaction.

Local validation is `not_sent`; parsed `ok=false` is `rejected`; a valid Message
is `confirmed`; timeout, connection loss, and malformed send responses are
`unknown`. Only bounded confirmed rejections retry. Unknown results do not
retry automatically because ordinary Telegram sends have no caller idempotency
key. This policy favors avoiding duplicate visible bot messages.

Reply UUIDs resolve only to same-conversation platform message IDs and retain
their topic/thread. Mentions preserve plan order, remove duplicates, recheck
preference, omit unavailable identities, and calculate UTF-16 offsets. Sticker
intents resolve only through configuration; a missing mapping safely skips its
action.

## Recovery And Validation

`outbound_recovery` lists safe unknown-action identifiers and requires
`--confirm-possible-duplicate` to requeue exactly one. `validate-delivery.sh`
uses only project PostgreSQL/Redis and fake adapters. The optional delivery
verification script is configuration-only by default; a synthetic live send
requires two explicit flags and dedicated test-chat configuration.

SPEC-007 does not add other message types, web administration, RBAC, a new
queue, LLM behavior, Zalo, frontend, deployment, or SPEC-008 bootstrap work.
