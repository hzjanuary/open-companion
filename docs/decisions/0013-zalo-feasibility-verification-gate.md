# ADR 0013: Zalo Feasibility Verification Gate

## Decision

Defer every Zalo runtime implementation behind a dedicated test OA/app operator
verification gate. The current decision is `BLOCKED_PENDING_OFFICIAL_VERIFICATION`.

The potential scope after that gate is OA direct messaging or, separately,
OA-managed GMF. Ordinary private Zalo friend-group parity is not established and
must not be inferred from GMF, ZBS, Social API, or Social Plugins.

## Consequences

No `Platform.ZALO`, migration, setting, credential, webhook, API client, or
adapter is introduced. Existing platform-neutral application policy remains
reusable, while Telegram-specific entities, polling, roles, stickers, and
outbound conventions are documented as candidate refactor areas. Reconsider
this ADR only with new official evidence or operator-owned test verification.
