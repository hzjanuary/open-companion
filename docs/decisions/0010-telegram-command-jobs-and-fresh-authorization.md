# ADR 0010: Durable Command Jobs and Fresh Authorization

## Decision

Telegram command parsing remains at the infrastructure boundary and produces a
typed normalized command only from Telegram entity data. Recognized commands
create durable command jobs before model-planning eligibility. A command
response plan has exactly one durable source: a planning job or a command job.

Protected group changes obtain current authorization through the generic
platform adapter outside the database transaction. Cached membership is not
authorization. Deterministic code-owned responses reuse outbound delivery.

## Consequences

Command retries are lease-based and cannot call provider/LLM code. Private
mutations remain local. Telegram command-menu management is intentionally not
part of runtime startup or CI.
