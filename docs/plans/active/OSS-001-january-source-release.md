# Execution Plan: OSS-001 January source release

Date: 2026-11-01

## Status

Active. Independent OpenCode audit BLOCKED pending the exact owner-approved
private SPEC-048 package path or export. Do not substitute public historical
documents. The owner explicitly permits other authorized offline work meanwhile.

## Outcome

Prepare January v0.1.0 — Initial Self-hosted Telegram AI Companion Source
Preview, distributed only as a GitHub Pre-release with GitHub-generated source
ZIP and tar.gz. Stop at one Draft PR with exact-source independent audit and
remote Quality evidence; owner release authorization remains required.

## Context and authority

- Owner's OSS-001 instructions authorize legal/documentation/source fixes,
  synthetic isolated testing, local images, feature branch and (after privacy
  gates) normal push and one Draft PR. No merge, tag, release, deployment,
  registry publication, live Telegram/provider calls or production data access.
- [Workflow](../../WORKFLOW.md), [historical SPEC-048 handoff](../handoff/SPEC-048-HANDOFF.md),
  [Quality](../../../.github/workflows/ci.yml) and runtime/tests are the record.
- Repository ID 1423511659, public, default main, baseline
  `612f89c6724261873d38cfa9a9639eb5836cb41a`.
- Original public root `069642473d6a39824b7a5ccf9c844cb8e6c4f354` has no
  parent. Retain the root and every subsequent commit, branch and tag.
- Existing active ruleset `protect-main` (25766062) requires strict `quality`,
  pull requests and no force-push/deletion; no bypass actors. Do not change it.
- Owner explicitly supplies MIT identity `Hoang Nguyen`; retain upstream
  Harness copyright and MIT grant. No new runtime policy is authorized.

## Scope

License and complete source/dependency/container provenance; current public
documentation; implementation-backed governance review; redacted current and
reachable-history scans; exact-lock advisory audit; separate local-image scan;
all canonical and supplemental synthetic validation; clean-source installation;
source/archive integrity; independent audit; feature-branch Draft PR and exact
SHA remote Quality. Preserve all 26 migrations and architecture.

## Approach

1. Record repository, local state, complete refs/history and settings baseline.
2. Correct MIT identity/integrity checks and current publication instructions;
   classify all tracked files and installed Harness material without deleting it.
3. Inventory every locked dependency and image/tool/model license separately;
   reconcile privacy documentation with code, migrations and tests.
4. Run redacted history/current-source and pinned dependency/image scans;
   record findings without suppression. Stop on genuine secrets/private records.
5. Rehearse locked Python 3.12 Quality in canonical order and supplemental
   recovery/self-host tests against exclusively task-owned synthetic services.
6. Materialize exact source/modes, verify archives and clean installation; bind
   receipts to source hashes. Obtain the independently reviewed approved package.
7. Review every changed file/mode, pass publication privacy checks, commit with
   noreply metadata, push feature branch normally, create one Draft PR and
   verify successful Quality on final PR SHA. Keep source and image decisions separate.

## Risks and recovery

- Never read real `.env`, `.local` or `.runtime` contents, personal databases,
  backups or unrelated personal directories. Inspect only tracked source,
  filename inventories and newly created task-owned receipts/services.
- Use a unique task project/name and verify resource ownership before tests.
  Never remove existing containers/volumes or run broad Docker cleanup.
- Preserve failed receipts; never weaken assertions, selectors or thresholds.
- Reversible edits live on `feat/oss-001-january-source-release`. Recover by
  reviewing/reverting only task changes; never reset main or rewrite history.
- Missing audit package blocks independent approval and release readiness.
  Unresolved image findings stay separate from any proposed source decision.

## Progress

- [x] Clean starting main checkout and expected HEAD; public repository ID verified.
- [x] Local full (non-shallow) topology: one root, three reachable commits,
  main and security branch; no local tags. Remote branches match, no tags/releases.
- [x] Ruleset read-only verification; baseline Quality 40069948712 completed/success
  on baseline SHA (push). This does not verify OSS-001 changes.
- [x] Create requested feature branch without changing main.
- [x] Enable private reporting after explicit owner permission; API readback
  `enabled: true` on 2026-11-01 and again 2026-11-04.
