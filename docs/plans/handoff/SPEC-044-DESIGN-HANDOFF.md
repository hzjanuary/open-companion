# SPEC-044 public release design handoff

Date: 2026-10-02

Status: REVIEWED DESIGN — IMPLEMENTATION VALIDATED — INDEPENDENT AUDIT PENDING

Authority is the [SPEC-044 product spec](../../product/specs/SPEC-044-public-open-source-release-maintainer-baseline.md)
and explicit owner MIT decision. Baseline `private-source-checkpoint-omitted`,
prior exact-SHA Quality `36889172611` success, one Alembic head
`0026_conversation_feedback`; no product/schema/migration change.

## License and metadata

Root LICENSE contains standard MIT with `Copyright (c) 2026 hzjanuary`, supported
by repository owner metadata and authored Git history, not a guessed legal
name. The current uv 0.6.5-style project remains unmodernized: pyproject uses
`license = { file = "LICENSE" }`, no invented publishing backend or new version.
The Dockerfile copies LICENSE/NOTICE into build and runtime stages. Dependency
license metadata and installed Harness source are separately audited; NOTICE
retains the upstream MIT text/copyright, not new terms in root LICENSE.

## Documentation topology

README and current docs carry MIT/current distribution truth; historical
SPEC-041/042/043 product/design/handoff/audit/completed files are untouched.
User onboarding remains the existing quickstart/VPS/upgrade/troubleshooting
guides. Contributor setup and review is in root CONTRIBUTING; CHANGELOG starts
Unreleased. Maintainer-only procedure, checklist, release notes template and
bounded dependency review live under `docs/maintainers/` and are navigable from
the docs map without adding release bureaucracy to first run.

Current stale license and unsupported-Zalo wording is corrected. No provider
affiliation, official image, fully-local hosted-provider privacy, comprehensive
semantic safety, regulatory certification or universal security claim is added.

## Contribution and reporting

One compact bug/self-host issue template asks only for reviewed diagnostic
metadata and synthetic reproduction; the PR template asks scope, test,
migration/docs/privacy and notice checks. No extra feature-template bureaucracy,
CLA/DCO, paid API or maintainer-only service requirement. No code of conduct is
added: optional maintainer policy with no invented enforcement contact.

SECURITY retains an honest private-channel fallback. The reporting-status API
returned 404; do not claim GitHub private reporting is available or expose
exploit details while requesting contact. Private reports include source,
profile and synthetic steps with credentials/user content redacted. Publication
checklist asks owner to establish the channel; no SLA/bounty is promised.

## Version and artifact identity

Unreleased identity is exact SHA; candidate identity additionally includes its
Git tree, new files and modes. Future tags use `vMAJOR.MINOR.PATCH` with explicit
pre-1.0 compatibility caveats. Existing metadata `0.1.0` does not choose the
first public version: OWNER DECISION REQUIRED. No fabricated dates/releases.
Release states separate local technical/licensed candidate, exact-SHA remote
CI, tagged, and actually published. The previous successful baseline run does
not certify this candidate.

Source archive is canonical, with Git-derived executable modes and no ignored
developer configuration/history. Images are built locally from source, retaining
license/notices; no registry/image publication or bitwise build guarantee.
Compatibility is current Python3.12/PostgreSQL16/Redis7/optional Qdrantv1.13.4,
not arbitrary-major support. Upgrade remains backup, notes/config, preflight,
single migration owner, readiness and deliberate smoke; no blind downgrade.

## Validation design

Existing self-host proof covers configuration, full worker graph, static doctor,
Compose, runtime boundaries and some doc links. It does not enforce MIT text,
metadata, public artifacts or release claims. A separate bounded stdlib validator
owns that new contract, invoked by a fail-fast Bash wrapper through existing
PATH/local UV resolution, offline and locked. Add exactly one CI step; preserve
all baseline checks/commands/selectors. Mutation tests operate on isolated
copies and prove process nonzero, not only exception helpers. It must run with
no Git repository or network and must never publish/migrate/start services.

Materialized permissions can be checked offline; actual Git modes must also be
proved separately from a complete alternate-index tree, especially because
local `core.filemode=false`. All direct CI scripts plus self-host entrypoints
and production fingerprint have mode100755; documents/LICENSE mode100644.
Frozen archive and depth-1 proofs use fresh environments and external PATH uv,
not copied developer caches/config. Caches may supply locked public packages,
but are not source requirements.

Full meaningful CI order uses owned synthetic PostgreSQL/Redis/Qdrant only,
with baseline Docker inventory preserved. Broad runtime tests use the explicit
stock local image; fake-only Telegram/provider adapters. Supplemental required
validators, exact eval, static/Harness/shell/diff, source privacy and test-integrity
review remain mandatory. Failures must be recorded and corrected, not skipped.
The final handoff (private execution record omitted from this snapshot) maps all82 phases/50 gates to observed
results. Local technical approval retains independent audit and owner publication
as the next separate actions.

## Owner boundary

No commit, push, tag, GitHub Release, public visibility change, registry/PyPI
publication, deployment, live provider/Telegram action or SPEC-045. Owner first
version and later publication remain separate decisions. Technical completion
requires evidence, then independent OpenCode public OSS release audit.
