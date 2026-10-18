# 0015 Operational Recovery And Provider Concurrency

Status: Accepted

## Decision

January records recovery classification in PostgreSQL as a content-free,
platform-independent work kind, disposition, closed reason, and event history.
Dead letters are known-safe bounded-retry failures and can be replayed one at a
time through a local operator command. Quarantine is non-replayable through the
generic path; `delivery_unknown` is quarantine because Telegram side effects may
already have occurred.

Same-conversation business processing takes a PostgreSQL transaction advisory
lock keyed by connection/conversation identity. The lock is released by commit,
rollback, or process failure and never spans provider or Telegram I/O.

Provider in-flight capacity is a Redis TTL semaphore keyed only by deployment
and provider. It is independent of distributed throughput rate limiting.

## Consequences

The recovery schema deliberately does not store payloads, prompts, usernames,
or provider bodies. Redis can be reconstructed after a restore and cannot be
used as an authoritative business backup. Operators must use the separate
legacy ambiguity workflow when accepting a possible duplicate delivery.
