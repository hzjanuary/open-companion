# Zalo Operator Verification Plan

Status: Phase 1 complete; Phase 2 is blocked pending an operator-controlled
dedicated nonproduction environment.

## Current Operator Boundary

No dedicated Zalo application/OA is currently available. Ordinary personal Zalo
accounts may be `USER-A` and `USER-B` test participants only after a supported
OA/GMF gate exists. They must never be used as January's bot or runtime
identity. Do not use personal-account APIs, unofficial SDKs, browser automation,
packet inspection, or automated consumer-account control.

## Operator Prerequisites

Confirm without sending values through chat that:

1. A dedicated nonproduction Zalo application and OA exist and are authorized
   for testing.
2. The OA/app serves no production customers; `USER-A` exists, and `USER-B` is
   available if GMF member/role testing is approved.
3. The operator understands package charges and has a temporary HTTPS callback
   if webhook testing is required.
4. Values are placed directly in ignored `.env.zalo-verification.local` or the
   local shell; no secret file appears in `git status --short`.
5. Every external mutation is explicitly approved immediately before it occurs.

## Ordered Gates

1. **AUTH-001:** Link the test OA/app and verify issue, refresh, expiry,
   invalid/revoked credential behavior, approval, multi-OA constraints, and
   request-proof requirements. Log field names/durations/error codes only.
2. **WEBHOOK-001:** Register a temporary callback only with approval. Verify
   handshake, trust fields, IDs, timestamps, duplicates, retries, ordering, and
   timeout/non-2xx behavior. Raw payloads remain local and untrusted until
   signature/authentication is verified.
3. **OA-DIRECT-001:** Have `USER-A` send the fixed inbound string, then send the
   fixed outbound string. Observe aliases, field presence/types, policy-window,
   reply, and error behavior. Do not campaign or send non-synthetic text.
4. **GMF-001:** Only if entitled and approved, create/select a test GMF and
   inspect identity, members, roles, joins/leaves, quotas, and limits.
5. **GMF-002:** Independently verify inbound/outbound text, identifiers,
   replies, mentions, stickers/media when low-cost, retries, and ordering.
6. **PRIVATE-GROUP-001:** Use only official UI/docs/support or public API to
   determine whether an OA can join an existing ordinary friend group. Manual
   consumer-app observation may inform product understanding but never promotes
   an API capability. GMF does not answer this question.
7. **COMMERCIAL-001:** Record current verification/package/OpenAPI/messaging/
   GMF entitlement and policy warnings. Never purchase or upgrade automatically.

## Evidence Procedure

Use [redaction-policy.md](redaction-policy.md). Update only
`operator-verification-results.yaml` with redacted evidence. One happy path
does not prove retry, duplicate, ordering, or scope guarantees. Update the
capability matrix only after a verified operator test; never promote GMF proof
to ordinary friend-group parity.

## Stop Conditions

Stop and mark the relevant check `BLOCKED` when a required official security
semantic is unknown, operator approval is absent, a production account appears,
or a requested action would purchase, alter, or expose non-test data.
