# 0003 Telegram HTTP Adapter

Date: 2026-07-29

## Status

Accepted

## Decision

Use a direct `httpx.AsyncClient` Telegram Bot API adapter, typed boundary DTOs,
and platform-independent application values. The adapter owns only clients it
constructs, redacts tokens, and never automatically retries outbound sends.
Mock transports prove behavior without live credentials.

## Consequences

Telegram transport and JSON parsing remain infrastructure concerns. Update
delivery remains deferred to SPEC-004.
