# Source release process and compatibility

January AI Companion is MIT-licensed, local-first and self-hosted. Source is the
canonical distribution. This guide describes future owner-controlled releases;
it does not authorize an agent to commit, push, tag, publish or deploy. Ordinary
users start with the [quickstart](../runbooks/self-hosted-quickstart.md), not this
procedure. Contributions follow [CONTRIBUTING](../../CONTRIBUTING.md).

## Identity and release states

Use an exact Git SHA for unreleased source. An uncommitted candidate additionally
needs its complete Git tree identity and verified materialization; HEAD alone
does not identify uncommitted changes. Archive recipients should retain the SHA
and release metadata alongside the extracted source.

Future tags follow `vMAJOR.MINOR.PATCH`: patches for bounded compatible fixes,
minor increments for additive work, major increments for deliberate incompatible
changes after a stable series is established. Before 1.0, minor releases may
change interfaces; always read configuration and migration notes. This is a
lightweight convention, not a stable public API or LTS promise. Existing
operator HTTP APIs remain current implementation interfaces.

FIRST PUBLIC VERSION: v0.1.0 — OWNER APPROVED; NOT YET PUBLISHED.

Package metadata is `0.1.0`. This creates no tag, publication date or release
history. The existing public repository is https://github.com/hzjanuary/open-companion.
Preserve its public root and subsequent history; identify uncommitted work by
its reviewed file manifest, modes and SHA-256 content hashes. See the
[post-publication procedure](post-publication-source-release.md).

| State | Evidence required |
| --- | --- |
| TECHNICAL OSS CANDIDATE | Exact candidate sources, all applicable local Quality and distribution proof; legal integration may still be open. |
| LICENSED OSS CANDIDATE | Standard MIT, consistent metadata/notices and successful technical gates; independent audit can still be pending. |
| REMOTE CI VERIFIED OSS BASELINE | Owner-pushed exact SHA with completed successful GitHub Quality, following independent audit. A baseline run does not cover new uncommitted work. |
| TAGGED RELEASE | Owner-approved version tag resolves to that verified SHA. |
| PUBLISHED GITHUB RELEASE | Owner publishes release notes and artifacts for that exact tag/SHA. |

The historical SPEC-048 snapshot is not independent audit approval. A prior
baseline CI run does not verify new source changes. Current source approval
requires independent review and completed successful Quality on the exact SHA.

## Compatibility and support

The current locked/tested runtime uses Python 3.12, PostgreSQL 16 and Redis 7;
optional Qdrant is exercised with `v1.13.4`. Do not infer support for arbitrary
major versions. Compose must support `env_file` `format: raw`; doctor renders
the actual topology to test that requirement. Linux/Bash/POSIX permissions are
the documented host path. Local Ollama requires separately selected reachable
models and capability declarations; there is no automatic model parity promise.

Database changes are Alembic-managed with one approved head (currently
`0026_conversation_feedback`). Configuration and interfaces may evolve, with
release notes and upgrade instructions. No arbitrary database or application
downgrade guarantee, long-term support window, availability SLA, managed backup
or security response timeline is promised. Community maintenance is best-effort.
Zalo remains unsupported/frozen. External LLM/TTS services receive data for
enabled capabilities; local Ollama does not remove Telegram's data boundary.

## Prepare and verify

1. Choose the exact candidate and review [CHANGELOG](../../CHANGELOG.md),
   configuration and compatibility. Obtain owner approval for the version;
   do not silently use the current package version. Preserve historical product contracts; omit private receipts and redact private
   provenance with an explanation.
2. Check local worktree/index, intended source/modes and the single Alembic
   head. Run locked setup, focused checks, general and public/self-host
   validators, plus full meaningful [Quality order](../../.github/workflows/ci.yml)
   on fresh isolated synthetic services. Run supplemental reliability,
   backup/restore, governance and production-readiness gates. Never use live
   credentials or personal databases. Preserve failures; no weakened selectors.
3. Independently audit the exact candidate and owner-approved private package.
   Preserve existing history and use a normal feature branch and Draft PR under
   the [post-publication procedure](post-publication-source-release.md).
   Recheck a clean worktree, source SHA and the **same SHA's** remote
   Quality: completed/success, correct branch/event. Do not use an older green
   run as approval of new files. Repeat affected proof after changes.
4. Fill the [release notes template](release-notes-template.md), documenting
   source, run, migration head, compatibility, limitations and upgrade path.
   Keep the approved v0.1.0 entry explicitly NOT YET PUBLISHED until actual
   publication; add a date and source identity only from observed events.
5. Scan the exact current tree for secrets/private content, including all new
   files. Review matches without printing values. If history was not scanned,
   state that limitation; rotation, not deleting a line, invalidates leaked
   credentials. History rewriting is a separate owner decision.
6. Materialize the exact source manifest without importing private files.
   Check the existing public candidate commit's source archive
   and shallow checkout. Check required
   files, executable modes and validation without a developer `.venv`, ignored
   `.env`, `.tools`, `.git` history or generated local evidence. VCS-free users
   need ordinary PATH uv/Python only for contributor validation, not Docker
   self-hosting. No source file may depend on maintainer `/tmp` receipts.
7. Optionally build the stock Dockerfile from that exact source. Record image
   ID/digest, architecture and base/dependency provenance. Locked Python
   dependencies help repeat builds, but mutable base tags are not a guarantee
   of byte-identical images across dates. Check LICENSE/NOTICE remain included.
8. Complete the [GitHub checklist](github-release-checklist.md). Owner actions
   only: create the approved tag on the verified SHA, verify its target, then
   create the GitHub Release with reviewed notes/source artifacts. Never move
   a published tag silently. No auto-publishing workflow is installed here.

## Source and container contract

A GitHub-style source archive contains LICENSE, NOTICE, README, SECURITY,
CONTRIBUTING, CHANGELOG, `pyproject.toml`, `uv.lock`, Dockerfile, Compose files,
all runtime/migrations, self-host tools, docs/examples and validation source.
Direct scripts are Git mode `100755`; normal documents and LICENSE are `100644`.
Do not rely on a local chmod while Git records a different mode.

No official published GHCR/Docker Hub image or PyPI distribution is promised.
The supported container route is the quickstart's local build. A future registry
publication needs explicit owner action and its actual immutable digest in the
release notes, along with retained third-party notices. Building is not publishing.
Public repository visibility is also an owner action, separate from MIT licensing.

Upgrades remain: protected backup and erasure record → review changelog/config
and source → migration preflight → one reviewed migration owner → restart →
readiness/worker checks → deliberate smoke. Follow the exact
[backup/restore/upgrade guide](../runbooks/self-hosted-upgrades.md); do not promise
blind downgrade or restore over live data. See [SECURITY](../../SECURITY.md) for
reporting limitations and [dependency review](dependency-licenses.md).
