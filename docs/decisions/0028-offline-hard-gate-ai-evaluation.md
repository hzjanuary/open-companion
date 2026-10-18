# 0028 Offline Hard-Gate AI Evaluation

Date: 2026-09-13

## Status

Accepted under the Product Owner-authorized SPEC-032 implementation.

## Context

The repository has strong correctness, safety, privacy and reliability tests but
no reusable conversation-quality scenario framework. Subjective model judging
can vary, require credentials, spend provider budget and leak fixture content.
Treating a high average score as compensation for a privacy or safety violation
would contradict existing product authority.

## Decision

Canonical evaluation is repository-local, offline and deterministic. Versioned
JSON fixtures execute only a closed catalog of drivers built over existing pure
product seams and controlled provider doubles. All hard gates must pass; one
privacy, safety, authority, provenance, external-call or forbidden-mutation
failure fails the suite regardless of soft scores.

Subjective 0–4 rubrics are first-class review data but are not heuristically
scored. Without an explicitly compatible judge they are `NOT_EVALUATED`, never
PASS or zero. SPEC-032 v1 provides no live judge adapter. A future judge must
cross SPEC-026 governance and cannot replace deterministic hard gates.

Fixtures/results remain repository-local and transient. Production conversation
harvesting, persisted eval state and migration 0022 are not introduced.

## Alternatives Considered

1. Exact generated-text snapshots: rejected because flexible prose changes are
   brittle and are not semantic-quality evidence.
2. Keyword/regex scoring for subjective dimensions: rejected because it would
   make an unsupported quality claim.
3. Mandatory LLM-as-judge CI: rejected because it is nondeterministic, costly,
   credentialed and provider-dependent.
4. PostgreSQL eval-run tables: rejected because checked-in fixtures and
   transient reports represent v1 without expanding production data scope.
5. Remote baseline service: rejected because reviewable checked-in expectations
   are sufficient and avoid a second source of truth.

## Consequences

Positive:

- Canonical CI is reproducible, credential-free, zero-cost and privacy-safe.
- Hard product contracts cannot be averaged away.
- Scenario and rubric changes are ordinary reviewable source diffs.
- Future governed judges can implement the stable rubric/result interface.

Tradeoffs:

- V1 does not automatically score semantic relevance, warmth or personality
  fit; these remain visibly unevaluated without future approved judge support.
- Deterministic drivers prove only their declared objective properties, not
  general model quality or production SLOs.

## Follow-Up

- Any live judge/provider comparison requires a new approved decision that
  specifies governance, data eligibility, budgets, versioning and retention.
- Review and evolve the synthetic suite with future Telegram product changes.
