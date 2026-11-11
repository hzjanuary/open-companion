# OSS-001 acceptance and source verification ledger

Status: **IN PROGRESS — NOT RELEASE READY**. Updated 2026-11-04.

Repository: https://github.com/hzjanuary/open-companion (ID `1423511659`).
Baseline main/starting HEAD: `612f89c6724261873d38cfa9a9639eb5836cb41a`.
Working branch: `feat/oss-001-january-source-release`; the local candidate is identified by the commit containing this ledger,
not by baseline HEAD alone. Its full SHA and post-commit archive hashes belong
in the task handoff receipt (`git rev-parse HEAD` in this feature checkout).
Draft PR URL, remote candidate archives and new Actions run IDs remain pending.

PASS records only the bounded observation in the evidence column. NOT_RUN is
not PASS. BLOCKED identifies a missing required input. FAIL identifies an
executed check or observed contract that did not pass. Synthetic checks never
prove live Telegram/provider availability. Independent audit remains BLOCKED
until the exact approved private package/export and independent results exist.

| Criterion | Requirement | Status | Evidence / remaining work |
| --- | --- | --- | --- |
| OSS-01 | Correct repository identity and public root | PASS | GitHub API ID 1423511659/public/main; parentless root 069642473d6a39824b7a5ccf9c844cb8e6c4f354. |
| OSS-02 | No private original Git history imported | PASS | All five candidate reachable commits descend from the sole public root; no parent before root. Content review is separate. |
| OSS-03 | All current refs/history reviewed | PASS | All advertised remote heads/tags/PR heads fetched into audit aliases; local candidate scan: 5 commits, 699 objects, 589 historical paths, 79 exact heuristic findings dispositioned, zero unresolved. Unadvertised/unreachable server objects excluded. |
| OSS-04 | No unexplained Git identity or private path | PASS | Root/feature noreply and GitHub merge committer verified; owner acknowledged existing merge-author metadata. Three path detections are public URL components or synthetic detector fixtures. |
| OSS-05 | All tracked files classified | PASS | Per-file source classifications and recorded/proposed Git modes; updated again after final artifact additions. |
| OSS-06 | Official MIT copyright is Hoang Nguyen | PASS | LICENSE updated; standard MIT grant unchanged. |
| OSS-07 | LICENSE hash validator updated | PASS | LICENSE SHA-256 4d7986336b20626e0f4b37bdcd8010f718856bdf0fecb11f40dfdd5f705d49e1; all 33 public-release regressions pass. |
| OSS-08 | NOTICE retains installed Harness obligations | PASS | Exact upstream MIT retained; core 0.1.7 manifest: 38 comparisons, 33 matches and five adapted current docs. No Harness files removed; no external Harness fetch required. |
| OSS-09 | Direct/transitive dependency inventory verified | PASS | All 41 locked third-party components reverified against installed metadata/license hashes and exact locked Windows wheel; CycloneDX covers identical names/versions. |
| OSS-10 | Container and optional model licensing disclosed | PASS | Machine container inventory records actual image/package licenses, Redis 7.4.11 RSAL/SSPL boundary, uv build tool and optional model-weight terms. Engineering inventory, no legal certification. |
| OSS-11 | Current source secret scan PASS | PASS | Current-source contextual review has zero unresolved findings; pinned redacted Gitleaks raw exit 1 contains only two enum false positives. Final publication snapshot and its exact manifest are checked before local commit; no scanner suppression. |
| OSS-12 | Complete-history scan coverage PASS | PASS | Complete non-shallow local HEAD/all-refs scan after advertised PR-ref expansion and candidate commit: 79 heuristic findings reviewed by exact ID; Gitleaks raw exit 1 has only two reviewed enum false positives. No suppression or history rewrite. |
| OSS-13 | No real user conversations/memories in source | PASS | Current 589-path committed source review: 69 content findings; 68 match prior exact-object dispositions, one changed closed-Docker fixture reviewed separately. Only synthetic fixtures/examples and code/schema matches; no real records identified. |
| OSS-14 | Private data and operator paths excluded | PASS | Source manifests/archive extraction exclude operator .env/.local/.runtime, environments, databases/backups, weights and private receipts; four clearly synthetic env examples retained. Existing operator data preserved. |
| OSS-15 | Data governance matches implementation | PASS | Reviewed code/migrations/export/erasure and privacy tests; corrected stale-job cutoff, future/missing-time handling and edit non-resurrection. Separate memory/context retention, provider/Telegram boundaries and backup reconciliation disclosed. |
| OSS-16 | Encryption limitations accurately disclosed | PASS | Docs match production HTTPS validation and owner TLS/storage/backup/key responsibilities; plaintext private env files and local/internal HTTP disclosed; no field/E2E encryption. |
| OSS-17 | Private vulnerability disclosure channel verified | PASS | Owner-authorized enablement; API readback enabled:true on 2026-11-01 and 2026-11-04; working private advisory URL in SECURITY. |
| OSS-18 | Dependency advisory audit recorded | PASS | pip-audit 2.9.0 on exact unchanged lock, all 41 packages, exit 0 / zero known advisories on 2026-11-04. PyPI API exposes no immutable DB revision; raw snapshot/hash retained. |
| OSS-19 | OS/container image scan recorded without suppression | PASS | Actual corrected-source image scanned with pinned Trivy 0.76.1; raw exit 1 retained. 45 OS HIGH, 0 CRITICAL, no fixed version for HIGH; other severities/base pip findings retained. This row proves recording, not image approval. |
| OSS-20 | Locked Python 3.12 setup succeeds | PASS | uv 0.6.5 sync --all-groups --locked: CPython 3.12.9, 40 distributions installed. |
| OSS-21 | Full canonical Quality passes | PASS | Local R4 canonical campaign on exact candidate 2db1b9cba9dc195020f86c8bfbfcb8402e67d730: all recorded commands exit 0 (receipt set oss-001-20261111-r4). 962 unit tests and 184 integration tests pass. Remote exact-SHA gate separately tracked as OSS-37 (PASS). || OSS-22 | Single Alembic head verified | PASS | All 26 migration blobs unchanged from baseline; AST graph has sole head 0026_conversation_feedback. Executable migration lifecycle proof remains separately required. |
| OSS-23 | Migration lifecycle tests pass | PASS | Canonical step 25 fresh synthetic lifecycle: upgrade head, downgrade base, upgrade, downgrade 0005, upgrade, downgrade 0007, upgrade; supplementary feature migration/guard proofs pass. |
| OSS-24 | Synthetic PostgreSQL/Redis/Qdrant integration passes | PASS | Fresh owned PostgreSQL 16 / Redis 7 / Qdrant v1.13.4; canonical 184 integration tests plus semantic-memory/RAG index rebuild/reconciliation validators pass. No personal/production database used. |
| OSS-25 | Tenant/Assistant/connection authorization passes | PASS | Multi-tenancy validator and 184-test integration run cover Tenant/Assistant/connection authority, authenticated control plane and denied cross-scope operations. |
| OSS-26 | Memory/privacy/erasure tests pass | PASS | Eight schema tests and 31 final-delta memory/command/delivery/governance integrations pass; canonical personal-context/governance/export/erasure/retention suites also pass. |
| OSS-27 | Provider governance and budget tests pass | PASS | Provider-governance validator and canonical provider schema suites pass with synthetic adapters, budget/capability/health/fallback admission; no hosted/local inference. |
| OSS-28 | Worker recovery and delivery semantics pass | PASS | Canonical ingress, ordered delivery, reliability and recovery suites pass. Final-delta expiry tests preserve terminal outcomes, fence leases and quarantine uncertain delivery without retry. |
| OSS-29 | Backup/restore and upgrade proof passes | PASS | Fresh synthetic backup/restore validator passes revision/redaction/idempotency/safety/recovery/voice-artifact/feedback assertions; migration lifecycle and upgrade compatibility proofs pass. Backup encryption/purge remain owner obligations. |
| OSS-30 | Offline AI evaluation preserves accurate states | PASS | Deterministic offline JSON: 125 PASS, 5 NOT_EVALUATED, 0 FAIL, 0 ERROR; judge disabled. PASS here concerns execution/state integrity, not the five unevaluated quality judgments. |
| OSS-31 | Clean self-host distribution test passes | PASS | Local 589-file source archive extracted without .git/operator state; locked sync, self-host/public/Graphify validators and closed Docker polling/restart/dedup/webhook acceptance pass. |
| OSS-32 | Docker non-root and local topology checks pass | PASS | Final-cutoff stock image: uid/gid 999, CapEff zero, correct LICENSE/NOTICE, no /app private env/state/Git. Closed fixture checks loopback topology, authenticated setup, migration ownership and required worker graph. |
| OSS-33 | Source archive/private-path integrity passes | PASS | Local archive hashes/modes match all 589 manifest paths; all 26 migrations, source/tests/docs/scripts/legal included. No private path/database/weight/receipt. GitHub-generated archive verification remains separate OSS-38. |
| OSS-34 | Clean archive extraction and documented setup pass | PASS | tar and ZIP extraction hash/mode checks plus clean locked setup, synthetic secret generation, offline doctor/authenticated setup and actual closed Docker first-run test pass. Final live setup not executed. |
| OSS-35 | README/release docs match public repository state | PASS | README, current maintainer procedure, draft notes and quickstart describe existing public repository/root/history. Historical SPEC-048 remains unchanged; v0.1.0 unpublished. |
| OSS-36 | Independent OpenCode audit complete | BLOCKED | Independent OpenCode V2 review completed with verdict NOT READY (not a release-readiness approval). Exact owner-approved private SPEC-048 package path/export remains unavailable; public handoff is not a substitute. || OSS-37 | Exact-SHA GitHub Quality passes | PASS | GitHub Quality run 43006339971 (job quality) completed success on PR #3 head 2db1b9cba9dc195020f86c8bfbfcb8402e67d730; all 44 workflow steps success, no bypass. || OSS-38 | GitHub source artifacts/checksums verified | PASS | Candidate archives for 2db1b9cba9dc195020f86c8bfbfcb8402e67d730 verified: ZIP SHA-256 41247a5577b15aeda191aacaedab7ca268d8a0661e1b6130ebce8843ec91bf84; tar.gz SHA-256 8562999fb47a522cb1d54b0a8ddd66046d0ca3a37805969685b22dc9784e4ae3; 589 files each, all blob hashes match Git tree, executable modes preserved, 26 migrations, LICENSE/NOTICE present. Candidate archives, not release-tag archives. || OSS-39 | Source-only and Docker-image decisions separate | PASS | Separate source/image decisions in current procedure; no image publication or approval. |
| OSS-40 | Owner release decision explicitly pending | PASS | No merge, tag or Release publication authorized. Stop at Draft PR. |

