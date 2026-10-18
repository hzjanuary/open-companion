# Documentation Map

Start with the smallest current map. Retrieve compatibility, historical, or
upstream-maintenance material only when the task explicitly needs it.

## Installed Core

- `WORKFLOW.md`: canonical request, planning, judgment, validation, and
  completion behavior.
- `product/`: consumer-owned product behavior derived from accepted intent.
- `plans/`: one evolving Git-native plan for work that needs durable memory.
- `decisions/`: lasting product and architecture choices.
- `templates/decision.md`: lasting-decision template.
- `templates/exec-plan.md`: durable execution-plan template.
- `.agents/skills/onboard-repository/`: explicit, read-only-first brownfield
  repository mapping and improvement proposals.
- `.agents/skills/audit-onboarding-proposal/`: explicit independent proposal
  and patch verification.

These files are generic Harness structure. They do not select an application
stack, replace a consumer README or architecture, fabricate validation
commands, or require the optional SQLite control-plane lifecycle. The installed
`harness` binary only maintains this core structure. The skills do not run
automatically; invoke `$onboard-repository` only when repository onboarding is
the requested outcome.

## Consumer-Owned Truth

The consumer repository's own README, architecture, code, tests, CI, runtime
signals, and application behavior remain authoritative. Harness adds navigation
and working-memory structure around that truth; it does not install upstream
`repository-harness` product documents over it.

## January application

- [January](../README.md), [quickstart](runbooks/self-hosted-quickstart.md),
  [VPS](runbooks/self-hosted-vps.md), [upgrades](runbooks/self-hosted-upgrades.md)
  and [troubleshooting](runbooks/self-hosted-troubleshooting.md).
- [Architecture](ARCHITECTURE.md), [product](product/SPEC.md),
  [product contracts](product/README.md) and [decisions](decisions/README.md).
- [Contributing](../CONTRIBUTING.md), [workflow](WORKFLOW.md),
  [security](../SECURITY.md), [MIT](../LICENSE) and [notices](../NOTICE).
- [v0.1.0 draft notes](releases/first-public-release-candidate.md),
  [release process](maintainers/release-process.md),
  [owner checklist](maintainers/github-release-checklist.md),
  [new public-root procedure](maintainers/first-public-publication.md)
  and [history review tool](maintainers/public-history-review.md).
- [Optional Graphify navigation](maintainers/graphify.md).

Current operations are documented under `runbooks/`; the README links the most
useful entry points. Dated product specifications and technical design handoffs
remain as behavior/design context. Private implementation receipts, historical
owner audits and promotion inventories are intentionally omitted. Private source
checkpoints are explicitly redacted; they are not public repository identities.
Earlier version/license/publication observations remain historical and are
superseded by the approved v0.1.0 unpublished snapshot policy.

## Source-Repository Indexes

The following material is deliberately outside the default installation:

- [Application-legibility plan](https://github.com/hoangnb24/repository-harness/blob/main/docs/plans/active/application-legibility.md): current consumer-first evidence matrix and next gate.
- [Control-plane freeze decision](https://github.com/hoangnb24/repository-harness/blob/main/docs/decisions/0022-control-plane-freeze-and-compatibility-runway.md): current compatibility boundary for SQLite and protocol v1.
- [Optional-consumer ownership decision](https://github.com/hoangnb24/repository-harness/blob/main/docs/decisions/0023-optional-consumer-ownership.md): current ownership split between Harness, Symphony, and consumer applications.
- [Test suite map](https://github.com/hoangnb24/repository-harness/blob/main/tests/README.md): behavior protected by each current, compatibility, and historical test group.
- [CLI compatibility index](https://github.com/hoangnb24/repository-harness/blob/main/docs/compatibility/README.md): SQLite lifecycle, orchestration protocol, bootstrap, schemas, and CLI maintenance.
- [Historical index](https://github.com/hoangnb24/repository-harness/blob/main/docs/provenance/README.md): superseded decisions, story-era evidence, reviews, and migration provenance.
- [Upstream repository](https://github.com/hoangnb24/repository-harness): Rust implementation, installer, release, and maintenance truth.

Selecting the optional CLI profile installs the compatibility material required
to operate that surface. Historical and upstream-only material remains in the
source repository and Git history.
