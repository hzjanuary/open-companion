# 0001 Backend Bootstrap Boundaries

Date: 2026-07-29

## Status

Accepted

## Context

The product contract requires a scalable modular monolith and a strict inward
dependency direction, while SPEC-001 must not scaffold empty future domains.

## Decision

Use a Python 3.12 FastAPI application factory in `backend/app`. Keep the
initial implementation limited to outer runtime and HTTP-interface concerns.
Use `uv` and `pyproject.toml` as the sole Python dependency manager. Add inner
layer directories only when a concrete feature requires them.

## Alternatives Considered

1. Create the full target module tree now.
2. Place all future adapters and business behavior in FastAPI routes.

## Consequences

Positive:

- The service is immediately runnable and observable.
- Future adapters have documented boundaries without premature folders.

Tradeoffs:

- The current application has no product domain behavior, by design.

## Follow-Up

- SPEC-002 introduces persistence abstractions only when its accepted scope
  requires them.
