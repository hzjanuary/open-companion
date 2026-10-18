# Conversation Summaries

Conversation summaries are disabled by default and are not explicit or semantic
memory. Enable both settings only after configuring an existing model provider:

```bash
JANUARY_CONVERSATION_SUMMARIES_ENABLED=true
JANUARY_SUMMARY_WORKER_ENABLED=true
uv run python -m app.runtime.conversation_summary_worker --once
```

The worker uses retained incoming raw messages from one conversation/thread,
provider rate and concurrency coordination, and PostgreSQL job leases. It does
not send Telegram actions. The normal inspector reports only status/counts and
never summary or source text.

To roll back behavior immediately, set both flags to `false`. Stored summaries
remain inert; privacy invalidation and retention cleanup continue. Do not use a
database downgrade as the ordinary rollback path.

Run synthetic proof with `./scripts/validate-summaries.sh`. It uses local
PostgreSQL/Redis and fake providers only, so it does not establish semantic or
factual summary quality.
