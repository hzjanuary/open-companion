# 0021 Safety Moderation Protection State and Review Queue

## Status

Accepted for SPEC-024 implementation.

## Context

SPEC-024 formalizes SPEC-012 structural safety enforcement into an observable
product surface: per-member protection (`FR-10`), per-group safety level and
teasing cap (`FR-09`), a bounded human-in-the-loop review queue (`FR-07`), and
content-free telemetry and alerting. Durable enforcement requires that
protection survive restarts, that per-group configuration be immutable and
revisioned, and that review decisions be auditable. The existing content-free
`safety_policy_decisions` table records per-message gate outcomes but cannot
represent the protected/restored participant state, the configuration revision,
or the review queue.

## Decision

One additive alembic migration (`0015_safety_moderation`) adds only structural,
content-free state:

- `participants.protected_at` (nullable timestamp). Set by the deterministic
  `/protect` command and by targeting-surge protective enforcement; cleared by
  `/unprotect` or a review action. Rechecking delivery against this flag is
  FR-08/FR-10 enforcement.
- `conversation_configuration_revisions.safety_level` and
  `.teasing_cap`. These are immutable revision copies (defaults `standard`,
  `3`) carried through the existing revision apply path so every enforcement
  decision uses the configuration version the plan was built against.
- A `safety_review_items` table carrying only categories, stage, outcome
  counts, opaque conversation/participant references, protection state, status,
  action, timestamps, and source — never message text, prompts, memories,
  usernames, or raw platform identifiers (NFR-01/FR-12). It is populated from
  content-free aggregates and mirrors the deterministic `SafetyDecision`
  outcomes already written to `safety_policy_decisions`.

The migration id is `0015_safety_moderation` because the alembic `version_num`
column is `varchar(32)`; the longer descriptive name would truncate.

## Alternatives considered

1. A single content-bearing moderation store that captured rejected messages
   and profiles: rejected because SPEC-012 is explicitly not semantic
   moderation and SPEC-024 must never store the content it rejects.
2. In-memory or Redis-only protection state: rejected because protection must
   be durable and independently verifiable, not coupled to cache availability.
3. Per-signal tables instead of one review queue: rejected; the queue is a
   bounded projection and one content-free table keeps the review path
   deterministic and content-safe.

## Consequences

- The alembic head is `0015_safety_moderation`; the readiness check and the
  safety, command, and memory schema-pin tests reference it, and the
  `validate-safety.sh` validator exercises `downgrade 0008`/`upgrade head`.
- Configurable defaults are not policy authority: `safety_level` and
  `teasing_cap` defaults remain operator-configurable via the `/safety`
  command and settings; the effective threshold is read from the conversation
  revision at enforcement time.
- Protection is reversed only through the deterministic review or
  `/unprotect` path; enforcement fails closed on repository errors.
- Both changes are additive and downgrade cleanly; downgrade restores the
  pre-SPEC-024 schema without data loss for protected state (the flag is
  dropped).

## Follow-up

Retention for `safety_review_items` and `safety_policy_decisions` stays
consistent with SPEC-011 privacy controls and the SPEC-015 content-free
telemetry boundary; the operating owner approves the retention and access
policy with the SPEC-024 handoff.
