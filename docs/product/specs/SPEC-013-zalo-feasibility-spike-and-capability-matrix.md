# SPEC-013: Zalo Feasibility Spike and Platform Capability Matrix

## Outcome

Research official Zalo OA and GMF feasibility without implementing a Zalo
runtime, credentials, webhook, migration, or platform enum.

## Decision

`BLOCKED_PENDING_OFFICIAL_VERIFICATION` for any Zalo adapter scope. OA direct
messaging is a possible narrow future surface; OA GMF and ordinary friend-group
parity remain unverified. See the [decision](../../platforms/zalo/decision.md),
[source register](../../platforms/zalo/official-source-register.md), and
[capability matrix](../../platforms/zalo/capability-matrix.yaml).

## Deterministic Conclusions

- OA, OA messaging, GMF, and webhooks are separate official product areas.
- OA messaging is constrained by user interaction/consent and policy/package
  entitlements.
- GMF must not be equated with an ordinary Zalo friend group.
- January's core safety, rate limiting, privacy deletion, response planning, and
  durable ingress/outbound patterns remain reusable only after real platform
  semantics are verified.

## Non-goals

No Zalo HTTP client, credentials, OAuth flow, DPoP, webhook, polling, adapter,
GMF runtime, database migration, setting, Docker service, or production code.

## Validation

```bash
./scripts/validate-zalo-feasibility.sh
```

This static validator parses the evidence artifacts and guards against
credential-like content and accidental Zalo runtime work. The manual operator
verification plan is documented but was not executed.
