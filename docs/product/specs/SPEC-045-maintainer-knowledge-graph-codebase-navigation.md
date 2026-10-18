# SPEC-045 — Maintainer knowledge graph and codebase navigation

Status: APPROVED OPTIONAL MAINTAINER TOOLING SPEC

## Authority and baseline

The owner's supplied SPEC-045 objective authorizes only optional Graphify
navigation tooling. Repository source, product contracts and Harness are the
system of record. Baseline `private-source-checkpoint-omitted`, GitHub
Quality 37037448621 success, single Alembic head `0026_conversation_feedback`.
SPEC-044 remains complete, MIT unchanged, first public version remains OWNER
DECISION REQUIRED. No migration or product behavior change is authorized.

## Required outcome

- Independently audit Graphify version/package/licenses and current Codex,
  OpenCode and git installer/hook behavior before integration.
- Consume exact pinned external tooling, without vendoring or normal project,
  contributor, self-host, image or canonical CI dependency.
- Provide a bounded root-discovering executable wrapper for local code-only
  build/update and existing-graph query/path/explain, plus offline status/version.
- Protect sensitive local material with supported ignore rules; keep generated
  output local, ignored, derived, rebuildable and non-authoritative.
- Preserve the existing Harness block byte-for-byte. No forced graph-first
  work, implicit installers, source mutation hooks, provider calls or uploads.
- Document purpose, install/run, commands, platforms, privacy, staleness,
  upgrade, cleanup, troubleshooting and the MIT/Apache-2.0 boundary.
- Add offline deterministic integration validation and meaningful static and
  wrapper tests, including all six required isolated failure injections.
- Prove source archive, exact candidate, fresh depth-one and VCS-free full
  Quality without Graphify installed or output present. Include public release,
  self-host, reliability, production readiness/deployment, every direct CI
  validator and canonical governance/safety/tenancy/memory/RAG/Telegram checks.
- Record local code-only compatibility and at least three useful graph findings,
  each corroborated in authoritative source. Keep external smoke separate
  from canonical evidence; do not depend solely on package-index availability.
- Verify source/modes/secret/test integrity, no app/Alembic/eval changes, exact
  130/125/5/0/0 eval totals and zero critical/high unresolved findings.

## Non-goals and authority boundary

No application/Telegram/HTTP/provider/memory/RAG changes, schema migration,
required Graphify account/key, shared graph, semantic external extraction,
global installs/configuration, auto hooks, release version, publication or
SPEC-046. Canonical Quality must remain green. Stop if integration requires
product/architecture changes; do not weaken validation to pass.

## Design and acceptance evidence

See [design handoff](../../plans/handoff/SPEC-045-DESIGN-HANDOFF.md),
[maintainer guide](../../maintainers/graphify.md) and
final handoff (private execution record omitted from this snapshot) for exact audit,
implementation, failure injections, candidate identity and full gate evidence.
Implementation approval status is separate from this bounded scope's authority:
APPROVED GRAPHIFY INTEGRATION CANDIDATE — INDEPENDENT AUDIT PENDING,
REQUIRES FIXES, or BLOCKED — GRAPHIFY INTEGRATION REQUIRES PRODUCT/ARCHITECTURE CHANGE.
