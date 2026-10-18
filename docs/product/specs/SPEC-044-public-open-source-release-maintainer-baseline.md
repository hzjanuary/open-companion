# SPEC-044 Public open-source release and maintainer baseline

Date: 2026-10-02

Status: APPROVED PUBLIC OSS RELEASE SPEC

This approves the bounded owner-directed release contract, not candidate proof
or publication. Baseline: `private-source-checkpoint-omitted`, exact-SHA
GitHub Quality `36889172611` main/push/completed/success. Alembic remains
`0026_conversation_feedback`. New migrations and product behavior: NONE.

## Authority and scope

The owner explicitly selected standard MIT. No alternative, dual licensing,
noncommercial condition, UI-attribution demand, CLA, new DCO or field-of-use
restriction is authorized. Repository owner metadata and recent authored Git
history identify `hzjanuary`; root copyright is `Copyright (c) 2026 hzjanuary`.
Existing third-party ownership must remain distinct and be retained verbatim.
MIT permits downstream commercial use under its terms; a managed SaaS is outside
this project's scope, not prohibited downstream use.

Local Docker/self-host, polling, optional webhook and single-VPS remain the
supported distribution direction. No feature, command, API route, provider
capability, model, schema, deployment, live I/O, package/registry publication or
telemetry is introduced. SPEC-041/042/043 history remains unchanged: the license
was selected later in SPEC-044, not retroactively during their audits.

## Public distribution contract

1. Root LICENSE must contain the unmodified standard MIT grant/conditions and
   disclaimer, with the supported copyright identity. Metadata and current
   README/docs must agree. License text is a normal non-executable file.
2. Existing pyproject packaging conventions must be respected without unrelated
   modernization/version changes. Reference LICENSE using the supported file
   table for the current uv toolchain; no PyPI publication claim or redundant
   license classifier. Locked setup and container build must still work.
3. Retain concrete third-party notices. Bounded direct-dependency metadata
   review records reported licenses and unknowns; do not present it as legal
   advice or exhaustive transitive/image/model review. Installed Harness MIT
   copyright is preserved in NOTICE; do not assign it to the project owner.
4. README must identify the self-hosted Telegram system, optional features and
   useful first-run links, with factual capabilities, no affiliation or blanket
   security/compliance claims, and no supported Zalo claim. External providers
   receive enabled-feature data; local Ollama is separate, not fully local
   Telegram. No exactly-once, zero-retention or zero-data-loss promise.
5. Current docs link quickstart, VPS/configuration, upgrade/backup/troubleshooting,
   security, contribution, license and architecture without historical SPEC
   knowledge. Historical license observations remain historical only.

## Contribution and safe reporting

6. Public CONTRIBUTING covers locked setup, topic branches/worktrees, existing
   style, focused/general/affected validation, broader Quality, migration rules
   and proportionate SPEC discipline. Small fixes do not require a new SPEC.
   Tests require no maintainer services, paid keys or live bot. CI stays fork-
   friendly, fake-boundary and secret-free. No check or selector is weakened.
7. Schema changes in future work require a reviewed migration, single head and
   proof; no casual committed-history edits or manual production ALTER escape.
   This SPEC has no schema change.
8. Security reporting must be truthful. Current GitHub reporting query returns
   404, not confirmation of an available private channel. Request private
   contact without exploit/secret details if unavailable; do not invent an
   email, bounty or SLA. Private reproduction includes source identity,
   prerequisites, expected/actual behavior and synthetic steps only.
9. Lightweight bug/self-host and PR guidance asks for version/SHA, profile,
   redacted doctor/error/service/health evidence, migration head and synthetic
   reproduction; never env files, tokens, keys, dumps, user/account identities,
   conversations, memories or provider responses. Preserve fail-closed auth,
   safety, provider governance and content-safe metrics in contributions.
10. Community support is best-effort. No hosted service, 24/7 support, managed
    backup, response-time promise or regulatory certification. A code of conduct
    is OPTIONAL MAINTAINER POLICY, not automatically added or a release blocker.

## Version and release workflow

