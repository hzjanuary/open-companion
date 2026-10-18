# SPEC-012: Safety Policy and Distributed Rate Limiting

January applies `safety-policy-v1` deterministically before provider and
Telegram I/O. Hard boundaries prohibit harassment, identity attacks, targeted
humiliation, private-data disclosure, sexual content involving minors,
self-harm encouragement, dangerous instruction execution, and persistent or
sensitive teasing. No configuration disables these boundaries or enables roast
mode.

Model output uses `response-plan-v2`, with closed structural interaction
metadata. Mentions and teasing target only current internal context IDs and are
rechecked against current opt-outs and privacy deletion before external I/O.
Unsafe or contradictory teasing becomes a short language-aware neutral
fallback; model refusal is valid. This is deterministic structural enforcement,
not comprehensive semantic moderation.

When enabled, Redis coordinates fixed-window generation budgets by deployment,
connection, conversation, participant, and provider, and delivery budgets by
deployment, connection, and conversation. A single Lua operation checks all
scopes before consuming any. Redis unavailability fails closed for provider and
Telegram I/O, requeuing durable work with bounded backoff; privacy and
administration mutations remain local.

Migration `0009_safety_rate_limiting` persists content-free policy decisions
and rate events. Inspector output includes IDs, policy/schema versions, codes,
scopes, retry-after values, and aggregate state only. It never shows rejected
text, prompts, raw platform identifiers, or credentials.

```bash
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-safety.sh
```
