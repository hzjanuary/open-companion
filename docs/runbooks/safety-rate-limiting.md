# Safety And Rate Limiting

`safety-policy-v1` deterministically enforces structural boundaries before
provider and Telegram I/O. It rejects unknown interaction metadata, limits
mentions and teasing to current internal context IDs, honors mention/teasing
opt-outs and privacy deletion, disallows sensitive teasing, and has no roast
mode. It does not claim comprehensive semantic moderation.

Unsafe or contradictory teasing is changed to a short language-aware neutral
fallback with no mention or sticker. A model refusal remains a safe result.

When `JANUARY_RATE_LIMIT_ENABLED=true`, Redis uses an atomic fixed-window Lua
check. Generation scopes are deployment, connection, conversation, participant,
and provider; delivery scopes are deployment, connection, and conversation.
Redis coordination failure fails closed for provider and Telegram I/O and
requeues durable work. Database-only privacy and administration commands remain
available, though their delivery acknowledgements can wait for capacity.

Run the synthetic, no-credential validation from the repository root:

```bash
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-safety.sh
```

The inspector exposes only internal IDs, policy/schema versions, outcomes,
reason codes, limiter scopes, and retry values. It never includes rejected
text, prompts, raw platform IDs, or credentials.
