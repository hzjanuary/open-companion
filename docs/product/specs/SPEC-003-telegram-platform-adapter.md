# SPEC-003: Telegram Platform Adapter

## Outcome

A typed, lifecycle-managed Telegram Bot API adapter supplies platform-independent
values to application code without exposing Telegram DTOs or HTTP objects.

## Scope

Implemented capabilities are bot identity verification, text sending and reply
parameters, sticker sending by existing asset reference, and chat-member
lookup. Telegram configuration is disabled by default and token-redacted.

## Contracts And Errors

Application contracts expose platform identifier strings, typed requests,
messages, identities, membership states, capabilities, and stable error
categories. The adapter maps Bot API envelopes and preserves rate-limit and
chat-migration hints without retrying or sleeping.

## Security And Non-Goals

The token remains in infrastructure-only request paths and never appears in
errors, logs, or settings representations. No updates, polling, webhooks,
ingestion, persistence writes, automatic retries, queues, or response behavior
are included.

## Validation

Mock `httpx` transport tests exercise every operation without credentials or
public network access. `scripts/verify-telegram.sh` is an explicit `getMe`
operator command and fails safely unless enabled with a token.
