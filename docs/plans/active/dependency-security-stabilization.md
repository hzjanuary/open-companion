# Execution Plan: Dependency security stabilization

Date: 2026-10-19

Last verified: 2026-10-24 (Asia/Ho_Chi_Minh)

## Status

SECURITY PATCH CANDIDATE — INDEPENDENT AUDIT PENDING.

All 39 canonical blocks and four supplemental validators exited 0 on the final
frozen snapshot. All 24 known advisory ranges are patched, with zero unresolved
Critical, High, Medium, or Low findings. Fresh source/privacy and exact-object
history reviews have zero unresolved findings. The completion audit passed;
independent OpenCode acceptance and the owner-only publication gates remain.

The original follow-up permits proven test/environment corrections only; the
later explicit certifi authorization is a bounded exception.
Production pool defaults, feedback transactions, connection/session lifecycle,
JWT/HTTP security, tenant isolation, and actual service health are outside the
authorized correction scope. A proven defect in those surfaces requires a new
owner decision. No unrelated expensive validation may run before diagnosis.

The ordered follow-up is: inspect full original traces and relevant code;
instrument the exact feedback test on an isolated owned database; compare the
committed baseline under the same conditions where needed; capture Docker
health/bindings and actual curl failure categories; apply only a proven scoped
test/environment correction; execute the exact failing tests, ten feedback
repetitions and cleanup proof; then reliability, affected tests/static checks,
and the remaining canonical workflow serially. No concurrency assertion,
operation/key count, timeout, health check, or security boundary may be weakened.

## Outcome

Resolve all current Critical/High dependency findings, account for every
Medium/Low advisory, preserve Python 3.12 and existing behavior, and prepare an
uncommitted patch with serial Quality evidence for independent OpenCode audit.

## Context

Authority: the owner's security maintenance instructions, `AGENTS.md`,
`docs/WORKFLOW.md`, `pyproject.toml`, `.github/workflows/ci.yml`, existing JWT
verification/configuration, and the public release/history review contracts.
No new product policy is authorized or needed.

Baseline: `069642473d6a39824b7a5ccf9c844cb8e6c4f354`; clean worktree;
origin is the intended open repository; visibility is private. Git author and
committer use the repository-local GitHub noreply identity. GitHub Quality run
39093786388 is completed/success for main/push at this SHA.

## Scope

All 23 live Dependabot alerts (1 Critical, 8 High, 13 Medium, 1 Low), separate
read-only review of Mako PR #1, minimal dependency changes, necessary security
regressions, all 39 canonical CI run blocks and relevant supplemental validators,
privacy/history review, and precise owner handoff.

No commits, pushes, merges, tags, visibility changes, real credentials, alert
dismissals, CI weakening, or modifications to the original private checkout.

## Approach

1. Inventory live advisories and verify authoritative package metadata.
2. Inspect JWT and HTTP exposure; select compatible patched releases.
3. Regenerate the lock with uv 0.6.5; sync all groups with the lock enforced.
4. Add focused regressions where needed; run all canonical steps in order and
   serially, preserving environment and container isolation.
5. Reassess resolved versions, run privacy/history checks with fresh review,
   and prepare a requirement-by-requirement handoff.

## Risks And Recovery

- FastAPI/Starlette cross-version changes require full HTTP and runtime proof.
- Stop and report any proven production runtime/security defect; never weaken a check.
  The owner separately authorized proven test/environment corrections for the
  two reliability failures, as recorded below.
- Run resource-heavy Docker validators serially and use project-owned fixtures.
- Preserve baseline files for comparison; owner can discard this uncommitted
  patch. Never reset unrelated work or remove containers belonging to others.
- GitHub findings remain open until an owner-pushed commit is processed.

## Progress

- [x] Verified clean expected baseline, remote, identity, visibility and Quality.
- [x] Retrieved all 23 current advisories and reviewed PR #1 diff separately.
- [x] Reviewed all Critical/High PyJWT prerequisites against the application.
- [x] Select and resolve minimal patched dependencies.
- [x] Complete focused compatibility/security regressions (31 passed).
- [x] Execute all 39 canonical run blocks serially and supplemental proof.
- [x] Reassess all advisories and complete fresh privacy/history review.
- [x] Prepare independent audit and owner publication gates, with final receipts and historical failures explicit.

## Decisions

- 2026-10-19: HS256-only verification, configured minimum secret length, fresh
  per-call options, and no JWK/JWKS use limit application exposure. Dependency
  severity alone is not evidence of exploitation.
- 2026-10-19: PyJWT must be at least 2.15.0 because live Medium findings extend
  beyond the owner's initial 2.14.0 target. Alert #21 has no patched-version
  metadata; assess its explicit affected range and executable behavior.
- 2026-10-19: PR #1 changes Mako 1.3.12 to 1.4.2 in the lock only. Review it as
  an independent overlapping security change; do not merge or modify the PR.

## Historical Validation — Before Bounded Reliability Remediation

Then-current dependency freeze: FastAPI 0.151.0, Starlette 1.3.1, PyJWT 2.15.1,
Mako 1.4.3, and pytest 9.0.3 under Python 3.12.9 and uv 0.6.5.
`uv sync --all-groups --locked` and installed dependency compatibility passed.
The focused 52-case run includes all 31 new security regressions. Canonical
unit selection passed 950 tests, followed by Ruff, formatting and mypy.

Canonical blocks 1–17 passed in order. Block 18 (`validate-reliability.sh`)
failed: its database integration subrun had 151 passed, two failed, and 979
deselected. The runner exited with code 1 and launched no later block.
Blocks 19–39 and all four supplemental validators were not run. The dedicated
182-test canonical integration selection at block 24 is therefore unverified.
Full Quality is red and the candidate is not ready for independent acceptance.

Durable private receipts and source fingerprints are in ignored
`.local/dependency-security-20261020/`. `quality-results.json` and `18.log`
record the failed attempt; earlier version attempts are separate and cannot
establish final Quality. No check was skipped, weakened, or marked successful
to conceal these failures. The canonical script's existing optional Harness
binary branch reported absence; selected unit tests had no skips.

## Dependency Review

| Dependency | Baseline | Resolved | Reason |
| --- | --- | --- | --- |
| FastAPI | 0.115.14 | 0.151.0 | Latest supported upstream release, compatible with patched Starlette. |
| Starlette | 0.46.2 | 1.3.1 | Meets every current Starlette advisory's patched boundary. |
| PyJWT | 2.13.0 | 2.15.1 | Covers 2.14 fixes and the additional 2.15 JWK/payload fixes. |
| Mako | 1.3.12 | 1.4.3 | Compatible patch release beyond the 1.4.2 Windows traversal fix. |
| pytest (dev) | 8.3.5 | 9.0.3 | First patched tmpdir handling release. |
| certifi | 2026.7.22 | 2026.10.23 | Later owner-authorized removal of the compromised emSign trust root; GHSA-6q48-6c7w-9gw2, minimum floor 2026.10.19. |
| annotated-doc | absent | 0.0.5 | Required by the compatible FastAPI release. |
| Pygments (dev) | absent | 2.21.0 | Required by patched pytest. |
| opentelemetry-api | absent | 1.45.1 | Required by the maintained FastAPI release; no optional telemetry SDK/exporter installed. |

