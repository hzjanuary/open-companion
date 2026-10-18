# SPEC-006: LLM Provider and Response Planning

## Outcome

Eligible durable incoming messages create one PostgreSQL planning job. A
separate worker rebuilds bounded context, requests structured output through a
typed provider port, validates policy locally, and stores one platform-neutral
response plan. It never sends Telegram actions.

## Contracts

Supported provider IDs are `openai`, `gemini`, `groq`, `openrouter`, and
`ollama`; models and capabilities are explicit configuration. Direct HTTP
adapters use JSON Schema output where declared, revalidate locally, and expose
only typed, redacted results and errors. Official documentation surfaces were
reviewed on 2026-07-29: OpenAI Structured Outputs, Gemini Structured Output,
Groq Structured Outputs, OpenRouter Structured Outputs, and Ollama Structured
Outputs.

Planning jobs use PostgreSQL leases and `SKIP LOCKED`; claim transactions finish
before provider I/O. Attempts and final plans are durable. Retryable transport
failures are bounded, malformed output gets at most one correction, and one
fallback may follow primary exhaustion. No exactly-once generation claim is
made across a crash boundary.

Response plans are strict: no unknown fields, raw platform IDs, arbitrary
actions, unknown sticker intents, invalid references, or opt-out mentions.
Silence has no action fields. Prompts are deterministic, versioned, bounded,
and delimit untrusted conversation data.

## Validation

```bash
./scripts/validate.sh
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-planning.sh
```

Both commands use no provider credential or public model request. Live provider
verification is intentionally not part of normal validation.

## Non-Goals

No Telegram send, outbound action table, tool/function calling, streaming,
memory, personality persistence, sticker resolution, rate limiting, frontend,
Zalo, or SPEC-007 behavior is included.
