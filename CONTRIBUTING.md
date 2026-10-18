# Contributing to January AI Companion

January is a self-hosted Telegram companion. Contributions use public
source, synthetic tests and normal pull requests; no maintainer account, paid
model key, Telegram bot or internal service is needed. Support is community
and best-effort, with no response SLA or managed hosting/backup service.

## Setup and scope

Use Python 3.12 and uv. From your fork/checkout, create a topic branch or a
separate worktree; preserve unrelated local changes. Follow
[local development](docs/runbooks/local-development.md) for disposable
PostgreSQL 16, Redis 7 and optional integration Qdrant prerequisites. The
[self-host quickstart](docs/runbooks/self-hosted-quickstart.md) is the operator
path, not a requirement to connect a live bot while developing.

```bash
uv sync --all-groups --locked
./scripts/validate.sh
git diff --check
```

Read [the workflow](docs/WORKFLOW.md) and the relevant code/tests. A small bug
or typo fix needs a bounded explanation and proportionate tests, not a new
SPEC. New user-visible behavior needs an agreed product SPEC/design record
before implementation; do not infer policy from configurable defaults.
Multi-session work uses one evolving plan under `docs/plans/active/`, moved
to completed only after proof. See [architecture](docs/ARCHITECTURE.md).

## Tests and review

Run relevant focused tests, `./scripts/validate.sh`, the affected validator(s),
and `git diff --check`. Use Ruff lint/format and strict mypy as configured in
`pyproject.toml`; do not introduce a competing style configuration. Tests must
be offline at external Telegram/model boundaries; local disposable services
are permitted. Optional live tests must stay explicitly guarded and are not
required of contributors. Never supply production data to a validator.

For broad changes, run the meaningful full [Quality workflow](.github/workflows/ci.yml)
in its recorded order with fresh isolated dependencies. Broad integration
includes a local stock self-host image build and Qdrant; follow the native
guide's prerequisites. Check host ports/project ownership first. Do not run
overlapping validators against the same database or remove unrelated stacks.
CI provisions synthetic services and needs no repository secrets or paid APIs.
The optional ignored Harness binary is not required of external contributors;
when installed, the general validator checks it as well.

Schema changes need a reviewed Alembic migration, one head, upgrade and relevant
recovery proof. Do not casually edit committed migration history, manually
ALTER a production schema, or promise destructive downgrades are safe.

In your PR, explain scope, behavioral evidence, exact checks/results, migration
and configuration effects, documentation, and remaining risks. Keep changes
reviewable. Do not hide failures with skip/xfail, reduced selectors, or ignored
exit codes. Update [CHANGELOG](CHANGELOG.md) for meaningful user-visible changes;
do not invent a release date or choose the maintainer's first version.

## Security and privacy

Never commit real credentials, `.env`, database dumps, private hostnames,
account identifiers, conversations, prompts, memories or provider responses.
Use clearly synthetic examples. Redact diagnostics before sharing; even
third-party error messages may contain private data. Do not weaken fail-closed
authentication, safety, provider admission, tenancy or erasure. Never put
content or raw platform/user identifiers into metric labels.

Report vulnerabilities using [SECURITY.md](SECURITY.md), not a public exploit
or credential-bearing issue. Ordinary bug reports should include a SHA/tag,
deployment profile, reviewed doctor output, migration head, closed error class
and minimal synthetic reproduction. See
[troubleshooting](docs/runbooks/self-hosted-troubleshooting.md).

Project contributions are under the [MIT License](LICENSE); retain applicable
third-party notices, including [NOTICE](NOTICE). No CLA or DCO requirement is
introduced. A code of conduct is OPTIONAL MAINTAINER POLICY, not a release
gate; none is currently supplied and no enforcement contact is invented.

Publishing is a separate maintainer activity described in the
[release process](docs/maintainers/release-process.md). A green PR does not
authorize deployment, live I/O, a tag or a release.

## Optional maintainer tooling

Contributors can work without Graphify. The pinned
[Graphify navigation wrapper](docs/maintainers/graphify.md) is optional developer
tooling, separate from application dependencies, self-host prerequisites and
canonical Quality. Its local graph is derived and may be stale; verify source.