All other package versions remain unchanged. `pyproject.toml` raises three
direct version ranges and adds uv constraints for three transitive security
floors. These intersect upstream requirements; they do not override them.
The narrower minor ranges bound this maintenance update. No extra FastAPI
optional capabilities are installed. FastAPI's [security support policy](https://github.com/fastapi/fastapi/security/policy)
supports the latest versions. The dependency freeze on 2026-10-20 selects 0.151.0, the latest release in the refreshed authoritative metadata. Later publication still requires a fresh advisory review.

Exact candidate metadata was fetched from the authoritative PyPI JSON API:
[FastAPI](https://pypi.org/pypi/fastapi/0.151.0/json),
[Starlette](https://pypi.org/pypi/starlette/1.3.1/json),
[PyJWT](https://pypi.org/pypi/PyJWT/2.15.1/json),
[Mako](https://pypi.org/pypi/Mako/1.4.3/json), and
[pytest](https://pypi.org/pypi/pytest/9.0.3/json).
All support Python 3.12. FastAPI's `starlette>=0.46.0` permits this resolution;
its Pydantic requirement permits the existing 2.13.4. A fresh check of all 41
resolved registry packages against version-specific PyPI metadata returned no
vulnerability records. This is supporting evidence, not a universal security
guarantee or a claim that GitHub closed alerts.

uv 0.6.5 generated the lock without manual hash edits. It normalizes the lock
format from revision 3 to revision 1 and removes upload timestamps. No existing
artifact hash for an unchanged package changed. It additionally records two
greenlet artifacts and omits four pydantic-core artifacts; package versions and
common artifact checksums are preserved. Locked sync verifies downloaded
artifacts using the generated hashes.

### JWT and HTTP Compatibility

`backend/app/interface/http/control_plane.py::principal_for` allows only HS256,
uses the configured `SecretStr`, verifies issuer/audience/expiry, and requires
iss/sub/aud/exp. Configuration rejects absent, empty, and shorter-than-32-character
secrets when the control plane is enabled. Token header algorithms and key IDs
do not select algorithms or keys. No asymmetric, JWK, JWKS, DPoP, or unverified
decode path exists in application code. The local setup helper signs HS256
with the same configured authority. Tenant/role authority is looked up from
database memberships rather than accepted from token claims.

Critical #15 and High #11/#12/#14 require asymmetric-key/HMAC confusion
conditions absent here. High #13 requires JWKS fetching, also absent. High #18
requires an empty oct JWK, absent here. All dependencies are patched regardless
of those narrower exposure findings. There is no application production-code
change because the existing boundaries remain appropriate.

The new security suite exercises rejected algorithms, missing claims, wrong
issuer/audience/expiry, invalid signatures, empty/missing/short secret config,
nested malformed JWT header/payload rejection, noncanonical signature rejection,
path-to-authority isolation, unchanged valid identity behavior,
untrusted tenant/role claims, options-dict non-mutation, empty-oct-JWK rejection,
TestClient lifespan, request-ID middleware, and malformed-Host control errors.
Starlette emits a deprecation warning for the still-supported HTTPX TestClient
backend. Existing HTTPX 0.28.1 is retained; no warning or test is suppressed.
Database-backed tenancy/governance/concurrency and lifecycle checks remain
required in the canonical matrix.

January serves JSON HTTP routes and enforces a JSON webhook acceptance-size limit. It does not use
`StaticFiles`, `FileResponse`, `HTTPEndpoint`, or `request.form()`. These advisory
surfaces are patched transitively; new production endpoints are unnecessary.
The existing `request.url.path` access selects the control-plane error envelope,
not authorization. The new malformed-Host case verifies that envelope remains
correct on a protected route.

### Mako PR #1

Read-only review of [PR #1](https://github.com/hzjanuary/open-companion/pull/1)
at head `73cc6b9e3916dd2d12573b43592e15e28a510569`: its only changed file is
`uv.lock`, updating Mako 1.3.12 to 1.4.2 plus dependency ordering. Its release
notes identify the Windows drive-designator traversal fix. This local candidate
resolves 1.4.3 under Alembic's compatible dependency range and independently
validates migration behavior. The PR remains open and unmodified; the owner must
reconcile the overlapping lock change after independent review.

## Result

**REQUIRES FIXES**

Dependency remediation is implemented locally and all 23 resolved versions are
outside the current affected ranges. The release gate remains closed because
full Quality did not pass. Per section 7 of the supplied mission:

> On a genuine runtime/security defect: STOP and report the exact blocker.

At the original stop, no runtime remediation or validation workaround was
attempted. The owner subsequently authorized the bounded test/environment
follow-up recorded below. Production fixes still require separate authority.
The plan stays active while the new complete Quality run is pending.

### Exact Quality Blockers

1. `backend/tests/integration/test_conversation_feedback.py::test_feedback_concurrent_opposite_commands_have_no_lost_updates`
   failed at the 100-command concurrent application stage (test lines 821/863;
   repository call at `backend/app/infrastructure/database/feedback.py:65`).
   SQLAlchemy raised `TimeoutError`: pool size 5, overflow 5, connection timeout
   3.00 seconds. The expected 100 successful outcomes, 50 current states at
   revision 2, and 100 immutable events were not fully proven in this run.
2. `backend/tests/integration/test_self_host_runtime.py::test_fresh_docker_first_run_polling_restart_webhook_and_governed_delivery`
   failed at test line 675: `curl --fail --silent --show-error` against the
   owned fixture's loopback `/live` endpoint after its bridge/restart handoff.
   The helper at lines 72/90 reported `Owned runtime proof command failed
   (details redacted)`. It deliberately does not expose subprocess stderr or
   the curl exit code, so the underlying network/HTTP cause is not established.
   The later loopback `/ready` and final acceptance assertions were not reached.

The isolated feedback validator (block 13) passed earlier; that does not
invalidate the concurrency failure in the combined reliability selection.
Causation by the dependency update, a pre-existing defect, load, or environment
has not been established. No baseline rerun or new experiment was started after
this stop. Pool sizes/timeouts, concurrency requirements, routes, exposure,
and test assertions were not changed to obtain a passing result.

The failure log SHA-256 is
`807214e4a497ac2019a241830f6640fa6bded9e76bf5ecca8bc347059ad9492c`.
Independent OpenCode acceptance, all remaining Quality, owner publication, and
the post-owner-commit history audit remain outstanding. GitHub's alerts remain
open; local resolution is not a remote closure claim. No commit, push, merge,
tag, publication, visibility change, or change to the private development
checkout was performed.

## Live Advisory Inventory And Lock Reassessment

Retrieved 2026-10-19 from the repository Dependabot API: all 23 are open, with
1 Critical, 8 High, 13 Medium, and 1 Low. Every locked/installed version was
compared with its own current advisory range; none remains in an affected
range. This is a local patch assessment, not a GitHub closure claim. No alert
was dismissed.

| Alert | Severity | Package / scope | Installed baseline | GHSA / CVE | Affected range | First patched | Resolved / decision | Application exposure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | medium | starlette (runtime, transitive) | 0.46.2 | [GHSA-2c2j-9gv5-cj73](https://github.com/advisories/GHSA-2c2j-9gv5-cj73) / CVE-2025-54121 | `< 0.47.2` | 0.47.2 | 1.3.1 — PATCHED | No multipart/form routes. |
| 2 | high | starlette (runtime, transitive) | 0.46.2 | [GHSA-7f5h-v6xp-fcq8](https://github.com/advisories/GHSA-7f5h-v6xp-fcq8) / CVE-2025-62727 | `>= 0.39.0, <= 0.49.0` | 0.49.1 | 1.3.1 — PATCHED | No file/static serving. |
| 3 | medium | pytest (development, direct) | 8.3.5 | [GHSA-6w46-j5rx-g56g](https://github.com/advisories/GHSA-6w46-j5rx-g56g) / CVE-2025-71176 | `< 9.0.3` | 9.0.3 | 9.0.3 — PATCHED | Development tmp_path fixtures; patched. |
| 4 | medium | starlette (runtime, transitive) | 0.46.2 | [GHSA-86qp-5c8j-p5mr](https://github.com/advisories/GHSA-86qp-5c8j-p5mr) / CVE-2026-48710 | `<= 1.0.0` | 1.0.1 | 1.3.1 — PATCHED | URL path used for control error envelope; regression covered. |
| 5 | medium | starlette (runtime, transitive) | 0.46.2 | [GHSA-x746-7m8f-x49c](https://github.com/advisories/GHSA-x746-7m8f-x49c) / CVE-2026-48817 | `< 1.1.0` | 1.1.0 | 1.3.1 — PATCHED | No HTTPEndpoint subclasses. |
| 6 | high | starlette (runtime, transitive) | 0.46.2 | [GHSA-wqp7-x3pw-xc5r](https://github.com/advisories/GHSA-wqp7-x3pw-xc5r) / CVE-2026-48818 | `< 1.1.0` | 1.1.0 | 1.3.1 — PATCHED | No StaticFiles; Docker is Linux. |
| 7 | low | Starlette (runtime, transitive) | 0.46.2 | [GHSA-jp82-jpqv-5vv3](https://github.com/advisories/GHSA-jp82-jpqv-5vv3) / CVE-2026-54282 | `< 1.3.0` | 1.3.0 | 1.3.1 — PATCHED | No hostname-based authority. |
| 8 | high | starlette (runtime, transitive) | 0.46.2 | [GHSA-82w8-qh3p-5jfq](https://github.com/advisories/GHSA-82w8-qh3p-5jfq) / CVE-2026-54283 | `>= 0.4.1, < 1.3.1` | 1.3.1 | 1.3.1 — PATCHED | No request.form(); bounded JSON webhooks. |
| 9 | medium | PyJWT (runtime, direct) | 2.13.0 | [GHSA-w6j9-cwv2-h6wq](https://github.com/advisories/GHSA-w6j9-cwv2-h6wq) / CVE-2026-102274 | `>= 2.9.0, <= 2.13.0` | 2.14.0 | 2.15.1 — PATCHED | No JWK Set import. |
| 10 | medium | pyjwt (runtime, direct) | 2.13.0 | [GHSA-2gx3-rcp4-g85q](https://github.com/advisories/GHSA-2gx3-rcp4-g85q) / CVE-2026-101917 | `<= 2.13.0` | 2.14.0 | 2.15.1 — PATCHED | No JWKS client/fetch. |
| 11 | high | PyJWT (runtime, direct) | 2.13.0 | [GHSA-r6x4-923q-g947](https://github.com/advisories/GHSA-r6x4-923q-g947) / CVE-2026-102272 | `= 2.13.0` | 2.14.0 | 2.15.1 — PATCHED | HS256 only; configured secret, no public JWK. |
| 12 | high | pyjwt (runtime, direct) | 2.13.0 | [GHSA-p4g4-x82p-q773](https://github.com/advisories/GHSA-p4g4-x82p-q773) / CVE-2026-102271 | `>= 2.4.0, < 2.14.0` | 2.14.0 | 2.15.1 — PATCHED | No asymmetric DER verification keys. |
| 13 | high | PyJWT (runtime, direct) | 2.13.0 | [GHSA-9v7f-9g4p-ffgj](https://github.com/advisories/GHSA-9v7f-9g4p-ffgj) / CVE-2026-102267 | `<= 2.13.0` | 2.14.0 | 2.15.1 — PATCHED | No JWKS requests or redirect trust. |
| 14 | high | PyJWT (runtime, direct) | 2.13.0 | [GHSA-w2cx-738m-mc7w](https://github.com/advisories/GHSA-w2cx-738m-mc7w) / CVE-2026-102273 | `= 2.13.0` | 2.14.0 | 2.15.1 — PATCHED | No public JWK/JWKS containers as keys. |
| 15 | critical | PyJWT (runtime, direct) | 2.13.0 | [GHSA-ffc3-869f-jxw9](https://github.com/advisories/GHSA-ffc3-869f-jxw9) / CVE-2026-102268 | `<= 2.13.0` | 2.14.0 | 2.15.1 — PATCHED | No mixed symmetric/asymmetric algorithms or PEM keys. |
| 16 | medium | PyJWT (runtime, direct) | 2.13.0 | [GHSA-hxm8-2xgr-2p9m](https://github.com/advisories/GHSA-hxm8-2xgr-2p9m) / CVE-2026-102269 | `<= 2.13.0` | 2.14.0 | 2.15.1 — PATCHED | No raw-token revocation index; malformed serialization patched. |
| 17 | medium | pyJWT (runtime, direct) | 2.13.0 | [GHSA-8wjv-2p76-3863](https://github.com/advisories/GHSA-8wjv-2p76-3863) / CVE-2026-102265 | `>= 2.13.0, < 2.14.0` | 2.14.0 | 2.15.1 — PATCHED | Untrusted header parse reachable; nested-token regression covered. |
| 18 | high | PyJWT (runtime, direct) | 2.13.0 | [GHSA-9j54-fg26-wv3r](https://github.com/advisories/GHSA-9j54-fg26-wv3r) / CVE-2026-102266 | `>= 2.13.0, < 2.14.0` | 2.14.0 | 2.15.1 — PATCHED | No oct JWK; config rejects empty secret; library regression covered. |
| 19 | medium | pyjwt (runtime, direct) | 2.13.0 | [GHSA-jwrc-g2q2-pq5p](https://github.com/advisories/GHSA-jwrc-g2q2-pq5p) / CVE-2026-102270 | `<= 2.13.0` | 2.14.0 | 2.15.1 — PATCHED | Key is operator configuration, not request input. |
| 20 | medium | PyJWT (runtime, direct) | 2.13.0 | [GHSA-42vr-xj54-vc7v](https://github.com/advisories/GHSA-42vr-xj54-vc7v) / CVE-2026-101918 | `>= 2.0.0a1, <= 2.14.0` | 2.15.0 | 2.15.1 — PATCHED | No unverified decode/JWKS; recursive payload regression covered. |
| 21 | medium | PyJWT (runtime, direct) | 2.13.0 | [GHSA-gvp8-978c-rx2q](https://github.com/advisories/GHSA-gvp8-978c-rx2q) / CVE-2026-103001 | `>= 2.11.0, <= 2.13.0` | unset* | 2.15.1 — PATCHED | Fresh options per application call; non-mutation/reuse regression passed. |
| 22 | medium | Mako (runtime, transitive) | 1.3.12 | [GHSA-5639-2j2p-m4mx](https://github.com/advisories/GHSA-5639-2j2p-m4mx) / CVE-2026-102991 | `<= 1.4.1` | 1.4.2 | 1.4.3 — PATCHED | Alembic templates only; no request-controlled template URI. |
| 23 | medium | PyJWT (runtime, direct) | 2.13.0 | [GHSA-x33g-cr3x-6449](https://github.com/advisories/GHSA-x33g-cr3x-6449) / CVE-2026-102275 | `>= 2.1.0, <= 2.14.0` | 2.15.0 | 2.15.1 — PATCHED | No OKP JWK or DPoP integration. |

*Alert #21 has no `first_patched_version` in the live record. Its affected range
ends at 2.13.0. Resolved 2.15.1 is outside that range, and the explicit options
non-mutation/verification-mode-reuse regression passes. January already creates
a fresh options mapping per decode. This is sufficient local patch evidence;
the owner and independent auditor should confirm the advisory metadata on
publication day. There is no request to dismiss it.

All 14 Medium/Low findings in the original 23-alert inventory are PATCHED by the
local assessment; none is silently accepted or dismissed. Those original
Critical/High ranges are also resolved. The 2026-10-24 refresh below supersedes
the earlier zero-unresolved assessment: one additional Critical certifi advisory
affected the candidate and required the separately authorized update below.
GitHub still exposes the original 23 open repository
alerts; that count is not a complete package-security assessment.

## Independent OpenCode Audit Requirements

Independent audit is pending. Review the exact final uncommitted candidate and
its file hashes, baseline SHA, manifest, generated lock, security tests, fresh
23-alert inventory/reassessment, package metadata, and complete serial command
receipts. Do not substitute the baseline GitHub Quality result or partial local
attempt for final-lock evidence.

The auditor must independently verify Python 3.12 resolution, FastAPI support
policy and Starlette compatibility, all Critical/High PyJWT prerequisites, key
and algorithm boundaries, claim validation, database-backed tenant authority,
HTTP parsing/limits/path handling, lifecycle, concurrency, Docker acceptance,
backup/restore, migrations, RAG/feedback/provider governance, and every canonical
CI block. Confirm no validation, dependency verification, CI block, or security
control was weakened. Confirm newly required dependencies and unchanged-package
artifact normalization are legitimate. Recheck alert #21's missing patched
metadata against its range and executable non-mutation regression.

Reperform source/privacy review and inspect every exact-object scanner
disposition rather than inheriting it. Verify the single-root noreply history
and lack of imported private history. Review Mako PR #1's overlap separately.
Any unresolved Critical/High, runtime/security defect, required red gate, or
missing material proof prevents acceptance. No publication action is authorized
by this report or by an audit acceptance.

## Owner Commit, Push, And PR Gates

1. Obtain independent OpenCode acceptance for the exact candidate and complete
   local Quality receipts. Review the final diff, new files, file modes, and
   public-source inventory. Resolve any audit findings before publication.
2. Only the owner may stage/commit. Verify the exact approved GitHub noreply
   identity for both author and committer, including environment overrides.
   No original private refs, objects, hooks, or history may be imported.
3. Repeat current-source and full reachable-history audit after that eventual
   commit. These pre-commit results cannot cover a future commit or metadata.
4. Only the owner may push/open or reconcile a PR. Keep repository visibility
   private. Inspect/rebase the separate Mako PR overlap through normal owner
   review; do not automatically merge it or dismiss findings.
5. Require completed/success GitHub Quality on the exact owner-pushed SHA,
   correct branch/event, and verify Dependabot has processed that commit.
   Confirm zero unresolved Critical/High and reassess all remaining severities
   against then-current advisories. Local version comparison does not close
   GitHub alerts.
6. Follow the existing first-public-publication checklist, including a verified
   private disclosure channel and separately authorized visibility/tag/release
   decisions. This maintenance task performs none of those actions and does
   not establish that v0.1.0 is published.

## Fresh Privacy And History Review

The fresh all-local-refs-and-HEAD scan covered one root commit, no parents or
merges, 631 reachable objects (566 blobs, 64 trees, one commit), 580 historical
paths, and no deleted paths. Both identity headers are GitHub noreply. No
original private history is reachable in this repository. `git fsck --full --no-reflogs --unreachable` also completed without findings;
`git count-objects -v` reports exactly those 631 loose objects, no packs and no
garbage. No ref or history mutation was performed.

All 75 automatic history findings were reviewed anew against exact objects and
matching source context: 54 synthetic fixtures, 12 false positives, and nine
documented examples. Automatic detections remain visible; the reviewed scanner
result is `NO_UNRESOLVED_AUTOMATIC_FINDINGS`, zero unresolved. URL path segments
in official Zalo links account for two apparent personal-checkout matches; the
third is deliberate synthetic scanner test input. Credential shapes occur in
fake adapters/negative tests or documented local placeholders. Private-record
matches are synthetic evaluation/SQL fixtures or executable schema-building
code. High-risk filenames are example configuration or documentation/validator
source, not operational secret or backup files. No old dispositions were reused.

Current-source review includes untracked candidate files and excludes ignored
runtime/private evidence. New signing and webhook test values are explicitly
synthetic. Email-pattern matches are reserved examples or synthetic URL userinfo
in negative tests. No personal email, real private checkout path, or operational
credential was identified in the candidate's public source. Heuristic review
cannot guarantee the absence of every secret. Independent review and a new
history audit after the owner's later commit remain required.

### FastAPI Router Test Compatibility

The initial FastAPI compatibility trial found one test-only incompatibility: direct
`app.routes` iteration assumed every included router exposed `.path`. FastAPI
0.146 uses lazy included-router objects. The provider-route gate and governance integration inventory tests
now check the supported OpenAPI path inventory, preserving both route-presence
assertions and adding absent-route coverage plus real HTTP 404 (disabled) and
401 (enabled without credentials) checks for both routes. The focused provider-route test passed. The governance integration test
retains its HTTP single-use-token, no-query-string, and no-store assertions. No production route, authentication dependency, or assertion was
removed. The complete canonical sequence restarted from block 1 afterward.

The focused suite additionally proves webhook authentication precedes parsing,
declared and actual body-size limits remain enforced, malformed lengths/JSON
return safe client errors without persistence I/O, and 20 concurrent HTTP
requests preserve separate request IDs. A temporary exported-tree formatting
failure was corrected before the final sequence restarted; no check was skipped.

## Recovery And Durable Receipts (2026-10-20)

The previous temporary evidence directory and tool/process handles are missing.
A fresh process inventory confirms no prior Quality runner or validator is live.
Earlier narrative results are historical observations, not final receipts. The
full canonical sequence restarted with fresh service fixtures and unchanged
code/test/CI inputs. New command logs, process identity, input fingerprints, raw
metadata, and individual exit receipts are retained in ignored local evidence
under `.local/dependency-security-20261020/`. All 23 live alerts, repository
visibility, expected baseline Quality, local identities, and Mako PR #1 were
rechecked. A fresh privacy/history review will accompany the new receipts.

The 2026-10-20 metadata refresh identified FastAPI 0.151.0. The initial
durable run stopped at the boundary after canonical block 8 completed normally;
its earlier receipts remain separate from the final dependency freeze. Only
FastAPI was re-resolved, and the complete final matrix restarts from block 1.

## Changed Files

- `pyproject.toml`: three direct security/compatibility ranges and three transitive uv security floors, including the separately authorized certifi update.
- `uv.lock`: supported-uv resolution and verified artifact hashes.
- `backend/tests/test_dependency_security.py` (new): 32 security/HTTP/lifecycle/concurrency/trust-bundle regression cases.
- `backend/tests/test_provider_governance.py`: compatible route inventory plus actual disabled/authentication HTTP checks.
- `backend/tests/integration/test_governance_schema.py`: compatible route inventory; existing retrieval and authorization assertions preserved.
- `backend/tests/integration/test_conversation_feedback.py`: bounded preprovisioned test pool, structured sibling cleanup, preserved 100-operation/50-key atomicity assertions, and deterministic cleanup regression.
- `backend/tests/integration/test_self_host_runtime.py`: retain real commands/health checks and report redacted numeric failure categories.
- `backend/tests/test_self_host_runtime.py`: four redacted failure cases and successful-output preservation.
- `docs/plans/active/dependency-security-stabilization.md` (new): execution record, full advisory inventory, failed proof, and owner/audit handoff.

## Original Failed Canonical Quality Receipt Inventory

The preserved original attempt completed blocks 1–17 with exit 0 and stopped at
block 18 with exit 1 (151 passed, two failed, 979 deselected). Blocks 19–39 and
all four supplements were not launched. Its `quality-results.json`, `state.json`,
and `01.log`–`18.log` remain in the private evidence root. Original `18.log`
SHA-256: `807214e4a497ac2019a241830f6640fa6bded9e76bf5ecca8bc347059ad9492c`.
The full two-failure traceback extraction is retained in
`reliability-diagnosis/original-complete-tracebacks.txt` (770 lines).

| Exact original failing node | Original evidence and classification |
| --- | --- |
| `backend/tests/integration/test_conversation_feedback.py::test_feedback_concurrent_opposite_commands_have_no_lost_updates` | `sqlalchemy.exc.TimeoutError` at connection acquisition from `session.get`: QueuePool 5, overflow 5, timeout 3.00 seconds. Test admission starvation and an independently proven helper teardown race; no demonstrated production transaction defect or connection leak. Final test capacity and cleanup proof are recorded below. |
| `backend/tests/integration/test_self_host_runtime.py::test_fresh_docker_first_run_polling_restart_webhook_and_governed_delivery` | AssertionError after host curl of IPv4 loopback `/live` during the publication/restart phase. The legacy helper redacted the underlying numeric curl status; it cannot be recovered. Historical root cause remains undetermined. No production health or dependency incompatibility was reproduced. Real health/port/startup/shutdown assertions remain unchanged; scoped diagnostic categories prevent this loss of evidence in future failures. |

The final receipt table below covers every unchanged canonical command. Earlier
partial or failed attempts are historical evidence and do not establish final
Quality.

## Bounded Reliability Diagnosis — Owner Follow-up

Preflight revalidated HEAD and `origin/main` at the expected baseline, exact
uncommitted candidate files, installed versions, all prior exit receipts, and
the complete original tracebacks. Original receipts are unchanged. The complete
traceback extraction is retained privately under
`.local/dependency-security-20261020/reliability-diagnosis/`.

### Initial Feedback Findings And Scoped Corrections — 2026-10-20

The exact original test was run once with observation-only SQLAlchemy pool and
transaction tracing on a fresh owned PostgreSQL fixture. It passed all 100
operations and the existing 50-state/revision/event assertions. The committed
baseline was exported without Git history and tested in a separate locked
virtual environment against the same fixture; it also passed. Both used the
production-default 5+5 pool, reached ten checked-out connections, and took
about 2.25–2.29 seconds to admit the last operation in the burst. Both returned
every connection, closed all ten physical connections, and left zero observed
PostgreSQL backends. SQLAlchemy, asyncpg, database lifecycle code, and feedback
transaction code are identical between the baseline and candidate. No
production transaction, authorization, or session-lifecycle defect was observed.

The original failure is a pool-admission timeout at the three-second limit,
not a constraint/deadlock exception or demonstrated connection leak. The test
was using short production admission defaults for a synchronized 100-operation
atomicity proof across 50 independent keys, with cold pool startup inside that
burst. A first scoped trial provisioning 50 cold test connections still failed
(exit 1, 17 timeouts); the repetition runner stopped immediately. Tracing showed
49 connection handshakes occupying about 1.4 seconds after the gate and the
first commit only around 2.47 seconds. That failed receipt is preserved and is
not counted as green evidence.

That trial also proved a test-helper teardown race: `asyncio.gather` propagated
the first failure with 44 sibling operations still running while fixture
cleanup began. A new deterministic regression failed against the old helper
(exit 1: sibling cleanup had not finished) and passed with structured task
joining/cancellation (exit 0). It checks that the original SQLAlchemy error
remains visible.

The scoped test changes provision a bounded 50-connection test pool before the
100-operation gate, explicitly check zero checked-out connections, and join or
cancel all helper tasks before teardown. All 100 logical operations, 50 keys,
50 final states at revision 2, 100 events, and current/event consistency
assertions remain intact. Production pool defaults and the three-second
acquisition timeout are unchanged. There are no sleeps, skips, xfails, error
suppression, production code changes, or reduced-concurrency shortcuts.

The proof is one exact post-fix run followed by ten repetitions, fail-fast, with
pool events, transaction completion, and post-disposal backend checks retained
for every run. Completed results and the historical Docker limitation follow.

### Initial Focused Follow-up Results — 2026-10-20

The warm test-only pool correction passed its exact initial run and all ten
planned repetitions (eleven runs total, every exit code 0). Each retained all
100 saved outcomes, 50 final states, revision 2, 100 events, and latest-event
consistency. Every run recorded zero checked-out connections before disposal,
equal physical opens/closes, completed transactions, zero remaining observed
PostgreSQL backends, and no cold connection creation during the operation gate.
The earlier cold-pool trial remains recorded as failed; it was not retried
unchanged or counted as a pass. The helper cancellation regression has a
recorded red/green result, with the SQLAlchemy failure preserved.

The exact original Docker test passed once under observation-only diagnostics
(exit 0; all 76 commands exit 0). Its own fresh project had healthy backend,
PostgreSQL and Redis containers; migration exit 0; the expected IPv4 loopback
host port matched both configured and actual Docker bindings; the final bridge
was non-internal as intended; both curl probes exited 0 and independent direct
HTTP observations returned 200 for `/live` and `/ready`. No proxy variables were
present, no IPv6 resolution was involved, and no stale project, conflicting
port, missing provisioning, or current sandbox restriction was observed.
Task-owned resources were absent after cleanup.

The historical Docker failure's original curl exit category is irrecoverable
from its redacted helper output. It has not been reproduced or attributed to
production health or dependency incompatibility. No speculative port, network,
health-check, retry, or timeout change was made. The test orchestration helper
now reports only executable type, numeric exit code, and a fixed error category
while keeping arguments/stdout/stderr redacted. Four negative cases and a
success case prove that diagnostic behavior and private-detail rejection.
The actual curl commands and health assertions remain unchanged.

Affected self-host unit tests plus the 31 dependency-security regressions passed
56 cases (exit 0), and affected Ruff/format checks passed.

The post-change exact Docker acceptance run passed through the normal helper
(exit 0), with its real health/provisioning/cleanup assertions unchanged. The
complete affected feedback module passed nine tests (exit 0). Full-backend Ruff
and formatting, and mypy over 168 application files, passed (all exit 0). The
owned diagnostic database had zero remaining client backends and was removed
cleanly. No production source file changed.

A fresh complete canonical run now uses one frozen post-fix source snapshot and
separate private receipts under
`.local/dependency-security-20261020/quality-after-reliability-fix/`. Original
failed and diagnostic receipts remain intact. This run executes all 39 commands
in their original order, serially, including the full reliability validator at
block 18 before subsequent blocks, then four supplemental validators. Prior
partial results do not establish final Global Quality.

### Host Restart Recovery — 2026-10-24

The post-fix sequence completed canonical blocks 1–19, every exit code 0. Block
2 passed 955 unit tests and the required static checks. Block 18 completed the
whole reliability chain, including its 154-case combined integration selection,
feedback concurrency, Docker acceptance, Redis concurrency, and synthetic
backup/restore. Its final exit code is 0; block 19 also exited 0.

The host restarted during block 20's Docker integration test. Recovery confirmed
a different kernel boot ID, absent original parent and child processes, an
unfinished log, and no command-exit receipt. This interruption is neither a test
pass nor a demonstrated runtime failure. All 581 fingerprinted validation
inputs are unchanged and all 19 completed log hashes still match their receipts.
The interrupted state and log are preserved separately; no original failed or
completed receipt was overwritten.

The orphan project `spec043-runtime-8fbcf7ac6d7b` was identified by its repository
working-directory label, pytest-48 fixture path, and creation timestamp during
block 20. Only that project's containers, volumes, and networks were removed;
all cleanup commands exited 0 and exact-label inventories were empty afterward.
Other Docker projects were left untouched. CI service fixtures are reprovisioned
with their original health checks. The sequence resumes at the interrupted block
20, then continues 21–39 and four supplements serially on the same source
snapshot. A recovery-driver import failure occurred before any validator ran;
using the system Python with its existing YAML module corrected the private
driver environment without changing project dependencies.

## Additional Critical Advisory — Separate Owner Decision Record

The authoritative package refresh at 2026-10-23 17:49 UTC (2026-10-24 local)
returned two alias records for one new advisory:
[GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2),
Critical, CVSS 9.1, published 2026-10-20 19:35:05 UTC. It affects certifi
`>=2019.03.09,<2026.10.19`; the patched boundary is 2026.10.19. The record was
published after this candidate's dependency freeze. The separate PyPI alias is
PYSEC-2026-4320, not a second independent vulnerability. No CVE is assigned in
the retrieved GitHub record.

Exact root cause: the locked and installed certifi 2026.7.22 trust bundle retains
emSign ECC Root CA - G3. The advisory reports compromised intermediate keys
chaining to that root, allowing an on-path attacker to present certificates that
affected clients trust. This is a real production dependency security defect,
not a feedback or Docker test defect. The same version is in the committed
baseline, so this candidate did not introduce it. Exploitation against January
has not been demonstrated or claimed.

Read-only executable evidence confirms that the installed HTTPX default SSL
context loads `certifi.where()` and that an SSL context created from that exact
bundle contains the affected root. Production model-provider, Telegram, TTS,
semantic-memory, and knowledge adapters construct HTTPX clients with default
verification. The trust-bundle SHA-256 is
`9cc2a774b5198dcff14d9be1e66091f538975d867ce029a96bce15a55dfd730f`.
Relevant affected surfaces are `uv.lock`, the HTTPX dependency chain in
`pyproject.toml`, `backend/app/infrastructure/model_providers.py`,
`backend/app/infrastructure/telegram/adapter.py`,
`backend/app/infrastructure/text_to_speech.py`,
`backend/app/infrastructure/semantic_memory.py`, and
`backend/app/infrastructure/knowledge.py`. None of those production files was
edited for this diagnosis.

Private evidence in `quality-after-reliability-fix/` includes the complete
`certifi-advisory.json`, refreshed 41-package `pypi-resolved-audit.json`,
`certifi-runtime-exposure.json`, and installed HTTPX SSL-context source.
The current 23 repository alerts remain open and their patched-range assessment
is unchanged. Before the separately authorized certifi update, this evidence
identified one unresolved Critical and zero unresolved High findings, blocking
the security release gate.

Recommended separately authorized remediation: add a minimal certifi security
floor `>=2026.10.19`, regenerate `uv.lock` with supported uv 0.6.5, confirm only
the required resolution changes, run locked all-group sync and compatibility
checks, and rebuild images that vendor the bundle. Regression proof should
inspect the actual installed trust bundle for absence of the affected root,
retain normal trusted TLS and invalid-certificate rejection, preserve existing
HTTP/JWT/tenant/security tests, and repeat all 39 canonical blocks plus four
supplements serially on the changed snapshot. No live credentials or malicious
network calls are needed. Do not disable TLS verification or replace the trust
store with an arbitrary bundle.

The owner's follow-up limits corrections to proven test/environment defects;
its production stop rule and the original security mission prevent silently
making this unrelated runtime dependency change or accepting the vulnerability.
Separate authorization was requested for exactly the certifi floor, generated
lock update, image rebuild, and complete validation. The owner answered:
"Authorize the certifi security update and full validation." Preserve the
candidate and all receipts, finish the running validator's cleanup boundary,
apply that minimal update, prove the trust-bundle regression, and restart all
39 canonical blocks plus four supplements. No completion audit or Global
Quality GREEN claim is valid before those gates pass on the new snapshot.

### Authorized Certifi Remediation And Stronger Admission Isolation

uv 0.6.5 regenerated the lock using `uv lock --upgrade-package certifi` after
adding the authorized `certifi>=2026.10.19` constraint. It resolved 2026.10.23,
whose authoritative version-specific PyPI metadata supports Python 3.12 and
contains no vulnerability records. Only certifi's complete package record
changed; all 41 other package records and artifact checksums are identical to
the preserved prior candidate. No lock hash was manually edited.

Locked all-group sync and `uv pip check` exited 0. The exact trust-bundle
regression failed against 2026.7.22 (exit 1, affected root present) and passed
against 2026.10.23 (exit 0). It checks the actual installed bundle excludes
emSign ECC Root CA - G3 and retains required peer verification and hostname
checking. An independent offline MemoryBIO TLS exchange accepted a trusted
synthetic chain using TLS 1.3, rejected an untrusted issuer with verification
code 20, and rejected a wrong hostname with verification code 62. Ephemeral
synthetic keys were deleted with their private temporary directory; no external
service or live credential was used. The affected unit/security selection passed
57 tests, including all 32 security cases. Ruff and formatting exited 0.

An additional final-lock feedback repetition deliberately rechecked the original
pool correction. Its initial run and repeats 1–5 passed, but repeat 6 failed
(exit 1) and the runner stopped. Full tracebacks and instrumentation remain in
`certifi-remediation-20261024/`. The exception group contains ten SQLAlchemy
pool-admission TimeoutErrors with pool 50, overflow 0, timeout 3.00 seconds.
All 100 operations started; 41 saved before failure and 49 were cancelled and
joined. Every transaction completed, all 50 physical connections closed, and
zero connections remained checked out. No cold connection was created during
the gate. The first commit occurred about 1.83 seconds after the gate, and
advisory-lock waits reached about 1.33 seconds. Thus prewarming alone did not
fully isolate 100 operations from a 50-slot admission queue; the earlier eleven
passes remain historical evidence, not a guarantee or substitute for this red
repeat. No lost-update, deadlock, or production connection leak was observed.

A proposed retained pool of 100 was rejected by the existing Settings upper
bound of 50 (exit 1 before any transaction). That failed attempt is preserved;
production configuration validation was not changed or bypassed. The scoped
test now uses the supported 50 retained plus 50 bounded overflow slots, matching
all 100 simultaneous operations, and warms the 50 retained slots before the
barrier. All 50 keys, 50 final states, revision 2, 100 events, current/event
consistency, zero-checkout assertions, and structured task cleanup remain.
Production defaults and the three-second pool timeout remain unchanged.
The new exact run and all ten planned repetitions passed (eleven exit codes 0),
followed by the complete feedback module (nine passed, exit 0). Every repetition
peaked at 100 checked-out connections, saved all 100 operations, verified 50
states at revision 2 and 100 events, completed all transactions, joined every
task, closed all 100 physical connections, and left zero checked-out connections
or observed PostgreSQL backends. The owned database was healthy with its real
check enabled and was removed cleanly (exit 0).

The full final-lock sequence now runs all 39 canonical blocks and four
supplements, serially, with fresh fixtures and unchanged CI commands/health
checks. Receipts are separate under
`.local/dependency-security-20261020/quality-certifi-final-20261024/`; original
failed, interrupted, prior passing, and scoped diagnostic receipts remain
preserved. Production source and CI remain unchanged. The new snapshot includes
the 50+50 test capacity and certifi 2026.10.23; earlier partial matrices cannot
establish its Global Quality status.

The final run's block 2 passed 956 unit tests with 183 integration tests
deselected by the canonical unit selection, Ruff/format passed all 256 backend
files, and mypy passed 168 application files. The unchanged optional Harness
binary branch reported absence; no selected pytest case was skipped or xfailed.
Block 6 rebuilt the actual local acceptance image. An offline read-only container
probe exited 0 and confirmed certifi 2026.10.23, no compromised root, required
certificate verification, and hostname checking. Image ID:
`sha256:81d95081c81f682453cbb3554f877f80856e6147c8a0cefe990ec3212e46595e`.
The container uses Python 3.12.15; local proof uses Python 3.12.9. Both satisfy
the unchanged Python 3.12 requirement. Remaining gates are still pending.

Final-snapshot canonical blocks 1–19 have now completed successfully. Block 18
exited 0 after its entire reliability chain: 154-case combined integration
selection, feedback, fresh Docker loopback acceptance and cleanup, ingress,
conversation, planning, delivery, commands, memory, safety, Redis concurrency,
and synthetic backup/restore including feedback state/history. Block 19 exited
0. Their log hashes match the exit receipts, and the original failed block-18
log remains byte-for-byte unchanged. Block 20 and the later canonical and
supplemental gates are still pending, so Global Quality is not yet green.

Blocks 20–25 have subsequently passed on that same snapshot. Block 23 completed
the unchanged seven-command migration lifecycle. Block 24 passed all 183
integration cases with no failed, skipped, or xfailed cases; its exit code is 0
and its log hash matches the receipt. The full selection includes both fresh
self-host runtime and setup acceptance, all feedback cases, safety, tenancy,
governance, and the other marked integrations. At that milestone blocks 26–39 and the four supplements remained pending; the
final completion record below supersedes that partial status.

## Final Local Quality And Security Handoff

Verification cutoff: 2026-10-24 01:03:59 UTC. Baseline, HEAD, `origin/main`, and remote main remain
`069642473d6a39824b7a5ccf9c844cb8e6c4f354`. Repository visibility remains private.
The existing GitHub baseline Quality run 39093786388 remains main/push,
completed/success. No new Git commit or GitHub Quality result is claimed.

All 39 canonical blocks and four relevant supplements passed locally, serially,
on one final product/test/CI snapshot: 581 source hashes excluding this execution
record. Every command, step environment, ordinal, exit code, log hash, and serial
timestamp is checked against the unchanged `.github/workflows/ci.yml`. The final
receipt root is `.local/dependency-security-20261020/quality-certifi-final-20261024/`.
The unit gate passed 956 cases; the complete integration gate passed 183 cases,
with no selected cases skipped or xfailed. Fresh collection confirms all 182
original integration node IDs remain; the only addition is the fixture cleanup
regression. All 32 dependency-security cases passed. Static checks, AI evaluation,
full migration lifecycle, feedback, real Qdrant, tenant/provider governance,
Docker acceptance, and backup/restore completed successfully.

The final manifest resolves FastAPI 0.151.0, Starlette 1.3.1, PyJWT 2.15.1,
Mako 1.4.3, certifi 2026.10.23, and dev pytest 9.0.3. Local Python is 3.12.9;
the rebuilt acceptance image uses 3.12.15. All 41 registry packages support
both versions according to refreshed authoritative metadata and have no PyPI
vulnerability records at this cutoff. Installed versions match the generated
lock. All 23 current open GitHub advisory ranges and the additional Critical
certifi range are PATCHED locally: zero unresolved Critical/High, and all 14
Medium/Low findings patched. The new certifi advisory is additional to the
repository alert inventory and its two PyPI aliases represent one finding.
The 23 GitHub alerts are still open; none was dismissed or claimed closed.

Final feedback proof is the exact test plus ten planned repetitions, all exit 0,
with 100 logical operations, 50 independent keys, 50 states at revision 2,
100 events, equal 100 physical opens/closes, completed transactions, all tasks
joined, and zero observed backend/checked-out connections in every run. The
complete affected feedback module passed nine cases. The earlier 50-slot failed
repeat and rejected retained-size-100 attempt remain visible; they are not green
receipts. The supported final test capacity is 50 retained + 50 bounded overflow;
production defaults, validation bounds, timeout, and transaction code are intact.

Docker acceptance passed through the normal helper in the complete matrix.
The independent controlled diagnosis also recorded 76 command exits 0, healthy
backend/PostgreSQL/Redis, migration exit 0, actual/expected
`127.0.0.1:34849 -> 8000` binding, curl exits 0 and independent HTTP 200 for both
`/live` and `/ready`, and complete owned cleanup. IPv6, proxy interference,
missing provisioning, port conflict, stale ownership, or sandbox restrictions
were not observed in that controlled reproduction. Historical curl failure
classification remains unavailable; no speculative retry, timeout, network,
health-check, or production change was made.

The final test-run primary services were healthy before shutdown. Their Compose
shutdown and the base fixture shutdown exited 0. An initial cleanup inventory exited 1 after finding a retained owned fixture.
The semantic and SPEC-027/033 Qdrant fixtures retained by validators were identified by their exact current
project labels, then removed with their owned volumes/networks (all exits 0).
The final cleanup inventory is empty for every final-run task project. Other
Docker resources were left untouched. No socket permissions, sudo, health-check
bypasses, skips, xfails, arbitrary sleeps, or reduced-concurrency assertions were
introduced.

Remaining limitations: the original curl error category is irrecoverable; the
still-supported HTTPX TestClient emits a Starlette deprecation warning; alert
#21 has no patched-version metadata and needs its documented range/regression
rechecked on publication day. Block 9's receipt spans 21,719.1 wall seconds while
its process/boot identity remained unchanged; its command and all subruns exited
0. The exact cause of that elapsed span is not established. Local receipts do
not establish future GitHub runner timing or a new remote Quality result.
Independent review, future advisories, and the owner's post-commit history audit,
exact-SHA GitHub Quality, Dependabot processing, and separate publication gates
remain required. No commit, push, merge, tag, visibility change, or publication
was performed, and the original private checkout was not modified.

### Final Canonical Receipts

| Block | Canonical command | Exit | Log |
| --- | --- | --- | --- |
| 1 | `uv sync --all-groups --locked` | 0 | `01.log` |
| 2 | `./scripts/validate.sh` | 0 | `02.log` |
| 3 | `./scripts/validate-self-hosted.sh` | 0 | `03.log` |
| 4 | `./scripts/validate-public-release.sh` | 0 | `04.log` |
| 5 | `./scripts/validate-graphify-integration.sh` | 0 | `05.log` |
| 6 | `docker build --tag january-self-host:spec043-development .` | 0 | `06.log` |
| 7 | `./scripts/validate-ai-evals.sh` | 0 | `07.log` |
| 8 | `./scripts/validate-telegram-conversation-ux.sh` | 0 | `08.log` |
| 9 | `./scripts/validate-telegram-presence.sh` | 0 | `09.log` |
| 10 | `./scripts/validate-telegram-regeneration.sh` | 0 | `10.log` |
| 11 | `./scripts/validate-telegram-reactions.sh` | 0 | `11.log` |
| 12 | `./scripts/validate-telegram-voice-tts.sh` | 0 | `12.log` |
| 13 | `./scripts/validate-conversation-feedback.sh` | 0 | `13.log` |
| 14 | `./scripts/validate-deployment.sh` | 0 | `14.log` |
| 15 | `./scripts/validate-zalo-feasibility.sh` | 0 | `15.log` |
| 16 | `./scripts/validate-zalo-verification.sh` | 0 | `16.log` |
| 17 | `./scripts/validate-observability.sh` | 0 | `17.log` |
| 18 | `./scripts/validate-reliability.sh` | 0 | `18.log` |
| 19 | `./scripts/validate-scalability.sh` | 0 | `19.log` |
| 20 | `./scripts/validate-ambient.sh` | 0 | `20.log` |
| 21 | `./scripts/validate-summaries.sh` | 0 | `21.log` |
| 22 | `./scripts/validate-semantic-memory.sh` | 0 | `22.log` |
| 23 | `uv run alembic upgrade head; uv run alembic downgrade base; uv run alembic upgrade head; uv run alembic downgrade 0005_outbound_delivery; uv run alembic upgrade head; uv run alembic downgrade 0007_telegram_commands; uv run alembic upgrade head` | 0 | `23.log` |
| 24 | `uv run pytest -m integration` | 0 | `24.log` |
| 25 | `uv run pytest -m ingress_integration` | 0 | `25.log` |
| 26 | `uv run pytest -m conversation_integration` | 0 | `26.log` |
| 27 | `uv run pytest -m planning_integration` | 0 | `27.log` |
| 28 | `uv run pytest -m delivery_integration` | 0 | `28.log` |
| 29 | `uv run pytest -m demo_integration` | 0 | `29.log` |
| 30 | `uv run pytest backend/tests/test_personality.py && uv run pytest -m 'planning_integration or personality_integration'` | 0 | `30.log` |
| 31 | `uv run pytest backend/tests/test_telegram_commands.py && uv run pytest -m command_integration` | 0 | `31.log` |
| 32 | `uv run pytest -m memory_integration` | 0 | `32.log` |
| 33 | `./scripts/validate-safety.sh` | 0 | `33.log` |
| 34 | `./scripts/validate-provider-governance.sh` | 0 | `34.log` |
| 35 | `./scripts/validate-personal-context.sh` | 0 | `35.log` |
| 36 | `./scripts/validate-telegram-media.sh` | 0 | `36.log` |
| 37 | `./scripts/validate-proactive-scheduling.sh` | 0 | `37.log` |
| 38 | `./scripts/validate-multi-tenancy.sh` | 0 | `38.log` |
| 39 | `./scripts/validate-knowledge-rag.sh` | 0 | `39.log` |

### Final Supplemental Receipts

| Validator | Exit | Log |
| --- | --- | --- |
| `./scripts/validate-production-readiness.sh --offline` | 0 | `supplement-01.log` |
| `./scripts/validate-governance.sh` | 0 | `supplement-02.log` |
| `./scripts/validate-live-acceptance.sh` | 0 | `supplement-03.log` |
| `./scripts/validate-public-release.sh` | 0 | `supplement-04.log` |

The independent OpenCode audit requirements and owner-only gates above remain
in force. Review this exact nine-file uncommitted candidate and the final receipt
hashes, including the separately authorized certifi change and 50+50 test-only
capacity. No audit acceptance or publication action is implied by local green
validation.

Final source/privacy review covered all 582 current source files, including
untracked candidate files and this report: 69 automatic content detections and
five email-pattern matches reviewed, zero unresolved. The fresh historical scan
has the same exact 75 findings and objects as the independently reviewed root
snapshot: 54 synthetic fixtures, 12 false positives, and nine documented examples.
One root commit, 631 reachable objects, 580 historical paths, two noreply identity
headers, no imported private history, and empty `git fsck` findings were verified.
The post-report public-release validator also exited 0. Final source hashes and
all 43 command receipts are checked by `completion-audit.json`; independent
acceptance remains pending. Git status contains only the nine listed candidate
files, with nothing staged and no publication action performed.
