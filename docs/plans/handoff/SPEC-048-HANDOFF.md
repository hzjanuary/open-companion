# SPEC-048 independent audit handoff

Status: SNAPSHOT STAGED — INDEPENDENT AUDIT PENDING.
Version: v0.1.0 — NOT YET PUBLISHED. No tag or publication date assigned.

## Scope and source

The planned public repository is https://github.com/hzjanuary/open-companion.
The owner-approved archive was reviewed as a local VCS-free snapshot. No private
Git history, repository configuration or owner execution receipts are imported.
Public files retain runtime, immutable migrations, tests, fixtures, CI, legal
notices, architecture, current product contracts, designs and self-host guidance.
The original private repository remains read-only. Product behavior, architecture,
runtime pool defaults and migrations are unchanged; head is
`0026_conversation_feedback`. MIT LICENSE and NOTICE are preserved byte-for-byte.

## Implementation and proof

Public URLs and approved version documentation were adapted; private provenance
was redacted and private implementation/audit records excluded individually.
Documentation links were repaired. Extracted files were normalized to recorded
source modes. GitHub Actions has read-only contents permission and checkout
credential persistence disabled; no live secrets, artifact uploads or publication
workflow is added. Version regression cases preserve all earlier negative checks.
Twelve validators honor TMPDIR. The personal-context validator accepts an isolated
project override while retaining its original default and all assertions.

All 39 canonical Quality blocks and 13 supplemental validators passed serially
with task-owned PostgreSQL 16, Redis 7 and Qdrant v1.13.4 and fake external adapters.
General Quality reports 919 tests passed. Canonical evaluation is 130 scenarios:
125 PASS, 5 NOT_EVALUATED, 0 FAIL and 0 ERROR. Per-gate counts and exact exit statuses
are in the private audit package. A clean manifest materialization independently
passed general Quality, public/self-host/Graphify contracts, scanner synthetic
cases, release-tool static checks, Alembic head and a local Docker build. No
original .git, operator environment, prior volumes or developer venv was input.

An ownership collision was refused before tests and existing Docker resources
were preserved. A first run's archive-mode failure was diagnosed as harness
umask 077, then corrected to CI-equivalent 022 for extraction and rerun from the
beginning. All failure receipts remain available. No assertion, selector or
runtime behavior was relaxed. Full-history scanning of the VCS-free source
correctly returns COVERAGE_INCOMPLETE (exit 2); this is not a historical security
approval. Disposable scanner Git fixtures live outside the final snapshot.

## Independent audit inputs and remaining gates

The separately retained owner-only package contains the per-file inventory,
redacted exact-content findings/dispositions, endpoint review, private exclusions,
source origin and unchanged-original fingerprints, changed-file accounting,
final manifest/hashes, all commands/exits, clean-source and image identities.
Audit that exact package and these exact source files; do not inherit this
implementation's dispositions or treat green builds as publication approval.

No actual credential or private user record was identified in the bounded
proposed-source review. Protected personal email and actual checkout paths are
absent from proposed public files. Synthetic detector fixtures and public URL
path components remain explicitly accounted for. This is contextual implementation
review, not a universal secret-absence guarantee or independent audit.

The owner must confirm a real private disclosure channel, review repository
settings, supply exact GitHub Settings noreply metadata for author AND committer,
and separately authorize a NEW root commit/push. Then obtain exact-SHA public
Quality, review the new public history and archive, and separately authorize
visibility, annotated v0.1.0 tag and GitHub Release publication. No Git init in
staging, publication commit, remote creation, push, tag, Release, upload or
visibility/settings change occurred. No official registry image is published.

See [execution plan](../completed/SPEC-048-clean-public-snapshot.md),
[scope](../../product/specs/SPEC-048-clean-public-snapshot.md),
[owner procedure](../../maintainers/first-public-publication.md),
[checklist](../../maintainers/github-release-checklist.md) and
[draft notes](../../releases/first-public-release-candidate.md).
