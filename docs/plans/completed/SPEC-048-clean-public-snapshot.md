# Execution Plan: SPEC-048 clean public snapshot

Date: 2026-10-17

## Status

Completed local implementation — independent audit pending.

## Outcome

Prepare a VCS-free January v0.1.0 source snapshot for independent review.
Version approved; NOT YET PUBLISHED. No tag exists from this work.

## Context

Authority: owner SPEC-048; [workflow](../../WORKFLOW.md),
[architecture](../../ARCHITECTURE.md), [release process](../../maintainers/release-process.md),
and existing product contracts and canonical Quality.

## Scope

Source inventory, contextual privacy review, public identity/version documentation,
release tooling checks, source modes and clean-source validation. Product behavior,
architecture, migrations and runtime pool defaults remain unchanged. Original
repository is read-only. No Git initialization in this snapshot, commit, remote,
push, tag, release, upload or repository visibility/settings change is authorized.
Private evidence is kept outside the snapshot in an owner-approved directory.

## Approach

1. Verify origin and capture source fingerprints; review all proposed public files.
2. Classify individual files; remove private execution receipts while preserving
   current contracts, design, legal, code, migrations, tests and contributor paths.
3. Correct public repository identity and approved version without publication claims.
4. Run canonical Quality serially with isolated synthetic dependencies, supplemental
   gates and explicit VCS-free history-scanner coverage limitation.
5. Bind the final inventory, modes and hashes to a clean-source rehearsal and
   unchanged-original proof; prepare independent audit handoff and owner gates.

## Risks And Recovery

Stop for actual credentials/private records, uncertain attribution, source Git
contamination, unavailable Docker/CI prerequisites or runtime defects. Filtering
must preserve tests and distribution; do not weaken assertions. Recover only
task-owned staged changes and synthetic services. Never alter original source.

## Progress

- [x] Owner selected v0.1.0 and approved separate owner-only private evidence.
- [x] Baseline and empty private target verified read-only; archive bytes match.
- [x] Per-file classification and contextual privacy review.
- [x] Public identity, release draft and version checks.
- [x] Full serial Quality and clean-source proof.
- [x] Final manifest, unchanged-source proof and independent audit handoff.

## Decisions

- 2026-10-17: Preserve license/notices verbatim. Normalize extraction modes to
  recorded source modes. Keep private receipts outside public source.
- 2026-10-17: Approved v0.1.0 is unpublished; future exact-SHA CI, independent
  audit and owner publication remain separate gates.

## Validation

Derive checks from .github/workflows/ci.yml. Use PostgreSQL 16, Redis 7 and
Qdrant v1.13.4 with fake external adapters. Record every executed exit status.
The VCS-free full-history scanner must return COVERAGE_INCOMPLETE (exit 2);
its synthetic Git tests remain required outside the final snapshot.

## Result

SNAPSHOT STAGED — INDEPENDENT AUDIT PENDING.

All 39 canonical Quality blocks and 13 supplementary validators exited 0 in
serial order on owned synthetic services. Unit count: 919 passed; full integration
and marker-specific results remain in separate private receipts. Static typing,
lint/format, migration lifecycle, Docker build, reliability and canonical eval
were executed. Clean materialization passed general/public/self-host/Graphify,
scanner synthetic, static, migration-head and Docker-build checks. History
coverage exited 2 as expected without Git. No runtime, architecture, migration
or pool-default change was made.

An initial preflight refused an unrelated pre-existing validator volume/network.
A staged project-name override preserved default behavior and isolated the work.
A first Quality attempt stopped at regeneration clean export because the private
harness umask reduced archive mode 755 to 700. Diagnostic reproduction confirmed
077→700 versus 022→755. The failing receipt is retained; a fresh full run with
CI-equivalent extraction permissions passed without weakening any assertion.
Twelve validators now honor TMPDIR for private temporary receipts.

The private audit package binds original/source fingerprints, every file's
classification, exclusions, redacted findings, endpoint review, source modes,
manifest/hashes, changed-file accounting and exact command exits. No private
execution receipt or original Git history is part of the snapshot. Original
content/modes and Git baseline are verified separately after final checks.

Publication prerequisites: independent OpenCode audit of the exact manifest;
verified private disclosure channel; reviewed settings; owner-supplied exact
GitHub Settings noreply identities for BOTH author and committer; separately
authorized new root commit/push; exact-SHA public Quality; separate visibility,
annotated v0.1.0 tag and GitHub Release approvals. NOT YET PUBLISHED; no date or
existing tag is claimed. No staging Git initialization or publication action.