11. Source SHA identifies unreleased code; an uncommitted candidate also needs
    its complete tree. Existing metadata `0.1.0` is not a published first tag.
    FIRST PUBLIC VERSION: OWNER DECISION REQUIRED. Future `vMAJOR.MINOR.PATCH`
    tags follow conservative SemVer-style convention; pre-1.0 changes require
    reading notes, with no stable API, LTS or arbitrary downgrade guarantee.
12. CHANGELOG starts Unreleased with real implemented baseline capabilities,
    not fabricated dated versions. Release notes contain owner version, exact
    SHA/Quality, Alembic/migration/config/breaking changes, upgrade steps,
    limitations and security notes without values/secrets.
13. Maintainer process/checklist requires exact source, local proof, independent
    audit, owner commit/push, same-SHA remote Quality, clean source archive,
    notices/license, privacy review, optional build/digest, then owner tag and
    GitHub Release. Publication actions are documented, never performed here.
14. State model separates TECHNICAL OSS CANDIDATE, LICENSED OSS CANDIDATE,
    REMOTE CI VERIFIED OSS BASELINE, TAGGED RELEASE and PUBLISHED GITHUB RELEASE.
    At most a licensed approved candidate with independent audit pending is
    delivered by this SPEC, not an actual tagged/published release.

## Compatibility and source proof

15. Python 3.12, PostgreSQL 16, Redis 7 and optional tested Qdrant v1.13.4 are
    the current verified baseline, not an arbitrary-major support promise.
    Compose must support raw env files. Config may evolve through release
    notes; database schema is migration-managed. Backup/review/preflight/single
    migration/restart/readiness/smoke remains canonical; no blind downgrade.
16. Git archive includes all source, migration, lock/config examples, Docker/
    Compose/self-host tooling, docs, license/notices and tests. No reliance on
    ignored files, maintainer temp artifacts, `.git` history or developer venv.
    All direct user/CI scripts are Git mode 100755 and executable on extraction;
    normal docs/LICENSE are 100644. Worktree stat is not Git-tree proof.
17. Source distribution is canonical; local Docker builds supported. No invented
    official registry image. Image packaging includes project notices; base
    tags and locked dependencies do not imply bitwise reproducibility.
18. Scan tracked and new candidate sources for real credentials, private
    identifiers/content/hostnames and unsafe examples without displaying
    suspect values. Expected real secrets/private data: zero. Current-tree
    scope does not prove all Git history; historical audit must be disclaimed
    unless actually performed. No history rewrite is authorized.

## Executable acceptance and artifacts

Add an offline, deterministic, VCS-free public release validator only for the
currently uncovered MIT/metadata/docs/mode contract; it must never use network,
GitHub API, a daemon or publication. Isolated removal of LICENSE, README license
substitution, broken CONTRIBUTING link and non-executable direct script must
fail. CI integration is additive, with zero masking/secret requirements.

Re-run general/self-host/doctor/topology/quickstart proof; full meaningful
candidate CI order and every required regression group; reliability exit 0 and
zero failures; canonical eval exactly 130/125/5/0/0 with zero new scenarios;
deployment/readiness, governance/backup/tenancy/safety, Telegram/provider/
memory/RAG/scheduling; authoritative Ruff/format/mypy/shell/Harness/diff checks.
Prove complete candidate clean/fresh, actual depth-1 and VCS-free exports with
ordinary PATH uv and no secrets, real Git modes, and source archive validation.
No app/Alembic/route/command/domain/provider behavior change is allowed.

Deliver this approved spec, design handoff, public artifacts, one validated
completed execution plan and final handoff with requirement-by-requirement
evidence for all original 82 phases and 50 gates. No unresolved Critical/High.
Final technical status may be APPROVED PUBLIC OSS CANDIDATE — INDEPENDENT AUDIT
PENDING, REQUIRES FIXES, the explicit copyright input condition, or product/
architecture blocker; never claim publication or label the handoff COMPLETE.

DO NOT COMMIT. DO NOT PUSH. DO NOT TAG. DO NOT CREATE GITHUB RELEASE.
DO NOT START SPEC-045. Next: independent OpenCode public OSS release audit.