## Baseline and boundaries

GitHub baseline Quality [40069948712](https://github.com/hzjanuary/open-companion/actions/runs/40069948712)
was completed/success, event push, exact baseline SHA. Existing ruleset
[protect-main](https://github.com/hzjanuary/open-companion/rules/25766062)
requires strict `quality`, PRs, prevents deletion/non-fast-forward updates,
and has no bypass actors. No ruleset mutation, history rewrite or visibility
change occurred. Root identities are noreply; owner acknowledged the existing
merge-author metadata without authorizing its repetition in reports.

No real Telegram login/delivery, provider inference, LLM judge, external Zalo
scan or production data access is performed: **NOT_RUN (not authorized)**.
Private audit package: **BLOCKED / PENDING**; owner explicitly permits other
authorized offline work, but no independent completion/readiness claim.

## Current corrected-source findings

The PostgreSQL cutoff regression reproduced retained stale content on the old
implementation (messages 4/6 cleared, outbound payloads 1/6, command arguments
0/6). A late edit also restored redacted text. The bounded fix uses original
source age for command arguments, clears expired stalled work, fences old leases,
retains unknown delivery/quarantine and preserves edit tombstones. All eight
focused schema tests pass. No migration, dependency version, provider default,
architecture or live integration is changed. Full canonical local Quality and the final-cutoff affected proof now pass;
baseline GitHub runs are not reused as final approval.

The first proof attempt's raw receipts in `/tmp` are no longer available after
session recovery. New task-owned ignored receipt sets retain raw scans,
manifests, command exits/hashes, reproduced failures and corrected proofs.
General corrected-source Quality: 962 passed, 184 integration deselections,
Ruff/format pass, mypy 168 source files pass. Those deselections are the existing
unit selection; integration is executed separately without weakened markers.

Trivy reports 45 HIGH OS package/advisory instances with no fixed version in
the observed DB. There are also 72 MEDIUM, 62 LOW and six UNKNOWN OS instances,
and five MEDIUM/one LOW for base-image pip 25.0.1 (fixed versions recorded in the
[machine container inventory](OSS-001-container-inventory.json)). No CRITICAL
was reported. This is an unresolved image finding, not a source-code security
PASS or image approval. Source-only publication needs a separate explicit owner
risk decision and security notice, in addition to every other release gate.

## Source-only decision

Pending independent audit, required security/functional gates, exact-SHA remote
Quality, archive verification and owner authorization. Proposed output is only
the titled v0.1.0 GitHub Pre-release with source ZIP/tar.gz. No merge/tag/Release
is authorized in OSS-001 execution.

## Docker-image decision

**NOT APPROVED FOR PUBLICATION**. Local build/scan evidence is separate from
source review. Preserve raw results, exit statuses, HIGH/CRITICAL findings and
fixed-version availability without suppression. No official prebuilt image,
registry push, binary/package distribution, model weights or deployment.

## Executable evidence and binding

Receipts are retained in ignored, task-owned `oss-001-20261104-final` storage;
raw private receipt files are excluded from public archives. They are available
for the later approved independent package. No raw secret values are copied
here. Earlier failed host/network and reproduced privacy regressions remain
in their original receipt sets; subsequent passing runs do not erase them.

The full canonical run used a frozen 589-file source snapshot. Its bounded
runtime deltas change message/command cutoff expressions in `retention.py`
and strengthen the regression for future platform time and late-created jobs.
The intermediate cutoff manifest records its narrower change and intervening
documentation/inventory edits.
The latest `source-final` manifest binds the complete runtime correction. Its
962 general tests and 31 affected integrations pass; the actual stock image was
rebuilt and rescanned with the same unsuppressed findings. Closed first-run
verification also passes against that image (one test, 147.17 seconds). All current backend/script/migration
bytes match that manifest; earlier image hashes are retained only as history.
No weakened markers/assertions or baseline-only source approval is used.
Documentation/inventory updates after these snapshots are included in the
separate publication privacy snapshot and public-contract validation before
local commit. Remote Quality must still test the
final committed candidate; these local receipts do not satisfy OSS-37.

| Receipt | Observation | SHA-256 |
| --- | --- | --- |
| Canonical command results | All 48 recorded commands exit 0; 39 workflow blocks plus setup/supplementary proof | `996836bcdf09ceb94ff4f75e79e8bca44e3348974f5937458ce7368bcbf922f4` |
| Latest runtime/build/image command results | Eight checks have expected exits; Trivy vulnerabilities remains exit 1 | `71a899901ace05a00ac2274179cc32413e079cea3f59e6415778afe22004d7fd` |
| Additional fresh integration results | 184 tests on earlier cutoff snapshot, migrations/services/stop exit 0 | `c22618c11d8c8faa222748845ce994a16c7c8a24f5d497b493e9cd9057e8d581` |
| Final-delta command results | Nine affected checks, all exit 0 | `c9d0af03383ff493575181ea155bca3da83840b096e1bc95b05a7c6b211b6150` |
| Archive command results | All six expected exits, including honest history exit 2 | `366ecb7a44bfe7504be7253ba738507696c8bc7c0502aed388e8ddf742e88a56` |
| Canonical source manifest | Frozen complete local workflow input | `012ef1bf255b879b08d279d00b1115cc4c0dce2d963e38212940edd2df4c9c6c` |
| Latest runtime source manifest | Includes late-created-command/source-age correction; code bytes match local candidate | `2134c20d022a31128114a1b6a5bdefc86deb7665936d1b314a0295e98dc6adc0` |
| Intermediate cutoff source manifest | Earlier future-time cutoff proof, superseded by latest runtime manifest | `84cf20d1c3a81534e2b1f9bfea5e0c463b60b70742d1f2978da7a1199641627c` |
| Expanded reviewed history JSON | 4 commits / 652 objects / 582 paths; 78 exact dispositions, zero unresolved | `8720c4cf5d4ddbf31d7a45843c72baaf87a013efd4440782e783d63dc19f4001` |
| Expanded Gitleaks JSON | 8.30.1, redaction 100, all refs; raw exit 1, two enum false positives | `8b0de1733accce6fa7347a17611bb9814855a1e5fadce5264ba0b5e34c3833ae` |
| pip-audit JSON | 2.9.0 / exact 41-package lock / PyPI API / 2026-11-04; exit 0, zero known advisories | `f7fd330a841fca10f53e7e0aa235e1490c07515eee16aa5e5531a16e6c3d1b52` |
| Latest actual-image Trivy JSON | 0.76.1 / 2026-11-04 / raw exit 1; findings unsuppressed | `851e4781e9e125e559e4e81d45a9f56527dd667b4172500d8df34ae6f3ad5cb5` |
| Final actual-image license JSON | Per-component metadata; exit 0 is not legal certification | `703b3472ceb26a269aa866a76cd0a5ab2d4f8663f426687b6b62423b5e9551a0` |
| Final image runtime inspection | Non-root, no effective capabilities, legal hashes/private-path checks | `cd352ccc85634713abea2e589d4fdf8052135f353e1ec30e3717566e93b604a9` |

The exact `uv.lock` SHA-256 is
`207824e1ff4166fda7f71e9e2dc21a33a9bdc649db6eafb4673ca983464d8794`.
PyPI does not expose an immutable advisory database revision; the timestamp
and response hash identify the observed result. Trivy's observed database
metadata and image/source digests are in the machine container inventory.
Gitleaks findings refer to `provider_tokenizer` enum/schema values in migration
0017 and provider control code, not credentials; raw exit 1 remains recorded.
The history tool's raw exit 1 becomes reviewed exit 0 only with exact finding-ID
dispositions; it is not independent audit approval or a scanner allowlist.

Local proof archives (not GitHub-generated release assets) have SHA-256:

- tar.gz: `34c4b9f59a62e4995f2818e7ab02a28a903a1dfa7e360e35ec185e5a6b509a13`
- ZIP: `6f73c92c001f791523a2c84c8e579ff99491cd4870514d7c1668cfe5cd8c9f79`

They bind the recorded archive-input manifest, before later documentation/inventory edits.
The VCS-free archive history tool correctly returns COVERAGE_INCOMPLETE, exit 2.
It is never used as a full-history PASS. Docker build used the stock Dockerfile
with host networking only during dependency installation because builder DNS
failed locally. Synthetic runtime networks retained their original isolation;
explicit unused IPAM subnets avoided host address-pool exhaustion. No unrelated
network, volume, local image tag or operator resource was overwritten/pruned.

## Bàn giao hiện tại cho chủ sở hữu

Đây là bàn giao giữa kỳ, **chưa đủ điều kiện phát hành**.

| Nội dung | Kết quả |
| --- | --- |
| Repository và public root | Đúng ID/public/main; root không có parent, toàn bộ lịch sử công khai được giữ nguyên. |
| SHA nguồn và main | Main vẫn `612f89c6724261873d38cfa9a9639eb5836cb41a`; candidate local nằm trên feature branch; SHA đầy đủ nằm trong receipt bàn giao sau commit, không lấy SHA baseline làm SHA candidate. |
| Quyền sở hữu và MIT | Theo tuyên bố độc lập của chủ sở hữu; LICENSE dùng Hoang Nguyen, giữ nguyên MIT grant. |
| Bên thứ ba và Harness | Đủ 41 dependency khóa, SBOM, container inventory; giữ thông báo MIT Harness và phân loại tooling tùy chọn. |
| Scan nguồn/lịch sử | Không phát hiện credential thật; raw exit/finding và phân loại chính xác được giữ, không suppression. |
| OS/container | 45 HIGH, 0 CRITICAL; không có fixed version cho HIGH tại thời điểm scan. Chưa phê duyệt image. |
| Quyền riêng tư | Tài liệu phản ánh lưu trữ, provider/Telegram, retention riêng, thiếu field/E2E encryption và nghĩa vụ backup; đã sửa lỗi retention có kiểm thử. |
| Migration và phục hồi | Giữ đủ 26 migration, một head; lifecycle và backup/restore giả lập qua. |
| Quality và bổ sung | Full workflow cục bộ qua; general 962 test, integration 184 test, delta 31 test; offline eval 125 PASS/5 NOT_EVALUATED. |
| Self-host từ nguồn sạch | Archive local và Docker fixture kín qua; không thao tác Telegram/provider thật. |
| Kiểm toán độc lập | BLOCKED: chờ đường dẫn/export chính xác của gói riêng SPEC-048 được duyệt. |
| Ma trận nghiệm thu | Đủ 40 dòng ở trên; các gate còn thiếu không được suy thành PASS. |
| Draft PR và HEAD | Chưa tạo/push trong khi gate kiểm toán còn thiếu; không có URL/SHA PR cuối. |
| GitHub Actions | Baseline Quality `40069948712` success; chưa có run Quality cho candidate cuối. |
| Quyết định còn lại | Cung cấp đúng gói audit; xử lý kết quả độc lập; xem xét rủi ro source-only riêng; chỉ quyết định release sau Draft PR/CI/archive đầy đủ. |
| Image, branch và worktree | Không publish image/deploy; candidate được lưu bằng commit trên feature branch local; receipt bàn giao ghi trạng thái worktree sau commit. Main/ruleset/tag/release không bị thay đổi. |
