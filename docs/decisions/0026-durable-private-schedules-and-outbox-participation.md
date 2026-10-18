# 0026 Durable Private Schedules and Outbox Participation

Date: 2026-09-11

## Status

Accepted under the SPEC-029 Product Owner authority. The implementation
candidate passed repository-safe validation; Docker-backed proof remains pending.

## Context

Private reminders and opted-in check-ins must survive restarts and downtime while
preserving privacy erasure, quiet hours, command idempotency, bounded catch-up,
and the existing Telegram delivery ambiguity contract. In-memory timers, host
cron, fabricated incoming messages, or a second sender would each weaken an
accepted boundary.

## Decision

- PostgreSQL is authoritative for exact-participant timezone preferences,
  schedules, command receipts, occurrences, leases, and terminal outcomes.
- A bounded scheduler worker materializes only the latest eligible missed local
  occurrence, advances recurrence directly beyond the current time, and creates
  a normal response plan/outbound action. It performs no network I/O.
- Scheduled delivery uses the existing outbound worker and `scheduled` origin.
  Cancellation, privacy revision, membership, pause, quiet hours, and check-in
  inactivity are rechecked atomically immediately before Telegram I/O.
- Schedule calculations store IANA timezone plus wall-clock recurrence. A DST
  gap resolves to the first valid minute after the gap; a fold uses the earlier
  instant once. One-time reminder UTC instants do not move after timezone edits.
- Command receipts and exact source/occurrence unique constraints make replay
  idempotent. Lease token, owner, attempt, expiry, schedule version, and privacy
  revision fence stale workers. No exactly-once Telegram-delivery claim is made.
- Reminder text is user-supplied private content. Check-ins use versioned,
  deterministic code-owned text and make no background provider call. Neither
  path writes memory or personal context.

## Alternatives Considered

1. OS cron or process timers: not portable, not transactional, and not durable
   across replicas or restarts.
2. Synthetic incoming messages: corrupts authorship and risks prompt, memory,
   safety, and privacy boundary confusion.
3. Provider-generated check-ins: creates background cost and safety complexity
   without a product need in bounded v1.
4. One occurrence per missed recurrence: causes catch-up floods after downtime.

## Consequences

Positive:

- Multiple scheduler replicas safely share bounded work through familiar lease
  and SKIP LOCKED conventions.
- Existing outbound rate limits, safety preflight, recovery, and ambiguity
  quarantine remain authoritative.
- Subject export, erasure, and bounded retention cover schedule content.

Tradeoffs:

- V1 is private-conversation only, has no schedule editing or arbitrary cron,
  and supports one-time, daily, and selected-weekday recurrence only.
- A confirmed provider-generated proactive-writing product would require later
  Product Owner authority; SPEC-029 does not make provider calls.
- Delivery can still be unknown after Telegram I/O and is never described as
  exactly once.

## Follow-Up

- Complete the SPEC-029 migration/runtime validation and independent release
  audit.
- SPEC-030 — not started.