- [x] MIT identity and integrity validator/regressions updated; current release
  instructions now preserve existing public history. 589 source paths classified,
  with recorded/proposed Git modes. All Harness material retained; 38 manifest
  comparisons: 33 identical upstream copies and five documented adaptations.
- [x] Governance/code and distribution review; bounded retention corrections and
  separate memory/privacy/backup boundaries documented.
- [x] Full canonical and supplementary synthetic proof: 48 commands exit 0,
  including all 39 workflow run blocks; final bounded runtime deltas receive
  renewed affected proof and actual image scans, separately bound below.
- [x] Clean archive/setup proof: both formats, all 589 hashes/modes, no private
  state, actual closed Docker polling/restart/webhook/authentication fixture.
- [x] Final runtime/image proof: source-final manifest binds 962 general and
  31 affected tests, stock rebuild/Trivy and actual closed first-run PASS.
  Image findings remain 45 HIGH / 0 CRITICAL, publication not approved.
- [ ] Check final publication privacy receipts, preserve local candidate commit
  and post-commit full-history review in handoff. No push while audit is blocked.
- [ ] Independent approved-package audit (BLOCKED).
- [ ] Privacy-approved push, one Draft PR, exact-SHA remote Quality.
- [ ] Vietnamese final handoff and owner release decision (pending).

## Decisions

- 2026-11-01: Owner confirms preserving existing public merge-author personal
  metadata. Do not repeat its value in reports. Root and feature commit use
  GitHub noreply; merge committer is GitHub noreply. No history rewrite.
- 2026-11-01: Owner authorizes enabling GitHub Private Vulnerability Reporting.
- 2026-11-01: Owner has not confirmed private audit package location. No home
  directory search or public-document substitute; continue authorized offline work.

## Session recovery, 2026-11-04

Previous process handles are gone and the former `/tmp` receipts are absent.
Do not infer full canonical completion from the surviving image or worktree.
The earlier general run and scans were observed, but required raw receipts and
remaining integration outcomes must be regenerated. A new exclusively task-owned
ignored receipt set `oss-001-20261104-ad0a54b9` stores orchestration, source/mode
manifest, command/exit/hash records and raw redacted scanners. It contains no
owner-approved SPEC-048 private audit package. Do not search for such a package.

Fresh synthetic projects use prefix `january-oss001-r2`; existing OSS-001 and
operator resources are preserved. Read-only preflight verified absent project
resources and unused `10.252.0.0/16`. A task-local Docker wrapper specifies IPAM
only for test Compose startup, preserving the original internal-network and
egress assertions. The stock Dockerfile uses host networking only during build
to avoid the previously observed Docker DNS failure. The self-host integration
fixture accepts a task-specific image tag, preserving its default and every
assertion, so existing image tags are not overwritten. Git modes, not checkout
filesystem group-write bits, determine source materialization modes.

Fresh general Quality and canonical steps through 19 passed on the pre-fix
snapshot. Step 20 stopped at the closed self-host fixture setup: Compose `run`
also needs explicit IPAM on this Docker host. The task wrapper now applies the
same IPAM-only override to `run` as to `up`; no assertion/selector is weakened.
The corrected runtime source needs a new full candidate proof; prior results
are baseline diagnostics, not final acceptance. Missing exits are not PASS.

## Retention finding, 2026-11-04

Code review found `_redact_actions` restricts payload clearing to terminal
outbound actions, and `_redact_commands` uses completion age/terminal state.
This can retain copies of raw user content beyond the maximum 30-day policy
when work stalls. Reproduce against a newly owned synthetic PostgreSQL database;
do not mark governance acceptance PASS until resolved.

