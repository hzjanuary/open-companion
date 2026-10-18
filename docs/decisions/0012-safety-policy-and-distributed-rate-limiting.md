# ADR 0012: Safety Policy and Distributed Rate Limiting

## Decision

Use a versioned platform-independent deterministic safety policy and
`response-plan-v2` structural interaction metadata. Redis coordinates all
enabled generation and delivery scopes with one atomic Lua fixed-window check.
If coordination is unavailable, provider and Telegram I/O fail closed and
durable work is requeued; privacy and administration mutations remain local.

## Consequences

Hard target boundaries can be enforced from current durable context and
preferences, including privacy deletion, while semantic moderation remains a
model-assisted defense-in-depth limitation. Content-free policy and rate events
are inspectable without retaining rejected text or prompts.
