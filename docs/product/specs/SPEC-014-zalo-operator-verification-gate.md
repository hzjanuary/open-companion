# SPEC-014: Zalo Operator Verification Gate

## Outcome

Convert SPEC-013's blocking Zalo OA and GMF unknowns into reproducible,
redacted, operator-owned evidence. This specification does not implement a
Zalo runtime adapter.

## Phase 1 Result

Repository preparation is complete. The canonical result is currently
`BLOCKED` / `STILL_BLOCKED` because no dedicated nonproduction OA/application
has been confirmed for operator-controlled live verification.

## Gate Scope

The only candidate future surfaces are OA direct assistant and, separately,
OA-managed GMF. Existing ordinary private Zalo friend-group parity remains a
distinct question and is excluded unless supported official evidence proves it.

## Safety And Privacy

Credentials, IDs, raw payloads, and private messages stay in ignored local
storage. Tracked results use aliases, field presence/type observations, safe
synthetic text, redacted fingerprints, and official error/status data only.

## Non-goals

No Zalo platform enum, API client, webhook route, token store, migration,
command runtime, GMF runtime, Docker service, or production settings.
