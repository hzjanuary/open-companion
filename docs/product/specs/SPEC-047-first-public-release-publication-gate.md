# SPEC-047 — First public release preparation and publication gate

Date: 2026-10-16

Status: IMPLEMENTATION CANDIDATE VALIDATED — INDEPENDENT AUDIT PENDING

## Authority and scope

The owner requests fresh reconstruction from committed baseline
`private-source-checkpoint-omitted` after loss of the previous
uncommitted candidate. Existing source, current CI and newly executed checks
are authority. Old candidate hashes, receipts and approvals cannot be reused.
This is publication preparation: no product capability, schema, migration,
runtime semantic change or production pool adjustment. Alembic remains solely
`0026_conversation_feedback`. The existing MIT license and notices remain.

## Publication safety contract

Review every locally reachable commit/tree/blob across HEAD and all local,
remote-tracking and tag refs, including deleted paths. State exact scope,
ref coverage, counts, dates, binary/size exclusions and limitations. Refuse
shallow, partial, missing-object, replacement or otherwise unproved coverage.
Unreachable/reflog objects, unfetched refs, GitHub issues/PRs/Actions/artifacts,
LFS payloads and external services are not implicitly reviewed.

The read-only scanner uses bounded local Git commands and deterministic,
redacted metadata. It detects probable tokens/keys/credential URLs, risky
historical paths, private records, platform identifiers and personal checkout
paths. Findings retain automatic detections separately from exact-object human
dispositions. No unconditional historical-security PASS is possible. No real
credential/private record or unreviewed high-risk material may receive approval.
Never print matched values, private content or commit identities. Findings
use object IDs, path fingerprints, categories and line numbers.

Names/emails and personal historical paths require separate owner consent.
Unsigned commits alone do not fail security review; signature presence is not
signature validation. Synthetic fixtures, local defaults, examples and code
references require narrow contextual review, never blanket directory exclusions.

## Preparation and owner decisions

Publish concise unversioned/unpublished notes describing actual Telegram,
five-provider, self-host, context/memory/RAG, safety/privacy and operations
behavior. Preserve polling-first local/VPS support, optional HTTPS webhook,
derived Qdrant and optional TTS. Telegram and enabled external providers receive
content by design. Zalo is frozen/unsupported; support is community best-effort.
No managed SaaS, official registry image, LTS, guaranteed rollback or general
privacy/compliance claim. CHANGELOG stays Unreleased.

The [owner publication process](../../maintainers/first-public-publication.md)
requires separate independent audit, owner-reviewed commit/push, exact pushed-
SHA Quality and a refreshed history review including the publication commit.
Owner metadata/path consent, first public version, hosting/security settings,
Private-to-Public decision, annotated tag and GitHub Release remain distinct
owner gates. Package version is not authorization. Public clones cannot be
retracted by returning a repository to private visibility. Issuer revocation/
rotation under owner control precedes any response to an exposed credential;
history rewriting alone is insufficient and is not authorized here.

## Feedback diagnostic boundary

Independently investigate the existing 100-operation, 50-key opposite-command
test: barrier, leases, transaction lifetime, advisory locks, pool capacity,
cleanup and isolated PostgreSQL capacity. A clean run or old narrative cannot
prove root cause. If repeated unchanged runs pass and no correction is justified,
preserve the fixture. A justified test-only correction must retain all operations,
synchronization and domain assertions, unchanged three-second timeout and
production semantics. Warmup, if used, must hold the desired connections
simultaneously and return them before the barrier. Prove no checkout/transaction
leak; require ten focused and three dedicated consecutive measurements.
No throttling, sleeps, retries, skip/xfail, relaxed timeouts or masked failures.
A runtime semantic defect stops this work for separately scoped stabilization.

## Acceptance

- Scanner synthetic disposable-repository tests exercise clean/deleted-risk,
  key/URL/token/redaction, narrow dispositions, coverage and Git failures offline.
- Precise contextual reachable-history and current-candidate reviews find no
  unresolved high-risk content; metadata/path owner gates remain explicit.
- Every current CI block passes in order, serially, with owned disposable
  dependencies. Required supplemental backup/restore, governance, memory,
  readiness and related validators pass. All failures remain in evidence.
- Feedback passes at its actual CI position, full integration and reliability
  pass, and eval stays 130 total / 125 PASS / 5 NOT_EVALUATED / 0 FAIL / 0 ERROR.
- A newly assembled temporary-index tree includes every intended source file,
  excludes local/private/generated inputs and preserves Git executable modes.
  Clean materialization, fresh depth-one and VCS-free proofs satisfy existing
  source/self-host/Quality contracts; history review fails closed without Git.
- Critical and High findings are zero; independent audit remains pending.

Only after all applicable gates may implementation report
`APPROVED PUBLICATION CANDIDATE — INDEPENDENT AUDIT PENDING`.
Otherwise report REQUIRES FIXES or the precise environment, historical-exposure
or runtime-defect blocker. Never call SPEC-047 complete or self-approve the
independent audit. No commit, push, tag, release, visibility/settings change,
history rewrite, credential rotation or SPEC-048 is authorized.

See [design](../../plans/handoff/SPEC-047-DESIGN-HANDOFF.md),
execution plan (private execution record omitted from this snapshot)
and handoff (private execution record omitted from this snapshot).
