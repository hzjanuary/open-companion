# 0024 User-Controlled Personal Context and Recall

## Status

Accepted for the Product Owner-authorized SPEC-027 implementation candidate.

## Context

Lumi already stores explicit, same-conversation memory and optionally builds a
derived semantic index. Users need bounded inspection, correction, deletion,
and recall controls without creating an inferred profile, global identity, or
cross-conversation disclosure path. Telegram group command replies are visible
to the group, so they cannot safely carry creator-private context.

## Decision

Extend the canonical `memory_items` architecture with a `personal_context`
kind. Personal context is user-authored, creator-only, and available only in an
exact private conversation. Its key is one of five closed values and one active
record per owner/conversation/key is enforced in PostgreSQL. It never enters
Qdrant.

Memory and personal-context records have positive optimistic revisions.
Mutation commands are idempotent by durable command identity, and owner update
or delete locks the exact row. A bounded, resumable clear operation records its
progress in a content-free operation ledger. Existing group-administrator
authority continues to cover shared explicit facts only.

Recall policy is exact participant plus conversation. No row means enabled for
backward compatibility. Recall-off for the current participant suppresses all
memory retrieval for that response and skips semantic query I/O; recall-off by
a fact's creator also excludes that fact during canonical PostgreSQL
revalidation. PostgreSQL status and the conversation privacy revision remain
authoritative even when a derived vector is stale.

Context precedence is system policy, current turn, personal context, explicit
memory, recent history, then derived summary. Personal context and memory are
JSON-delimited untrusted user data with independent item limits and a combined
character ceiling. Context assembly closes its database session before any
embedding or Qdrant I/O.

Memory/recall reads use a savepoint so a failed lookup omits memory rather than
defaulting to enabled. SQL parameters are hidden by the database engine; memory
command failures expose only a fixed content-free error to worker tracebacks,
leaving the durable lease eligible for the existing restart/reclaim behavior.

Subject export includes only the subject's exact-scope records and recall
state. Group export excludes personal context and recall policies. Erasure and
expiry physically clear content/hash, invalidate temporary exports and stale
planning, and schedule semantic deletes only for explicit facts. Erasure also
disables applicable recall policies; individual record expiry does not change
the owner's recall preference.

## Consequences

- Migration `0018_user_controlled_memory` adds record revision/key shape,
  recall-policy state, and a content-free command-operation ledger.
- There is no global subject, portable profile, cross-conversation recall,
  automatic extraction, or sensitive-trait inference.
- Management commands make no provider call; generation containing recalled
  context still traverses SPEC-026 safety, budget, rate, and concurrency gates.
- Downgrade is refused once SPEC-027 state exists because discarding ownership,
  recall, or mutation history would be destructive.
- Audit retention duration, backup purge/reapply policy, and production rollout
  remain operating-owner decisions; no compliance certification is claimed.

## Alternatives considered

- Participant matching by Telegram user ID across conversations was rejected
  because the repository has no approved global identity authority.
- Storing personal context in Qdrant was rejected because deterministic bounded
  selection is sufficient and the derived disclosure surface is unnecessary.
- Group-visible personal-context commands were rejected because a Telegram
  reply cannot provide creator-private delivery semantics.
