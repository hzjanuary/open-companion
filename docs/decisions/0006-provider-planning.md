# 0006 Provider Planning and Durable Leases

Date: 2026-07-29

## Status

Accepted

## Decision

Use direct typed HTTP adapters behind a provider-neutral port. Require strict
local response-plan validation even when a provider advertises JSON Schema
enforcement. Use a PostgreSQL planning job with a bounded lease, durable attempt
records, and one immutable final response plan.

## Consequences

Workers can scale through `FOR UPDATE SKIP LOCKED`; expired leases recover, but
a crash may duplicate generation before finalization. Retry and correction are
bounded; one fallback is permitted after eligible primary failure. Provider
credentials, raw prompts, raw responses, and platform actions never persist.
