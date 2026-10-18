# Zalo Feasibility Decision

## Recommendation

`BLOCKED_PENDING_OFFICIAL_VERIFICATION`

This applies to any January Zalo adapter scope. No production adapter work is
approved by this spike.

SPEC-014 is `DEFERRED / BLOCKED_ON_EXTERNAL_PREREQUISITE`, not an active
Telegram MVP blocker. Its remaining credentialed checks resume only when an
operator-owned dedicated nonproduction OA/application is available; they do not
block Telegram/product work under SPEC-015 or later accepted Telegram slices.

SPEC-014 Phase 1 added a redacted operator verification plan and static guards.
It did not execute live verification, so the decision remains unchanged.

## Candidate Scope After The Gate

A narrow **Zalo OA direct assistant** may be useful: users interact with one OA
in one-to-one chat, and January sends only policy-eligible text. OA-managed GMF
is a separate candidate, not a substitute for an ordinary private friend group.

## Product Questions

1. **OA one-to-one:** potentially yes, as a policy-constrained OA direct assistant; request/payload details need verification.
2. **Documented group suitable for January:** GMF exists as an OA product, but suitability is unverified.
3. **GMF:** a separate OA group documentation surface, not evidence of ordinary private-group equivalence.
4. **Ordinary inbound messages:** an OA user-message webhook category is documented; payload and delivery semantics are unverified.
5. **Replies through APIs:** OA consultation-message send documentation exists; reply-reference behavior is unverified.
6. **Stable IDs:** OA-scoped UID is policy-documented; stable conversation, message, event, and group identifiers need verification.
7. **Reply/mention/sticker/member/admin:** unknown for GMF and insufficient for Telegram parity.
8. **Business restrictions:** consent, recent interaction, message category, package entitlement, and OA policy materially apply.
9. **Existing ordinary private friend group:** no supported public-API path was verified; this is `not_documented`, not permanent impossibility.
10. **Proceed:** defer adapter work until the operator verification gate, then reconsider OA direct-only or OA-managed GMF.

## Deferred Scope

January cannot currently claim supported public-API participation in an existing
ordinary private Zalo friend group comparable to Telegram. The official sources
reviewed do not establish that an OA can be added to such a group.

GMF may become a useful OA-managed group experience, but group creation,
membership, inbound/outbound message semantics, role lookup, stable IDs,
mentions, replies, quotas, and lifecycle events must be proved with a dedicated
test OA/app first.

## Product Fit

- A. OA direct assistant: **3/5**. Documented messaging is useful but consent,
  interaction-window, package, and payload constraints are material.
- B. OA-managed GMF social assistant: **1/5**. A dedicated surface exists, but
  critical group semantics are unresolved.
- C. Existing ordinary private Zalo friend group: **1/5**. No supported public
  participation path was found; do not treat missing evidence as unsupported
  forever, but it blocks this intended scope now.

Unknown dimensions are intentionally not averaged into these scores.

## Architecture Impact

The domain/application core remains reusable. A future adapter would need a new
infrastructure adapter and possibly schema evolution for OA-scoped identity,
conversation identity, platform message/event keys, eligibility/consent state,
and platform policy classification. Telegram-specific assumptions needing
refactor include Bot API update shape, polling, entities/mentions, sticker asset
resolution, member-role lookup, and outbound confirmation conventions.

No enum, migration, setting, endpoint, or adapter is added in SPEC-013.

| Current abstraction | Assessment |
| --- | --- |
| Platform, PlatformConnection, normalized event, ConversationType, MessageType | Reusable with a new adapter; candidate enum/schema evolution is deferred. |
| Participant identity, privacy subject, rate-limit scope | Reusable with OA-scoped identity and verified external quota mapping. |
| Response plans, outbound actions, safety, explicit memory | Reusable unchanged at inner boundaries. |
| Webhook ingress, durable inbox/outbox, outbound certainty | Reusable with a new adapter after payload/retry semantics are verified. |
| Mentions, replies, stickers, admin authorization, member lifecycle | Telegram-specific assumption requiring refactor or capability gating. |
| Polling, Telegram rendering/assets, Bot API errors | Telegram-specific; unsupported or unknown on Zalo. |
| Operator bootstrap and inspector | Reusable with new secret/identity fields only after credentialed verification. |

## Future Slices

1. Operator verification gate with a dedicated test OA/app only.
2. Re-evaluate this matrix and approve either OA direct-only or GMF scope.
3. Design a minimal adapter boundary from observed official payloads.
4. Implement only the approved scope with synthetic tests before credentials.

Rollback/defer strategy: retain this research record and make no runtime change.

## Manual Live Verification: NOT EXECUTED

Use only test OA/app/users/groups, never production data. Require explicit
operator confirmation before every external mutation. Do not paste tokens into
chat or logs; redact IDs in evidence.

1. Link a dedicated OA and app; issue and refresh a token.
2. Register and authenticate a test webhook.
3. Verify direct inbound text and direct outbound reply.
4. Create/list GMF only if operator-approved; verify inbound/outbound text.
5. Check member/admin lookup, mention/reply semantics, identifiers/dedupe, and
   quota/error behavior.
