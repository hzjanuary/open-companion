# SPEC-005: Conversation Domain and Context

## Outcome

The durable Telegram ingress reference is consumed into normalized conversation,
participant, message, membership, eligibility, and processing-ledger state.
This creates the bounded context required by a later response specification; it
does not call an LLM or send an outgoing message.

## Contracts

- Telegram payloads are parsed and normalized at the infrastructure boundary.
  Inner layers receive typed platform-independent values only.
- Conversation and participant identifiers are strings, preserving Telegram IDs
  beyond 32-bit limits. Unknown additive payload fields are ignored; malformed
  required nested values are rejected durably.
- The PostgreSQL processing ledger is unique on `incoming_update_id`. State and
  ledger commit before the Redis Stream entry is acknowledged. Duplicate events
  are safe to acknowledge; transient failures remain pending for reclaim.
- Eligibility is deterministic and occurs before any future model call. Private
  text is eligible; group behavior follows conversation response mode, explicit
  mentions, assistant replies, or bounded case-folded assistant-name matching.
- Context always includes the current message, then its bounded reply chain,
  then newest same-conversation and same-topic history under deterministic age,
  character, and token budgets. It contains no raw Telegram payloads, secrets,
  database models, or cross-conversation data.

## Runtime

`python -m app.runtime.conversation_worker` is a dedicated Redis Streams
consumer. It validates queue schema metadata, loads durable ingress state,
normalizes, commits business state, and only then acknowledges. Its logs carry
identifiers and outcomes, never message text or credentials.

## Validation

```bash
./scripts/validate.sh
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-conversation.sh
```

The integration command starts only repository PostgreSQL and Redis, applies
the current schema, proves durable processing and duplicate acknowledgement,
and stops those services. It makes no Telegram or LLM request.

## Non-Goals

No LLM provider, January personality, outbound delivery, memory, Telegram
polling changes, authentication, frontend, Zalo, or external deployment is
introduced here.
