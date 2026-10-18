# SPEC-047 design handoff

Date: 2026-10-16

Status: IMPLEMENTATION DESIGN — INDEPENDENT AUDIT PENDING

The [product contract](../../product/specs/SPEC-047-first-public-release-publication-gate.md)
authorizes publication preparation only, from baseline
`private-source-checkpoint-omitted`. No capability, migration, runtime
semantics or production configuration changes. Prior lost work is not resumed.

## Scanner and review

`scripts/public_release/audit_history.py` is a stdlib CLI with `--root`, repeated
`--ref` and optional `--dispositions`. Default scope is HEAD plus every local
ref, including remote-tracking refs and tags. Explicit scope must cover them
all. It rejects ancestor Git discovery, shallow/partial/grafted/replaced or
alternate history, missing objects, noncommit refs, unsupported submodules,
unmapped content and exceeded size/count bounds. It never fetches, invokes an
API or mutates refs/history/index/worktree. Local Git reads have timeouts and
lazy fetching/optional locks/replacements disabled.
Inherited Git directory/object/config/trace overrides are removed; system/global
Git config is disabled. Every enabled Git-boolean spelling of promisor metadata
is rejected before object reads.

Enumerate commits and every reachable object; batch-read all objects with
type/size/stream validation. Enumerate historical path-to-blob relationships
from each commit tree; identify deleted paths against HEAD. Scan blobs and
commit content. Record counts, earliest/latest committer dates, merges,
binary/large-object metadata, redacted identity categories and signature-header
presence. Do not verify signatures or treat unsigned commits as failures.

Output never includes matched text, names/emails, raw filenames, Git stderr or
private records. Path SHA-256 IDs enable local mapping without publication of
sensitive paths. Finding IDs bind object, detector, paths and line numbers.
Human dispositions require an exact ID and reason; stale IDs fail, and a
changed blob creates a new unresolved finding. Owner-path consent is permitted
only for the personal-checkout detector and cannot waive a credential.
Exit 0 means no unresolved automatic finding, never publication approval;
exit 1 means review required; exit 2 means coverage incomplete.

`backend/tests/test_public_history.py` creates only disposable synthetic Git
repositories. Its local test commits are not commits to January. Cases cover
deleted Telegram/provider/JWT credentials, key material, URLs, old env/binary
files, identifier/private-record/path detection, redaction, exact dispositions,
empty env values, missing refs/objects/Git, noncommit refs, shallow/partial and
VCS-free rejection. It needs Git but no January history, external credentials,
network, Telegram, provider or GitHub requests, so ordinary archived-source
Quality can execute the unit tests.

Contextual review is a separate human task. Inspect every detected object and
historical data-bearing/large path without emitting content; use exact-object
dispositions and safe review summaries. Pattern absence is not an exhaustive
security claim. Genuine exposure or unreviewed high-risk material withholds
approval. Commit metadata and personal-path publication consent remain owner
decisions. See [history review](../../maintainers/public-history-review.md).

## Feedback and resource isolation

Inspect the unchanged session-context lifecycle and per-key advisory locks.
The existing test releases 100 calls over 50 keys from one barrier. Production
defaults are pool 5 plus overflow 5 and timeout 3 seconds; test changes are
permitted only after new evidence supports them. Measure checkout high water,
connection return, idle transactions and isolated PostgreSQL capacity. Preserve
every assertion and synthetic/no-external-I/O boundary. A runtime semantic
defect is a stop, not a release-documentation fix.

Inventory containers, volumes, networks and ports before work. Use unique
task-owned projects and existing per-validator override variables. Run expensive
gates serially; clean only proven-owned projects, including profile services.
Retain exit codes and logs. Never remove an unrelated stack or increase host
PostgreSQL capacity to force a test pass.

## Source and publication

The required spec/design/plan/final handoff, history review, owner process and
unversioned notes form one implementation record, with bounded navigation and
checklist updates. Historical SPEC-041–046 records remain unchanged.

A temporary Git index assembles the intended tree without staging the real
index or creating a January commit. Exclude local inputs/evidence and preserve
Git modes on materialization. Candidate identity and receipts live outside
the tree to avoid self-reference. Verify clean source, depth-one checkout and
VCS-free behavior with ordinary uv on PATH, no inherited operator env/keys or
global Graphify. Ordinary Quality remains VCS-free; history review does not.

All current canonical and required supplemental gates, eval counts, connection
proofs and distribution checks must be reconciled before implementation
approval. Independent OpenCode audit is separate and pending. Owner commit/push,
exact-SHA remote CI, refreshed history, metadata/version/settings/visibility/tag/
release decisions remain outside this authorization.
