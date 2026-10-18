# 0007 Outbound Delivery and Ambiguous Results

Date: 2026-07-29

## Status

Accepted

## Decision

Compile validated response plans into ordered PostgreSQL actions in the same
transaction as plan completion. Lease actions with PostgreSQL locks, release
the transaction before Telegram HTTP, and persist confirmed outgoing Messages
with final action state atomically.

Telegram has no application idempotency key for ordinary sends. A timeout,
network interruption, or malformed send response is therefore terminal
`delivery_unknown`, not an automatic retry. Explicit operator requeue requires
acknowledging a possible duplicate.

## Consequences

The system prioritizes avoiding duplicate visible bot messages over guaranteed
delivery after ambiguous failures. Confirmed Telegram rejections can use
bounded retries. This is not exactly-once Telegram delivery.