Authority: owner OSS-001 B3 maximum 30-day raw-content policy, SPEC-025 FR-08,
and the current data-governance schedule. Recovery authority: existing outbound
lease recovery preserves unknown delivery certainty, and existing privacy/voice
expiry fences leases using current terminal states. A bounded fix must clear
expired raw content regardless of work state, fence unfinished command/delivery
work, preserve delivery uncertainty if external I/O already started, retain
content-free history, and leave separate explicit-memory retention unchanged.
A new PostgreSQL regression reproduced the cutoff gap: expected six cleared
rows per category but observed messages=4, outbound=1 and command arguments=0.
An additional late-edit regression reproduced plaintext resurrection after
redaction. Raw failures and source hashes are retained in the task receipt set.
The bounded fix clears all expired raw work, uses original source age for command
arguments, quarantines started/unknown sends and preserves edit tombstones.
A strengthened case also reproduced a future platform timestamp extending
retention beyond local creation age. Raw message expiry now uses the earlier
of creation and source time, with creation as the missing-time fallback.
The final delta (retention cutoff SQL and its strengthened regression) must be
revalidated on the final source; keep it separate from the initial r3 manifest.

All eight memory/privacy schema tests now pass, including exact cutoff, bounded
batches, idempotency, fresh-work preservation, stale-lease fencing, uncertainty,
quarantine and late-edit non-resurrection. Ruff and strict mypy pass for the
three changed runtime modules.

No migration rewrite, new schema/state or live I/O is needed. Add meaningful
synthetic cutoff/batching/lease/idempotency regressions and rerun affected and
canonical proof on the corrected exact source.

## Corrected candidate proof

Receipt set `oss-001-20261104-final` uses a new source/mode manifest and fresh
`january-oss001-r3` synthetic projects on unused `10.250.0.0/16`. The r2 CI
services were stopped without deleting their data; unrelated resources remain
untouched. The Docker wrapper applies IPAM-only overrides to both `up` and `run`.
General Quality passed again: 962 tests, Ruff, format and strict mypy. New
retention integration tests remain in the original integration selection.
The final cutoff delta is captured in a separate `delta-source` manifest. Its
general Quality, self-host/public/Graphify contracts, 31 PostgreSQL/Redis
memory/command/delivery/governance tests and strict release-tool checks pass.
Deterministic evaluation records 125 PASS, 5 NOT_EVALUATED, 0 FAIL/ERROR, judge
disabled. Final-cutoff image rebuild/scan and clean archive proof pass; the final
publication privacy scan is still required. The main r3 canonical sequence completed with its original source/mode
manifest; preserve that binding and record bounded cutoff delta/revalidation
explicitly.

Full canonical/supplementary proof completed at 2026-11-04T13:12:00Z: 48
recorded commands, every expected exit zero. This includes all 39 workflow run
blocks and supplementary governance, offline production-readiness, backup/restore,
demo and personality validators. General 962 and integration 184 tests pass.
The final delta and image/archive proof remain separately bound; exact remote
Quality is still required. A final command-source-age review additionally
includes Message.created_at when a delayed command references future platform
time; its eight schema regressions pass. The final source-final snapshot
repeats general Quality, 31 affected integrations, actual stock build, pinned
Trivy and the closed first-run fixture (147.17 seconds), all expected exits.
No code changes follow that snapshot. Public inventory now identifies this
image; earlier hashes remain historical proof only.

## Advertised PR-ref coverage expansion

A complete `git ls-remote origin` inventory also advertises `refs/pull/1/head`
at `73cc6b9e3916dd2d12573b43592e15e28a510569`, outside current branch heads.
The initial 3-commit scans covered every local ref but did not include this
remote PR head. Public PR refs were fetched into audit-only remote-tracking
aliases without changing main, the feature worktree or tags. Repeated history
review covers 4 commits, 652 objects and 582 historical paths with the same
78 exact dispositions and zero unresolved findings. Repeated Gitleaks reports
only the same two enum false positives, raw exit 1, without suppression. Do not claim complete remote history from a heads/tags-only
inventory. Original-root preservation is checked on the expanded graph.

## Validation

Track PASS / FAIL / BLOCKED / NOT_RUN and evidence in
[OSS-001 acceptance](../../validation/OSS-001-acceptance.md). Historical SPEC-048
receipts and baseline CI are context, never proof of the new candidate. Keep
raw scanner/test receipts task-owned and excluded from source; publish only
reviewed redacted summaries, hashes and command exits.

## Result

Offline source preparation is validated with separate manifests and command
receipts; the local checkpoint must be recorded by exact commit SHA in handoff.
Independent audit, final remote Quality and GitHub-generated source artifacts
remain BLOCKED. No release readiness, image approval or publication is claimed.
