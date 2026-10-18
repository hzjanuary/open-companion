# SPEC-004: Telegram Ingress, Queue, and Idempotency

## Outcome

January accepts Telegram updates through one selected mode: secure webhook or
controlled long polling. Both modes validate at the Telegram boundary and use
the same PostgreSQL durable inbox and transactional outbox before Redis Streams
publication.

## Contracts

- Delivery defaults to `disabled`; `webhook` and `polling` are mutually
  exclusive settings.
- Webhook delivery requires an enabled Telegram adapter, bot token, platform
  connection ID, HTTPS public base URL, and redacted Telegram secret token.
- The webhook route is `POST /api/v1/platforms/telegram/webhook/{connection}`.
  It uses constant-time secret comparison, a bounded JSON body, and a typed
  accepted/duplicate acknowledgement after the database transaction commits.
- Polling checks `getWebhookInfo` and refuses to poll while Telegram reports a
  webhook URL. It never deletes a webhook automatically. Its cursor advances
  only after the batch is durable.
- Supported update types are `message`, `edited_message`, `my_chat_member`, and
  `chat_member`. Unknown types are stored as rejected and never create queue
  work. Raw Telegram JSON stays in the infrastructure persistence boundary.

## Delivery And Recovery

Telegram ingress, Redis Streams, and downstream handling are at-least-once.
PostgreSQL `incoming_platform_updates` is the final deduplication authority on
`(platform_connection_id, platform_update_id)`. Each supported new update gets
one `ingress_outbox_events` row in the same transaction. Dispatch marks it
published only after `XADD`; a crash in that window can duplicate a Stream
event, so consumers must deduplicate by stable `incoming_update_id`.

`polling_cursors` records the next Telegram offset per connection. Outbox retry
metadata keeps failed publication pending with a bounded future availability.
Redis consumer helpers create groups idempotently, read, acknowledge, and
reclaim stale pending entries. No business consumer is shipped here.

## Validation

```bash
./scripts/validate.sh
JANUARY_DB_HOST_PORT=5433 ./scripts/validate-db.sh
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-ingress.sh
```

The ingress command starts only project PostgreSQL and Redis, migrates to
`0002_telegram_ingress`, proves webhook idempotency, outbox publication, Stream
acknowledgement, reclaim, and polling cursor behavior, then stops those
services. It uses no Telegram credential, webhook, or public network call.

## Non-Goals

No conversations, participants, or messages are created. Context assembly,
response behavior, LLMs, memory, authentication, Zalo, and a production
business consumer are deferred.
